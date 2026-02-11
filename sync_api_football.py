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
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from pathlib import Path
from threading import Lock

# Импортируем API ключ из config
from config import API_FOOTBALL_KEY

# Импортируем database функции для team mapping и сохранения
try:
    from database import (
        get_apif_team_id,
        set_apif_team_id,
        update_match_apif_enrichment,
        update_match_apif_top_scorers,
        get_all_matches
    )
except ImportError:
    # Для тестирования без БД
    get_apif_team_id = None
    set_apif_team_id = None
    update_match_apif_enrichment = None
    update_match_apif_top_scorers = None
    get_all_matches = None

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

    def search_team_by_name(self, team_name: str,
                            league_id: str = None) -> Optional[str]:
        """
        Найти API-Football team_id по названию команды.

        Endpoint: GET /teams

        Args:
            team_name: Название команды (например, "Chelsea")
            league_id: ID лиги для фильтрации (опционально)

        Returns:
            team_id (str) или None если не найдено

        Пример использования:
            team_id = client.search_team_by_name("Chelsea", "39")
            # Вернёт "49"
        """
        params = {"search": team_name}

        data = self.make_request("teams", params)

        if not data or 'response' not in data:
            logger.warning(f"Не найдено команд для '{team_name}'")
            return None

        teams = data['response']

        if not teams:
            logger.warning(f"Нет результатов поиска для '{team_name}'")
            return None

        # Если указана лига, фильтруем результаты
        if league_id:
            filtered = []
            for team in teams:
                # Проверяем доступные лиги команды
                team_id = str(team.get('team', {}).get('id', ''))
                team_full_name = team.get('team', {}).get('name', '')

                # Некоторые команды возвращают список venue с league_id
                # Простая проверка: если team найден, берём первый
                filtered.append({
                    'id': team_id,
                    'name': team_full_name
                })

            if filtered:
                result_id = filtered[0]['id']
                result_name = filtered[0]['name']
                logger.info(
                    f"Найдена команда: '{result_name}' (ID: {result_id})"
                )
                return result_id
        else:
            # Берём первый результат
            team_id = str(teams[0].get('team', {}).get('id', ''))
            team_full_name = teams[0].get('team', {}).get('name', '')
            logger.info(
                f"Найдена команда: '{team_full_name}' (ID: {team_id})"
            )
            return team_id

        logger.warning(f"Не найдено подходящих команд для '{team_name}'")
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


def find_or_search_team_id(sportsdb_team_id: str, team_name: str,
                           league_id: str = None,
                           client: APIFootballClient = None) -> Optional[str]:
    """
    Гибридный поиск API-Football team_id.

    Алгоритм:
    1. Проверить БД: есть ли apif_team_id для этой команды?
    2. Если есть → вернуть
    3. Если нет → поиск через API
    4. Сохранить в БД
    5. Вернуть ID

    Args:
        sportsdb_team_id: TheSportsDB team_id команды
        team_name: Название команды для поиска
        league_id: API-Football league_id (опционально)
        client: APIFootballClient экземпляр (создаст новый если None)

    Returns:
        API-Football team_id (str) или None если не найдено

    Пример:
        team_id = find_or_search_team_id("133604", "Arsenal", "39")
        # Вернёт "49" (сначала проверит БД, потом API если нужно)
    """
    # Шаг 1: Проверка БД
    if get_apif_team_id:
        cached_id = get_apif_team_id(sportsdb_team_id)
        if cached_id:
            logger.info(
                f"Team ID найден в БД: {team_name} → {cached_id} "
                f"(TheSportsDB: {sportsdb_team_id})"
            )
            return cached_id

    # Шаг 2: Поиск через API
    logger.info(
        f"Team ID не найден в БД, поиск через API: '{team_name}'"
    )

    if client is None:
        client = APIFootballClient()

    apif_team_id = client.search_team_by_name(team_name, league_id)

    if not apif_team_id:
        logger.warning(
            f"Не удалось найти API-Football team_id для '{team_name}'"
        )
        return None

    # Шаг 3: Сохранение в БД
    if set_apif_team_id:
        try:
            set_apif_team_id(sportsdb_team_id, apif_team_id)
            logger.info(
                f"Сохранён mapping: {team_name} → {apif_team_id} "
                f"(TheSportsDB: {sportsdb_team_id})"
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения mapping: {e}")

    return apif_team_id


def _get_field(obj, field: str, default=None):
    """
    Безопасно получить поле из dict или sqlite3.Row.

    Args:
        obj: dict или sqlite3.Row объект
        field: Имя поля
        default: Значение по умолчанию

    Returns:
        Значение поля или default
    """
    try:
        if field in obj.keys():
            return obj[field]
        return default
    except (KeyError, TypeError, AttributeError):
        return default


def _is_data_fresh(fetched_at_str: str, ttl_hours: int = 12) -> bool:
    """
    Проверить актуальность данных по timestamp.

    Args:
        fetched_at_str: ISO8601 timestamp (например, "2026-02-11T15:30:00")
        ttl_hours: TTL в часах (по умолчанию 12h)

    Returns:
        True если данные свежие (< TTL), False если устарели
    """
    if not fetched_at_str:
        return False

    try:
        fetched_at = datetime.fromisoformat(fetched_at_str)
        now = datetime.now()
        age = now - fetched_at
        is_fresh = age < timedelta(hours=ttl_hours)

        logger.debug(
            f"Данные {'свежие' if is_fresh else 'устарели'}: "
            f"возраст {age}, TTL {ttl_hours}h"
        )

        return is_fresh

    except Exception as e:
        logger.error(f"Ошибка парсинга timestamp '{fetched_at_str}': {e}")
        return False


def _needs_enrichment(match: Dict, field: str, ttl_hours: int = 12) -> bool:
    """
    Проверить нужно ли обогащать поле матча.

    Args:
        match: Словарь или sqlite3.Row с данными матча из БД
        field: Имя поля ('stats', 'injuries', 'full_standings', 'top_scorers')
        ttl_hours: TTL в часах

    Returns:
        True если нужно обогатить (пусто или устарело)
    """
    json_field = f'apif_{field}_json'
    ts_field = f'apif_{field.replace("full_", "")}_fetched_at'

    # Проверка наличия данных (поддержка dict и Row)
    try:
        json_value = match[json_field] if json_field in match.keys() else None
    except (KeyError, TypeError):
        json_value = None

    if not json_value:
        logger.debug(f"Поле {json_field} пусто → нужно обогатить")
        return True

    # Проверка TTL
    try:
        timestamp = match[ts_field] if ts_field in match.keys() else None
    except (KeyError, TypeError):
        timestamp = None

    if not _is_data_fresh(timestamp, ttl_hours):
        logger.debug(f"Поле {json_field} устарело → нужно обогатить")
        return True

    logger.debug(f"Поле {json_field} актуально → пропускаем")
    return False


# Маппинг лиг TheSportsDB → API-Football
LEAGUE_MAPPING = {
    "4328": "39",   # Premier League
    "4335": "140",  # La Liga
    "4331": "78",   # Bundesliga
    "4332": "135",  # Serie A
    "4334": "61",   # Ligue 1
}


def enrich_match(match: Dict, client: APIFootballClient,
                 force: bool = False) -> Dict:
    """
    Обогатить один матч данными из API-Football.

    Args:
        match: Словарь с данными матча из БД
        client: APIFootballClient экземпляр
        force: Игнорировать TTL и обновить всё

    Returns:
        Dict со статистикой: {stats_added, injuries_added, ...}
    """
    stats = {
        'stats_added': 0,
        'injuries_added': 0,
        'standings_added': 0,
        'scorers_added': 0,
        'errors': 0
    }

    match_id = match['id']
    home_team = match['team1']
    away_team = match['team2']
    home_team_id_sdb = _get_field(match, 'home_team_id')
    away_team_id_sdb = _get_field(match, 'away_team_id')

    logger.info(f"Обогащение матча #{match_id}: {home_team} vs {away_team}")

    # Определить лигу и сезон
    league_sdb_id = _get_field(match, 'league_id')
    season = "2024"  # TODO: определять из match_date

    # Маппинг лиги
    league_apif_id = LEAGUE_MAPPING.get(str(league_sdb_id)) if league_sdb_id else "39"

    # Получить API-Football team IDs
    home_team_id_apif = find_or_search_team_id(
        home_team_id_sdb, home_team, league_apif_id, client
    ) if home_team_id_sdb else None

    away_team_id_apif = find_or_search_team_id(
        away_team_id_sdb, away_team, league_apif_id, client
    ) if away_team_id_sdb else None

    if not home_team_id_apif or not away_team_id_apif:
        logger.warning(
            f"Не найдены API-Football team IDs для матча #{match_id}, пропускаем"
        )
        stats['errors'] += 1
        return stats

    # 1. Team Statistics (home + away)
    if force or _needs_enrichment(match, 'stats', ttl_hours=12):
        try:
            home_stats = client.fetch_team_statistics(
                home_team_id_apif, league_apif_id, season
            )
            away_stats = client.fetch_team_statistics(
                away_team_id_apif, league_apif_id, season
            )

            if home_stats and away_stats:
                combined_stats = {
                    'home_stats': home_stats,
                    'away_stats': away_stats
                }
                update_match_apif_enrichment(match_id, 'stats', combined_stats)
                stats['stats_added'] = 1
                logger.info(f"✓ Добавлены team stats для #{match_id}")
            else:
                logger.warning(f"Не удалось получить team stats для #{match_id}")
                stats['errors'] += 1

        except Exception as e:
            logger.error(f"Ошибка получения stats для #{match_id}: {e}")
            stats['errors'] += 1

    # 2. Injuries (home + away)
    if force or _needs_enrichment(match, 'injuries', ttl_hours=12):
        try:
            home_injuries = client.fetch_injuries(
                home_team_id_apif, league_apif_id, season
            )
            away_injuries = client.fetch_injuries(
                away_team_id_apif, league_apif_id, season
            )

            if home_injuries or away_injuries:
                combined_injuries = {
                    'home_injuries': home_injuries.get('injuries', []) if home_injuries else [],
                    'away_injuries': away_injuries.get('injuries', []) if away_injuries else []
                }
                update_match_apif_enrichment(match_id, 'injuries', combined_injuries)
                stats['injuries_added'] = 1
                logger.info(f"✓ Добавлены injuries для #{match_id}")
            else:
                logger.warning(f"Нет injuries для #{match_id}")

        except Exception as e:
            logger.error(f"Ошибка получения injuries для #{match_id}: {e}")
            stats['errors'] += 1

    # 3. Full Standings (если команды вне топ-5 TheSportsDB)
    if force or _needs_enrichment(match, 'full_standings', ttl_hours=24):
        # Проверить есть ли standings от TheSportsDB
        sdb_standings = _get_field(match, 'standings_json')

        if not sdb_standings or 'table_missing' in str(sdb_standings):
            # Нужны standings от API-Football
            try:
                standings = client.fetch_full_standings(league_apif_id, season)

                if standings:
                    update_match_apif_enrichment(match_id, 'full_standings', standings)
                    stats['standings_added'] = 1
                    logger.info(f"✓ Добавлены standings для #{match_id}")
                else:
                    logger.warning(f"Не удалось получить standings для #{match_id}")
                    stats['errors'] += 1

            except Exception as e:
                logger.error(f"Ошибка получения standings для #{match_id}: {e}")
                stats['errors'] += 1

    # 4. Top Scorers (1 раз на лигу, кэшируется)
    if force or _needs_enrichment(match, 'top_scorers', ttl_hours=24):
        try:
            scorers = client.fetch_top_scorers(league_apif_id, season)

            if scorers:
                update_match_apif_top_scorers(match_id, scorers)
                stats['scorers_added'] = 1
                logger.info(f"✓ Добавлены top scorers для #{match_id}")
            else:
                logger.warning(f"Не удалось получить top scorers для #{match_id}")
                stats['errors'] += 1

        except Exception as e:
            logger.error(f"Ошибка получения top scorers для #{match_id}: {e}")
            stats['errors'] += 1

    return stats


def fill_gaps(limit: int = None, force: bool = False,
              dry_run: bool = False) -> Dict:
    """
    Заполнить пробелы в данных матчей через API-Football.

    CLI entry point для обогащения всех матчей.

    Args:
        limit: Ограничить количество матчей (для тестирования)
        force: Игнорировать TTL и обновить всё
        dry_run: Режим preview (не сохранять в БД)

    Returns:
        Dict со статистикой обогащения
    """
    print("=" * 70)
    print("API-Football: Заполнение пробелов в данных матчей")
    print("=" * 70)
    print()

    if not get_all_matches:
        print("[ERROR] Модуль database не доступен")
        return {'error': 'Database module not available'}

    # Получить все матчи
    all_matches = get_all_matches()

    if not all_matches:
        print("[INFO] Нет матчей в БД")
        return {'total': 0}

    # Ограничить количество если указано
    if limit:
        all_matches = all_matches[:limit]

    print(f"Найдено матчей: {len(all_matches)}")
    print(f"Режим: {'DRY RUN (preview)' if dry_run else 'LIVE'}")
    print(f"Force update: {'ДА' if force else 'НЕТ (TTL проверка)'}")
    print()

    if dry_run:
        print("[DRY RUN] Изменения НЕ будут сохранены в БД")
        print()

    client = APIFootballClient()

    total_stats = {
        'total': len(all_matches),
        'processed': 0,
        'stats_added': 0,
        'injuries_added': 0,
        'standings_added': 0,
        'scorers_added': 0,
        'errors': 0,
        'skipped': 0
    }

    for i, match in enumerate(all_matches, 1):
        match_id = match['id']
        home = match['team1']
        away = match['team2']

        print(f"[{i}/{len(all_matches)}] Матч #{match_id}: {home} vs {away}")

        if dry_run:
            # Preview: только показать что будет обогащено
            needs_stats = force or _needs_enrichment(match, 'stats', 12)
            needs_injuries = force or _needs_enrichment(match, 'injuries', 12)
            needs_standings = force or _needs_enrichment(match, 'full_standings', 24)
            needs_scorers = force or _needs_enrichment(match, 'top_scorers', 24)

            if needs_stats or needs_injuries or needs_standings or needs_scorers:
                print("  > Будет обогащено:")
                if needs_stats:
                    print("    - team stats")
                if needs_injuries:
                    print("    - injuries")
                if needs_standings:
                    print("    - standings")
                if needs_scorers:
                    print("    - top scorers")
            else:
                print("  > Пропущено (данные актуальны)")
                total_stats['skipped'] += 1

            total_stats['processed'] += 1
            continue

        # LIVE mode: обогащение
        try:
            match_stats = enrich_match(match, client, force=force)

            total_stats['stats_added'] += match_stats['stats_added']
            total_stats['injuries_added'] += match_stats['injuries_added']
            total_stats['standings_added'] += match_stats['standings_added']
            total_stats['scorers_added'] += match_stats['scorers_added']
            total_stats['errors'] += match_stats['errors']
            total_stats['processed'] += 1

            print(f"  [OK] Обработано (добавлено: {sum(match_stats.values())} полей)")

        except QuotaExceededError as e:
            print(f"  [ERROR] Квота исчерпана: {e}")
            print("\nОстановка: достигнут дневной лимит API")
            break

        except Exception as e:
            logger.error(f"Ошибка обогащения матча #{match_id}: {e}")
            total_stats['errors'] += 1
            print(f"  [ERROR] {e}")

        print()

    # Итоговая статистика
    print("=" * 70)
    print("ИТОГО:")
    print("=" * 70)
    print(f"Обработано матчей:     {total_stats['processed']}/{total_stats['total']}")
    print(f"Team stats добавлено:  {total_stats['stats_added']}")
    print(f"Injuries добавлено:    {total_stats['injuries_added']}")
    print(f"Standings добавлено:   {total_stats['standings_added']}")
    print(f"Top scorers добавлено: {total_stats['scorers_added']}")
    print(f"Ошибок:                {total_stats['errors']}")
    print(f"Пропущено:             {total_stats['skipped']}")
    print(f"Использовано запросов: {client.requests_made}/{client.daily_limit}")
    print("=" * 70)

    return total_stats


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
    parser = argparse.ArgumentParser(
        description="API-Football integration tool"
    )
    parser.add_argument(
        '--fill-gaps',
        action='store_true',
        help='Заполнить пробелы в данных матчей'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Ограничить количество матчей (для тестирования)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Игнорировать TTL и обновить всё'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Режим preview (не сохранять в БД)'
    )

    args = parser.parse_args()

    try:
        if args.fill_gaps:
            # CLI mode: fill gaps
            fill_gaps(
                limit=args.limit,
                force=args.force,
                dry_run=args.dry_run
            )
        else:
            # Demo mode: test endpoints
            main()

    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
