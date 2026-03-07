"""Интеграционные тесты для sync_matches.py."""
import sys
import os
import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from sync_matches import SportsDBSyncer, run_coverage_check  # noqa: E402

# Генерируем актуальные даты для моков (today и tomorrow)
_today = datetime.now().date()
_tomorrow = _today + timedelta(days=1)

# Мок-ответ API (3 матча)
MOCK_EVENTS_RESPONSE = {
    "events": [
        {
            "idEvent": "1001",
            "strEvent": "Arsenal vs Chelsea",
            "strHomeTeam": "Arsenal",
            "strAwayTeam": "Chelsea",
            "dateEvent": _today.strftime('%Y-%m-%d'),
            "strTime": "15:00:00",
            "strLeague": "Premier League",
            "intRound": "30",
            "strVenue": "Emirates Stadium",
            "strStatus": "Scheduled",
            "idHomeTeam": "133604",
            "idAwayTeam": "133610",
            "intHomeScore": None,
            "intAwayScore": None,
        },
        {
            "idEvent": "1002",
            "strEvent": "Liverpool vs Man Utd",
            "strHomeTeam": "Liverpool",
            "strAwayTeam": "Manchester United",
            "dateEvent": _today.strftime('%Y-%m-%d'),
            "strTime": "17:30:00",
            "strLeague": "Premier League",
            "intRound": "30",
            "strVenue": "Anfield",
            "strStatus": "Scheduled",
            "idHomeTeam": "133602",
            "idAwayTeam": "133612",
            "intHomeScore": None,
            "intAwayScore": None,
        },
        {
            "idEvent": "1003",
            "strEvent": "Tottenham vs Man City",
            "strHomeTeam": "Tottenham",
            "strAwayTeam": "Manchester City",
            "dateEvent": _tomorrow.strftime('%Y-%m-%d'),
            "strTime": "20:00:00",
            "strLeague": "Premier League",
            "intRound": "30",
            "strVenue": "Tottenham Stadium",
            "strStatus": "Scheduled",
            "idHomeTeam": "133616",
            "idAwayTeam": "133613",
            "intHomeScore": None,
            "intAwayScore": None,
        },
    ]
}


def _build_match(
    api_event_id,
    team1,
    team2,
    match_date,
    match_time,
    league,
):
    return {
        "sport": "football",
        "team1": team1,
        "team2": team2,
        "match_date": match_date,
        "match_time": match_time,
        "league": league,
        "api_event_id": api_event_id,
        "price": 150,
        "is_active": 1,
        "source": "TheSportsDB",
    }

# SQL для создания тестовой схемы
CREATE_MATCHES_SQL = '''
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport TEXT NOT NULL,
        team1 TEXT NOT NULL,
        team2 TEXT NOT NULL,
        match_date TEXT NOT NULL,
        match_time TEXT NOT NULL,
        league TEXT,
        venue TEXT,
        api_event_id TEXT UNIQUE,
        source TEXT,
        home_team_id TEXT,
        away_team_id TEXT,
        home_score INTEGER,
        away_score INTEGER,
        match_datetime TEXT,
        round TEXT,
        status TEXT DEFAULT 'Scheduled',
        analysis_text TEXT,
        price INTEGER DEFAULT 150,
        is_active BOOLEAN DEFAULT 1,
        coverage_ok INTEGER DEFAULT NULL,
        coverage_checked_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
'''


def _create_test_db():
    """Создать временную тестовую БД."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_MATCHES_SQL)
    conn.commit()
    conn.close()
    return db_path


def _insert_match(
    db_path,
    *,
    api_event_id,
    match_date,
    coverage_ok=None,
    team1="Team A",
    team2="Team B",
    match_time="23:59"
):
    """Добавляет тестовый матч в БД и возвращает его id."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO matches (
            sport, team1, team2, match_date, match_time,
            league, api_event_id, source, home_team_id, away_team_id,
            price, is_active, coverage_ok
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            'football',
            team1,
            team2,
            match_date,
            match_time,
            'Premier League',
            api_event_id,
            'TheSportsDB',
            '1',
            '2',
            150,
            1,
            coverage_ok
        )
    )
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


def _db_connection_factory(db_path):
    """Фабрика для подмены database.get_db_connection в тестах витрины."""

    def _get_conn():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    return _get_conn


class TestSyncTop3:
    """Тесты: default mode (top3) вставляет ровно 3 матча."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_top3_inserts_exactly_3(self, mock_api):
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="top3", limit=3
            )
            matches = syncer.sync()
            assert len(matches) == 3
            results = syncer.save_matches_to_db(matches)
            assert results['inserted'] == 3
        finally:
            os.unlink(db_path)

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_top3_respects_limit(self, mock_api):
        """Лимит top3 с limit=2 возвращает ровно 2 матча."""
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="top3", limit=2
            )
            matches = syncer.sync()
            assert len(matches) == 2
        finally:
            os.unlink(db_path)


class TestIdempotence:
    """Тесты: повторный sync не создаёт дубликатов."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_no_duplicates_on_resync(self, mock_api):
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="top3", limit=3
            )
            # Первый sync
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)
            # Второй sync (повторный)
            matches2 = syncer.sync()
            results2 = syncer.save_matches_to_db(matches2)
            assert results2['inserted'] == 0
            assert results2['skipped'] == 3
            # Проверяем общее количество в БД
            conn = sqlite3.connect(db_path)
            count = conn.execute(
                'SELECT COUNT(*) FROM matches'
            ).fetchone()[0]
            conn.close()
            assert count == 3
        finally:
            os.unlink(db_path)


class TestTracing:
    """Тесты: каждый матч имеет api_event_id и source."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_tracing_fields_present(self, mock_api):
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="top3", limit=3
            )
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM matches').fetchall()
            assert len(rows) == 3
            for row in rows:
                assert row['api_event_id'] is not None
                assert row['source'] == 'TheSportsDB'
                assert row['home_team_id'] is not None
                assert row['away_team_id'] is not None
                assert row['match_datetime'] is not None
            conn.close()
        finally:
            os.unlink(db_path)

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_team_ids_match_api(self, mock_api):
        """home_team_id и away_team_id соответствуют данным API."""
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="top3", limit=3
            )
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM matches ORDER BY api_event_id'
            ).fetchall()
            # Первый матч: Arsenal vs Chelsea
            assert rows[0]['home_team_id'] == '133604'
            assert rows[0]['away_team_id'] == '133610'
            conn.close()
        finally:
            os.unlink(db_path)


class TestBulkMode:
    """Тесты: режим all сохраняет все матчи."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    def test_all_mode_saves_all(self, mock_api):
        """Режим all сохраняет все полученные матчи."""
        mock_api.return_value = MOCK_EVENTS_RESPONSE
        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(
                db_path=db_path, mode="all"
            )
            matches = syncer.get_week_matches()
            results = syncer.save_matches_to_db(matches)
            # Все матчи должны быть вставлены (без дублей)
            assert results['errors'] == 0
            assert results['inserted'] + results['skipped'] == results['total']
        finally:
            os.unlink(db_path)


class TestTop3Ranking:
    """Тесты гибридного рейтинга и мягких квот по дням."""

    def test_normalize_team_name_strips_diacritics(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)

        assert syncer._normalize_team_name("Atlético Madrid") == "atletico madrid"
        assert syncer._normalize_team_name("Paris SG") == "paris saint-germain"
        assert syncer._normalize_team_name("Inter Milan") == "inter"

    def test_accented_team_name_gets_same_weight(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)

        assert syncer._get_team_weight("Atlético Madrid") == syncer._get_team_weight("Atletico Madrid")
        assert syncer._get_team_weight("Atlético Madrid") == 8

    def test_accented_tier_team_outranks_non_tier_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        accented_match = _build_match(
            "accented",
            "Atlético Madrid",
            "Real Sociedad",
            _today,
            "20:30",
            "La Liga. 27 тур",
        )
        regular_match = _build_match(
            "regular-accent",
            "Osasuna",
            "Mallorca",
            _today,
            "20:30",
            "La Liga. 27 тур",
        )

        assert syncer._score_match(accented_match) > syncer._score_match(regular_match)

    def test_day_quotas_keep_all_three_days_in_limit_15(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        day0 = _today
        day1 = _today + timedelta(days=1)
        day2 = _today + timedelta(days=2)
        matches = []

        for idx in range(6):
            matches.append(
                _build_match(
                    f"d0-{idx}",
                    f"Day0 Team {idx}",
                    f"Day0 Opp {idx}",
                    day0,
                    f"{12 + idx:02d}:00",
                    "Premier League. 30 тур",
                )
            )
        for idx in range(6):
            matches.append(
                _build_match(
                    f"d1-{idx}",
                    f"Day1 Team {idx}",
                    f"Day1 Opp {idx}",
                    day1,
                    f"{12 + idx:02d}:00",
                    "La Liga. 27 тур",
                )
            )
        matches.extend([
            _build_match("d2-0", "Real Madrid", "Barcelona", day2, "20:00", "UEFA Champions League. 1/8 финала"),
            _build_match("d2-1", "Arsenal", "Chelsea", day2, "18:00", "Premier League. 30 тур"),
            _build_match("d2-2", "Benfica", "Roma", day2, "16:00", "UEFA Europa League. 1/8 финала"),
            _build_match("d2-3", "Day2 Team 3", "Day2 Opp 3", day2, "14:00", "Ligue 1. 22 тур"),
            _build_match("d2-4", "Day2 Team 4", "Day2 Opp 4", day2, "12:00", "Bundesliga. 24 тур"),
        ])

        selected = syncer._select_top_matches_with_day_quotas(matches, limit=15)

        counts = {}
        for match in selected:
            counts[str(match["match_date"])] = counts.get(str(match["match_date"]), 0) + 1

        assert len(selected) == 15
        assert counts[str(day0)] >= 3
        assert counts[str(day1)] >= 3
        assert counts[str(day2)] >= 3

    def test_missing_day_capacity_is_redistributed(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        day0 = _today
        day1 = _today + timedelta(days=1)
        day2 = _today + timedelta(days=2)
        matches = [
            _build_match("d2-0", "Real Madrid", "Barcelona", day2, "20:00", "UEFA Champions League. 1/8 финала"),
            _build_match("d2-1", "Arsenal", "Chelsea", day2, "18:00", "Premier League. 30 тур"),
        ]

        for idx in range(8):
            matches.append(
                _build_match(
                    f"d0-{idx}",
                    f"Day0 Team {idx}",
                    f"Day0 Opp {idx}",
                    day0,
                    f"{10 + idx:02d}:00",
                    "Premier League. 30 тур",
                )
            )
        for idx in range(8):
            matches.append(
                _build_match(
                    f"d1-{idx}",
                    f"Day1 Team {idx}",
                    f"Day1 Opp {idx}",
                    day1,
                    f"{10 + idx:02d}:00",
                    "Serie A. 28 тур",
                )
            )

        selected = syncer._select_top_matches_with_day_quotas(matches, limit=15)
        counts = {}
        for match in selected:
            counts[str(match["match_date"])] = counts.get(str(match["match_date"]), 0) + 1

        assert len(selected) == 15
        assert counts[str(day2)] == 2
        assert counts[str(day0)] + counts[str(day1)] == 13

    def test_strong_match_on_third_day_survives_dense_first_days(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        day0 = _today
        day1 = _today + timedelta(days=1)
        day2 = _today + timedelta(days=2)
        matches = []

        for idx in range(10):
            matches.append(
                _build_match(
                    f"d0-{idx}",
                    f"Mid Day0 {idx}",
                    f"Opp Day0 {idx}",
                    day0,
                    f"{10 + idx:02d}:00",
                    "Ligue 1. 22 тур",
                )
            )
        for idx in range(10):
            matches.append(
                _build_match(
                    f"d1-{idx}",
                    f"Mid Day1 {idx}",
                    f"Opp Day1 {idx}",
                    day1,
                    f"{10 + idx:02d}:00",
                    "Bundesliga. 24 тур",
                )
            )
        marquee = _build_match(
            "d2-marquee",
            "Real Madrid",
            "Barcelona",
            day2,
            "21:00",
            "UEFA Champions League. 1/4 финала",
        )
        matches.extend([
            marquee,
            _build_match("d2-1", "Arsenal", "Chelsea", day2, "19:00", "Premier League. 30 тур"),
            _build_match("d2-2", "Benfica", "Roma", day2, "17:00", "UEFA Europa League. 1/8 финала"),
        ])

        selected = syncer._select_top_matches_with_day_quotas(matches, limit=15)

        assert any(match["api_event_id"] == "d2-marquee" for match in selected)

    def test_tier_a_match_outranks_regular_same_league_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        big_match = _build_match(
            "big",
            "Arsenal",
            "Chelsea",
            _today,
            "19:00",
            "Premier League. 30 тур",
        )
        regular_match = _build_match(
            "regular",
            "Wolves",
            "Brentford",
            _today,
            "18:00",
            "Premier League. 30 тур",
        )

        assert syncer._score_match(big_match) > syncer._score_match(regular_match)

    def test_tier_a_and_tier_b_match_outranks_regular_same_league_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        premium_match = _build_match(
            "premium",
            "Arsenal",
            "Roma",
            _today,
            "19:00",
            "Premier League. 30 С‚СѓСЂ",
        )
        regular_match = _build_match(
            "regular-ab",
            "Wolves",
            "Brentford",
            _today,
            "18:00",
            "Premier League. 30 С‚СѓСЂ",
        )

        assert syncer._score_match(premium_match) > syncer._score_match(regular_match)

    def test_ucl_outranks_mid_tier_league_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        ucl_match = _build_match(
            "ucl",
            "Benfica",
            "Roma",
            _today,
            "20:00",
            "UEFA Champions League. 1/8 финала",
        )
        league_match = _build_match(
            "league",
            "Day Team 1",
            "Day Team 2",
            _today,
            "18:00",
            "Ligue 1. 22 тур",
        )

        assert syncer._score_match(ucl_match) > syncer._score_match(league_match)

    def test_stage_bonus_boosts_playoff_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        playoff_match = _build_match(
            "playoff",
            "Benfica",
            "Roma",
            _today,
            "20:00",
            "UEFA Europa League. 1/4 финала",
        )
        league_match = _build_match(
            "league",
            "Benfica",
            "Roma",
            _today,
            "20:00",
            "UEFA Europa League",
        )

        assert syncer._score_match(playoff_match) > syncer._score_match(league_match)

    def test_neutral_match_penalty_is_applied(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        neutral_match = _build_match(
            "neutral",
            "Team A",
            "Team B",
            _today,
            "20:00",
            "La Liga. 27 С‚СѓСЂ",
        )

        breakdown = syncer._score_match_breakdown(neutral_match)

        assert breakdown["penalty"] == 4
        assert breakdown["total"] == 26

    def test_neutral_match_penalty_not_applied_to_playoff_match(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        playoff_match = _build_match(
            "neutral-playoff",
            "Team A",
            "Team B",
            _today,
            "20:00",
            "UEFA Europa League. Quarter-final",
        )

        breakdown = syncer._score_match_breakdown(playoff_match)

        assert breakdown["stage"] == 10
        assert breakdown["penalty"] == 0

    def test_premium_pair_bonus_applies_only_for_strong_league_and_team_weight(self):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        premium_match = _build_match(
            "premium-pair",
            "Arsenal",
            "Roma",
            _today,
            "20:00",
            "Premier League. 30 С‚СѓСЂ",
        )
        not_premium_match = _build_match(
            "not-premium-pair",
            "Arsenal",
            "Roma",
            _today,
            "20:00",
            "Ligue 1. 22 С‚СѓСЂ",
        )

        assert syncer._get_premium_pair_bonus(premium_match) == 4
        assert syncer._get_premium_pair_bonus(not_premium_match) == 0

    def test_limit_below_9_skips_day_quotas(self):
        syncer = SportsDBSyncer(mode="top3", limit=2)
        day0 = _today
        day1 = _today + timedelta(days=1)
        matches = [
            _build_match("day1-big", "Real Madrid", "Barcelona", day1, "21:00", "UEFA Champions League. 1/4 финала"),
            _build_match("day1-mid", "Arsenal", "Chelsea", day1, "19:00", "Premier League. 30 тур"),
            _build_match("day0-low", "Team A", "Team B", day0, "11:00", "Ligue 1. 22 тур"),
            _build_match("day0-low2", "Team C", "Team D", day0, "12:00", "Ligue 1. 22 тур"),
        ]

        selected = syncer._select_top_matches_with_day_quotas(matches, limit=2)

        assert len(selected) == 2
        assert [match["api_event_id"] for match in selected] == ["day1-big", "day1-mid"]

    def test_selected_matches_are_logged_in_info(self, caplog):
        syncer = SportsDBSyncer(mode="top3", limit=15)
        day0 = _today
        day1 = _today + timedelta(days=1)
        day2 = _today + timedelta(days=2)
        matches = []

        for idx in range(4):
            matches.append(
                _build_match(
                    f"d0-{idx}",
                    f"Day0 Team {idx}",
                    f"Day0 Opp {idx}",
                    day0,
                    f"{12 + idx:02d}:00",
                    "Premier League. 30 С‚СѓСЂ",
                )
            )
            matches.append(
                _build_match(
                    f"d1-{idx}",
                    f"Day1 Team {idx}",
                    f"Day1 Opp {idx}",
                    day1,
                    f"{12 + idx:02d}:00",
                    "La Liga. 27 С‚СѓСЂ",
                )
            )
        matches.extend([
            _build_match("d2-0", "Real Madrid", "Barcelona", day2, "20:00", "UEFA Champions League. 1/8 С„РёРЅР°Р»Р°"),
            _build_match("d2-1", "Arsenal", "Chelsea", day2, "18:00", "Premier League. 30 С‚СѓСЂ"),
            _build_match("d2-2", "Benfica", "Roma", day2, "16:00", "UEFA Europa League. 1/8 С„РёРЅР°Р»Р°"),
            _build_match("d2-3", "Day2 Team 3", "Day2 Opp 3", day2, "14:00", "Ligue 1. 22 С‚СѓСЂ"),
        ])

        with caplog.at_level(logging.INFO, logger="sync_matches"):
            selected = syncer._select_top_matches_with_day_quotas(matches, limit=10)

        assert len(selected) == 10
        selected_logs = [
            record.message for record in caplog.records
            if record.message.startswith("Top3 selected [")
        ]
        assert len(selected_logs) == 10
        assert any("Top3 selected [Q]" in message for message in selected_logs)
        assert any("Top3 selected [G]" in message for message in selected_logs)
        assert any("score=" in message for message in selected_logs)


class TestCoverageCheck:
    """Тесты фоновой проверки покрытия."""

    @patch('match_data_fetcher.MatchDataFetcher.fetch_match_data')
    @patch('analysis_formatter.build_table_data')
    def test_coverage_check_sets_ok(self, mock_build_table_data, mock_fetch_match_data):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            match_id = _insert_match(
                db_path,
                api_event_id='cov-ok-1',
                match_date=future_date,
                coverage_ok=None
            )
            mock_fetch_match_data.return_value = {}
            mock_build_table_data.return_value = {
                'raw_coverage_rows_count': 6,
                'raw_missing_cells_count': 1,
            }

            results = run_coverage_check(db_path=db_path, sleep_seconds=0)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT coverage_ok, coverage_checked_at FROM matches WHERE id = ?',
                (match_id,)
            ).fetchone()
            conn.close()

            assert results['checked'] == 1
            assert results['ok'] == 1
            assert results['hidden'] == 0
            assert row[0] == 1
            assert row[1] is not None
        finally:
            os.unlink(db_path)

    @patch('match_data_fetcher.MatchDataFetcher.fetch_match_data')
    @patch('analysis_formatter.build_table_data')
    def test_coverage_check_sets_bad(self, mock_build_table_data, mock_fetch_match_data):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            match_id = _insert_match(
                db_path,
                api_event_id='cov-bad-1',
                match_date=future_date,
                coverage_ok=None
            )
            mock_fetch_match_data.return_value = {}
            mock_build_table_data.return_value = {
                'raw_coverage_rows_count': 1,
                'raw_missing_cells_count': 3,
            }

            results = run_coverage_check(db_path=db_path, sleep_seconds=0)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT coverage_ok, coverage_checked_at FROM matches WHERE id = ?',
                (match_id,)
            ).fetchone()
            conn.close()

            assert results['checked'] == 1
            assert results['ok'] == 0
            assert results['hidden'] == 1
            assert row[0] == 0
            assert row[1] is not None
        finally:
            os.unlink(db_path)

    @patch('match_data_fetcher.MatchDataFetcher.fetch_match_data')
    @patch('analysis_formatter.build_table_data')
    def test_coverage_check_rechecks_old_hidden_match(
        self,
        mock_build_table_data,
        mock_fetch_match_data
    ):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        stale_checked_at = (
            datetime.now() - timedelta(hours=4)
        ).strftime('%Y-%m-%d %H:%M:%S')
        try:
            match_id = _insert_match(
                db_path,
                api_event_id='cov-recheck-old-1',
                match_date=future_date,
                coverage_ok=0
            )
            conn = sqlite3.connect(db_path)
            conn.execute(
                'UPDATE matches SET coverage_checked_at = ? WHERE id = ?',
                (stale_checked_at, match_id)
            )
            conn.commit()
            conn.close()

            mock_fetch_match_data.return_value = {}
            mock_build_table_data.return_value = {
                'raw_coverage_rows_count': 6,
                'raw_missing_cells_count': 0,
            }

            results = run_coverage_check(db_path=db_path, sleep_seconds=0)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT coverage_ok, coverage_checked_at FROM matches WHERE id = ?',
                (match_id,)
            ).fetchone()
            conn.close()

            assert results['checked'] == 1
            assert results['ok'] == 1
            assert results['hidden'] == 0
            assert row[0] == 1
            assert row[1] is not None
            assert row[1] != stale_checked_at
        finally:
            os.unlink(db_path)

    @patch('match_data_fetcher.MatchDataFetcher.fetch_match_data')
    @patch('analysis_formatter.build_table_data')
    def test_coverage_check_rechecks_hidden_match_without_timestamp(
        self,
        mock_build_table_data,
        mock_fetch_match_data
    ):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            match_id = _insert_match(
                db_path,
                api_event_id='cov-recheck-null-1',
                match_date=future_date,
                coverage_ok=0
            )

            mock_fetch_match_data.return_value = {}
            mock_build_table_data.return_value = {
                'raw_coverage_rows_count': 6,
                'raw_missing_cells_count': 0,
            }

            results = run_coverage_check(db_path=db_path, sleep_seconds=0)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT coverage_ok, coverage_checked_at FROM matches WHERE id = ?',
                (match_id,)
            ).fetchone()
            conn.close()

            assert results['checked'] == 1
            assert results['ok'] == 1
            assert results['hidden'] == 0
            assert row[0] == 1
            assert row[1] is not None
        finally:
            os.unlink(db_path)


class TestStorefrontCoverageFilter:
    """Тесты фильтрации витрины по coverage_ok."""

    def test_storefront_hides_unchecked(self):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            _insert_match(
                db_path,
                api_event_id='store-null-1',
                match_date=future_date,
                coverage_ok=None
            )
            with patch(
                'database.get_db_connection',
                side_effect=_db_connection_factory(db_path)
            ):
                matches = database.get_matches_by_date_filtered('football', future_date)
                dates = database.get_available_dates_with_matches('football')
            assert len(matches) == 0
            assert future_date not in dates
        finally:
            os.unlink(db_path)

    def test_storefront_hides_bad(self):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            _insert_match(
                db_path,
                api_event_id='store-bad-1',
                match_date=future_date,
                coverage_ok=0
            )
            with patch(
                'database.get_db_connection',
                side_effect=_db_connection_factory(db_path)
            ):
                matches = database.get_matches_by_date_filtered('football', future_date)
                dates = database.get_available_dates_with_matches('football')
            assert len(matches) == 0
            assert future_date not in dates
        finally:
            os.unlink(db_path)

    def test_storefront_shows_good(self):
        db_path = _create_test_db()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            _insert_match(
                db_path,
                api_event_id='store-good-1',
                match_date=future_date,
                coverage_ok=1
            )
            with patch(
                'database.get_db_connection',
                side_effect=_db_connection_factory(db_path)
            ):
                matches = database.get_matches_by_date_filtered('football', future_date)
                dates = database.get_available_dates_with_matches('football')
            assert len(matches) == 1
            assert dates == [future_date]
        finally:
            os.unlink(db_path)


class TestRoundFormatting:
    """Тесты форматирования тура/раунда в строке лиги."""

    def test_cup_round_is_human_readable(self):
        syncer = SportsDBSyncer(mode="top3", limit=1)
        event = {
            "idEvent": "2001",
            "strHomeTeam": "Team A",
            "strAwayTeam": "Team B",
            "dateEvent": _today.strftime('%Y-%m-%d'),
            "strTime": "19:00:00",
            "strLeague": "UEFA Champions League",
            "idLeague": "4480",
            "intRound": "32",
            "idHomeTeam": "1",
            "idAwayTeam": "2",
        }

        parsed = syncer._parse_event(event)
        assert parsed is not None
        assert parsed['league'] == "UEFA Champions League. 1/16 финала"

    def test_league_round_keeps_tour_suffix(self):
        syncer = SportsDBSyncer(mode="top3", limit=1)
        event = {
            "idEvent": "2002",
            "strHomeTeam": "Team A",
            "strAwayTeam": "Team B",
            "dateEvent": _today.strftime('%Y-%m-%d'),
            "strTime": "19:00:00",
            "strLeague": "Premier League",
            "idLeague": "4328",
            "intRound": "30",
            "idHomeTeam": "1",
            "idAwayTeam": "2",
        }

        parsed = syncer._parse_event(event)
        assert parsed is not None
        assert parsed['league'] == "Premier League. 30 тур"
