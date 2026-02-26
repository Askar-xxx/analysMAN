"""Интеграционные тесты для sync_matches.py."""
import sys
import os
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
