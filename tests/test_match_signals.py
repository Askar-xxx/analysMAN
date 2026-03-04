"""Тесты для чистых функций match_signals.py."""

from datetime import datetime, timedelta

import match_signals


def test_clamp_limits_values():
    assert match_signals._clamp(50, 0, 100) == 50
    assert match_signals._clamp(-5, 0, 100) == 0
    assert match_signals._clamp(150, 0, 100) == 100


def test_to_float_handles_valid_and_invalid_values():
    assert match_signals._to_float("3.5") == 3.5
    assert match_signals._to_float(None) is None
    assert match_signals._to_float("abc") is None


def test_parse_date_supports_known_formats_and_garbage():
    assert match_signals._parse_date("2026-03-03").strftime("%Y-%m-%d") == "2026-03-03"
    assert match_signals._parse_date("2026-03-03 19:45:00").strftime("%Y-%m-%d %H:%M:%S") == "2026-03-03 19:45:00"
    assert match_signals._parse_date("garbage") is None


def test_find_standings_entry_returns_match_or_none():
    table = [
        {"name": "Arsenal", "rank": 1},
        {"name": "Chelsea FC", "rank": 4},
    ]

    assert match_signals._find_standings_entry(table, "Arsenal") == {"name": "Arsenal", "rank": 1}
    assert match_signals._find_standings_entry(table, "Chelsea") == {"name": "Chelsea FC", "rank": 4}
    assert match_signals._find_standings_entry(table, "Liverpool") is None
    assert match_signals._find_standings_entry([], "Arsenal") is None


def test_team_recent_points_counts_points_and_winless_streak():
    form = [
        {"home_team": "Arsenal", "away_team": "A", "home_score": 2, "away_score": 0},
        {"home_team": "B", "away_team": "Arsenal", "home_score": 0, "away_score": 1},
        {"home_team": "Arsenal", "away_team": "C", "home_score": 3, "away_score": 1},
        {"home_team": "D", "away_team": "Arsenal", "home_score": 1, "away_score": 1},
    ]

    assert match_signals._team_recent_points(form, "Arsenal", limit=5) == (10, 1)
    assert match_signals._team_recent_points([], "Arsenal", limit=5) == (0, 0)
    assert match_signals._team_recent_points(form[:2], "Arsenal", limit=5) == (6, 0)


def test_extract_h2h_stats_averages_handles_populated_and_empty_stats():
    h2h_stats = [
        {
            "stats": {
                "Жёлтые карточки": {"home": "2", "away": "1"},
                "Красные карточки": {"home": "0", "away": "1"},
                "Фолы": {"home": "12", "away": "11"},
            }
        },
        {
            "stats": {
                "Жёлтые карточки": {"home": "3", "away": "2"},
                "Красные карточки": {"home": "0", "away": "0"},
                "Фолы": {"home": "10", "away": "13"},
            }
        },
        {
            "stats": {
                "Жёлтые карточки": {"home": "1", "away": "2"},
                "Красные карточки": {"home": "0", "away": "0"},
                "Фолы": {"home": "14", "away": "12"},
            }
        },
    ]

    result = match_signals._extract_h2h_stats_averages(h2h_stats)

    assert round(result["avg_cards"], 2) == round((4 + 5 + 3) / 3, 2)
    assert round(result["avg_fouls"], 2) == round((23 + 23 + 26) / 3, 2)
    assert match_signals._extract_h2h_stats_averages([]) == {}


def test_detect_match_loser_handles_home_away_draw_and_bad_score():
    assert match_signals._detect_match_loser(
        {"home_team": "A", "away_team": "B", "home_score": 0, "away_score": 2},
        "A",
        "B",
    ) == ("A", 2)
    assert match_signals._detect_match_loser(
        {"home_team": "A", "away_team": "B", "home_score": 3, "away_score": 1},
        "A",
        "B",
    ) == ("B", 2)
    assert match_signals._detect_match_loser(
        {"home_team": "A", "away_team": "B", "home_score": 1, "away_score": 1},
        "A",
        "B",
    ) == (None, 0)
    assert match_signals._detect_match_loser(
        {"home_team": "A", "away_team": "B", "home_score": "x", "away_score": 1},
        "A",
        "B",
    ) == (None, 0)


def test_build_derby_signal_contributions_and_fallback():
    match = {"team1": "A", "team2": "B"}

    same_country = match_signals._build_derby_signal(
        match,
        {"team1_meta": {"country": "England"}, "team2_meta": {"country": "England"}},
    )
    assert any("одной страны" in reason for reason in same_country["reasons"])

    same_city = match_signals._build_derby_signal(
        match,
        {"team1_meta": {"stadium_location": "London, UK"}, "team2_meta": {"stadium_location": "London, UK"}},
    )
    assert any("одного города" in reason for reason in same_city["reasons"])

    rich_h2h = match_signals._build_derby_signal(match, {"h2h": [{}] * 5})
    assert any("история очных" in reason for reason in rich_h2h["reasons"])

    cards = match_signals._build_derby_signal(
        match,
        {"h2h_recent_stats": [{"stats": {"Жёлтые карточки": {"home": "3", "away": "2"}}}]},
    )
    assert any("карточ" in reason for reason in cards["reasons"])

    fouls = match_signals._build_derby_signal(
        match,
        {"h2h_recent_stats": [{"stats": {"Фолы": {"home": "12", "away": "12"}}}]},
    )
    assert any("фолов" in reason for reason in fouls["reasons"])

    fallback = match_signals._build_derby_signal(match, {})
    assert fallback["reasons"] == ["ярких признаков принципиального дерби по данным немного"]


def test_build_motivation_signal_branches_and_fallback():
    match = {"team1": "A", "team2": "B"}

    minimal_gap = match_signals._build_motivation_signal(
        match,
        {"standings": {"table": [{"name": "A", "rank": 5, "points": 50}, {"name": "B", "rank": 6, "points": 48}]}},
    )
    assert any("разрыв по очкам" in reason for reason in minimal_gap["reasons"])
    assert any("рядом в таблице" in reason for reason in minimal_gap["reasons"])

    top_table = match_signals._build_motivation_signal(
        match,
        {"standings": {"table": [{"name": "A", "rank": 1, "points": 60}, {"name": "B", "rank": 10, "points": 45}]}},
    )
    assert any("верх таблицы" in reason for reason in top_table["reasons"])

    relegation = match_signals._build_motivation_signal(
        match,
        {"standings": {"table": [{"name": "A", "rank": 16, "points": 20}, {"name": "B", "rank": 17, "points": 18}]}},
    )
    assert any("зоны вылета" in reason for reason in relegation["reasons"])

    cup = match_signals._build_motivation_signal(match, {"is_cup": True, "round": "1/2 final"})
    assert any("кубковый формат" in reason for reason in cup["reasons"])
    assert any("поздняя стадия" in reason for reason in cup["reasons"])

    winless = match_signals._build_motivation_signal(
        match,
        {
            "team1_form": [
                {"home_team": "A", "away_team": "X", "home_score": 0, "away_score": 1},
                {"home_team": "Y", "away_team": "A", "home_score": 1, "away_score": 1},
                {"home_team": "A", "away_team": "Z", "home_score": 0, "away_score": 0},
            ],
            "team2_form": [
                {"home_team": "B", "away_team": "K", "home_score": 1, "away_score": 0},
                {"home_team": "L", "away_team": "B", "home_score": 0, "away_score": 1},
                {"home_team": "B", "away_team": "M", "home_score": 2, "away_score": 0},
            ],
        },
    )
    assert any("серии без побед" in reason for reason in winless["reasons"])

    fallback = match_signals._build_motivation_signal(match, {})
    assert fallback["reasons"] == ["базовая турнирная мотивация без экстремального фона"]


def test_build_revenge_signal_branches_and_fallback():
    match = {"team1": "A", "team2": "B"}
    assert match_signals._build_revenge_signal(match, {"h2h": []})["reasons"] == [
        "очных встреч в доступной выборке недостаточно"
    ]

    recent_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    revenge = match_signals._build_revenge_signal(
        match,
        {
            "h2h": [
                {"date": recent_date, "home_team": "A", "away_team": "B", "home_score": 0, "away_score": 3},
                {"date": "2025-12-01", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 2},
            ]
        },
    )
    assert any("последней очной" in reason for reason in revenge["reasons"])
    assert any("крупным" in reason for reason in revenge["reasons"])

    no_signal = match_signals._build_revenge_signal(
        match,
        {"h2h": [{"date": "2025-01-01", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 1}]},
    )
    assert no_signal["reasons"] == ["очные не дают сильного сигнала на реванш"]


def test_build_confidence_thresholds():
    low = match_signals._build_confidence({})
    medium = match_signals._build_confidence({"standings": {"table": [{}]}, "h2h": [{}]})
    high = match_signals._build_confidence(
        {
            "standings": {"table": [{}]},
            "h2h": [{}],
            "team1_form": [{}],
            "team2_form": [{}],
            "team1_last_match_stats": {"shots": 5},
            "team1_meta": {"country": "A"},
            "team2_meta": {"country": "B"},
            "round": "1/2",
            "league_id": "epl",
        }
    )

    assert low["label"] == "низкая"
    assert medium["label"] == "средняя"
    assert high["label"] == "высокая"


def test_build_match_signals_returns_all_keys_with_full_data():
    recent_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    match = {"team1": "Arsenal", "team2": "Chelsea"}
    data = {
        "team1_meta": {"country": "England", "stadium_location": "London, UK"},
        "team2_meta": {"country": "England", "stadium_location": "London, UK"},
        "h2h": [
            {"date": recent_date, "home_team": "Arsenal", "away_team": "Chelsea", "home_score": 0, "away_score": 2},
            {"date": "2025-12-01", "home_team": "Chelsea", "away_team": "Arsenal", "home_score": 2, "away_score": 1},
            {"date": "2025-09-01", "home_team": "Arsenal", "away_team": "Chelsea", "home_score": 1, "away_score": 0},
            {"date": "2025-06-01", "home_team": "Chelsea", "away_team": "Arsenal", "home_score": 1, "away_score": 1},
            {"date": "2025-03-01", "home_team": "Arsenal", "away_team": "Chelsea", "home_score": 3, "away_score": 2},
        ],
        "h2h_recent_stats": [
            {
                "stats": {
                    "Жёлтые карточки": {"home": "3", "away": "3"},
                    "Красные карточки": {"home": "0", "away": "0"},
                    "Фолы": {"home": "14", "away": "12"},
                }
            }
        ],
        "standings": {
            "table": [
                {"name": "Arsenal", "rank": 2, "points": 61},
                {"name": "Chelsea", "rank": 3, "points": 60},
            ]
        },
        "team1_form": [
            {"home_team": "Arsenal", "away_team": "X", "home_score": 1, "away_score": 1},
            {"home_team": "Y", "away_team": "Arsenal", "home_score": 0, "away_score": 2},
        ],
        "team2_form": [
            {"home_team": "Chelsea", "away_team": "Z", "home_score": 0, "away_score": 0},
            {"home_team": "W", "away_team": "Chelsea", "home_score": 1, "away_score": 0},
        ],
        "team1_last_match_stats": {"shots": 10},
        "team2_last_match_stats": {"shots": 9},
        "round": "1/2 финала",
        "league_id": "epl",
        "is_cup": True,
    }

    result = match_signals.build_match_signals(match, data)

    assert set(result.keys()) == {"derby", "motivation", "revenge", "confidence"}
    assert result["derby"]["score"] > 0
    assert result["motivation"]["score"] > 0
    assert result["revenge"]["score"] > 0
    assert result["confidence"]["label"] in {"низкая", "средняя", "высокая"}


def test_build_match_signals_gracefully_handles_empty_data():
    result = match_signals.build_match_signals({"team1": "A", "team2": "B"}, {})

    assert set(result.keys()) == {"derby", "motivation", "revenge", "confidence"}
    assert result["derby"]["score"] >= 0
    assert result["motivation"]["score"] >= 0
    assert result["revenge"]["score"] >= 0
    assert result["confidence"]["label"] in {"низкая", "средняя", "высокая"}
