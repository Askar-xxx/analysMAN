"""
On-demand fetcher для обогащения матчей данными H2H/standings/form
из TheSportsDB Premium API при покупке анализа.
"""
import logging
import requests
from datetime import datetime
from typing import List, Optional
from config import THESPORTSDB_KEY

logger = logging.getLogger(__name__)


class MatchDataFetcher:
    """Класс для получения обогащённых данных матча из TheSportsDB Premium API"""

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
        self.session.verify = False

    def fetch_match_data(self, match: dict) -> dict:
        """
        Точка входа: получить все обогащённые данные для матча.

        Args:
            match: dict с полями team1, team2, home_team_id, away_team_id,
                   api_event_id, league

        Returns:
            {
                'h2h': [...],              # История личных встреч
                'standings': {...},        # Турнирная таблица
                'team1_form': [...],       # Последние матчи team1
                'team2_form': [...],       # Последние матчи team2
                'errors': []               # Список ошибок если были
            }
        """
        result = {
            'h2h': [],
            'standings': {},
            'team1_form': [],
            'team2_form': [],
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
                    logger.info(f"Event details: league {league_id}, season {season}")
        except Exception as e:
            error_msg = f"Ошибка получения event details: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        # 2. H2H (с фильтрацией по season из шага 1)
        try:
            h2h, h2h_is_current_season = self._fetch_h2h(team1, team2, season=season, league_id=league_id)
            if h2h:
                result['h2h'] = h2h
                result['h2h_is_current_season'] = h2h_is_current_season
                logger.info(f"H2H получен: {len(h2h)} матчей (текущий сезон: {h2h_is_current_season})")
        except Exception as e:
            error_msg = f"Ошибка получения H2H: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        # 3. Standings (использовать season и league_id из event_details)
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

        # 5. Lineups (составы) — для последних 2 матчей каждой команды
        try:
            # Получаем составы для team1
            if result.get('team1_form') and len(result['team1_form']) >= 2:
                for i in range(2):  # Последние 2 матча
                    event_id = result['team1_form'][i].get('event_id')
                    if event_id:
                        lineup = self._fetch_lineup(event_id)
                        if lineup:
                            result[f'lineup_{event_id}'] = lineup
                            logger.info(f"Lineup получен для event {event_id}: {len(lineup)} игроков")

            # Получаем составы для team2
            if result.get('team2_form') and len(result['team2_form']) >= 2:
                for i in range(2):  # Последние 2 матча
                    event_id = result['team2_form'][i].get('event_id')
                    if event_id:
                        lineup = self._fetch_lineup(event_id)
                        if lineup:
                            result[f'lineup_{event_id}'] = lineup
                            logger.info(f"Lineup получен для event {event_id}: {len(lineup)} игроков")
        except Exception as e:
            error_msg = f"Ошибка получения lineups: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        return result

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
            response = self.session.get(
                f"{self.base_url}/searchevents.php",
                params={'e': query},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"H2H: статус {response.status_code} для '{query}'")
                return [], True

            data = response.json()
            if not data or 'event' not in data or not data['event']:
                # Попробуем обратный порядок "team2 vs team1"
                query_reverse = f"{team2} vs {team1}"
                response = self.session.get(
                    f"{self.base_url}/searchevents.php",
                    params={'e': query_reverse},
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json()

            if not data or 'event' not in data or not data['event']:
                logger.debug(f"H2H: нет данных для '{team1}' vs '{team2}'")
                return [], True

            # Парсим события
            events = data['event']
            h2h_matches = []
            for event in events:
                # Фильтруем только завершённые матчи
                if event.get('strStatus') not in ['Match Finished', 'FT']:
                    continue

                h2h_matches.append({
                    'date': event.get('dateEvent', ''),
                    'home_team': event.get('strHomeTeam', ''),
                    'away_team': event.get('strAwayTeam', ''),
                    'home_score': event.get('intHomeScore', ''),
                    'away_score': event.get('intAwayScore', ''),
                    'score': f"{event.get('intHomeScore', '?')}:{event.get('intAwayScore', '?')}"
                })

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
                        logger.warning("H2H фильтрация вернула 0 матчей, используем топ-3 из всех")
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

            # Ограничиваем до 7 матчей (как в старой версии)
            return h2h_matches[:7], is_current_season

        except Exception as e:
            logger.error(f"Ошибка _fetch_h2h: {e}")
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
            response = self.session.get(
                f"{self.base_url}/lookuptable.php",
                params={'l': league_id, 's': season},
                timeout=10
            )
            if response.status_code != 200:
                logger.warning(f"Standings: статус {response.status_code} для league {league_id}")
                return {}

            data = response.json()
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
            logger.error(f"Ошибка _fetch_standings: {e}")
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
            response = self.session.get(
                f"{self.base_url}/eventslast.php",
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
            logger.error(f"Ошибка _fetch_team_last_matches: {e}")
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
            response = self.session.get(
                f"{self.base_url}/lookupevent.php",
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
                'event_name': event.get('strEvent'),
                'date': event.get('dateEvent')
            }

        except Exception as e:
            logger.error(f"Ошибка _fetch_event_details: {e}")
            return None

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
            response = self.session.get(
                f"{self.base_url}/lookuplineup.php",
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
            logger.error(f"Ошибка _fetch_lineup: {e}")
            return []


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
    # Кубки Европы: Champions League (4480), Europa League (4481)
    european_cups = ['4480', '4481']

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


def _calculate_stats_from_form(form_matches: list, is_home: bool) -> dict:
    """
    Вычислить статистику из последних матчей команды.

    Args:
        form_matches: список матчей из team_form
        is_home: True если считаем для домашней команды, False для выездной

    Returns:
        {
            'scored_pct': 75.0,  # % матчей где забили
            'conceded_pct': 60.0,  # % матчей где пропустили
            'avg_scored': 1.8,  # среднее голов за матч
            'avg_conceded': 1.2,  # среднее пропущено
            'home_away_form': 'WWDL',  # форма только дома/выезда
            'home_away_points': 9,  # очки в домашних/выездных
            'home_away_record': '3В,0Н,1П'  # статистика В-Н-П
        }
    """
    if not form_matches:
        return {}

    # Фильтруем матчи: только дома или только на выезде
    filtered = []
    for m in form_matches:
        if is_home and m.get('home_team'):  # Проверяем что команда была дома
            filtered.append(m)
        elif not is_home and m.get('away_team'):  # Проверяем что команда была на выезде
            filtered.append(m)

    if not filtered:
        filtered = form_matches  # Если фильтрация не дала результатов, используем все

    total = len(filtered)
    scored_count = 0
    conceded_count = 0
    total_scored = 0
    total_conceded = 0
    wins = 0
    draws = 0
    losses = 0
    form_str = ''

    for match in filtered:
        home_score = int(match.get('home_score', 0) or 0)
        away_score = int(match.get('away_score', 0) or 0)

        if is_home:
            goals_for = home_score
            goals_against = away_score
        else:
            goals_for = away_score
            goals_against = home_score

        if goals_for > 0:
            scored_count += 1
        if goals_against > 0:
            conceded_count += 1

        total_scored += goals_for
        total_conceded += goals_against

        # Определяем результат
        if goals_for > goals_against:
            wins += 1
            form_str += 'W'
        elif goals_for < goals_against:
            losses += 1
            form_str += 'L'
        else:
            draws += 1
            form_str += 'D'

    points = wins * 3 + draws

    return {
        'scored_pct': (scored_count / total * 100) if total > 0 else 0,
        'conceded_pct': (conceded_count / total * 100) if total > 0 else 0,
        'avg_scored': total_scored / total if total > 0 else 0,
        'avg_conceded': total_conceded / total if total > 0 else 0,
        'home_away_form': form_str[:6],  # Последние 6 матчей
        'home_away_points': points,
        'home_away_record': f"{wins}В,{draws}Н,{losses}П",
        'home_away_total': total
    }


def _determine_tournament_zone(rank: int, league: str) -> str:
    """
    Определить зону турнирной таблицы на основе позиции.

    Args:
        rank: позиция в таблице
        league: название лиги

    Returns:
        'зона ЛЧ' / 'зона еврокубков' / 'зона вылета' / ''
    """
    # Упрощённая логика для основных лиг
    if 'Premier League' in league or 'La Liga' in league or 'Bundesliga' in league or 'Serie A' in league:
        if rank <= 4:
            return 'зона ЛЧ'
        elif rank <= 7:
            return 'зона еврокубков'
        elif rank >= 18:
            return 'зона вылета'
    elif 'Ligue 1' in league:
        if rank <= 3:
            return 'зона ЛЧ'
        elif rank <= 5:
            return 'зона еврокубков'
        elif rank >= 19:
            return 'зона вылета'

    return ''


def _assess_home_away_quality(points: int, total_matches: int) -> str:
    """
    Оценить качество формы дома/на выезде.

    Args:
        points: набранные очки
        total_matches: всего матчей

    Returns:
        'Сильная' / 'Средняя' / 'Слабая'
    """
    if total_matches == 0:
        return 'Недостаточно данных'

    points_per_game = points / total_matches

    if points_per_game >= 2.0:
        return 'Сильная'
    elif points_per_game >= 1.2:
        return 'Средняя'
    else:
        return 'Слабая'


def build_enriched_context(match: dict, data: dict) -> str:
    """
    Форматирует обогащённые данные в текстовый контекст для AI промпта (табличный формат).

    Args:
        match: dict матча с полями team1, team2, league, и т.д.
        data: dict с полями h2h, standings, team1_form, team2_form

    Returns:
        Отформатированная строка с данными для табличного анализа
    """
    sections = []

    team1 = match.get('team1', 'Команда 1')
    team2 = match.get('team2', 'Команда 2')
    league = match.get('league', '')

    # === Турнирное положение ===
    if data.get('standings') and data['standings'].get('table'):
        table = data['standings']['table']
        team1_entry = None
        team2_entry = None

        for entry in table:
            team_name = entry['name']
            if team_name == team1 or team1 in team_name or team_name in team1:
                team1_entry = entry
            if team_name == team2 or team2 in team_name or team_name in team2:
                team2_entry = entry

        if team1_entry or team2_entry:
            lines = ["=== ТУРНИРНОЕ ПОЛОЖЕНИЕ ==="]
            if team1_entry:
                zone = _determine_tournament_zone(team1_entry['rank'], league)
                zone_str = f" ({zone})" if zone else ""
                lines.append(
                    f"{team1}: #{team1_entry['rank']} место{zone_str}, "
                    f"{team1_entry['points']} очков после {team1_entry['played']} матчей"
                )
            if team2_entry:
                zone = _determine_tournament_zone(team2_entry['rank'], league)
                zone_str = f" ({zone})" if zone else ""
                lines.append(
                    f"{team2}: #{team2_entry['rank']} место{zone_str}, "
                    f"{team2_entry['points']} очков после {team2_entry['played']} матчей"
                )
            sections.append('\n'.join(lines))

    # === Текущая форма (общая) ===
    form_lines = []
    if data.get('team1_form'):
        # Вычисляем форму из последних матчей
        form_str = ''
        for m in data['team1_form'][:6]:  # Последние 6
            hs = int(m.get('home_score', 0) or 0)
            as_ = int(m.get('away_score', 0) or 0)
            if m.get('home_team') == team1:
                form_str += 'W' if hs > as_ else ('D' if hs == as_ else 'L')
            else:
                form_str += 'W' if as_ > hs else ('D' if hs == as_ else 'L')
        form_lines.append(f"{team1}: {form_str}")

    if data.get('team2_form'):
        form_str = ''
        for m in data['team2_form'][:6]:
            hs = int(m.get('home_score', 0) or 0)
            as_ = int(m.get('away_score', 0) or 0)
            if m.get('home_team') == team2:
                form_str += 'W' if hs > as_ else ('D' if hs == as_ else 'L')
            else:
                form_str += 'W' if as_ > hs else ('D' if hs == as_ else 'L')
        form_lines.append(f"{team2}: {form_str}")

    if form_lines:
        sections.append("=== ТЕКУЩАЯ ФОРМА ===\n" + '\n'.join(form_lines))

    # === Форма дома/на выезде ===
    if data.get('team1_form') and data.get('team2_form'):
        team1_stats = _calculate_stats_from_form(data['team1_form'], is_home=True)
        team2_stats = _calculate_stats_from_form(data['team2_form'], is_home=False)

        lines = ["=== ФОРМА ДОМА/НА ВЫЕЗДЕ ==="]
        if team1_stats:
            quality = _assess_home_away_quality(
                team1_stats.get('home_away_points', 0),
                team1_stats.get('home_away_total', 1)
            )
            lines.append(
                f"{team1} ({quality} дома): {team1_stats.get('home_away_points', 0)} очков "
                f"в {team1_stats.get('home_away_total', 0)} матчах "
                f"({team1_stats.get('home_away_record', '—')})"
            )
        if team2_stats:
            quality = _assess_home_away_quality(
                team2_stats.get('home_away_points', 0),
                team2_stats.get('home_away_total', 1)
            )
            lines.append(
                f"{team2} ({quality} на выезде): {team2_stats.get('home_away_points', 0)} очков "
                f"в {team2_stats.get('home_away_total', 0)} матчах "
                f"({team2_stats.get('home_away_record', '—')})"
            )
        sections.append('\n'.join(lines))

    # === Ключевой игрок (заглушка) ===
    sections.append(f"=== КЛЮЧЕВЫЕ ИГРОКИ ===\n{team1}: Нет данных\n{team2}: Нет данных")

    # === Составы (заглушка) ===
    sections.append(f"=== СОСТАВЫ ===\n{team1}: Нет данных\n{team2}: Нет данных")

    # === H2H ===
    if data.get('h2h'):
        h2h_lines = ["=== ИСТОРИЯ ЛИЧНЫХ ВСТРЕЧ ==="]

        # Проверяем флаг: матчи из текущего сезона или fallback на прошлые
        is_current_season = data.get('h2h_is_current_season', True)

        if is_current_season:
            h2h_lines.append(f"Последние {len(data['h2h'])} матчей:")
        else:
            h2h_lines.append("В текущем сезоне команды не встречались.")
            h2h_lines.append(f"Последние встречи из прошлых сезонов ({len(data['h2h'])} матчей):")

        for h2h_match in data['h2h']:
            date = h2h_match.get('date', '')
            home = h2h_match.get('home_team', '')
            away = h2h_match.get('away_team', '')
            score = h2h_match.get('score', '?:?')
            h2h_lines.append(f"{date}: {home} {score} {away}")
        sections.append('\n'.join(h2h_lines))

    # === Статистические тренды ===
    if data.get('team1_form') and data.get('team2_form'):
        team1_stats = _calculate_stats_from_form(data['team1_form'], is_home=True)
        team2_stats = _calculate_stats_from_form(data['team2_form'], is_home=False)

        lines = ["=== СТАТИСТИЧЕСКИЕ ТРЕНДЫ ==="]
        lines.append(f"{team1}:")
        if team1_stats:
            lines.append(f"  • Забивают в {team1_stats.get('scored_pct', 0):.0f}% матчей")
            lines.append(f"  • Пропускают в {team1_stats.get('conceded_pct', 0):.0f}% домашних игр")
            lines.append(f"  • В среднем {team1_stats.get('avg_scored', 0):.2f} гола за матч")
            lines.append(f"  • Пропускают в среднем {team1_stats.get('avg_conceded', 0):.2f} гола")

        lines.append(f"\n{team2}:")
        if team2_stats:
            lines.append(f"  • Забивают в {team2_stats.get('scored_pct', 0):.0f}% матчей")
            lines.append(f"  • Пропускают в {team2_stats.get('conceded_pct', 0):.0f}% выездных игр")
            lines.append(f"  • В среднем {team2_stats.get('avg_scored', 0):.2f} гола за матч")
            lines.append(f"  • Пропускают в среднем {team2_stats.get('avg_conceded', 0):.2f} гола")

        sections.append('\n'.join(lines))

    # Объединяем все секции
    if not sections:
        return "Обогащённые данные недоступны."

    return '\n\n'.join(sections)
