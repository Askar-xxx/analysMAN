"""Интеграционные тесты для sync_matches.py."""
import sys
import os
import sqlite3
import json
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
        raw_json TEXT,
        source TEXT,
        home_team_id TEXT,
        away_team_id TEXT,
        home_score INTEGER,
        away_score INTEGER,
        match_datetime TEXT,
        round TEXT,
        h2h_json TEXT,
        h2h_fetched_at TEXT,
        standings_json TEXT,
        standings_fetched_at TEXT,
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
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_top3_inserts_exactly_3(self, mock_week, mock_api):
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
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_top3_respects_limit(self, mock_week, mock_api):
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
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_no_duplicates_on_resync(self, mock_week, mock_api):
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
    """Тесты: каждый матч имеет api_event_id, raw_json, source."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_tracing_fields_present(self, mock_week, mock_api):
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
                assert row['raw_json'] is not None
                assert row['source'] == 'TheSportsDB'
                assert row['home_team_id'] is not None
                assert row['away_team_id'] is not None
                assert row['match_datetime'] is not None
                # raw_json должен быть валидным JSON
                parsed = json.loads(row['raw_json'])
                assert 'idEvent' in parsed
            conn.close()
        finally:
            os.unlink(db_path)

    @patch('sync_matches.RateLimitedAPI.make_request')
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_team_ids_match_api(self, mock_week, mock_api):
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
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_all_mode_saves_all(self, mock_week, mock_api):
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


class TestEnrichment:
    """Тесты: обогащение матчей H2H и standings."""

    @patch('sync_matches.RateLimitedAPI.make_request')
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_enrich_h2h_saves_to_db(self, mock_week, mock_api):
        """H2H данные сохраняются в БД с timestamp."""
        # Mock для sync
        mock_api.return_value = MOCK_EVENTS_RESPONSE

        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(db_path=db_path, mode="top3", limit=1)
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)

            # Mock для H2H API
            mock_h2h_response = {
                "event": [
                    {
                        "dateEvent": "2025-08-25",
                        "strHomeTeam": "Arsenal",
                        "strAwayTeam": "Chelsea",
                        "intHomeScore": 2,
                        "intAwayScore": 1
                    }
                ]
            }

            with patch.object(syncer.api, 'make_request', return_value=mock_h2h_response):
                # Получаем match_id
                conn = sqlite3.connect(db_path)
                match_id = conn.execute('SELECT id FROM matches LIMIT 1').fetchone()[0]
                conn.close()

                # Вызываем fetch_h2h напрямую
                result = syncer.fetch_h2h(match_id, "Arsenal", "Chelsea")

                # Проверяем что данные сохранились
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute('SELECT h2h_json, h2h_fetched_at FROM matches WHERE id = ?',
                                   (match_id,)).fetchone()
                conn.close()

                assert row['h2h_json'] is not None
                assert row['h2h_fetched_at'] is not None
                assert "Arsenal" in row['h2h_json']
                assert result is not None

        finally:
            os.unlink(db_path)

    @patch('sync_matches.RateLimitedAPI.make_request')
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_enrich_standings_saves_to_db(self, mock_week, mock_api):
        """Standings данные сохраняются в БД с timestamp."""
        # Mock для sync
        mock_api.return_value = MOCK_EVENTS_RESPONSE

        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(db_path=db_path, mode="top3", limit=1)
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)

            # Mock для standings API
            mock_standings_response = {
                "table": [
                    {
                        "strTeam": "Arsenal",
                        "intRank": "1",
                        "intPoints": "56",
                        "strForm": "WWDWL",
                        "intGoalDifference": "32",
                        "intGoalsFor": "49",
                        "intGoalsAgainst": "17"
                    }
                ]
            }

            with patch.object(syncer.api, 'make_request', return_value=mock_standings_response):
                # Получаем match_id
                conn = sqlite3.connect(db_path)
                row = conn.execute('SELECT id, raw_json FROM matches LIMIT 1').fetchone()
                match_id = row[0]
                raw_json_str = row[1]
                conn.close()

                # Добавляем idLeague и strSeason в raw_json для теста
                raw_json = json.loads(raw_json_str)
                raw_json['idLeague'] = '4328'
                raw_json['strSeason'] = '2025-2026'

                conn = sqlite3.connect(db_path)
                conn.execute('UPDATE matches SET raw_json = ? WHERE id = ?',
                             (json.dumps(raw_json), match_id))
                conn.commit()
                conn.close()

                # Вызываем fetch_standings
                result = syncer.fetch_standings(match_id, '4328', '2025-2026', '133604', '133610')

                # Проверяем что данные сохранились
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute('SELECT standings_json, standings_fetched_at FROM matches WHERE id = ?',
                                   (match_id,)).fetchone()
                conn.close()

                assert row['standings_json'] is not None
                assert row['standings_fetched_at'] is not None
                assert "Arsenal" in row['standings_json']
                assert result is not None

        finally:
            os.unlink(db_path)

    @patch('sync_matches.RateLimitedAPI.make_request')
    @patch('sync_matches.SportsDBSyncer._is_within_week', return_value=True)
    def test_enrich_matches_full_flow(self, mock_week, mock_api):
        """Полный flow enrich_matches: матчи обогащаются H2H и standings."""
        # Mock для sync
        mock_api.return_value = MOCK_EVENTS_RESPONSE

        db_path = _create_test_db()
        try:
            syncer = SportsDBSyncer(db_path=db_path, mode="top3", limit=1)
            matches = syncer.sync()
            syncer.save_matches_to_db(matches)

            # Добавляем idLeague и strSeason в raw_json
            conn = sqlite3.connect(db_path)
            rows = conn.execute('SELECT id, raw_json FROM matches').fetchall()
            for row in rows:
                raw_json = json.loads(row[1])
                raw_json['idLeague'] = '4328'
                raw_json['strSeason'] = '2025-2026'
                conn.execute('UPDATE matches SET raw_json = ? WHERE id = ?',
                             (json.dumps(raw_json), row[0]))
            conn.commit()
            conn.close()

            # Mock для H2H и standings API
            mock_h2h = {"event": [{"dateEvent": "2025-08-25", "strHomeTeam": "Arsenal",
                                   "strAwayTeam": "Chelsea", "intHomeScore": 2, "intAwayScore": 1}]}
            mock_standings = {"table": [{"strTeam": "Arsenal", "intRank": "1", "intPoints": "56"}]}

            def mock_request_side_effect(endpoint, params=None):
                if 'searchevents' in endpoint:
                    return mock_h2h
                elif 'lookuptable' in endpoint:
                    return mock_standings
                return {}

            with patch.object(syncer.api, 'make_request', side_effect=mock_request_side_effect):
                # Вызываем enrich_matches
                stats = syncer.enrich_matches()

                # Проверяем результаты
                assert stats['h2h_enriched'] >= 1
                assert stats['standings_enriched'] >= 1

                # Проверяем БД
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT h2h_json, standings_json FROM matches').fetchall()
                conn.close()

                for row in rows:
                    assert row['h2h_json'] is not None
                    assert row['standings_json'] is not None

        finally:
            os.unlink(db_path)
