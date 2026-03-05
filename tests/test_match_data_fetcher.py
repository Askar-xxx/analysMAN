"""Unit-тесты для match_data_fetcher.py."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from match_data_fetcher import (  # noqa: E402
    MatchDataFetcher,
    build_enriched_context,
    _get_season_date_range
)


class TestMatchDataFetcher:
    """Тесты класса MatchDataFetcher с мок-данными."""

    def test_fetch_h2h_success(self):
        """H2H данные корректно получаются и парсятся."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "event": [
                {
                    "dateEvent": "2025-08-25",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea",
                    "idHomeTeam": "133604",
                    "idAwayTeam": "133610",
                    "intHomeScore": 2,
                    "intAwayScore": 1,
                    "strStatus": "Match Finished"
                },
                {
                    "dateEvent": "2025-01-12",
                    "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal",
                    "idHomeTeam": "133610",
                    "idAwayTeam": "133604",
                    "intHomeScore": 3,
                    "intAwayScore": 2,
                    "strStatus": "FT"
                }
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result, is_current_season = fetcher._fetch_h2h("Arsenal", "Chelsea")

            assert len(result) == 2
            assert is_current_season is True  # Без фильтрации = текущий сезон
            assert result[0]['home_team'] == "Arsenal"
            assert result[0]['away_team'] == "Chelsea"
            assert result[0]['home_team_id'] == "133604"
            assert result[0]['away_team_id'] == "133610"
            assert result[0]['score'] == "2:1"
            assert result[1]['home_team'] == "Chelsea"
            assert result[1]['away_team'] == "Arsenal"
            assert result[1]['home_team_id'] == "133610"
            assert result[1]['away_team_id'] == "133604"
            assert result[1]['score'] == "3:2"

    def test_fetch_h2h_no_data(self):
        """H2H возвращает пустой список если данных нет."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {"event": None}

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result, is_current_season = fetcher._fetch_h2h("Team1", "Team2")

            assert result == []
            assert is_current_season is True

    def test_fetch_standings_success(self):
        """Standings данные корректно получаются и парсятся."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "table": [
                {
                    "strTeam": "Arsenal",
                    "intRank": "1",
                    "intPoints": "56",
                    "intWin": "18",
                    "intDraw": "2",
                    "intLoss": "3",
                    "intGoalsFor": "55",
                    "intGoalsAgainst": "20",
                    "intGoalDifference": "35",
                    "strForm": "WWDWL",
                    "intPlayed": "23"
                },
                {
                    "strTeam": "Chelsea",
                    "intRank": "5",
                    "intPoints": "43",
                    "intWin": "12",
                    "intDraw": "7",
                    "intLoss": "4",
                    "intGoalsFor": "45",
                    "intGoalsAgainst": "28",
                    "intGoalDifference": "17",
                    "strForm": "WWWWL",
                    "intPlayed": "23"
                }
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_standings(4328, "2025-2026")

            assert result['league_id'] == 4328
            assert result['season'] == "2025-2026"
            assert len(result['table']) == 2
            assert result['table'][0]['name'] == "Arsenal"
            assert result['table'][0]['rank'] == 1
            assert result['table'][0]['points'] == 56
            assert result['table'][0]['form'] == "WWDWL"

    def test_fetch_standings_no_data(self):
        """Standings возвращает пустой dict если данных нет."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {"table": None}

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_standings(4328, "2025-2026")

            assert result == {}

    def test_fetch_team_last_matches_success(self):
        """Последние матчи команды корректно получаются."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "results": [
                {
                    "dateEvent": "2026-02-10",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Liverpool",
                    "intHomeScore": 2,
                    "intAwayScore": 1,
                    "strLeague": "Premier League"
                },
                {
                    "dateEvent": "2026-02-03",
                    "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal",
                    "intHomeScore": 0,
                    "intAwayScore": 2,
                    "strLeague": "Premier League"
                }
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_team_last_matches(133604, limit=5)

            assert len(result) == 2
            assert result[0]['home_team'] == "Arsenal"
            assert result[0]['score'] == "2:1"
            assert result[1]['away_team'] == "Arsenal"

    def test_fetch_event_details_success(self):
        """Детали события корректно получаются."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "events": [
                {
                    "idEvent": "1001",
                    "idLeague": "4328",
                    "strSeason": "2025-2026",
                    "strEvent": "Arsenal vs Chelsea",
                    "dateEvent": "2026-02-20"
                }
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_event_details(1001)

            assert result['league_id'] == "4328"
            assert result['season'] == "2025-2026"
            assert result['event_name'] == "Arsenal vs Chelsea"

    def test_fetch_team_details_includes_aliases(self):
        """Team details include parsed aliases from short/alternate names."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "teams": [
                {
                    "idLeague": "4328",
                    "strLeague": "Premier League",
                    "strTeam": "Wolverhampton Wanderers",
                    "strTeamShort": "Wolves",
                    "strAlternate": "Wolves, Wolverhampton",
                    "strCountry": "England",
                    "strStadiumLocation": "Wolverhampton"
                }
            ]
        }

        with patch.object(fetcher, '_get_with_retry') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_team_details("4063")

            assert result is not None
            assert result['team_short'] == "Wolves"
            assert result['team_alternate'] == "Wolves, Wolverhampton"
            assert "Wolves" in result['aliases']
            assert "Wolverhampton" in result['aliases']

    def test_fetch_cup_matches_by_season_filters_finished_and_season(self):
        """Кубковые матчи фильтруются по завершённости и текущему сезону."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "events": [
                {
                    "dateEvent": "2026-02-20",
                    "strSeason": "2025-2026",
                    "strStatus": "FT",
                    "strHomeTeam": "Juventus",
                    "strAwayTeam": "Galatasaray",
                    "intHomeScore": 2,
                    "intAwayScore": 1,
                },
                {
                    "dateEvent": "2026-02-18",
                    "strSeason": "2025-2026",
                    "strStatus": "Postponed",
                    "strHomeTeam": "Team A",
                    "strAwayTeam": "Team B",
                    "intHomeScore": None,
                    "intAwayScore": None,
                },
                {
                    "dateEvent": "2025-11-15",
                    "strSeason": "2024-2025",
                    "strStatus": "FT",
                    "strHomeTeam": "Old Team",
                    "strAwayTeam": "Legacy Team",
                    "intHomeScore": 1,
                    "intAwayScore": 0,
                }
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result = fetcher._fetch_cup_matches_by_season("4481", "2025-2026")

            assert len(result) == 1
            assert result[0]['dateEvent'] == "2026-02-20"
            assert mock_get.call_args[0][0].endswith('/eventsseason.php')

    def test_build_cup_path_from_events_filters_team_and_limit(self):
        """Кубковый путь берёт только матчи нужной команды и режется по лимиту."""
        events = [
            {
                "dateEvent": "2026-02-21",
                "strStatus": "FT",
                "strHomeTeam": "Juventus",
                "strAwayTeam": "Galatasaray",
                "intHomeScore": 1,
                "intAwayScore": 0,
            },
            {
                "dateEvent": "2026-02-18",
                "strStatus": "FT",
                "strHomeTeam": "Galatasaray",
                "strAwayTeam": "Juventus",
                "intHomeScore": 3,
                "intAwayScore": 2,
            },
            {
                "dateEvent": "2026-02-12",
                "strStatus": "FT",
                "strHomeTeam": "Another Team",
                "strAwayTeam": "Other Team",
                "intHomeScore": 2,
                "intAwayScore": 2,
            },
        ]

        result = MatchDataFetcher._build_cup_path_from_events(events, "Juventus", limit=2)

        assert len(result) == 2
        assert result[0] == "2026-02-21: Juventus 1:0 Galatasaray"
        assert result[1] == "2026-02-18: Galatasaray 3:2 Juventus"

    def test_build_last_match_events_filters_by_team_side(self):
        """События последнего матча фильтруются по нужной команде."""
        fetcher = MatchDataFetcher(api_key="test_key")
        form_match = {
            'event_id': '1001',
            'home_team': 'Arsenal',
            'away_team': 'Chelsea',
        }
        timeline = [
            {
                'strTimeline': 'subst',
                'strTimelineDetail': 'Player In',
                'strPlayer': 'Player Out',
                'strHome': 'Yes',
                'strTeam': 'Arsenal',
            },
            {
                'strTimeline': 'Card',
                'strTimelineDetail': 'Yellow Card',
                'strPlayer': 'Away Defender',
                'strHome': 'No',
                'strTeam': 'Chelsea',
            },
            {
                'strTimeline': 'Card',
                'strTimelineDetail': 'Red Card',
                'strPlayer': 'Home Midfielder',
                'strHome': 'Yes',
                'strTeam': 'Arsenal',
            },
        ]

        with patch.object(fetcher, '_fetch_timeline', return_value=timeline):
            result = fetcher._build_last_match_events(form_match, 'Arsenal')

        assert result['subs'] == ['Player Out → Player In']
        assert result['cards'] == ['Home Midfielder (КК)']

    def test_fetch_match_data_integration(self):
        """Полный flow fetch_match_data с моками."""
        fetcher = MatchDataFetcher(api_key="test_key")

        match = {
            'team1': 'Arsenal',
            'team2': 'Chelsea',
            'home_team_id': '133604',
            'away_team_id': '133610',
            'api_event_id': '1001'
        }

        # Моки для всех API вызовов
        with patch.object(
            fetcher, '_fetch_season_h2h_via_schedule',
            return_value=([{'date': '2025-08-25', 'score': '2:1'}], True)
        ), patch.object(
            fetcher, '_fetch_h2h',
            return_value=([{'date': '2025-08-25', 'score': '2:1'}], True)
        ), patch.object(
            fetcher, '_fetch_event_details',
            return_value={'league_id': '4328', 'season': '2025-2026'}
        ), patch.object(
            fetcher, '_fetch_standings',
            return_value={'table': [{'name': 'Arsenal', 'rank': 1}]}
        ), patch.object(
            fetcher, '_fetch_team_last_matches',
            return_value=[{'date': '2026-02-10', 'score': '2:1'}]
        ):

            result = fetcher.fetch_match_data(match)

            assert len(result['h2h']) == 1
            assert result['h2h_is_current_season'] is True
            assert result['h2h_season_source'] == 'schedule'
            assert 'table' in result['standings']
            assert len(result['team1_form']) == 1
            assert len(result['team2_form']) == 1
            assert len(result['errors']) == 0

    def test_fetch_match_data_with_schedule_confirmed_fallback(self):
        """Если schedule подтверждает отсутствие матчей в сезоне, используем историю прошлых сезонов."""
        fetcher = MatchDataFetcher(api_key="test_key")

        match = {
            'team1': 'Rayo Vallecano',
            'team2': 'Atletico Madrid',
            'home_team_id': '1',
            'away_team_id': '2',
            'api_event_id': '1001'
        }

        with patch.object(fetcher, '_fetch_season_h2h_via_schedule', return_value=([], True)), \
             patch.object(fetcher, '_fetch_h2h', return_value=([{'date': '2024-09-22', 'score': '1:1'}], True)), \
             patch.object(fetcher, '_fetch_event_details', return_value={'league_id': '4335', 'season': '2025-2026'}), \
             patch.object(fetcher, '_fetch_standings', return_value={}), \
             patch.object(fetcher, '_fetch_team_last_matches', return_value=[]):

            result = fetcher.fetch_match_data(match)

            assert len(result['h2h']) == 1
            assert result['h2h_is_current_season'] is False
            assert result['h2h_season_source'] == 'schedule_confirmed'


class TestBuildEnrichedContext:
    """Тесты форматирования обогащённого контекста."""

    def test_build_context_with_h2h(self):
        """Контекст корректно форматирует H2H данные."""
        match = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'Premier League'}
        data = {
            'h2h': [
                {'date': '2025-08-25', 'home_team': 'Arsenal', 'away_team': 'Chelsea', 'score': '2:1'},
                {'date': '2025-01-12', 'home_team': 'Chelsea', 'away_team': 'Arsenal', 'score': '3:2'}
            ],
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        assert "ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ" in context
        assert "2025-08-25: Arsenal 2:1 Chelsea" in context
        assert "2025-01-12: Chelsea 3:2 Arsenal" in context

    def test_build_context_h2h_alias_normalization_without_match_ids(self):
        """H2H names normalize by aliases from team meta when H2H rows miss team ids."""
        match = {
            'team1': 'Wolverhampton Wanderers',
            'team2': 'Liverpool',
            'home_team_id': '4063',
            'away_team_id': '133602',
            'league': 'FA Cup',
        }
        data = {
            'h2h': [
                {'date': '2026-03-03', 'home_team': 'Wolverhampton Wanderers', 'away_team': 'Liverpool',
                 'score': '2:1', 'home_team_id': '4063', 'away_team_id': '133602'},
                {'date': '2024-09-28', 'home_team': 'Wolves', 'away_team': 'Liverpool', 'score': '1:2'},
            ],
            'h2h_is_current_season': False,
            'h2h_season_source': 'schedule_confirmed',
            'team1_meta': {
                'team_name': 'Wolverhampton Wanderers',
                'team_short': 'Wolves',
                'team_alternate': 'Wolves',
                'aliases': ['Wolves'],
            },
            'standings': {},
            'team1_form': [],
            'team2_form': [],
        }

        context = build_enriched_context(match, data)

        assert "2026-03-03: Wolverhampton Wanderers 2:1 Liverpool" in context
        assert "2024-09-28: Wolverhampton Wanderers 1:2 Liverpool" in context

    def test_build_context_h2h_normalizes_alias_by_team_id(self):
        """Alias names in H2H are normalized to match team names using team ids."""
        match = {
            'team1': 'Wolverhampton Wanderers',
            'team2': 'Liverpool',
            'home_team_id': '4063',
            'away_team_id': '133602',
            'league': 'Premier League',
        }
        data = {
            'h2h': [
                {
                    'date': '2025-09-28',
                    'home_team': 'Wolves',
                    'away_team': 'Liverpool',
                    'home_team_id': '4063',
                    'away_team_id': '133602',
                    'score': '1:2'
                }
            ],
            'standings': {},
            'team1_form': [],
            'team2_form': [],
        }

        context = build_enriched_context(match, data)

        assert "2025-09-28: Wolverhampton Wanderers 1:2 Liverpool" in context

    def test_build_context_with_standings(self):
        """Контекст корректно форматирует standings."""
        match = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'Premier League'}
        data = {
            'h2h': [],
            'standings': {
                'table': [
                    {'name': 'Arsenal', 'rank': 1, 'points': 56, 'form': 'WWDWL', 'goaldifference': 35, 'played': 23},
                    {'name': 'Chelsea', 'rank': 5, 'points': 43, 'form': 'WWWWL', 'goaldifference': 17, 'played': 23}
                ],
                'season': '2025-2026'
            },
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        assert "ТУРНИРНОЕ ПОЛОЖЕНИЕ" in context
        assert "Arsenal: #1 место (зона ЛЧ), 56 очков после 23 матчей" in context
        assert "Chelsea: #5 место (зона еврокубков), 43 очка после 23 матчей" in context

    def test_build_context_with_form(self):
        """Контекст корректно форматирует form данные."""
        match = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'Premier League'}
        data = {
            'h2h': [],
            'standings': {},
            'team1_form': [
                {
                    'date': '2026-02-10', 'home_team': 'Arsenal', 'away_team': 'Liverpool',
                    'home_score': 2, 'away_score': 1
                }
            ],
            'team2_form': [
                {
                    'date': '2026-02-09', 'home_team': 'Man Utd', 'away_team': 'Chelsea',
                    'home_score': 0, 'away_score': 3
                }
            ]
        }

        context = build_enriched_context(match, data)

        assert "ТЕКУЩАЯ ФОРМА" in context
        assert "Arsenal: W" in context
        assert "Chelsea: W" in context

    def test_build_context_empty_data(self):
        """Пустые данные возвращают сообщение о недоступности."""
        match = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'Premier League'}
        data = {
            'h2h': [],
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        # При полностью пустых данных — сообщение о недоступности
        assert "недоступн" in context.lower()

    def test_build_context_h2h_fallback_text(self):
        """H2H с fallback показывает текст о прошлых сезонах."""
        match = {'team1': 'Rayo Vallecano', 'team2': 'Atletico Madrid', 'league': 'La Liga'}
        data = {
            'h2h': [
                {
                    'date': '2024-09-22', 'home_team': 'Rayo Vallecano',
                    'away_team': 'Atletico Madrid', 'score': '1:1'
                }
            ],
            'h2h_is_current_season': False,  # Флаг fallback
            'h2h_season_source': 'schedule_confirmed',
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        assert "ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ" in context
        assert "В этом сезоне лиги команды ещё не встречались." in context
        assert "Последние встречи из прошлых сезонов" in context
        assert "2024-09-22: Rayo Vallecano 1:1 Atletico Madrid" in context

    def test_build_context_h2h_error_text(self):
        """При ошибке schedule показываем нейтральный текст про отсутствие данных."""
        match = {'team1': 'Bournemouth', 'team2': 'Brentford', 'league': 'Premier League'}
        data = {
            'h2h': [
                {
                    'date': '2024-09-14', 'home_team': 'Brentford',
                    'away_team': 'Bournemouth', 'score': '2:1'
                }
            ],
            'h2h_is_current_season': False,
            'h2h_season_source': 'error',
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        assert "Данные о встречах в текущем сезоне не найдены." in context
        assert "Последние встречи из прошлых сезонов" in context
        assert "2024-09-14: Brentford 2:1 Bournemouth" in context


class TestHelperFunctions:
    """Тесты для вспомогательных функций вычисления статистики."""

    def test_get_season_date_range_premier_league(self):
        """Границы сезона для Premier League (август-май)."""
        from datetime import date
        start, end = _get_season_date_range("2025-2026", "4328")
        assert start == date(2025, 8, 1)
        assert end == date(2026, 5, 31)

    def test_get_season_date_range_champions_league(self):
        """Границы сезона для CL (сентябрь-май)."""
        from datetime import date
        start, end = _get_season_date_range("2025-2026", "4480")
        assert start == date(2025, 9, 1)
        assert end == date(2026, 5, 31)

    def test_get_season_date_range_invalid_format(self):
        """Некорректный формат сезона вызывает ValueError."""
        import pytest
        with pytest.raises(ValueError):
            _get_season_date_range("2025", "4328")

    def test_compute_cache_ttl_live_today(self):
        """Живой матч сегодня → TTL 20 минут."""
        from datetime import date
        today = str(date.today())
        events = [
            {'dateEvent': today, 'strStatus': '2H'},
            {'dateEvent': '2025-09-01', 'strStatus': 'Match Finished'},
        ]
        ttl = MatchDataFetcher._compute_cache_ttl(events)
        assert ttl == 20 * 60

    def test_compute_cache_ttl_recent_finished(self):
        """Матч завершён в последние 48ч → TTL 1 час."""
        from datetime import date, timedelta
        yesterday = str(date.today() - timedelta(days=1))
        events = [
            {'dateEvent': yesterday, 'strStatus': 'Match Finished'},
            {'dateEvent': '2025-09-01', 'strStatus': 'Match Finished'},
        ]
        ttl = MatchDataFetcher._compute_cache_ttl(events)
        assert ttl == 1 * 3600

    def test_compute_cache_ttl_old_data(self):
        """Все матчи старые → TTL 6 часов."""
        events = [
            {'dateEvent': '2025-09-01', 'strStatus': 'Match Finished'},
            {'dateEvent': '2025-10-15', 'strStatus': 'FT'},
        ]
        ttl = MatchDataFetcher._compute_cache_ttl(events)
        assert ttl == 6 * 3600

    def test_fetch_h2h_with_season_filter(self):
        """H2H фильтруется по текущему сезону."""
        fetcher = MatchDataFetcher(api_key="test_key")

        # Мок: 6 матчей (3 в нужной лиге и сезоне, 2 из прошлых сезонов, 1 из кубка)
        mock_response = {
            "event": [
                {
                    "dateEvent": "2025-10-20", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 2, "intAwayScore": 1,
                    "idLeague": "4328"
                },
                {
                    "dateEvent": "2026-03-15", "strStatus": "FT", "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal", "intHomeScore": 1, "intAwayScore": 1,
                    "idLeague": "4328"
                },
                {
                    # Прошлый сезон
                    "dateEvent": "2024-08-10", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 3, "intAwayScore": 0,
                    "idLeague": "4328"
                },
                {
                    "dateEvent": "2026-01-05", "strStatus": "FT", "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal", "intHomeScore": 2, "intAwayScore": 2,
                    "idLeague": "4328"
                },
                {
                    # Прошлый сезон
                    "dateEvent": "2024-05-30", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 1, "intAwayScore": 0,
                    "idLeague": "4328"
                },
                {
                    # Тот же соперник, но другая лига (кубок) — должен быть исключён
                    "dateEvent": "2025-09-25", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 1, "intAwayScore": 0,
                    "idLeague": "4481"
                },
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            # Вызов с фильтрацией по сезону 2025-2026
            result, is_current_season = fetcher._fetch_h2h(
                "Arsenal", "Chelsea", season="2025-2026", league_id="4328"
            )

            # Ожидаем только 3 матча из текущего сезона
            assert len(result) == 3
            assert is_current_season is True  # Матчи найдены в текущем сезоне
            assert result[0]['date'] == "2025-10-20"
            assert result[1]['date'] == "2026-03-15"
            assert result[2]['date'] == "2026-01-05"

    def test_fetch_season_h2h_via_schedule_uses_cache_and_filters_pair(self):
        """Schedule H2H берёт только нужную пару и не делает повторный HTTP-запрос при cache hit."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "events": [
                {
                    "idEvent": "1",
                    "dateEvent": "2026-02-10",
                    "strStatus": "FT",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea",
                    "intHomeScore": 2,
                    "intAwayScore": 1
                },
                {
                    "idEvent": "2",
                    "dateEvent": "2025-11-01",
                    "strStatus": "Match Finished",
                    "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal",
                    "intHomeScore": 0,
                    "intAwayScore": 0
                },
                {
                    "idEvent": "3",
                    "dateEvent": "2025-12-01",
                    "strStatus": "FT",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Liverpool",
                    "intHomeScore": 3,
                    "intAwayScore": 1
                },
                {
                    "idEvent": "4",
                    "dateEvent": "2026-04-01",
                    "strStatus": "NS",
                    "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea",
                    "intHomeScore": None,
                    "intAwayScore": None
                },
            ]
        }

        with patch.object(fetcher, '_get_with_retry') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            result, data_ok = fetcher._fetch_season_h2h_via_schedule(
                "4328", "2025-2026", "Arsenal", "Chelsea"
            )
            cached_result, cached_data_ok = fetcher._fetch_season_h2h_via_schedule(
                "4328", "2025-2026", "Arsenal", "Chelsea"
            )

            assert data_ok is True
            assert cached_data_ok is True
            assert mock_get.call_count == 1
            assert len(result) == 2
            assert result[0]['date'] == "2026-02-10"
            assert result[1]['date'] == "2025-11-01"
            assert cached_result == result

    def test_fetch_h2h_without_season_filter(self):
        """H2H без фильтрации возвращает все матчи."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = {
            "event": [
                {
                    "dateEvent": "2025-10-20", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 2, "intAwayScore": 1
                },
                {
                    "dateEvent": "2024-08-10", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 3, "intAwayScore": 0
                },
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            # Вызов БЕЗ season/league_id
            result, is_current_season = fetcher._fetch_h2h("Arsenal", "Chelsea")

            # Ожидаем ВСЕ матчи
            assert len(result) == 2
            assert is_current_season is True  # Без фильтрации = True

    def test_fetch_h2h_fallback_to_previous_seasons(self):
        """H2H fallback на прошлые сезоны когда в текущем нет матчей."""
        fetcher = MatchDataFetcher(api_key="test_key")

        # Моки: все матчи из сезона 2024-2025 (до августа 2025)
        mock_response = {
            "event": [
                {
                    "dateEvent": "2024-09-22", "strStatus": "FT", "strHomeTeam": "Rayo Vallecano",
                    "strAwayTeam": "Atletico Madrid", "intHomeScore": 1, "intAwayScore": 1
                },
                {
                    "dateEvent": "2024-03-10", "strStatus": "FT", "strHomeTeam": "Atletico Madrid",
                    "strAwayTeam": "Rayo Vallecano", "intHomeScore": 2, "intAwayScore": 0
                },
            ]
        }

        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response

            # Вызов с фильтрацией по сезону 2025-2026
            result, is_current_season = fetcher._fetch_h2h(
                "Rayo Vallecano", "Atletico Madrid", season="2025-2026", league_id="4335"
            )

            # Ожидаем fallback: топ-2 самых свежих матча из прошлых сезонов
            assert len(result) == 2
            assert is_current_season is False  # Флаг fallback
            assert result[0]['date'] == "2024-09-22"  # Самый свежий
            assert result[1]['date'] == "2024-03-10"

    def test_fetch_team_last_matches_from_season(self):
        """Season schedule фильтрует матчи команды по ID и статусу."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_events = [
            {'idEvent': '1', 'dateEvent': '2026-02-20', 'strHomeTeam': 'Arsenal',
             'strAwayTeam': 'Liverpool', 'idHomeTeam': '133604', 'idAwayTeam': '133602',
             'intHomeScore': '2', 'intAwayScore': '1', 'strStatus': 'Match Finished',
             'strLeague': 'Premier League'},
            {'idEvent': '2', 'dateEvent': '2026-02-15', 'strHomeTeam': 'Chelsea',
             'strAwayTeam': 'Arsenal', 'idHomeTeam': '133610', 'idAwayTeam': '133604',
             'intHomeScore': '0', 'intAwayScore': '1', 'strStatus': 'Match Finished',
             'strLeague': 'Premier League'},
            {'idEvent': '3', 'dateEvent': '2026-03-01', 'strHomeTeam': 'Arsenal',
             'strAwayTeam': 'Wolves', 'idHomeTeam': '133604', 'idAwayTeam': '133614',
             'intHomeScore': None, 'intAwayScore': None, 'strStatus': 'Not Started',
             'strLeague': 'Premier League'},
            {'idEvent': '4', 'dateEvent': '2026-02-10', 'strHomeTeam': 'Man City',
             'strAwayTeam': 'Liverpool', 'idHomeTeam': '133613', 'idAwayTeam': '133602',
             'intHomeScore': '3', 'intAwayScore': '3', 'strStatus': 'Match Finished',
             'strLeague': 'Premier League'},
        ]

        mock_response = type('MockResponse', (), {
            'status_code': 200,
            'json': lambda self: {'events': mock_events}
        })()

        with patch.object(fetcher, '_get_with_retry', return_value=mock_response):
            result = fetcher._fetch_team_last_matches_from_season(
                team_id=133604, league_id='4328', season='2025-2026', limit=10
            )

        # Только Arsenal матчи со статусом finished, отсортированы по дате DESC
        assert len(result) == 2
        assert result[0]['date'] == '2026-02-20'
        assert result[1]['date'] == '2026-02-15'
        assert result[0]['home_team_id'] == '133604'
        assert result[1]['away_team_id'] == '133604'

    def test_form_matches_include_team_ids(self):
        """Матчи из eventslast содержат home_team_id/away_team_id."""
        fetcher = MatchDataFetcher(api_key="test_key")

        mock_response = type('MockResponse', (), {
            'status_code': 200,
            'json': lambda self: {'results': [{
                'dateEvent': '2026-02-20', 'strHomeTeam': 'Arsenal',
                'strAwayTeam': 'Liverpool', 'idHomeTeam': '133604',
                'idAwayTeam': '133602', 'intHomeScore': '2',
                'intAwayScore': '1', 'strLeague': 'PL', 'idEvent': '99',
            }]}
        })()

        with patch.object(fetcher, '_get_with_retry', return_value=mock_response):
            result = fetcher._fetch_team_last_matches(133604, limit=5)

        assert len(result) == 1
        assert result[0]['home_team_id'] == '133604'
        assert result[0]['away_team_id'] == '133602'
