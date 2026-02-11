"""
Модуль для исследования API-Football endpoints.

Этап 1: Только fetch функции и сбор примеров JSON.
БЕЗ сохранения в БД - это будет в Этапе 2.

API-Football v3 documentation: https://www.api-football.com/documentation-v3
"""

import json
import logging
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from pathlib import Path
from threading import Lock

# Импортируем API ключ из config
from config import API_FOOTBALL_KEY

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APIFootballClient:
    """
    Клиент для работы с API-Football v3.

    Ограничения бесплатного tier:
    - 100 requests/day (сбрасывается в полночь UTC)
    - Rate limit: минимум 1 req/sec для безопасности

    Этап 1: Только fetch функции, БЕЗ сохранения в БД.
    """

    def __init__(self, api_key: str = None):
        """
        Инициализация клиента.

        Args:
            api_key: API ключ (если None, берётся из config.API_FOOTBALL_KEY)
        """
        self.api_key = api_key or API_FOOTBALL_KEY
        self.base_url = "https://v3.football.api-sports.io"

        # Rate limiting: daily quota
        self.daily_limit = 100
        self.requests_made = 0
        self.quota_reset_time = self._get_next_midnight_utc()
        self._lock = Lock()

        # Min interval между запросами (1 sec для безопасности)
        self.min_interval = 1.0
        self.last_request_time = 0.0

        # HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            'x-apisports-key': self.api_key,
            'Accept': 'application/json',
            'User-Agent': 'analysMAN-bot/1.0'
        })

        logger.info(
            f"APIFootballClient инициализирован. "
            f"Квота: {self.requests_made}/{self.daily_limit}, "
            f"сброс в {self.quota_reset_time.strftime('%H:%M:%S UTC')}"
        )

    def _get_next_midnight_utc(self) -> datetime:
        """Получить время следующей полночи UTC"""
        now = datetime.now(timezone.utc)
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return midnight

    def _check_and_reset_quota(self):
        """Проверить и сбросить квоту если наступила полночь UTC"""
        now = datetime.now(timezone.utc)
        if now >= self.quota_reset_time:
            logger.info(
                f"Сброс квоты (было {self.requests_made}/{self.daily_limit})"
            )
            self.requests_made = 0
            self.quota_reset_time = self._get_next_midnight_utc()

    def _wait_for_rate_limit(self):
        """Ожидание для соблюдения min interval между запросами"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time

            if elapsed < self.min_interval:
                wait = self.min_interval - elapsed
                logger.debug(f"Rate limit: ожидание {wait:.2f}s")
                time.sleep(wait)

            self.last_request_time = time.time()

    def make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Выполнить запрос к API-Football.

        Args:
            endpoint: API endpoint (например, "teams/statistics")
            params: Query parameters

        Returns:
            Dict с ответом от API или None при ошибке

        Raises:
            QuotaExceededError: если достигнут дневной лимит
        """
        # Проверяем квоту
        self._check_and_reset_quota()

        if self.requests_made >= self.daily_limit:
            logger.error(
                f"Достигнут дневной лимит запросов: "
                f"{self.requests_made}/{self.daily_limit}. "
                f"Сброс в {self.quota_reset_time.strftime('%H:%M:%S UTC')}"
            )
            raise QuotaExceededError(
                f"Daily quota exceeded ({self.requests_made}/{self.daily_limit}). "
                f"Reset at {self.quota_reset_time.strftime('%H:%M:%S UTC')}"
            )

        # Rate limiting
        self._wait_for_rate_limit()

        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"Запрос: {endpoint} (params: {params})")

            response = self.session.get(url, params=params, timeout=10)

            # Увеличиваем счётчик запросов
            with self._lock:
                self.requests_made += 1

            logger.info(
                f"Статус: {response.status_code}, "
                f"квота: {self.requests_made}/{self.daily_limit}"
            )

            if response.status_code == 429:
                logger.warning("HTTP 429: Rate limit exceeded")
                return None

            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code}: {response.text[:200]}")
                return None

            data = response.json()

            # API-Football возвращает структуру: {"response": [...], "errors": [...]}
            if data.get('errors'):
                logger.error(f"API errors: {data['errors']}")
                return None

            return data

        except Exception as e:
            logger.error(f"Ошибка запроса: {e}")
            return None

    def fetch_team_statistics(self, team_id: str, league_id: str,
                             season: str) -> Optional[Dict]:
        """
        Получить статистику команды из API-Football.

        Endpoint: GET /teams/statistics

        Args:
            team_id: ID команды в API-Football (например, "49" для Chelsea)
            league_id: ID лиги в API-Football (например, "39" для EPL)
            season: Сезон (например, "2024")

        Returns:
            Dict с обработанными данными или None при ошибке

        Пример возврата:
            {
                "team_id": "49",
                "team_name": "Chelsea",
                "league_id": "39",
                "season": "2024",
                "home_wins": 8,
                "home_draws": 2,
                "home_losses": 1,
                "home_goals_for": 24,
                "home_goals_against": 10,
                "away_wins": 3,
                "away_draws": 4,
                "away_losses": 5,
                "away_goals_for": 15,
                "away_goals_against": 20,
                "form": "WWDWLLLWWDWL",
                "raw_response": {...}
            }
        """
        params = {
            "team": team_id,
            "league": league_id,
            "season": season
        }

        data = self.make_request("teams/statistics", params)

        if not data or 'response' not in data:
            logger.warning(f"Пустой ответ для team_id={team_id}")
            return None

        response = data['response']

        # Извлекаем нужные поля
        try:
            fixtures = response.get('fixtures', {})
            goals = response.get('goals', {})

            result = {
                "team_id": team_id,
                "team_name": response.get('team', {}).get('name', 'Unknown'),
                "league_id": league_id,
                "season": season,
                # Home stats
                "home_wins": fixtures.get('wins', {}).get('home', 0),
                "home_draws": fixtures.get('draws', {}).get('home', 0),
                "home_losses": fixtures.get('loses', {}).get('home', 0),
                "home_goals_for": goals.get('for', {}).get('total', {}).get('home', 0),
                "home_goals_against": goals.get('against', {}).get('total', {}).get('home', 0),
                # Away stats
                "away_wins": fixtures.get('wins', {}).get('away', 0),
                "away_draws": fixtures.get('draws', {}).get('away', 0),
                "away_losses": fixtures.get('loses', {}).get('away', 0),
                "away_goals_for": goals.get('for', {}).get('total', {}).get('away', 0),
                "away_goals_against": goals.get('against', {}).get('total', {}).get('away', 0),
                # Form
                "form": response.get('form', ''),
                # Raw response для дальнейшего анализа
                "raw_response": response
            }

            logger.info(
                f"Team stats получены: {result['team_name']} "
                f"(home: {result['home_wins']}-{result['home_draws']}-{result['home_losses']}, "
                f"away: {result['away_wins']}-{result['away_draws']}-{result['away_losses']})"
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка парсинга team stats: {e}")
            return None

    def fetch_injuries(self, team_id: str, league_id: str,
                      season: str) -> Optional[Dict]:
        """
        Получить список травмированных игроков.

        Endpoint: GET /injuries

        Args:
            team_id: ID команды
            league_id: ID лиги
            season: Сезон

        Returns:
            Dict с данными о травмах

        Пример возврата:
            {
                "team_id": "49",
                "team_name": "Chelsea",
                "injuries_count": 3,
                "injuries": [
                    {
                        "player_name": "Reece James",
                        "reason": "Knee Injury",
                        "type": "Missing Fixture"
                    },
                    ...
                ],
                "raw_response": [...]
            }
        """
        params = {
            "team": team_id,
            "league": league_id,
            "season": season
        }

        data = self.make_request("injuries", params)

        if not data or 'response' not in data:
            logger.warning(f"Пустой ответ для injuries team_id={team_id}")
            return None

        response = data['response']

        try:
            injuries_list = []

            for injury in response:
                player = injury.get('player', {})
                fixture = injury.get('fixture', {})

                injuries_list.append({
                    "player_name": player.get('name', 'Unknown'),
                    "reason": player.get('reason', 'Unknown'),
                    "type": player.get('type', 'Unknown')
                })

            result = {
                "team_id": team_id,
                "team_name": response[0].get('team', {}).get('name', 'Unknown') if response else 'Unknown',
                "injuries_count": len(injuries_list),
                "injuries": injuries_list,
                "raw_response": response
            }

            logger.info(
                f"Injuries получены: {result['team_name']} - "
                f"{result['injuries_count']} травм"
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка парсинга injuries: {e}")
            return None

    def fetch_top_scorers(self, league_id: str, season: str,
                         limit: int = 10) -> Optional[Dict]:
        """
        Получить топ-бомбардиров лиги.

        Endpoint: GET /players/topscorers

        Args:
            league_id: ID лиги
            season: Сезон
            limit: Количество игроков (макс. 20)

        Returns:
            Dict с топ-бомбардирами

        Пример возврата:
            {
                "league_id": "39",
                "season": "2024",
                "top_scorers": [
                    {
                        "player_name": "Erling Haaland",
                        "team_name": "Manchester City",
                        "goals": 25,
                        "assists": 5
                    },
                    ...
                ],
                "raw_response": [...]
            }
        """
        params = {
            "league": league_id,
            "season": season
        }

        data = self.make_request("players/topscorers", params)

        if not data or 'response' not in data:
            logger.warning(f"Пустой ответ для top_scorers league_id={league_id}")
            return None

        response = data['response'][:limit]  # Ограничиваем количество

        try:
            scorers_list = []

            for item in response:
                player = item.get('player', {})
                statistics = item.get('statistics', [{}])[0]
                team = statistics.get('team', {})
                goals_data = statistics.get('goals', {})

                scorers_list.append({
                    "player_name": player.get('name', 'Unknown'),
                    "team_name": team.get('name', 'Unknown'),
                    "goals": goals_data.get('total', 0),
                    "assists": statistics.get('goals', {}).get('assists', 0)
                })

            result = {
                "league_id": league_id,
                "season": season,
                "top_scorers_count": len(scorers_list),
                "top_scorers": scorers_list,
                "raw_response": response
            }

            logger.info(
                f"Top scorers получены: {result['top_scorers_count']} игроков"
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка парсинга top scorers: {e}")
            return None

    def fetch_full_standings(self, league_id: str, season: str) -> Optional[Dict]:
        """
        Получить ПОЛНУЮ турнирную таблицу (все команды).

        Endpoint: GET /standings

        В отличие от TheSportsDB (только топ-5), API-Football возвращает
        полную таблицу всех команд.

        Args:
            league_id: ID лиги
            season: Сезон

        Returns:
            Dict с полной таблицей

        Пример возврата:
            {
                "league_id": "39",
                "season": "2024",
                "total_teams": 20,
                "standings": [
                    {
                        "rank": 1,
                        "team_name": "Arsenal",
                        "team_id": "42",
                        "points": 63,
                        "played": 28,
                        "win": 20,
                        "draw": 3,
                        "lose": 5,
                        "goals_for": 65,
                        "goals_against": 28,
                        "goal_diff": 37,
                        "form": "WWDWL"
                    },
                    ...
                ],
                "raw_response": {...}
            }
        """
        params = {
            "league": league_id,
            "season": season
        }

        data = self.make_request("standings", params)

        if not data or 'response' not in data:
            logger.warning(f"Пустой ответ для standings league_id={league_id}")
            return None

        response = data['response']

        try:
            # API-Football возвращает вложенную структуру
            if not response or not response[0].get('league', {}).get('standings'):
                logger.warning("Пустая таблица в ответе")
                return None

            # Берём первую группу standings (обычно это основная таблица)
            standings_data = response[0]['league']['standings'][0]

            standings_list = []

            for team_data in standings_data:
                standings_list.append({
                    "rank": team_data.get('rank', 0),
                    "team_name": team_data.get('team', {}).get('name', 'Unknown'),
                    "team_id": str(team_data.get('team', {}).get('id', '')),
                    "points": team_data.get('points', 0),
                    "played": team_data.get('all', {}).get('played', 0),
                    "win": team_data.get('all', {}).get('win', 0),
                    "draw": team_data.get('all', {}).get('draw', 0),
                    "lose": team_data.get('all', {}).get('lose', 0),
                    "goals_for": team_data.get('all', {}).get('goals', {}).get('for', 0),
                    "goals_against": team_data.get('all', {}).get('goals', {}).get('against', 0),
                    "goal_diff": team_data.get('goalsDiff', 0),
                    "form": team_data.get('form', '')
                })

            result = {
                "league_id": league_id,
                "season": season,
                "total_teams": len(standings_list),
                "standings": standings_list,
                "raw_response": response
            }

            logger.info(
                f"Full standings получены: {result['total_teams']} команд"
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка парсинга standings: {e}")
            return None


class QuotaExceededError(Exception):
    """Исключение при превышении дневной квоты"""
    pass


def save_example_json(data: Dict, filename: str, output_dir: str = "api_examples"):
    """
    Сохранить пример JSON в файл.

    Args:
        data: Данные для сохранения
        filename: Имя файла (например, "team_stats_49.json")
        output_dir: Папка для сохранения (по умолчанию "api_examples")
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    file_path = output_path / filename

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Пример сохранён: {file_path}")


def main():
    """
    Тестирование всех endpoints и сбор примеров JSON.

    Тестовые данные:
    - Chelsea (team_id=49), Man City (team_id=50)
    - English Premier League (league_id=39)
    - Season: 2024
    """
    print("=" * 70)
    print("Тестирование API-Football endpoints (Этап 1 - Исследование)")
    print("=" * 70)
    print()

    client = APIFootballClient()

    # Тестовые параметры
    CHELSEA_ID = "49"
    MAN_CITY_ID = "50"
    EPL_ID = "39"
    SEASON = "2024"

    results = {
        "team_stats": None,
        "injuries": None,
        "top_scorers": None,
        "standings": None
    }

    # 1. Team Statistics (Chelsea)
    print("1. Team Statistics (Chelsea)...")
    print("-" * 70)
    try:
        stats = client.fetch_team_statistics(CHELSEA_ID, EPL_ID, SEASON)
        if stats:
            results["team_stats"] = stats
            print(f"[OK] Получено полей: {len(stats)}")
            print(f"  Команда: {stats['team_name']}")
            print(f"  Дома: {stats['home_wins']}-{stats['home_draws']}-{stats['home_losses']}")
            print(f"  В гостях: {stats['away_wins']}-{stats['away_draws']}-{stats['away_losses']}")
            print(f"  Форма: {stats['form']}")

            # Сохраняем пример
            save_example_json(stats, "team_stats_49.json")
        else:
            print("[FAIL] Не удалось получить данные")
    except QuotaExceededError as e:
        print(f"[FAIL] Квота исчерпана: {e}")
    except Exception as e:
        print(f"[FAIL] Ошибка: {e}")

    print()

    # 2. Injuries (Chelsea)
    print("2. Injuries (Chelsea)...")
    print("-" * 70)
    try:
        injuries = client.fetch_injuries(CHELSEA_ID, EPL_ID, SEASON)
        if injuries:
            results["injuries"] = injuries
            print(f"[OK] Травм: {injuries['injuries_count']}")
            for injury in injuries['injuries'][:3]:  # Показываем первые 3
                print(f"  - {injury['player_name']}: {injury['reason']}")

            # Сохраняем пример
            save_example_json(injuries, "injuries_49.json")
        else:
            print("[FAIL] Не удалось получить данные")
    except QuotaExceededError as e:
        print(f"[FAIL] Квота исчерпана: {e}")
    except Exception as e:
        print(f"[FAIL] Ошибка: {e}")

    print()

    # 3. Top Scorers (EPL)
    print("3. Top Scorers (EPL)...")
    print("-" * 70)
    try:
        top_scorers = client.fetch_top_scorers(EPL_ID, SEASON, limit=10)
        if top_scorers:
            results["top_scorers"] = top_scorers
            print(f"[OK] Топ игроков: {top_scorers['top_scorers_count']}")
            for i, scorer in enumerate(top_scorers['top_scorers'][:5], 1):
                print(f"  {i}. {scorer['player_name']} ({scorer['team_name']}): {scorer['goals']} голов")

            # Сохраняем пример
            save_example_json(top_scorers, "top_scorers_39.json")
        else:
            print("[FAIL] Не удалось получить данные")
    except QuotaExceededError as e:
        print(f"[FAIL] Квота исчерпана: {e}")
    except Exception as e:
        print(f"[FAIL] Ошибка: {e}")

    print()

    # 4. Full Standings (EPL)
    print("4. Full Standings (EPL)...")
    print("-" * 70)
    try:
        standings = client.fetch_full_standings(EPL_ID, SEASON)
        if standings:
            results["standings"] = standings
            print(f"[OK] Команд в таблице: {standings['total_teams']}")
            print("\n  Топ-5:")
            for team in standings['standings'][:5]:
                print(f"  {team['rank']}. {team['team_name']}: {team['points']} очков (форма: {team['form']})")

            # Сохраняем пример
            save_example_json(standings, "standings_39.json")
        else:
            print("[FAIL] Не удалось получить данные")
    except QuotaExceededError as e:
        print(f"[FAIL] Квота исчерпана: {e}")
    except Exception as e:
        print(f"[FAIL] Ошибка: {e}")

    print()
    print("=" * 70)

    # Итоги
    successful = sum(1 for v in results.values() if v is not None)
    print(f"Результат: {successful}/4 endpoints успешно протестированы")
    print(f"Использовано запросов: {client.requests_made}/{client.daily_limit}")

    if successful == 4:
        print("\n[SUCCESS] Все примеры сохранены в папке api_examples/")
        print("\nСледующий шаг: проверить примеры и создать API_FOOTBALL_SPEC.md")
    else:
        print("\n[WARNING] Не все endpoints вернули данные. Проверьте логи.")

    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
