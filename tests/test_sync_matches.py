"""Интеграционные тесты для sync_matches.py."""
import sys
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_matches import SportsDBSyncer  # noqa: E402

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
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
'''

CREATE_TEAMS_SQL = '''
    CREATE TABLE IF NOT EXISTS teams (
        team_id TEXT PRIMARY KEY,
        name TEXT,
        short_name TEXT,
        badge_url TEXT,
        sport TEXT DEFAULT 'football',
        raw_json TEXT,
        source TEXT,
        cached_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
'''


def _create_test_db():
    """Создать временную тестовую БД."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_MATCHES_SQL)
    conn.execute(CREATE_TEAMS_SQL)
    conn.commit()
    conn.close()
    return db_path


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
