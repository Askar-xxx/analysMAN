"""
On-demand fetcher для обогащения матчей данными H2H/standings/form
из TheSportsDB Premium API при покупке анализа.
"""
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional
import time
from threading import Lock
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from config import THESPORTSDB_KEY, THESPORTSDB_VERIFY_TLS

logger = logging.getLogger(__name__)
CUP_LEAGUE_IDS = {'4480', '4481', '4482'}

EVENT_STAT_ALIASES = {
    'ball possession': 'Владение мячом',
    'shots total': 'Удары всего',
    'shots on goal': 'Удары в створ',
    'shots off goal': 'Удары мимо',
    'shots off target': 'Удары мимо',
    'blocked shots': 'Заблокированные удары',
    'corner kicks': 'Угловые',
    'fouls': 'Фолы',
    'fouls committed': 'Фолы',
    'offsides': 'Офсайды',
    'yellow cards': 'Жёлтые карточки',
    'red cards': 'Красные карточки',
    'goalkeeper saves': 'Сейвы вратаря',
    'passes total': 'Передачи',
    'passes %': 'Точность передач',
    'passes percentage': 'Точность передач',
    'pass accuracy': 'Точность передач',
    'expected goals': 'xG',
    'xg': 'xG',
}


class MatchDataFetcher:
    """Класс для получения обогащённых данных матча из TheSportsDB Premium API"""
    _REQUEST_LOCK = Lock()
    _LAST_REQUEST_TS = 0.0
    _MIN_REQUEST_INTERVAL_SEC = 1.0

    def __init__(self, api_key: str = THESPORTSDB_KEY):
        """
        Инициализация fetcher с premium API ключом.

        Args:
            api_key: Premium ключ TheSportsDB (default из config)
        """
        self.api_key = api_key
        # Premium API использует v1
        self.base_url = f"https://www.thesportsdb.com/api/v1/json/{self.api_key}"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        self.session.verify = THESPORTSDB_VERIFY_TLS
        if not THESPORTSDB_VERIFY_TLS:
            urllib3.disable_warnings(InsecureRequestWarning)

    @classmethod
    def _acquire_request_slot(cls):
        """
        Глобальный rate-limit для всех экземпляров fetcher в процессе.
        Ограничивает частоту, чтобы не провоцировать 429 в массовых проходах.
        """
        with cls._REQUEST_LOCK:
            now = time.monotonic()
            elapsed = now - cls._LAST_REQUEST_TS
            wait = cls._MIN_REQUEST_INTERVAL_SEC - elapsed
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            cls._LAST_REQUEST_TS = now

    def _get_with_retry(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        timeout: int = 10,
        retries: int = 3,
        base_backoff: float = 1.2
    ):
        """
        Выполнить GET к TheSportsDB с мягким ретраем на 429.
        Возвращает response даже при финальном 429, чтобы вызывающий код
        сохранил прежнюю логику проверки status_code.
        """
        url = f"{self.base_url}/{endpoint}"
        last_response = None
        for attempt in range(retries):
            self._acquire_request_slot()
            response = self.session.get(url, params=params, timeout=timeout)
            last_response = response
            if response.status_code != 429:
                return response
            if attempt < retries - 1:
                wait = base_backoff * (attempt + 1)
                logger.warning(
                    "HTTP 429 для %s (attempt %s/%s), retry через %.1fs",
                    endpoint, attempt + 1, retries, wait
                )
                time.sleep(wait)
        return last_response

    def fetch_match_data(
        self,
        match: dict,
        include_h2h: bool = True,
        include_standings: bool = True,
        include_lineups: bool = True,
        include_domestic_positions: bool = True,
        include_last_match_events: bool = True,
        include_event_stats: bool = True,
        include_cup_context: bool = True,
        lineup_scan_limit: Optional[int] = None
    ) -> dict:
        """
        Точка входа: получить все обогащённые данные для матча.

        Args:
            match: dict с полями team1, team2, home_team_id, away_team_id,
                   api_event_id, league

        Args:
            include_h2h: получать ли блок истории личных встреч
            include_standings: получать ли блок турнирной таблицы
            include_lineups: получать ли блок составов (дорогие API-вызовы)
            include_domestic_positions: получать ли позиции команд в домашних лигах
                                        (используется для кубковых матчей)
            include_last_match_events: получать ли события последнего матча
                                       (замены/карточки по timeline)
            include_event_stats: получать ли расширенную матчевую статистику
                                 (владение, удары, xG, карточки и т.д.)

        Returns:
            {
                'h2h': [...],              # История личных встреч
                'standings': {...},        # Турнирная таблица
                'team1_form': [...],       # Последние матчи team1
                'team2_form': [...],       # Последние матчи team2
                'team1_domestic_position': "...",   # Позиция в домашней лиге (для кубков)
                'team2_domestic_position': "...",   # Позиция в домашней лиге (для кубков)
                'team1_cup_path': [...],   # Кубковый путь (для кубков)
                'team2_cup_path': [...],   # Кубковый путь (для кубков)
                'team1_last_match_events': {...},  # События последнего матча team1
                'team2_last_match_events': {...},  # События последнего матча team2
                'current_event_stats': {...},      # Расширенная статистика текущего матча
                'team1_last_match_stats': {...},   # Расширенная статистика последнего матча team1
                'team2_last_match_stats': {...},   # Расширенная статистика последнего матча team2
                'h2h_recent_stats': [...],         # Расширенная статистика последних H2H
                'errors': []               # Список ошибок если были
            }
        """
        result = {
            'h2h': [],
            'standings': {},
            'team1_form': [],
            'team2_form': [],
            'team1_domestic_position': '',
            'team2_domestic_position': '',
            'team1_cup_path': [],
            'team2_cup_path': [],
            'team1_last_match_events': {},
            'team2_last_match_events': {},
            'team1_meta': {},
            'team2_meta': {},
            'current_event_stats': {},
            'team1_last_match_stats': {},
            'team2_last_match_stats': {},
            'h2h_recent_stats': [],
            'league_id': None,
            'season': None,
            'is_cup': False,
            'errors': []
        }

        team1 = match.get('team1', '')
        team2 = match.get('team2', '')
        home_team_id = match.get('home_team_id')
        away_team_id = match.get('away_team_id')
        api_event_id = match.get('api_event_id')

        # 1. Event details (получить season + league_id ПЕРВЫМ)
        season = None
        league_id = None
        try:
            if api_event_id:
                event_details = self._fetch_event_details(api_event_id)
                if event_details:
                    league_id = event_details.get('league_id')
                    season = event_details.get('season')
                    result['venue'] = event_details.get('venue', '')
                    result['time'] = event_details.get('time', '')
                    result['round'] = event_details.get('round', '')
                    logger.info(f"Event details: league {league_id}, season {season}")
        except Exception as e:
            error_msg = f"Ошибка получения event details: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        result['league_id'] = league_id
        result['season'] = season
        result['is_cup'] = self._is_cup_league(league_id)

        # 2. H2H (с фильтрацией по season из шага 1)
        if include_h2h:
            try:
                h2h, h2h_is_current_season = self._fetch_h2h(
                    team1, team2, season=season, league_id=league_id
                )
                if h2h:
                    result['h2h'] = h2h
                    result['h2h_is_current_season'] = h2h_is_current_season
                    logger.info(
                        f"H2H получен: {len(h2h)} матчей "
                        f"(текущий сезон: {h2h_is_current_season})"
                    )
            except Exception as e:
                error_msg = f"Ошибка получения H2H: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # 3. Standings (использовать season и league_id из event_details)
        if include_standings:
            try:
                if league_id and season:
                    standings = self._fetch_standings(league_id, season)
                    if standings:
                        result['standings'] = standings
                        logger.info(f"Standings получен для league {league_id}, season {season}")
            except Exception as e:
                error_msg = f"Ошибка получения standings: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # 4. Form (последние матчи команд)
        try:
            if home_team_id:
                team1_form = self._fetch_team_last_matches(home_team_id)
                if team1_form:
                    result['team1_form'] = team1_form
                    logger.info(f"Form team1 получен: {len(team1_form)} матчей")
        except Exception as e:
            error_msg = f"Ошибка получения form team1: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        try:
            if away_team_id:
                team2_form = self._fetch_team_last_matches(away_team_id)
                if team2_form:
                    result['team2_form'] = team2_form
                    logger.info(f"Form team2 получен: {len(team2_form)} матчей")
        except Exception as e:
            error_msg = f"Ошибка получения form team2: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        # 5. Метаданные команд (страна/локация)
        try:
            if home_team_id:
                team1_meta = self._fetch_team_details(str(home_team_id))
                if team1_meta:
                    result['team1_meta'] = team1_meta
            if away_team_id:
                team2_meta = self._fetch_team_details(str(away_team_id))
                if team2_meta:
                    result['team2_meta'] = team2_meta
        except Exception as e:
            error_msg = f"Ошибка получения метаданных команд: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        # 6. События последних матчей (замены/карточки) — по timeline
        if include_last_match_events:
            try:
                if result.get('team1_form'):
                    result['team1_last_match_events'] = self._build_last_match_events(
                        result['team1_form'][0], team1
                    )
                if result.get('team2_form'):
                    result['team2_last_match_events'] = self._build_last_match_events(
                        result['team2_form'][0], team2
                    )
            except Exception as e:
                error_msg = f"Ошибка получения событий последнего матча: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # 7. Расширенная статистика матчей (владение, удары, xG и т.д.)
        if include_event_stats:
            try:
                if api_event_id:
                    result['current_event_stats'] = self._fetch_event_stats(api_event_id)

                if result.get('team1_form'):
                    last_event_id = result['team1_form'][0].get('event_id')
                    if last_event_id:
                        result['team1_last_match_stats'] = self._fetch_event_stats(last_event_id)

                if result.get('team2_form'):
                    last_event_id = result['team2_form'][0].get('event_id')
                    if last_event_id:
                        result['team2_last_match_stats'] = self._fetch_event_stats(last_event_id)

                if result.get('h2h'):
                    h2h_stats = []
                    for h2h_match in result['h2h'][:2]:
                        h2h_event_id = h2h_match.get('event_id')
                        if not h2h_event_id:
                            continue
                        stats = self._fetch_event_stats(h2h_event_id)
                        if stats:
                            h2h_stats.append({
                                'event_id': str(h2h_event_id),
                                'date': h2h_match.get('date', ''),
                                'home_team': h2h_match.get('home_team', ''),
                                'away_team': h2h_match.get('away_team', ''),
                                'stats': stats
                            })
                    result['h2h_recent_stats'] = h2h_stats
            except Exception as e:
                error_msg = f"Ошибка получения расширенной статистики: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # 8. Lineups (составы) — для последних 2 матчей каждой команды
        if include_lineups:
            try:
                # Получаем составы для team1: первые 2 доступных lineup в форме
                if result.get('team1_form'):
                    collected = 0
                    scanned = 0
                    for form_match in result['team1_form']:
                        if lineup_scan_limit is not None and scanned >= lineup_scan_limit:
                            break
                        scanned += 1
                        if collected >= 2:
                            break
                        event_id = form_match.get('event_id')
                        if not event_id:
                            continue
                        lineup_key = f'lineup_{event_id}'
                        if lineup_key in result:
                            collected += 1
                            continue
                        lineup = self._fetch_lineup(event_id)
                        if lineup:
                            result[lineup_key] = lineup
                            collected += 1
                            logger.info(
                                f"Lineup получен для event {event_id}: {len(lineup)} игроков"
                            )

                # Получаем составы для team2: первые 2 доступных lineup в форме
                if result.get('team2_form'):
                    collected = 0
                    scanned = 0
                    for form_match in result['team2_form']:
                        if lineup_scan_limit is not None and scanned >= lineup_scan_limit:
                            break
                        scanned += 1
                        if collected >= 2:
                            break
                        event_id = form_match.get('event_id')
                        if not event_id:
                            continue
                        lineup_key = f'lineup_{event_id}'
                        if lineup_key in result:
                            collected += 1
                            continue
                        lineup = self._fetch_lineup(event_id)
                        if lineup:
                            result[lineup_key] = lineup
                            collected += 1
                            logger.info(
                                f"Lineup получен для event {event_id}: {len(lineup)} игроков"
                            )
            except Exception as e:
                error_msg = f"Ошибка получения lineups: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # 9. Кубковые данные: путь и домашние позиции команд
        if result['is_cup'] and include_cup_context:
            cup_events = self._fetch_cup_matches_by_season(league_id, season)
            result['team1_cup_path'] = self._build_cup_path_from_events(cup_events, team1)
            result['team2_cup_path'] = self._build_cup_path_from_events(cup_events, team2)

            if include_domestic_positions and season:
                standings_cache = {}
                result['team1_domestic_position'] = self._fetch_domestic_position(
                    home_team_id, team1, season, standings_cache
                )
                result['team2_domestic_position'] = self._fetch_domestic_position(
                    away_team_id, team2, season, standings_cache
                )

        return result

    def _build_last_match_events(self, form_match: dict, team_name: str) -> Dict[str, List[str]]:
        """
        Собрать ключевые события (замены/карточки) из timeline последнего матча.

        Args:
            form_match: запись матча из team*_form (первый элемент = самый свежий)
            team_name: название команды для фильтрации событий

        Returns:
            {
                'subs': [...],   # "Игрок А → Игрок Б"
                'cards': [...]   # "Игрок (ЖК/КК)"
            }
            или {} если данных нет
        """
        if not form_match:
            return {}

        event_id = form_match.get('event_id')
        if not event_id:
            return {}

        timeline = self._fetch_timeline(event_id)
        if not timeline:
            return {}

        is_home_team = form_match.get('home_team') == team_name
        substitutions: List[str] = []
        cards: List[str] = []

        for event in timeline:
            if not self._timeline_event_belongs_to_team(event, team_name, is_home_team):
                continue

            event_type = (event.get('strTimeline') or '').strip().lower()
            detail = (event.get('strTimelineDetail') or '').strip()
            player = (event.get('strPlayer') or '').strip()

            if event_type.startswith('subst'):
                if player and detail:
                    substitutions.append(f"{player} → {detail}")
                elif player or detail:
                    substitutions.append(player or detail)
            elif event_type == 'card':
                card_detail = detail.lower()
                card_label = "карточка"
                if "yellow" in card_detail or "желт" in card_detail:
                    card_label = "ЖК"
                elif "red" in card_detail or "крас" in card_detail:
                    card_label = "КК"

                if player:
                    cards.append(f"{player} ({card_label})")
                else:
                    cards.append(card_label)

        def _uniq(items: List[str], limit: int = 3) -> List[str]:
            uniq_items: List[str] = []
            for item in items:
                if item and item not in uniq_items:
                    uniq_items.append(item)
                if len(uniq_items) >= limit:
                    break
            return uniq_items

        substitutions = _uniq(substitutions)
        cards = _uniq(cards)

        if not substitutions and not cards:
            return {}

        return {
            'subs': substitutions,
            'cards': cards
        }

    @staticmethod
    def _timeline_event_belongs_to_team(event: dict, team_name: str, is_home_team: bool) -> bool:
        """
        Проверить, относится ли timeline-событие к нужной команде.

        Предпочитаем точный матчинг по strTeam, fallback — по strHome.
        """
        event_team = (event.get('strTeam') or '').strip()
        if event_team:
            return (
                event_team == team_name
                or team_name in event_team
                or event_team in team_name
            )

        home_marker = (event.get('strHome') or '').strip().lower()
        if home_marker in ('yes', 'true', '1'):
            return is_home_team
        if home_marker in ('no', 'false', '0'):
            return not is_home_team
        return False

    def _fetch_h2h(
        self, team1: str, team2: str,
        season: Optional[str] = None, league_id: Optional[str] = None
    ) -> tuple:
        """
        Получить историю личных встреч через searchevents.php.
        С фильтрацией по текущему сезону (если переданы season и league_id).

        Premium API: возвращает до 10 результатов (vs бесплатный 2-5).

        Args:
            team1: Название первой команды
            team2: Название второй команды
            season: (Optional) Сезон в формате "2025-2026" для фильтрации
            league_id: (Optional) ID лиги для определения границ сезона

        Returns:
            Tuple (matches, is_current_season):
            - matches: список матчей H2H
            - is_current_season: True если матчи из текущего сезона, False если fallback
        """
        # Формируем поисковый запрос: "team1 vs team2"
        query = f"{team1} vs {team2}"
        is_current_season = True  # По умолчанию считаем что матчи из текущего сезона

        try:
            response = self._get_with_retry(
                "searchevents.php",
                params={'e': query},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"H2H: статус {response.status_code} для '{query}'")
                return [], True

            data = response.json()
            events = data.get('event', []) if isinstance(data, dict) else []

            def _to_finished_h2h(rows: list) -> list:
                finished = []
                for event in rows or []:
                    if event.get('strStatus') not in ['Match Finished', 'FT']:
                        continue
                    finished.append({
                        'event_id': event.get('idEvent', ''),
                        'date': event.get('dateEvent', ''),
                        'home_team': event.get('strHomeTeam', ''),
                        'away_team': event.get('strAwayTeam', ''),
                        'home_score': event.get('intHomeScore', ''),
                        'away_score': event.get('intAwayScore', ''),
                        'score': f"{event.get('intHomeScore', '?')}:{event.get('intAwayScore', '?')}"
                    })
                return finished

            h2h_matches = _to_finished_h2h(events)

            # Если в прямом запросе нет завершённых H2H (или вообще нет событий),
            # пробуем обратный порядок команд.
            if not h2h_matches:
                query_reverse = f"{team2} vs {team1}"
                response = self._get_with_retry(
                    "searchevents.php",
                    params={'e': query_reverse},
                    timeout=10
                )
                if response.status_code == 200:
                    reverse_data = response.json()
                    reverse_events = (
                        reverse_data.get('event', [])
                        if isinstance(reverse_data, dict)
                        else []
                    )
                    h2h_matches = _to_finished_h2h(reverse_events)

            if not h2h_matches:
                logger.debug(f"H2H: нет завершённых данных для '{team1}' vs '{team2}'")
                return [], True

            # Фильтрация по текущему сезону (если переданы параметры)
            if season and league_id:
                try:
                    start_date, end_date = _get_season_date_range(season, league_id)
                    logger.info(f"H2H фильтрация: сезон {season}, диапазон {start_date} — {end_date}")

                    # Сохраняем список ДО фильтрации по датам (но уже после фильтра по статусу)
                    # Это нужно для fallback если в текущем сезоне нет матчей
                    matches_before_date_filter = h2h_matches.copy()

                    filtered = []
                    for m in h2h_matches:
                        match_date = datetime.strptime(m['date'], '%Y-%m-%d').date()
                        if start_date <= match_date <= end_date:
                            filtered.append(m)

                    logger.info(f"H2H: до фильтрации {len(h2h_matches)}, после {len(filtered)}")
                    h2h_matches = filtered

                    # Fallback: если после фильтрации 0 матчей, вернуть топ-3 самых свежих
                    if not h2h_matches and matches_before_date_filter:
                        logger.info("H2H фильтрация вернула 0 матчей, используем топ-3 из всех")
                        h2h_matches = sorted(
                            matches_before_date_filter,
                            key=lambda x: x['date'],
                            reverse=True
                        )[:3]
                        is_current_season = False  # Флаг что это матчи из прошлых сезонов
                except ValueError as e:
                    logger.warning(f"Ошибка расчета границ сезона: {e}, используем нефильтрованный H2H")
                except Exception as e:
                    logger.error(f"Ошибка фильтрации H2H: {e}, используем нефильтрованный H2H")

            # Ограничиваем до 10 матчей (последние N лет)
            return h2h_matches[:10], is_current_season

        except Exception as e:
            logger.warning(f"Ошибка _fetch_h2h: {e}")
            return [], True

    def _fetch_standings(self, league_id: int, season: str) -> dict:
        """
        Получить турнирную таблицу через lookuptable.php.

        Premium API: полная таблица (vs бесплатный топ-5).

        Args:
            league_id: ID лиги (например, 4328 для Premier League)
            season: Сезон (например, "2024-2025")

        Returns:
            {
                'table': [
                    {
                        'name': 'Liverpool',
                        'rank': 1,
                        'played': 25,
                        'win': 18,
                        'draw': 4,
                        'loss': 3,
                        'goalsfor': 52,
                        'goalsagainst': 21,
                        'goaldifference': 31,
                        'points': 58,
                        'form': 'WWDWL'
                    },
                    ...
                ],
                'league_id': league_id,
                'season': season
            }
        """
        try:
            response = self._get_with_retry(
                "lookuptable.php",
                params={'l': league_id, 's': season},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Standings: статус {response.status_code} для league {league_id}")
                return {}

            try:
                data = response.json()
            except ValueError:
                logger.debug(
                    "Standings: невалидный JSON для league %s, season %s (status=%s)",
                    league_id, season, response.status_code
                )
                return {}
            if not data or 'table' not in data or not data['table']:
                logger.debug(f"Standings: нет данных для league {league_id}, season {season}")
                return {}

            # Парсим таблицу
            table_entries = []
            for entry in data['table']:
                table_entries.append({
                    'name': entry.get('strTeam', ''),
                    'rank': int(entry.get('intRank', 0)),
                    'played': int(entry.get('intPlayed', 0)),
                    'win': int(entry.get('intWin', 0)),
                    'draw': int(entry.get('intDraw', 0)),
                    'loss': int(entry.get('intLoss', 0)),
                    'goalsfor': int(entry.get('intGoalsFor', 0)),
                    'goalsagainst': int(entry.get('intGoalsAgainst', 0)),
                    'goaldifference': int(entry.get('intGoalDifference', 0)),
                    'points': int(entry.get('intPoints', 0)),
                    'form': entry.get('strForm', '')
                })

            return {
                'table': table_entries,
                'league_id': league_id,
                'season': season
            }

        except Exception as e:
            logger.warning(f"Ошибка _fetch_standings: {e}")
            return {}

    def _fetch_team_last_matches(self, team_id: int, limit: int = 5) -> List[dict]:
        """
        Получить последние матчи команды через eventslast.php.

        Args:
            team_id: ID команды
            limit: Количество матчей (default: 5)

        Returns:
            Список матчей с результатами и датами
        """
        try:
            response = self._get_with_retry(
                "eventslast.php",
                params={'id': team_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Team last matches: статус {response.status_code} для team {team_id}")
                return []

            data = response.json()
            if not data or 'results' not in data or not data['results']:
                logger.debug(f"Team last matches: нет данных для team {team_id}")
                return []

            # Парсим последние матчи
            matches = []
            for event in data['results'][:limit]:
                matches.append({
                    'date': event.get('dateEvent', ''),
                    'home_team': event.get('strHomeTeam', ''),
                    'away_team': event.get('strAwayTeam', ''),
                    'home_score': event.get('intHomeScore', ''),
                    'away_score': event.get('intAwayScore', ''),
                    'score': f"{event.get('intHomeScore', '?')}:{event.get('intAwayScore', '?')}",
                    'league': event.get('strLeague', ''),
                    'event_id': event.get('idEvent', '')  # Добавлено для получения составов
                })

            return matches

        except Exception as e:
            logger.warning(f"Ошибка _fetch_team_last_matches: {e}")
            return []

    def _fetch_event_details(self, event_id: int) -> Optional[dict]:
        """
        Получить детали события для извлечения league_id и season.

        Args:
            event_id: ID события из TheSportsDB

        Returns:
            {'league_id': ..., 'season': ..., ...} или None
        """
        try:
            response = self._get_with_retry(
                "lookupevent.php",
                params={'id': event_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Event details: статус {response.status_code} для event {event_id}")
                return None

            data = response.json()
            if not data or 'events' not in data or not data['events']:
                logger.debug(f"Event details: нет данных для event {event_id}")
                return None

            event = data['events'][0]
            return {
                'league_id': event.get('idLeague'),
                'season': event.get('strSeason'),
                'league_name': event.get('strLeague', ''),
                'event_name': event.get('strEvent'),
                'date': event.get('dateEvent'),
                'venue': event.get('strVenue', ''),
                'time': event.get('strTime', ''),
                'round': event.get('intRound') or event.get('strRound', ''),
            }

        except Exception as e:
            logger.warning(f"Ошибка _fetch_event_details: {e}")
            return None

    @staticmethod
    def _is_cup_league(league_id: Optional[str]) -> bool:
        """Проверяет, относится ли турнир к еврокубкам."""
        if not league_id:
            return False
        return str(league_id) in CUP_LEAGUE_IDS

    @staticmethod
    def _is_finished_event(event: dict) -> bool:
        """Проверяет, что матч завершён (по статусу или по наличию счёта)."""
        status = (event.get('strStatus') or '').strip().lower()
        finished_statuses = {
            'match finished',
            'ft',
            'full time',
            'aet',
            'after et',
            'pen',
            'penalties',
        }
        if status in finished_statuses:
            return True

        home_score = event.get('intHomeScore')
        away_score = event.get('intAwayScore')
        return home_score not in (None, '') and away_score not in (None, '')

    def _fetch_cup_matches_by_season(self, league_id: Optional[str], season: Optional[str]) -> List[dict]:
        """
        Получить завершённые матчи текущего кубка и сезона.

        Предпочитаем `eventsseason.php` (точный сезон), fallback на `eventspastleague.php`
        с последующей фильтрацией по `strSeason`.
        """
        if not league_id:
            return []

        endpoints = []
        if season:
            endpoints.append(("eventsseason.php", {'id': league_id, 's': season}))
        endpoints.append(("eventspastleague.php", {'id': league_id}))

        for endpoint, params in endpoints:
            try:
                response = self._get_with_retry(
                    endpoint,
                    params=params,
                    timeout=10
                )
                if response.status_code != 200:
                    logger.warning(f"Cup events: статус {response.status_code} для {endpoint} league {league_id}")
                    continue

                data = response.json()
                events = data.get('events', []) if isinstance(data, dict) else []
                if not events:
                    continue

                filtered = [event for event in events if self._is_finished_event(event)]
                if season:
                    filtered = [
                        event for event in filtered
                        if str(event.get('strSeason') or '').strip() == str(season).strip()
                    ]

                if filtered:
                    return filtered
            except ValueError as e:
                logger.warning(f"Cup events: не удалось распарсить JSON ({endpoint}): {e}")
            except Exception as e:
                logger.warning(f"Ошибка _fetch_cup_matches_by_season ({endpoint}): {e}")

        return []

    @staticmethod
    def _team_name_matches(event_team: str, team_name: str) -> bool:
        """Мягкая проверка совпадения названий команд."""
        if not event_team or not team_name:
            return False
        event_team_lc = event_team.strip().lower()
        team_name_lc = team_name.strip().lower()
        return (
            event_team_lc == team_name_lc
            or event_team_lc in team_name_lc
            or team_name_lc in event_team_lc
        )

    @classmethod
    def _build_cup_path_from_events(
        cls,
        cup_events: List[dict],
        team_name: str,
        limit: int = 3
    ) -> List[str]:
        """Построить краткий кубковый путь команды по завершённым матчам турнира."""
        if not cup_events:
            return []

        cup_path = []
        sorted_events = sorted(
            cup_events,
            key=lambda event: event.get('dateEvent') or '',
            reverse=True
        )

        for event in sorted_events:
            if len(cup_path) >= limit:
                break
            if not cls._is_finished_event(event):
                continue

            home = (event.get('strHomeTeam') or '').strip()
            away = (event.get('strAwayTeam') or '').strip()
            if not (
                cls._team_name_matches(home, team_name)
                or cls._team_name_matches(away, team_name)
            ):
                continue

            home_score = event.get('intHomeScore')
            away_score = event.get('intAwayScore')
            if home_score in (None, '') or away_score in (None, ''):
                continue

            date = (event.get('dateEvent') or '').strip()
            path_item = f"{date}: {home} {home_score}:{away_score} {away}"
            if path_item not in cup_path:
                cup_path.append(path_item)

        return cup_path

    def _fetch_team_details(self, team_id: str) -> Optional[dict]:
        """Получить детали команды для определения домашней лиги."""
        if not team_id:
            return None

        try:
            response = self._get_with_retry(
                "lookupteam.php",
                params={'id': team_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Team details: статус {response.status_code} для team {team_id}")
                return None

            data = response.json()
            teams = data.get('teams') if isinstance(data, dict) else None
            if not teams:
                return None

            team = teams[0]
            return {
                'league_id': team.get('idLeague'),
                'league_name': team.get('strLeague', ''),
                'team_name': team.get('strTeam', ''),
                'country': team.get('strCountry', ''),
                'stadium_location': team.get('strStadiumLocation', ''),
            }
        except Exception as e:
            logger.warning(f"Ошибка _fetch_team_details: {e}")
            return None

    @staticmethod
    def _find_team_in_standings(table: List[dict], team_name: str) -> Optional[dict]:
        """Найти строку команды в турнирной таблице с мягким матчингом имён."""
        for entry in table:
            entry_name = entry.get('name', '')
            if (
                entry_name == team_name
                or team_name in entry_name
                or entry_name in team_name
            ):
                return entry
        return None

    def _fetch_domestic_position(
        self,
        team_id: str,
        team_name: str,
        season: str,
        standings_cache: Dict[str, dict]
    ) -> str:
        """
        Получить позицию команды в домашней лиге (для кубковых матчей).
        Если текущий сезон пуст — fallback на предыдущий сезон.

        Returns:
            Строка позиции или пустая строка если данных нет.
        """
        team_details = self._fetch_team_details(team_id)
        if not team_details:
            return ''

        league_id = str(team_details.get('league_id') or '')
        league_name = team_details.get('league_name') or 'домашней лиге'
        if not league_id or not season:
            return ''

        # Подбираем сезоны в 2 этапа:
        # 1) базовые форматы (YYYY-YYYY),
        # 2) fallback на одно-годичный формат (YYYY), если база не нашлась.
        primary_candidates: List[str] = []
        fallback_candidates: List[str] = []

        def _add_unique(container: List[str], value: Optional[str]):
            value = str(value or '').strip()
            if value and value not in container:
                container.append(value)

        _add_unique(primary_candidates, season)
        prev_season = self._get_previous_season(season)
        _add_unique(primary_candidates, prev_season)

        if '-' in season:
            try:
                start_year, end_year = season.split('-', 1)
                # Для даты матча в конце/после зимней паузы чаще релевантен второй год.
                _add_unique(fallback_candidates, end_year)
                _add_unique(fallback_candidates, start_year)
            except ValueError:
                pass

        if prev_season and '-' in prev_season:
            try:
                prev_start, prev_end = prev_season.split('-', 1)
                _add_unique(fallback_candidates, prev_end)
                _add_unique(fallback_candidates, prev_start)
            except ValueError:
                pass

        best_entry = None
        best_entry_season = ''
        best_played = -1

        def _process_candidates(candidates: List[str]):
            nonlocal best_entry, best_entry_season, best_played
            for season_candidate in candidates:
                cache_key = f"{league_id}_{season_candidate}"
                if cache_key not in standings_cache:
                    standings_cache[cache_key] = self._fetch_standings(league_id, season_candidate)

                standings = standings_cache.get(cache_key) or {}
                table = standings.get('table', [])
                entry = self._find_team_in_standings(table, team_name) if table else None
                if not entry:
                    continue

                played = int(entry.get('played', 0) or 0)
                # Если в целевом сезоне уже есть реальные данные — берём его сразу.
                if season_candidate == season and played > 0:
                    rank = entry.get('rank', 0)
                    points = entry.get('points', 0)
                    return f"#{rank} в {league_name}, {points} очков после {played} матчей"

                # Иначе собираем лучший fallback.
                # Предпочитаем вариант с наибольшим числом сыгранных матчей.
                if best_entry is None or played > best_played:
                    best_entry = entry
                    best_entry_season = season_candidate
                    best_played = played
            return None

        direct_result = _process_candidates(primary_candidates)
        if direct_result:
            return direct_result

        # К fallback-форматам (YYYY) переходим только если базовые не дали результат.
        if not best_entry:
            direct_result = _process_candidates(fallback_candidates)
            if direct_result:
                return direct_result

        if best_entry:
            rank = best_entry.get('rank', 0)
            points = best_entry.get('points', 0)
            played = best_entry.get('played', 0)
            if best_entry_season == season:
                return f"#{rank} в {league_name}, {points} очков после {played} матчей"
            return (
                f"#{rank} в {league_name} (сезон {best_entry_season}), "
                f"{points} очков после {played} матчей"
            )

        return ''

    @staticmethod
    def _get_previous_season(season: str) -> str:
        """Вычислить предыдущий сезон. '2025-2026' → '2024-2025', '2025' → '2024'."""
        if '-' in season:
            try:
                parts = season.split('-')
                start = int(parts[0])
                end = int(parts[1])
                return f"{start - 1}-{end - 1}"
            except (ValueError, IndexError):
                return ''
        try:
            return str(int(season) - 1)
        except ValueError:
            return ''

    def _fetch_lineup(self, event_id: int) -> List[dict]:
        """
        Получить составы игроков для события через V1 API.

        Args:
            event_id: ID события из TheSportsDB

        Returns:
            Список игроков с полями: strPlayer, strPosition, intSquadNumber,
            strSubstitute, strHome, strTeam
        """
        try:
            response = self._get_with_retry(
                "lookuplineup.php",
                params={'id': event_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Lineup: статус {response.status_code} для event {event_id}")
                return []

            data = response.json()
            if not data or 'lineup' not in data or not data['lineup']:
                logger.debug(f"Lineup: нет данных для event {event_id}")
                return []

            return data['lineup']

        except Exception as e:
            logger.warning(f"Ошибка _fetch_lineup: {e}")
            return []

    def _fetch_timeline(self, event_id: int) -> List[dict]:
        """
        Получить timeline события (замены/карточки/голы) через V1 API.

        Args:
            event_id: ID события из TheSportsDB

        Returns:
            Список событий timeline или [] если нет данных.
        """
        try:
            response = self._get_with_retry(
                "lookuptimeline.php",
                params={'id': event_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Timeline: статус {response.status_code} для event {event_id}")
                return []

            data = response.json()
            if not data or 'timeline' not in data or not data['timeline']:
                logger.debug(f"Timeline: нет данных для event {event_id}")
                return []

            return data['timeline']

        except Exception as e:
            logger.warning(f"Ошибка _fetch_timeline: {e}")
            return []

    @staticmethod
    def _normalize_event_stat_name(raw_name: str) -> str:
        """Нормализует название статистики в удобный русский лейбл."""
        raw = str(raw_name or '').strip()
        if not raw:
            return ''

        normalized = ' '.join(raw.lower().replace(':', '').split())
        return EVENT_STAT_ALIASES.get(normalized, raw)

    @staticmethod
    def _normalize_event_stat_value(value) -> str:
        """Приводит значение статистики к короткой строке."""
        if value is None:
            return ''
        text = str(value).strip()
        if text.lower() in ('', 'null', 'none', '-', '--'):
            return ''
        return text

    def _fetch_event_stats(self, event_id: int) -> dict:
        """
        Получить расширенную статистику события (владение, удары, xG и т.д.).

        Returns:
            {
                'Владение мячом': {'home': '55%', 'away': '45%'},
                'Удары всего': {'home': '16', 'away': '11'},
                ...
            }
            или {} если данных нет.
        """
        try:
            response = self._get_with_retry(
                "lookupeventstats.php",
                params={'id': event_id},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Event stats: статус {response.status_code} для event {event_id}")
                return {}

            data = response.json()
            if not isinstance(data, dict):
                return {}

            rows = (
                data.get('statistics')
                or data.get('stats')
                or data.get('eventstats')
                or []
            )
            if not isinstance(rows, list) or not rows:
                logger.debug(f"Event stats: нет данных для event {event_id}")
                return {}

            parsed = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue

                raw_name = (
                    row.get('strStat')
                    or row.get('strStatistic')
                    or row.get('strType')
                    or row.get('strKey')
                    or row.get('strName')
                )
                stat_name = self._normalize_event_stat_name(raw_name)
                if not stat_name:
                    continue

                home_value = self._normalize_event_stat_value(
                    row.get('strHome')
                    or row.get('strHomeValue')
                    or row.get('intHome')
                    or row.get('home')
                )
                away_value = self._normalize_event_stat_value(
                    row.get('strAway')
                    or row.get('strAwayValue')
                    or row.get('intAway')
                    or row.get('away')
                )
                if not home_value and not away_value:
                    continue

                # При дубликатах оставляем наиболее заполненный вариант.
                prev = parsed.get(stat_name, {})
                prev_home = prev.get('home', '')
                prev_away = prev.get('away', '')
                if (home_value and not prev_home) or (away_value and not prev_away) or not prev:
                    parsed[stat_name] = {'home': home_value or prev_home, 'away': away_value or prev_away}

            return parsed

        except Exception as e:
            logger.warning(f"Ошибка _fetch_event_stats: {e}")
            return {}


def _get_season_date_range(season: str, league_id: str) -> tuple:
    """
    Вычислить диапазон дат для сезона.

    Args:
        season: Сезон в формате "2025-2026"
        league_id: ID лиги (например, "4328" для Premier League)

    Returns:
        (start_date, end_date) — tuple из datetime.date

    Raises:
        ValueError: если формат season некорректный
    """
    if '-' not in season:
        raise ValueError(f"Некорректный формат сезона: '{season}'. Ожидается формат 'YYYY-YYYY'")

    try:
        parts = season.split('-')
        start_year = int(parts[0])
        end_year = int(parts[1])
    except (IndexError, ValueError) as e:
        raise ValueError(f"Ошибка парсинга сезона '{season}': {e}")

    # Определяем границы по типу турнира
    # Топ-лиги: Premier League (4328), La Liga (4335), Bundesliga (4331)
    top_leagues = ['4328', '4335', '4331']
    # Кубки Европы: Champions League (4480), Europa League (4481), Conference (4482)
    european_cups = ['4480', '4481', '4482']

    if league_id in top_leagues:
        # Топ-лиги: август - май
        start_month, start_day = 8, 1
        end_month, end_day = 5, 31
    elif league_id in european_cups:
        # Кубки: сентябрь - май (групповой этап позже)
        start_month, start_day = 9, 1
        end_month, end_day = 5, 31
    else:
        # Неизвестные лиги: fallback на август-май
        logger.warning(f"Неизвестный league_id: {league_id}, используем дефолтные границы (август-май)")
        start_month, start_day = 8, 1
        end_month, end_day = 5, 31

    from datetime import date
    start_date = date(start_year, start_month, start_day)
    end_date = date(end_year, end_month, end_day)

    return start_date, end_date


def _format_event_stats_block(title: str, stats: dict) -> str:
    """Формирует короткий блок по расширенной статистике матча."""
    if not stats:
        return ''

    preferred_order = [
        'Владение мячом',
        'xG',
        'Удары всего',
        'Удары в створ',
        'Удары мимо',
        'Заблокированные удары',
        'Угловые',
        'Фолы',
        'Офсайды',
        'Жёлтые карточки',
        'Красные карточки',
        'Сейвы вратаря',
        'Передачи',
        'Точность передач',
    ]

    lines = [f"{title}:"]
    used = set()

    for key in preferred_order:
        values = stats.get(key, {})
        if not isinstance(values, dict):
            continue
        home_val = str(values.get('home', '')).strip()
        away_val = str(values.get('away', '')).strip()
        if not home_val and not away_val:
            continue
        lines.append(f"- {key}: {home_val or '—'} / {away_val or '—'}")
        used.add(key)

    for key, values in stats.items():
        if key in used or not isinstance(values, dict):
            continue
        home_val = str(values.get('home', '')).strip()
        away_val = str(values.get('away', '')).strip()
        if not home_val and not away_val:
            continue
        lines.append(f"- {key}: {home_val or '—'} / {away_val or '—'}")

    if len(lines) == 1:
        return ''
    return '\n'.join(lines)


def build_enriched_context(match: dict, data: dict) -> str:
    """
    Форматирует обогащённые данные в текстовый контекст для AI промпта.

    Использует те же extract-функции из analysis_formatter, что и карточка,
    чтобы AI получал идентичные цифры.

    Args:
        match: dict матча с полями team1, team2, league, и т.д.
        data: dict с полями h2h, standings, team1_form, team2_form

    Returns:
        Отформатированная строка с данными для AI анализа
    """
    from analysis_formatter import (
        extract_tournament_position,
        extract_current_form,
        extract_home_away_form,
        extract_h2h_history,
        extract_lineup_changes,
        extract_last_match_events,
        extract_stats_trends,
        extract_domestic_position,
        extract_cup_path,
    )

    sections = []
    team1 = match.get('team1', 'Команда 1')
    team2 = match.get('team2', 'Команда 2')
    is_cup = data.get('is_cup', False)

    # === Venue / Time / Round (для intro) ===
    venue = data.get('venue', '')
    match_time = data.get('time', '')
    match_round = data.get('round', '')
    meta_lines = []
    if venue:
        meta_lines.append(f"Стадион: {venue}")
    if match_time:
        meta_lines.append(f"Время: {match_time}")
    if match_round:
        meta_lines.append(f"Тур/Раунд: {match_round}")
    if meta_lines:
        sections.append("=== МАТЧ ===\n" + '\n'.join(meta_lines))

    # === Турнирное положение / Лиговая позиция ===
    if is_cup:
        pos1 = extract_domestic_position(data, is_home=True)
        pos2 = extract_domestic_position(data, is_home=False)
        if pos1 or pos2:
            lines = ["=== ЛИГОВАЯ ПОЗИЦИЯ ==="]
            lines.append(f"{team1}: {pos1 or '—'}")
            lines.append(f"{team2}: {pos2 or '—'}")
            sections.append('\n'.join(lines))
    else:
        pos1 = extract_tournament_position(data, team1)
        pos2 = extract_tournament_position(data, team2)
        if pos1 or pos2:
            lines = ["=== ТУРНИРНОЕ ПОЛОЖЕНИЕ ==="]
            lines.append(f"{team1}: {pos1 or '—'}")
            lines.append(f"{team2}: {pos2 or '—'}")
            sections.append('\n'.join(lines))

    # === Кубковый путь (только для кубков) ===
    if is_cup:
        cup1 = extract_cup_path(data, is_home=True)
        cup2 = extract_cup_path(data, is_home=False)
        if cup1 or cup2:
            lines = ["=== КУБКОВЫЙ ПУТЬ ==="]
            if cup1:
                lines.append(f"{team1}:\n  {cup1.replace(chr(10), chr(10) + '  ')}")
            if cup2:
                lines.append(f"{team2}:\n  {cup2.replace(chr(10), chr(10) + '  ')}")
            sections.append('\n'.join(lines))

    # === Текущая форма ===
    form1 = extract_current_form(data, team1, is_home=True)
    form2 = extract_current_form(data, team2, is_home=False)
    if form1 or form2:
        lines = ["=== ТЕКУЩАЯ ФОРМА ==="]
        lines.append(f"{team1}: {form1 or '—'}")
        lines.append(f"{team2}: {form2 or '—'}")
        sections.append('\n'.join(lines))

    # === Форма дома/на выезде ===
    ha1 = extract_home_away_form(data, team1, is_home=True)
    ha2 = extract_home_away_form(data, team2, is_home=False)
    if ha1 or ha2:
        lines = ["=== ФОРМА ДОМА/НА ВЫЕЗДЕ ==="]
        lines.append(f"{team1}: {ha1 or '—'}")
        lines.append(f"{team2}: {ha2 or '—'}")
        sections.append('\n'.join(lines))

    # === Составы ===
    lu1 = extract_lineup_changes(data, team1, is_home=True)
    lu2 = extract_lineup_changes(data, team2, is_home=False)
    if lu1 or lu2:
        lines = ["=== СОСТАВЫ ==="]
        lines.append(f"{team1}: {lu1 or '—'}")
        lines.append(f"{team2}: {lu2 or '—'}")
        sections.append('\n'.join(lines))

    # === События последнего матча ===
    ev1 = extract_last_match_events(data, is_home=True)
    ev2 = extract_last_match_events(data, is_home=False)
    if ev1 or ev2:
        lines = ["=== СОБЫТИЯ ПОСЛЕДНЕГО МАТЧА ==="]
        lines.append(f"{team1}: {ev1 or '—'}")
        lines.append(f"{team2}: {ev2 or '—'}")
        sections.append('\n'.join(lines))

    # === История личных встреч ===
    h2h_lines = extract_h2h_history(data)
    if h2h_lines:
        sections.append("=== ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ ===\n" + '\n'.join(h2h_lines))

    # === Статистические тренды ===
    st1 = extract_stats_trends(data, team1, is_home=True)
    st2 = extract_stats_trends(data, team2, is_home=False)
    if st1 or st2:
        lines = ["=== СТАТИСТИЧЕСКИЕ ТРЕНДЫ ==="]
        if st1:
            lines.append(f"{team1}:\n  {st1.replace(chr(10), chr(10) + '  ')}")
        if st2:
            lines.append(f"{team2}:\n  {st2.replace(chr(10), chr(10) + '  ')}")
        sections.append('\n'.join(lines))

    # === Расширенная статистика матчей ===
    stats_sections = []
    current_stats = _format_event_stats_block(
        "Текущий матч (если доступно)",
        data.get('current_event_stats', {})
    )
    if current_stats:
        stats_sections.append(current_stats)

    team1_stats = _format_event_stats_block(
        f"Последний матч {team1}",
        data.get('team1_last_match_stats', {})
    )
    if team1_stats:
        stats_sections.append(team1_stats)

    team2_stats = _format_event_stats_block(
        f"Последний матч {team2}",
        data.get('team2_last_match_stats', {})
    )
    if team2_stats:
        stats_sections.append(team2_stats)

    h2h_recent_stats = data.get('h2h_recent_stats') or []
    for idx, item in enumerate(h2h_recent_stats[:2], start=1):
        if not isinstance(item, dict):
            continue
        title = (
            f"H2H статистика #{idx}: "
            f"{item.get('home_team', '')} vs {item.get('away_team', '')} "
            f"({item.get('date', '')})"
        ).strip()
        block = _format_event_stats_block(title, item.get('stats') or {})
        if block:
            stats_sections.append(block)

    if stats_sections:
        sections.append("=== РАСШИРЕННАЯ СТАТИСТИКА ===\n" + '\n\n'.join(stats_sections))

    # === Факторы матча: дерби, мотивация, реванш ===
    try:
        from match_signals import build_match_signals

        has_signal_input = any([
            data.get('h2h'),
            (data.get('standings') or {}).get('table'),
            data.get('team1_form'),
            data.get('team2_form'),
            data.get('team1_last_match_stats'),
            data.get('team2_last_match_stats'),
            data.get('h2h_recent_stats'),
        ])
        if has_signal_input:
            signals = build_match_signals(match, data)
            if signals:
                lines = ["=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ==="]
                for key in ('derby', 'motivation', 'revenge'):
                    block = signals.get(key, {})
                    if not isinstance(block, dict):
                        continue
                    label = block.get('label', key)
                    score = block.get('score', 0)
                    reasons = block.get('reasons') or []
                    reason_text = '; '.join(r for r in reasons if r) if reasons else 'слабый сигнал'
                    lines.append(f"{label}: {score}/100 — {reason_text}")
                sections.append('\n'.join(lines))
    except Exception as e:
        logger.warning(f"Не удалось собрать блок психологических факторов: {e}")

    if not sections:
        return "Обогащённые данные недоступны."

    return '\n\n'.join(sections)
