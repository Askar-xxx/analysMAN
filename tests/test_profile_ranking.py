import sqlite3
from datetime import datetime, timedelta

from profile_ranking import compute_catalog_score, compute_profile_score, select_profile_matches
from sync_matches import SportsDBSyncer


def _match(team1, team2, league, match_date, match_time):
    return {
        "team1": team1,
        "team2": team2,
        "league": league,
        "match_date": match_date,
        "match_time": match_time,
    }


def _sqlite_row_from_match(match):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE matches (
            team1 TEXT,
            team2 TEXT,
            league TEXT,
            match_date TEXT,
            match_time TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO matches (team1, team2, league, match_date, match_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            match["team1"],
            match["team2"],
            match["league"],
            match["match_date"],
            match["match_time"],
        ),
    )
    row = conn.execute("SELECT * FROM matches").fetchone()
    conn.close()
    return row


def test_compute_catalog_score_matches_sync_logic():
    syncer = SportsDBSyncer()
    match = _match(
        "Liverpool",
        "Manchester United",
        "UEFA Champions League. 1/2 финала",
        "2026-03-08",
        "22:00",
    )

    assert compute_catalog_score(match) == syncer._score_match(match)


def test_compute_profile_score_prioritizes_near_future_over_tomorrow():
    now = datetime(2026, 3, 7, 12, 0)
    today_match = _match(
        "Arsenal",
        "Chelsea",
        "Premier League",
        "2026-03-07",
        "14:00",
    )
    tomorrow_match = _match(
        "Arsenal",
        "Chelsea",
        "Premier League",
        "2026-03-08",
        "14:00",
    )

    assert compute_profile_score(today_match, now) > compute_profile_score(tomorrow_match, now)


def test_compute_profile_score_penalizes_recent_live_match():
    now = datetime(2026, 3, 7, 12, 0)
    live_match = _match(
        "Arsenal",
        "Chelsea",
        "Premier League",
        "2026-03-07",
        "10:30",
    )
    future_match = _match(
        "Arsenal",
        "Chelsea",
        "Premier League",
        "2026-03-07",
        "14:00",
    )

    assert compute_profile_score(future_match, now) > compute_profile_score(live_match, now)


def test_select_profile_matches_uses_profile_sorting():
    now = datetime(2026, 3, 7, 12, 0)
    matches = [
        _match("Arsenal", "Chelsea", "Premier League", "2026-03-08", "14:00"),
        _match("Liverpool", "Manchester United", "Premier League", "2026-03-07", "16:00"),
        _match("Real Madrid", "Barcelona", "La Liga", "2026-03-09", "21:00"),
        _match("Inter", "Juventus", "Serie A", "2026-03-07", "19:00"),
    ]

    selected = select_profile_matches(matches, now, limit=3)

    assert len(selected) == 3
    assert [match["team1"] for match in selected] == ["Liverpool", "Arsenal", "Real Madrid"]


def test_profile_ranking_accepts_sqlite_rows():
    now = datetime(2026, 3, 7, 12, 0)
    row = _sqlite_row_from_match(
        _match(
            "Liverpool",
            "Manchester United",
            "Premier League",
            "2026-03-07",
            "16:00",
        )
    )

    assert compute_catalog_score(row) > 0
    selected = select_profile_matches([row], now, limit=1)
    assert len(selected) == 1
    assert selected[0]["team1"] == "Liverpool"
