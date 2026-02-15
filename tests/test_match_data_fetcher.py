"""Unit-тесты для match_data_fetcher.py."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from match_data_fetcher import (  # noqa: E402
    MatchDataFetcher,
    build_enriched_context,
    _calculate_stats_from_form,
    _determine_tournament_zone,
    _assess_home_away_quality,
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
                    "intHomeScore": 2,
                    "intAwayScore": 1,
                    "strStatus": "Match Finished"
                },
                {
                    "dateEvent": "2025-01-12",
                    "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal",
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
            assert result[0]['score'] == "2:1"
            assert result[1]['home_team'] == "Chelsea"
            assert result[1]['away_team'] == "Arsenal"
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
        with patch.object(fetcher, '_fetch_h2h', return_value=([{'date': '2025-08-25', 'score': '2:1'}], True)), \
             patch.object(fetcher, '_fetch_event_details', return_value={'league_id': '4328', 'season': '2025-2026'}), \
             patch.object(fetcher, '_fetch_standings', return_value={'table': [{'name': 'Arsenal', 'rank': 1}]}), \
             patch.object(fetcher, '_fetch_team_last_matches', return_value=[{'date': '2026-02-10', 'score': '2:1'}]):

            result = fetcher.fetch_match_data(match)

            assert len(result['h2h']) == 1
            assert result['h2h_is_current_season'] is True
            assert 'table' in result['standings']
            assert len(result['team1_form']) == 1
            assert len(result['team2_form']) == 1
            assert len(result['errors']) == 0


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
        assert "Последние 2 матчей" in context
        assert "2025-08-25: Arsenal 2:1 Chelsea" in context
        assert "2025-01-12: Chelsea 3:2 Arsenal" in context

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
        assert "Chelsea: #5 место (зона еврокубков), 43 очков после 23 матчей" in context

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
        """Пустые данные возвращают заглушки для ключевых игроков и составов."""
        match = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'Premier League'}
        data = {
            'h2h': [],
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        # Новый формат всегда включает заглушки
        assert "КЛЮЧЕВЫЕ ИГРОКИ" in context
        assert "СОСТАВЫ" in context
        assert "Нет данных" in context

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
            'standings': {},
            'team1_form': [],
            'team2_form': []
        }

        context = build_enriched_context(match, data)

        assert "ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ" in context
        assert "В текущем сезоне команды не встречались" in context
        assert "Последние встречи из прошлых сезонов" in context
        assert "2024-09-22: Rayo Vallecano 1:1 Atletico Madrid" in context


class TestHelperFunctions:
    """Тесты для вспомогательных функций вычисления статистики."""

    def test_calculate_stats_from_form_home(self):
        """Вычисление статистики для домашней команды."""
        form_matches = [
            {'home_team': 'Arsenal', 'away_team': 'Liverpool', 'home_score': 2, 'away_score': 1},
            {'home_team': 'Arsenal', 'away_team': 'Chelsea', 'home_score': 0, 'away_score': 0},
            {'home_team': 'Arsenal', 'away_team': 'Man Utd', 'home_score': 3, 'away_score': 1},
        ]

        stats = _calculate_stats_from_form(form_matches, is_home=True)

        assert stats['scored_pct'] > 60  # Забивали в 2 из 3 матчей (66%)
        assert stats['home_away_form'] == 'WDW'
        assert stats['home_away_points'] == 7  # 2 победы + 1 ничья
        assert stats['home_away_record'] == '2В,1Н,0П'
        assert stats['avg_scored'] > 1.5  # (2+0+3)/3 = 1.67

    def test_calculate_stats_from_form_away(self):
        """Вычисление статистики для выездной команды."""
        form_matches = [
            {'home_team': 'Liverpool', 'away_team': 'Chelsea', 'home_score': 2, 'away_score': 3},
            {'home_team': 'Man Utd', 'away_team': 'Chelsea', 'home_score': 1, 'away_score': 1},
            {'home_team': 'Spurs', 'away_team': 'Chelsea', 'home_score': 0, 'away_score': 2},
        ]

        stats = _calculate_stats_from_form(form_matches, is_home=False)

        assert stats['home_away_form'] == 'WDW'
        assert stats['home_away_points'] == 7  # 2 победы + 1 ничья
        assert stats['home_away_record'] == '2В,1Н,0П'
        assert stats['conceded_pct'] > 60  # Пропускали в 2 из 3 матчей

    def test_calculate_stats_from_form_empty(self):
        """Пустой список матчей возвращает пустой dict."""
        stats = _calculate_stats_from_form([], is_home=True)

        assert stats == {}

    def test_determine_tournament_zone_champions_league(self):
        """Топ-4 в топ-лигах = зона ЛЧ."""
        assert _determine_tournament_zone(1, 'English Premier League') == 'зона ЛЧ'
        assert _determine_tournament_zone(4, 'La Liga') == 'зона ЛЧ'
        assert _determine_tournament_zone(3, 'Bundesliga') == 'зона ЛЧ'

    def test_determine_tournament_zone_europa(self):
        """5-7 место = зона еврокубков."""
        assert _determine_tournament_zone(5, 'Premier League') == 'зона еврокубков'
        assert _determine_tournament_zone(7, 'La Liga') == 'зона еврокубков'
        assert _determine_tournament_zone(6, 'Serie A') == 'зона еврокубков'

    def test_determine_tournament_zone_relegation(self):
        """18+ место = зона вылета."""
        assert _determine_tournament_zone(18, 'Premier League') == 'зона вылета'
        assert _determine_tournament_zone(20, 'Bundesliga') == 'зона вылета'
        assert _determine_tournament_zone(19, 'Ligue 1') == 'зона вылета'

    def test_determine_tournament_zone_midtable(self):
        """Средние позиции = пустая строка."""
        assert _determine_tournament_zone(10, 'Premier League') == ''
        assert _determine_tournament_zone(12, 'La Liga') == ''

    def test_assess_home_away_quality_strong(self):
        """Сильная форма: >=2.0 очка за матч."""
        assert _assess_home_away_quality(24, 12) == 'Сильная'  # 2.0 очка/матч
        assert _assess_home_away_quality(30, 12) == 'Сильная'  # 2.5 очка/матч

    def test_assess_home_away_quality_medium(self):
        """Средняя форма: 1.2-2.0 очка за матч."""
        assert _assess_home_away_quality(18, 12) == 'Средняя'  # 1.5 очка/матч
        assert _assess_home_away_quality(15, 12) == 'Средняя'  # 1.25 очка/матч

    def test_assess_home_away_quality_weak(self):
        """Слабая форма: <1.2 очка за матч."""
        assert _assess_home_away_quality(10, 12) == 'Слабая'  # 0.83 очка/матч
        assert _assess_home_away_quality(6, 12) == 'Слабая'   # 0.5 очка/матч

    def test_assess_home_away_quality_no_matches(self):
        """Нет матчей = недостаточно данных."""
        assert _assess_home_away_quality(0, 0) == 'Недостаточно данных'

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

    def test_fetch_h2h_with_season_filter(self):
        """H2H фильтруется по текущему сезону."""
        fetcher = MatchDataFetcher(api_key="test_key")

        # Мок: 5 матчей (3 в сезоне 2025-26, 2 в 2024-25)
        mock_response = {
            "event": [
                {
                    "dateEvent": "2025-10-20", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 2, "intAwayScore": 1
                },
                {
                    "dateEvent": "2026-03-15", "strStatus": "FT", "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal", "intHomeScore": 1, "intAwayScore": 1
                },
                {
                    # Прошлый сезон
                    "dateEvent": "2024-08-10", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 3, "intAwayScore": 0
                },
                {
                    "dateEvent": "2026-01-05", "strStatus": "FT", "strHomeTeam": "Chelsea",
                    "strAwayTeam": "Arsenal", "intHomeScore": 2, "intAwayScore": 2
                },
                {
                    # Прошлый сезон
                    "dateEvent": "2024-05-30", "strStatus": "FT", "strHomeTeam": "Arsenal",
                    "strAwayTeam": "Chelsea", "intHomeScore": 1, "intAwayScore": 0
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
