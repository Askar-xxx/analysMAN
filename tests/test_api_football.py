"""
Тесты для модуля sync_api_football.py

Этап 1: Тесты для fetch функций с моками API.
БЕЗ тестов сохранения в БД (будет в Этапе 2).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

# Добавляем родительскую папку в путь для импорта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sync_api_football import (  # noqa: E402
    APIFootballClient,
    QuotaExceededError
)


# === Mock данные ===

MOCK_TEAM_STATS_RESPONSE = {
    "response": {
        "league": {
            "id": 39,
            "name": "Premier League",
            "season": 2024
        },
        "team": {
            "id": 49,
            "name": "Chelsea"
        },
        "form": "WWDWL",
        "fixtures": {
            "played": {"home": 19, "away": 19, "total": 38},
            "wins": {"home": 12, "away": 8, "total": 20},
            "draws": {"home": 5, "away": 4, "total": 9},
            "loses": {"home": 2, "away": 7, "total": 9}
        },
        "goals": {
            "for": {
                "total": {"home": 35, "away": 29, "total": 64}
            },
            "against": {
                "total": {"home": 18, "away": 25, "total": 43}
            }
        }
    }
}

MOCK_INJURIES_RESPONSE = {
    "response": [
        {
            "player": {
                "id": 123,
                "name": "R. Lavia",
                "reason": "Thigh Injury",
                "type": "Missing Fixture"
            },
            "team": {
                "id": 49,
                "name": "Chelsea"
            },
            "fixture": {
                "id": 1001
            }
        },
        {
            "player": {
                "id": 124,
                "name": "C. Gallagher",
                "reason": "Injury",
                "type": "Missing Fixture"
            },
            "team": {
                "id": 49,
                "name": "Chelsea"
            },
            "fixture": {
                "id": 1002
            }
        }
    ]
}

MOCK_TOP_SCORERS_RESPONSE = {
    "response": [
        {
            "player": {
                "id": 200,
                "name": "Mohamed Salah"
            },
            "statistics": [
                {
                    "team": {"id": 42, "name": "Liverpool"},
                    "goals": {"total": 29, "assists": 5}
                }
            ]
        },
        {
            "player": {
                "id": 201,
                "name": "A. Isak"
            },
            "statistics": [
                {
                    "team": {"id": 34, "name": "Newcastle"},
                    "goals": {"total": 23, "assists": 3}
                }
            ]
        }
    ]
}

MOCK_STANDINGS_RESPONSE = {
    "response": [
        {
            "league": {
                "id": 39,
                "name": "Premier League",
                "season": 2024,
                "standings": [
                    [
                        {
                            "rank": 1,
                            "team": {"id": 42, "name": "Liverpool"},
                            "points": 84,
                            "all": {
                                "played": 37,
                                "win": 27,
                                "draw": 3,
                                "lose": 7,
                                "goals": {"for": 97, "against": 48}
                            },
                            "goalsDiff": 49,
                            "form": "WWDWL"
                        },
                        {
                            "rank": 2,
                            "team": {"id": 40, "name": "Arsenal"},
                            "points": 74,
                            "all": {
                                "played": 37,
                                "win": 23,
                                "draw": 5,
                                "lose": 9,
                                "goals": {"for": 85, "against": 50}
                            },
                            "goalsDiff": 35,
                            "form": "LWDWW"
                        }
                    ]
                ]
            }
        }
    ]
}


# === Тесты ===

class TestAPIFootballClient:
    """Тесты для класса APIFootballClient"""

    @patch('sync_api_football.requests.Session.get')
    def test_fetch_team_statistics(self, mock_get):
        """Тест получения статистики команды"""
        # Настраиваем мок
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_TEAM_STATS_RESPONSE
        mock_get.return_value = mock_response

        # Создаём клиента
        client = APIFootballClient(api_key="test_key")

        # Получаем статистику
        result = client.fetch_team_statistics("49", "39", "2024")

        # Проверки
        assert result is not None
        assert result['team_id'] == "49"
        assert result['team_name'] == "Chelsea"
        assert result['home_wins'] == 12
        assert result['home_draws'] == 5
        assert result['home_losses'] == 2
        assert result['away_wins'] == 8
        assert result['away_draws'] == 4
        assert result['away_losses'] == 7
        assert result['home_goals_for'] == 35
        assert result['home_goals_against'] == 18
        assert result['away_goals_for'] == 29
        assert result['away_goals_against'] == 25
        assert result['form'] == "WWDWL"

        # Проверяем что запрос был сделан
        assert mock_get.called
        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    def test_fetch_injuries(self, mock_get):
        """Тест получения травм"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_INJURIES_RESPONSE
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_injuries("49", "39", "2024")

        assert result is not None
        assert result['team_id'] == "49"
        assert result['team_name'] == "Chelsea"
        assert result['injuries_count'] == 2
        assert len(result['injuries']) == 2
        assert result['injuries'][0]['player_name'] == "R. Lavia"
        assert result['injuries'][0]['reason'] == "Thigh Injury"
        assert result['injuries'][1]['player_name'] == "C. Gallagher"
        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    def test_fetch_top_scorers(self, mock_get):
        """Тест получения топ-бомбардиров"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_TOP_SCORERS_RESPONSE
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_top_scorers("39", "2024", limit=10)

        assert result is not None
        assert result['league_id'] == "39"
        assert result['season'] == "2024"
        assert result['top_scorers_count'] == 2
        assert len(result['top_scorers']) == 2
        assert result['top_scorers'][0]['player_name'] == "Mohamed Salah"
        assert result['top_scorers'][0]['team_name'] == "Liverpool"
        assert result['top_scorers'][0]['goals'] == 29
        assert result['top_scorers'][1]['player_name'] == "A. Isak"
        assert result['top_scorers'][1]['goals'] == 23
        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    def test_fetch_full_standings(self, mock_get):
        """Тест получения полной таблицы"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_STANDINGS_RESPONSE
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_full_standings("39", "2024")

        assert result is not None
        assert result['league_id'] == "39"
        assert result['season'] == "2024"
        assert result['total_teams'] == 2
        assert len(result['standings']) == 2

        # Проверяем первую команду
        liverpool = result['standings'][0]
        assert liverpool['rank'] == 1
        assert liverpool['team_name'] == "Liverpool"
        assert liverpool['team_id'] == "42"
        assert liverpool['points'] == 84
        assert liverpool['played'] == 37
        assert liverpool['win'] == 27
        assert liverpool['form'] == "WWDWL"

        # Проверяем вторую команду
        arsenal = result['standings'][1]
        assert arsenal['rank'] == 2
        assert arsenal['team_name'] == "Arsenal"
        assert arsenal['points'] == 74

        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    def test_daily_quota_tracking(self, mock_get):
        """Тест отслеживания дневной квоты"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {}}
        mock_get.return_value = mock_response

        # Создаём клиента с лимитом 3
        client = APIFootballClient(api_key="test_key")
        client.daily_limit = 3

        # Делаем 3 запроса
        client.fetch_team_statistics("49", "39", "2024")
        client.fetch_team_statistics("50", "39", "2024")
        client.fetch_team_statistics("51", "39", "2024")

        assert client.requests_made == 3

        # 4-й запрос должен выбросить исключение
        with pytest.raises(QuotaExceededError):
            client.fetch_team_statistics("52", "39", "2024")

        # Счётчик не должен увеличиться
        assert client.requests_made == 3

    @patch('sync_api_football.requests.Session.get')
    def test_quota_reset_at_midnight(self, mock_get):
        """Тест сброса квоты в полночь UTC"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {}}
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        client.daily_limit = 3

        # Делаем 3 запроса
        client.fetch_team_statistics("49", "39", "2024")
        client.fetch_team_statistics("50", "39", "2024")
        client.fetch_team_statistics("51", "39", "2024")

        assert client.requests_made == 3

        # Симулируем наступление полночи UTC
        # Устанавливаем quota_reset_time в прошлое (час назад)
        now = datetime.now(timezone.utc)
        client.quota_reset_time = now - timedelta(hours=1)

        # Теперь должна сброситься квота
        client._check_and_reset_quota()
        assert client.requests_made == 0

        # Запросы снова должны работать
        client.fetch_team_statistics("52", "39", "2024")
        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    @patch('time.sleep')
    def test_rate_limiting(self, mock_sleep, mock_get):
        """Тест rate limiting (min 1 req/sec)"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {}}
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        client.min_interval = 1.0

        # Делаем 2 запроса подряд
        client.fetch_team_statistics("49", "39", "2024")
        client.fetch_team_statistics("50", "39", "2024")

        # Проверяем что sleep был вызван (для соблюдения min_interval)
        assert mock_sleep.called

    @patch('sync_api_football.requests.Session.get')
    def test_api_error_handling(self, mock_get):
        """Тест обработки ошибок API"""
        # HTTP 429 (rate limit)
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_team_statistics("49", "39", "2024")

        assert result is None
        assert client.requests_made == 1  # Запрос был засчитан

    @patch('sync_api_football.requests.Session.get')
    def test_api_500_error(self, mock_get):
        """Тест обработки HTTP 500"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_team_statistics("49", "39", "2024")

        assert result is None
        assert client.requests_made == 1

    @patch('sync_api_football.requests.Session.get')
    def test_network_error_handling(self, mock_get):
        """Тест обработки сетевых ошибок"""
        # Симулируем timeout
        mock_get.side_effect = Exception("Connection timeout")

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_team_statistics("49", "39", "2024")

        assert result is None
        # Счётчик НЕ увеличился (ошибка до увеличения)
        assert client.requests_made == 0

    @patch('sync_api_football.requests.Session.get')
    def test_empty_response_handling(self, mock_get):
        """Тест обработки пустого ответа"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": None}
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_team_statistics("49", "39", "2024")

        # Должно вернуть None т.к. response пустой
        assert result is None

    @patch('sync_api_football.requests.Session.get')
    def test_malformed_response_handling(self, mock_get):
        """Тест обработки некорректного JSON"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {
                "team": {},  # Пустой объект команды
                "fixtures": None  # Нет данных
            }
        }
        mock_get.return_value = mock_response

        client = APIFootballClient(api_key="test_key")
        result = client.fetch_team_statistics("49", "39", "2024")

        # Парсинг должен обработать и вернуть None или частичные данные
        # В текущей реализации вернёт None из-за ошибки парсинга
        assert result is None


class TestQuotaExceededError:
    """Тесты для исключения QuotaExceededError"""

    def test_quota_exceeded_error_message(self):
        """Тест сообщения исключения"""
        error = QuotaExceededError("Test error message")
        assert str(error) == "Test error message"


class TestTeamMapping:
    """Тесты для функций team ID mapping (Issue #6)"""

    @patch('sync_api_football.APIFootballClient.make_request')
    def test_search_team_by_name_success(self, mock_request):
        """Тест поиска команды по названию"""
        # Mock ответ API
        mock_request.return_value = {
            "response": [
                {
                    "team": {
                        "id": 49,
                        "name": "Chelsea"
                    }
                }
            ]
        }

        client = APIFootballClient(api_key="test_key")
        team_id = client.search_team_by_name("Chelsea", league_id="39")

        assert team_id == "49"
        mock_request.assert_called_once_with("teams", {"search": "Chelsea"})

    @patch('sync_api_football.APIFootballClient.make_request')
    def test_search_team_by_name_not_found(self, mock_request):
        """Тест когда команда не найдена"""
        mock_request.return_value = {
            "response": []
        }

        client = APIFootballClient(api_key="test_key")
        team_id = client.search_team_by_name("NonExistentTeam")

        assert team_id is None

    @patch('sync_api_football.APIFootballClient.make_request')
    def test_search_team_by_name_multiple_results(self, mock_request):
        """Тест когда найдено несколько команд (берём первую)"""
        mock_request.return_value = {
            "response": [
                {"team": {"id": 15653, "name": "Wigan Athletic U23"}},
                {"team": {"id": 53, "name": "Wigan Athletic"}}
            ]
        }

        client = APIFootballClient(api_key="test_key")
        team_id = client.search_team_by_name("Wigan Athletic")

        # Должен вернуть первый результат
        assert team_id == "15653"

    def test_league_mapping_exists(self):
        """Тест наличия маппинга лиг"""
        from sync_api_football import LEAGUE_MAPPING

        # Проверяем наличие топ-5 лиг
        assert "4328" in LEAGUE_MAPPING  # Premier League
        assert LEAGUE_MAPPING["4328"] == "39"

        assert "4335" in LEAGUE_MAPPING  # La Liga
        assert LEAGUE_MAPPING["4335"] == "140"

        assert "4331" in LEAGUE_MAPPING  # Bundesliga
        assert LEAGUE_MAPPING["4331"] == "78"

        assert "4332" in LEAGUE_MAPPING  # Serie A
        assert LEAGUE_MAPPING["4332"] == "135"

        assert "4334" in LEAGUE_MAPPING  # Ligue 1
        assert LEAGUE_MAPPING["4334"] == "61"


# === Интеграционные тесты (опционально) ===

@pytest.mark.integration
class TestAPIFootballIntegration:
    """
    Интеграционные тесты с реальным API.

    ВНИМАНИЕ: Эти тесты используют РЕАЛЬНЫЙ API и расходуют квоту!
    Запускать только вручную: pytest -m integration
    """

    def test_real_api_team_stats(self):
        """Реальный запрос к API (только для ручного тестирования)"""
        pytest.skip("Интеграционный тест - запускать вручную")

        client = APIFootballClient()
        result = client.fetch_team_statistics("49", "39", "2024")

        assert result is not None
        assert result['team_name'] == "Chelsea"
        assert result['league_id'] == "39"

    def test_real_api_quota_tracking(self):
        """Проверка квоты с реальным API"""
        pytest.skip("Интеграционный тест - запускать вручную")

        client = APIFootballClient()
        initial_quota = client.requests_made

        client.fetch_team_statistics("49", "39", "2024")

        assert client.requests_made == initial_quota + 1
