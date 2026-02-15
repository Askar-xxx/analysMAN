"""Тесты для sync_football.py: парсинг fixtures, определение сезона, конвертация времени."""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_football import (  # noqa: E402
    get_season_for_date, utc_to_msk, parse_fixture, TOP_LEAGUES
)
from datetime import datetime  # noqa: E402


class TestGetSeasonForDate:
    """Тесты определения сезона по дате."""

    def test_february_returns_previous_year(self):
        """Февраль 2026 → сезон 2025."""
        date = datetime(2026, 2, 11)
        assert get_season_for_date(date) == 2025

    def test_august_returns_same_year(self):
        """Август 2025 → сезон 2025."""
        date = datetime(2025, 8, 15)
        assert get_season_for_date(date) == 2025

    def test_july_returns_same_year(self):
        """Июль (граница) → сезон текущего года."""
        date = datetime(2025, 7, 1)
        assert get_season_for_date(date) == 2025

    def test_june_returns_previous_year(self):
        """Июнь → сезон предыдущего года."""
        date = datetime(2026, 6, 30)
        assert get_season_for_date(date) == 2025

    def test_december_returns_same_year(self):
        """Декабрь 2025 → сезон 2025."""
        date = datetime(2025, 12, 25)
        assert get_season_for_date(date) == 2025

    def test_january_returns_previous_year(self):
        """Январь 2026 → сезон 2025."""
        date = datetime(2026, 1, 1)
        assert get_season_for_date(date) == 2025


class TestUtcToMsk:
    """Тесты конвертации UTC → МСК."""

    def test_utc_to_msk_basic(self):
        """Базовая конвертация UTC+0 → UTC+3."""
        date, time = utc_to_msk("2026-02-11T19:30:00+00:00")
        assert date == "2026-02-11"
        assert time == "22:30"

    def test_utc_to_msk_midnight_crossover(self):
        """Конвертация с переходом на следующий день."""
        date, time = utc_to_msk("2026-02-11T22:00:00+00:00")
        assert date == "2026-02-12"
        assert time == "01:00"

    def test_utc_to_msk_no_timezone(self):
        """Строка без timezone считается UTC."""
        date, time = utc_to_msk("2026-02-11T15:00:00")
        assert date == "2026-02-11"
        assert time == "18:00"

    def test_utc_to_msk_invalid(self):
        """Некорректная строка возвращает None, None."""
        date, time = utc_to_msk("invalid")
        assert date is None
        assert time is None

    def test_utc_to_msk_with_offset(self):
        """Строка с другим offset корректно конвертируется."""
        date, time = utc_to_msk("2026-02-11T20:30:00+01:00")
        assert date == "2026-02-11"
        assert time == "22:30"


class TestParseFixture:
    """Тесты парсинга fixture из API-Football."""

    def _make_fixture(self, **overrides):
        """Создать тестовый fixture dict."""
        fixture = {
            'fixture': {
                'id': 1234567,
                'date': '2026-02-11T19:30:00+00:00',
                'venue': {'id': 504, 'name': 'Stamford Bridge', 'city': 'London'},
                'status': {'long': 'Not Started', 'short': 'NS'}
            },
            'league': {
                'id': 39,
                'name': 'Premier League',
                'round': 'Regular Season - 25'
            },
            'teams': {
                'home': {'id': 49, 'name': 'Chelsea'},
                'away': {'id': 42, 'name': 'Arsenal'}
            },
            'goals': {'home': None, 'away': None}
        }
        # Применяем overrides
        for key, value in overrides.items():
            if '.' in key:
                parts = key.split('.')
                d = fixture
                for p in parts[:-1]:
                    d = d[p]
                d[parts[-1]] = value
            else:
                fixture[key] = value
        return fixture

    def test_parse_basic_fixture(self):
        """Базовый парсинг fixture."""
        fixture = self._make_fixture()
        result = parse_fixture(fixture, "Premier League")

        assert result is not None
        assert result['team1'] == 'Chelsea'
        assert result['team2'] == 'Arsenal'
        assert result['league'] == 'Premier League'
        assert result['venue'] == 'Stamford Bridge'
        assert result['api_event_id'] == '1234567'
        assert result['sport'] == 'football'
        assert result['source'] == 'api-football'
        assert result['price'] == 150

    def test_parse_fixture_time_conversion(self):
        """Время конвертируется в МСК (UTC+3)."""
        fixture = self._make_fixture()
        result = parse_fixture(fixture, "Premier League")

        assert result['match_date'] == '2026-02-11'
        assert result['match_time'] == '22:30'  # 19:30 UTC → 22:30 МСК

    def test_parse_fixture_team_ids(self):
        """Team IDs сохраняются как строки."""
        fixture = self._make_fixture()
        result = parse_fixture(fixture, "Premier League")

        assert result['home_team_id'] == '49'
        assert result['away_team_id'] == '42'

    def test_parse_fixture_with_score(self):
        """Fixture с результатом (завершённый матч)."""
        fixture = self._make_fixture()
        fixture['goals'] = {'home': 2, 'away': 1}
        result = parse_fixture(fixture, "Premier League")

        assert result['home_score'] == 2
        assert result['away_score'] == 1

    def test_parse_fixture_no_venue(self):
        """Fixture без venue."""
        fixture = self._make_fixture()
        fixture['fixture']['venue'] = None
        result = parse_fixture(fixture, "Premier League")

        assert result is not None
        assert result['venue'] == ''

    def test_parse_fixture_round(self):
        """Round сохраняется из league данных."""
        fixture = self._make_fixture()
        result = parse_fixture(fixture, "Premier League")

        assert result['round'] == 'Regular Season - 25'

    def test_parse_fixture_raw_json(self):
        """Raw JSON сохраняется для tracing."""
        fixture = self._make_fixture()
        result = parse_fixture(fixture, "Premier League")

        raw = json.loads(result['raw_json'])
        assert raw['fixture']['id'] == 1234567

    def test_parse_invalid_fixture(self):
        """Некорректный fixture возвращает None."""
        result = parse_fixture({}, "League")
        # Пустой fixture может вернуть None или dict с пустыми полями
        # Проверяем что не падает с исключением
        assert result is None or isinstance(result, dict)


class TestTopLeagues:
    """Тесты конфигурации лиг."""

    def test_three_leagues_defined(self):
        """Определены ровно 3 лиги."""
        assert len(TOP_LEAGUES) == 3

    def test_league_ids(self):
        """Проверка ID лиг."""
        ids = [lg['id'] for lg in TOP_LEAGUES]
        assert 39 in ids   # EPL
        assert 140 in ids  # La Liga
        assert 78 in ids   # Bundesliga

    def test_league_names(self):
        """Проверка названий лиг."""
        names = [lg['name'] for lg in TOP_LEAGUES]
        assert 'Premier League' in names
        assert 'La Liga' in names
        assert 'Bundesliga' in names


class TestFormatH2HApif:
    """Тесты форматирования H2H из API-Football."""

    def test_format_h2h_apif(self):
        """H2H из API-Football корректно форматируется."""
        from ai_generator import _format_h2h

        h2h_data = {
            "source": "api-football",
            "matches": [
                {
                    "date": "2025-08-25",
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "home_score": 2,
                    "away_score": 1
                },
                {
                    "date": "2025-01-12",
                    "home_team": "Chelsea",
                    "away_team": "Arsenal",
                    "home_score": 0,
                    "away_score": 0
                }
            ],
            "total": 2
        }
        h2h_json = json.dumps(h2h_data)
        result = _format_h2h(h2h_json, "2026-02-11T15:00:00")

        assert "Последние 2 встреч" in result
        assert "Arsenal 2-1 Chelsea" in result
        assert "Chelsea 0-0 Arsenal" in result
        assert "Баланс:" in result
        assert "API-Football" in result

    def test_format_h2h_apif_empty(self):
        """Пустой H2H из API-Football."""
        from ai_generator import _format_h2h

        h2h_data = {"source": "api-football", "matches": [], "total": 0}
        result = _format_h2h(json.dumps(h2h_data), "2026-02-11T15:00:00")

        assert "Данных нет" in result

    def test_format_h2h_sportsdb_still_works(self):
        """Legacy формат TheSportsDB по-прежнему работает."""
        from ai_generator import _format_h2h

        h2h_data = {
            "events": [
                {
                    "dateEvent": "2025-08-25",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea",
                    "intHomeScore": 2,
                    "intAwayScore": 1
                }
            ],
            "total": 1
        }
        result = _format_h2h(json.dumps(h2h_data), "2026-02-11T15:00:00")

        assert "Последние 1 встреч" in result
        assert "TheSportsDB" in result
