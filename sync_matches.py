import sys
import argparse
import logging
from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict, Optional, Tuple
from threading import Lock
import requests
import time
import re
from collections import defaultdict
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from config import THESPORTSDB_KEY, THESPORTSDB_VERIFY_TLS

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _extract_coverage_metrics(table_data: Dict) -> Tuple[int, int]:
    """Возвращает (кол-во заполненных строк, кол-во пустых ячеек)."""
    rows_count = int(
        table_data.get(
            'raw_coverage_rows_count',
            table_data.get('coverage_rows_count', 0)
        )
    )
    if 'raw_missing_cells_count' in table_data:
        missing_cells = int(table_data.get('raw_missing_cells_count', 0))
    else:
        missing_cells = 0
        for row in table_data.get('rows', []):
            if row.get('colspan'):
                continue
            for side in ('left', 'right'):
                value = str(row.get(side, '')).strip().lower()
                if value == 'недостаточно данных':
                    missing_cells += 1
    return rows_count, missing_cells


def _ensure_coverage_columns(cursor) -> None:
    """Гарантирует наличие колонок coverage в таблице matches."""
    try:
        cursor.execute("ALTER TABLE matches ADD COLUMN coverage_ok INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE matches ADD COLUMN coverage_checked_at TEXT DEFAULT NULL")
    except Exception:
        pass


class RateLimitedAPI:
    """Класс для работы с лимитированным API (token bucket)"""

    def __init__(self, capacity=100, refill_rate=100):
        self.api_key = THESPORTSDB_KEY
        self.base_url = f"https://www.thesportsdb.com/api/v1/json/{self.api_key}"
        # Token bucket (premium: 100 req/min)
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per 60 seconds
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = Lock()
        # Backoff
        self.max_retries = 3
        self.base_backoff = 2.0
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        self.session.verify = THESPORTSDB_VERIFY_TLS
        if not THESPORTSDB_VERIFY_TLS:
            urllib3.disable_warnings(InsecureRequestWarning)

    def make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Выполнить запрос с token bucket + exponential backoff на 429"""
        for attempt in range(self.max_retries + 1):
            self._acquire_token()
            try:
                url = f"{self.base_url}/{endpoint}"
                response = self.session.get(url, params=params, timeout=10)
                if response.status_code == 429:
                    wait = self.base_backoff ** (attempt + 1)
                    logger.warning(
                        f"HTTP 429, backoff {wait:.1f}s (attempt {attempt + 1})"
                    )
                    time.sleep(wait)
                    continue
                if response.status_code != 200:
                    logger.debug(f"Статус {response.status_code} для {endpoint}")
                    return {}
                return response.json()
            except Exception as e:
                logger.error(f"Ошибка запроса: {e}")
                return {}
        logger.error(f"Все {self.max_retries} попыток исчерпаны для {endpoint}")
        return {}

    def _acquire_token(self):
        """Token bucket: ждать пока появится токен"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * (self.refill_rate / 60.0)
            )
            self.last_refill = now
            if self.tokens < 1.0:
                wait = (1.0 - self.tokens) / (self.refill_rate / 60.0)
                logger.debug(f"Rate limit: ожидание {wait:.2f}s")
                time.sleep(wait)
                self.tokens = 0.0
                self.last_refill = time.time()
            else:
                self.tokens -= 1.0


class SportsDBSyncer:
    """Синхронизатор матчей из TheSportsDB"""

    def __init__(self, db_path: str = "sports_bot.db", mode: str = "top3",
                 limit: int = 3, batch_size: int = 15,
                 min_coverage_rows: int = 0,
                 max_missing_cells: int = 1):
        self.db_path = db_path
        self.api = RateLimitedAPI()
        self.mode = mode
        self.limit = limit
        self.batch_size = batch_size
        self.min_coverage_rows = max(0, int(min_coverage_rows))
        self.max_missing_cells = max(0, int(max_missing_cells))
        self.source = "TheSportsDB"
        # 3 популярных лиги (premium)
        self.top_leagues = [
            {'id': '4328', 'name': 'Premier League'},
            {'id': '4335', 'name': 'La Liga'},
            {'id': '4331', 'name': 'Bundesliga'},
        ]
        # 3 кубка
        self.cups = [
            {'id': '4480', 'name': 'UEFA Champions League'},
            {'id': '4481', 'name': 'UEFA Europa League'},
            {'id': '4482', 'name': 'UEFA Europa Conference League'},
        ]
        # Окно синхронизации: 3 дня (сегодня + завтра + послезавтра)
        self.sync_days = 3

    def sync(self) -> List[Dict]:
        """Основной метод: выбирает режим sync"""
        if self.mode == "top3":
            matches = self.get_top3_matches()
        else:
            matches = self.get_week_matches()

        if self.min_coverage_rows > 0:
            max_needed = self.limit if self.mode == "top3" else None
            filtered = self._filter_by_min_coverage(
                matches,
                min_rows=self.min_coverage_rows,
                max_missing_cells=self.max_missing_cells,
                max_needed=max_needed
            )
            if filtered:
                matches = filtered
            else:
                logger.warning(
                    "Мягкий фильтр качества вернул 0 матчей, "
                    "используем исходную выборку без фильтра"
                )

        if self.mode == "top3":
            return matches[:self.limit]
        return matches

    def _get_sync_dates(self):
        """Получить список дат для синхронизации (3 дня)"""
        today = datetime.now().date()
        return [today + timedelta(days=i) for i in range(self.sync_days)]

    def get_top3_matches(self) -> List[Dict]:
        """Получить top-N матчей на ближайшие 3 дня (default mode)"""
        all_matches = []
        sync_dates = self._get_sync_dates()

        logger.info(
            f"Режим top3: получение {self.limit} матчей "
            f"на {sync_dates[0]} - {sync_dates[-1]}..."
        )

        all_tournaments = self.top_leagues + self.cups

        for league in all_tournaments:
            if (
                self.min_coverage_rows <= 0
                and len(all_matches) >= self.limit
            ):
                break
            try:
                logger.info(f"Получение матчей из: {league['name']}")
                data = self.api.make_request(
                    "eventsnextleague.php", {"id": league['id']}
                )
                if not data or 'events' not in data or not data['events']:
                    continue
                for event in data['events']:
                    if (
                        self.min_coverage_rows <= 0
                        and len(all_matches) >= self.limit
                    ):
                        break
                    match = self._parse_event(event)
                    if not match:
                        continue

                    # ФИЛЬТР: только ближайшие 3 дня
                    if match['match_date'] not in sync_dates:
                        continue

                    all_matches.append(match)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка для {league['name']}: {e}")
                continue
        unique = self._remove_duplicates(all_matches)
        unique.sort(key=lambda x: (x['match_date'], x['match_time']))
        return unique

    def _filter_by_min_coverage(
        self,
        matches: List[Dict],
        min_rows: int = 3,
        max_missing_cells: int = 1,
        max_needed: Optional[int] = None
    ) -> List[Dict]:
        """
        Мягкий фильтр качества: пропускаем матч если в адаптивной карточке
        меньше min_rows заполненных строк.
        """
        if not matches:
            return matches

        from match_data_fetcher import MatchDataFetcher
        from analysis_formatter import build_table_data

        logger.info(
            f"Мягкий фильтр качества: минимум {min_rows} строк из карточки "
            f"(проверка {len(matches)} матчей)..."
        )

        fetcher = MatchDataFetcher()
        filtered = []

        for i, match in enumerate(matches, start=1):
            try:
                # Лёгкий режим: без lineups и без домашних позиций (дорогие вызовы).
                enriched_data = fetcher.fetch_match_data(
                    match,
                    include_h2h=False,
                    include_standings=False,
                    include_lineups=True,
                    include_domestic_positions=False,
                    include_last_match_events=True,
                    include_event_stats=False,
                    include_cup_context=False,
                    lineup_scan_limit=2
                )
                table_data = build_table_data(match, enriched_data)
                rows_count, missing_cells = _extract_coverage_metrics(table_data)

                if rows_count >= min_rows and missing_cells <= max_missing_cells:
                    filtered.append(match)
                    if max_needed and len(filtered) >= max_needed:
                        logger.info(
                            f"Достигнут лимит матчей после мягкого фильтра: {max_needed}"
                        )
                        break
                else:
                    logger.info(
                        "Пропуск по мягкому фильтру: "
                        f"{match['team1']} vs {match['team2']} | rows={rows_count}, missing_cells={missing_cells}"
                    )
            except Exception as e:
                logger.warning(
                    "Ошибка мягкого фильтра для "
                    f"{match.get('team1', '?')} vs {match.get('team2', '?')}: {e}"
                )

            time.sleep(0.8)
            if i % 5 == 0:
                logger.info(f"Проверено {i}/{len(matches)} матчей мягкого фильтра")

        logger.info(
            f"Мягкий фильтр завершён: {len(filtered)} из {len(matches)} матчей"
        )
        return filtered

    def get_week_matches(self) -> List[Dict]:
        """Получить ВСЕ матчи из всех лиг и кубков на ближайшие 3 дня"""
        all_matches = []
        all_leagues = self.top_leagues + self.cups
        sync_dates = self._get_sync_dates()

        logger.info(
            f"Поиск матчей из {len(all_leagues)} лиг/кубков "
            f"на {sync_dates[0]} - {sync_dates[-1]}..."
        )
        # МЕТОД 1: Получение матчей по лигам (eventsnextleague.php)
        for league in all_leagues:
            try:
                logger.info(f"Метод 1: Получение матчей из: {league['name']}")
                data = self.api.make_request(
                    "eventsnextleague.php", {"id": league['id']}
                )
                if not data or 'events' not in data:
                    logger.warning(f"Пустой ответ для {league['name']}")
                    continue
                events = data['events']
                if not events:
                    logger.info(f"Нет матчей для {league['name']}")
                    continue
                logger.info(
                    f"Найдено {len(events)} событий в {league['name']}"
                )
                for event in events:
                    match = self._parse_event(event)
                    if not match:
                        continue

                    # ФИЛЬТР: только ближайшие 3 дня
                    if match['match_date'] not in sync_dates:
                        continue

                    all_matches.append(match)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка для {league['name']}: {e}")
                continue
        # МЕТОД 2: Получение матчей по дням (eventsday.php)
        logger.info(f"Метод 2: Поиск матчей по дням ({self.sync_days} дня)...")
        for current_date in sync_dates:
            try:
                logger.info(f"Поиск матчей на {current_date}")
                data = self.api.make_request("eventsday.php", {
                    "d": current_date.strftime('%Y-%m-%d')
                })
                if not data or 'events' not in data:
                    continue
                events = data['events']
                for event in events:
                    match = self._parse_event(event)
                    if match:
                        league_name = match.get('league', '')
                        is_target_league = any(
                            target_league['name'] in league_name
                            for target_league in all_leagues
                        )
                        if is_target_league and match not in all_matches:
                            all_matches.append(match)
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Ошибка для даты {current_date}: {e}")
                continue
        # Удаляем дубликаты
        unique_matches = self._remove_duplicates(all_matches)
        unique_matches.sort(key=lambda x: (x['match_date'], x['match_time']))
        logger.info(
            f"Итого найдено уникальных матчей: {len(unique_matches)}"
        )
        return unique_matches

    def _parse_event(self, event: Dict) -> Optional[Dict]:
        """Парсить событие с конвертацией времени в МСК"""
        try:
            date_str = event.get('dateEvent')
            time_str = event.get('strTime', '18:00:00')
            if not date_str:
                return None

            # Team IDs
            home_team_id = event.get('idHomeTeam', '')
            away_team_id = event.get('idAwayTeam', '')

            # Парсим дату и время
            try:
                if time_str:
                    dt_str = f"{date_str} {time_str}"
                    match_datetime = datetime.strptime(
                        dt_str, '%Y-%m-%d %H:%M:%S'
                    )
                else:
                    match_datetime = datetime.strptime(date_str, '%Y-%m-%d')
                    match_datetime = match_datetime.replace(
                        hour=18, minute=0
                    )
            except Exception as e:
                logger.debug(f"Ошибка парсинга даты: {e}")
                return None
            # Проверяем названия команд
            home_team_raw = event.get('strHomeTeam')
            away_team_raw = event.get('strAwayTeam')
            if not home_team_raw or not away_team_raw:
                return None
            home_team = home_team_raw.strip() if home_team_raw else ''
            away_team = away_team_raw.strip() if away_team_raw else ''
            if not home_team or not away_team:
                return None

            # Чистим названия
            def clean_name(name):
                if not name:
                    return "Unknown Team"

                # Суффиксы которые удаляем только если они в КОНЦЕ названия
                # (чтобы не сломать "Real Betis" → "Realetis")
                end_suffixes = [
                    ' FC', ' AFC', ' CF', ' SS', ' Club',
                    ' U19', ' U21', ' U23', ' B', ' II'
                ]

                for suffix in end_suffixes:
                    if name.endswith(suffix):
                        name = name[:-len(suffix)]
                        break  # Удаляем только один суффикс

                return name.strip()

            # Конвертируем время в МСК (UTC+3)
            match_datetime_msk = match_datetime + timedelta(hours=3)
            # UTC datetime в ISO8601
            match_datetime_utc = match_datetime.strftime(
                '%Y-%m-%dT%H:%M:%S+00:00'
            )
            # Создаем ID события
            api_event_id = event.get('idEvent')
            if not api_event_id:
                api_event_id = f"{home_team}_{away_team}_{date_str}"
            # Получаем лигу и тур/раунд для отображения
            league_name = event.get('strLeague', 'Unknown League')
            league_id = str(event.get('idLeague') or '')
            round_info = event.get('intRound') or event.get('strRound') or ''
            league_display = self._format_league_display(
                league_name=league_name,
                league_id=league_id,
                round_info=round_info
            )

            return {
                'sport': 'football',
                'team1': clean_name(home_team),
                'team2': clean_name(away_team),
                'match_date': match_datetime.date(),
                'match_datetime': match_datetime_msk,
                'match_time': match_datetime_msk.time().strftime('%H:%M'),
                'league': league_display,
                'api_event_id': api_event_id,
                'price': 150,
                'is_active': 1,
                'source': self.source,
                'home_team_id': str(home_team_id),
                'away_team_id': str(away_team_id),
                'match_datetime_utc': match_datetime_utc,
            }
        except Exception as e:
            logger.debug(f"Ошибка парсинга: {e}")
            return None

    @staticmethod
    def _format_cup_round(round_info) -> str:
        """Нормализует раунд еврокубка в читабельный формат."""
        round_map = {
            64: "1/32 финала",
            32: "1/16 финала",
            16: "1/8 финала",
            8: "1/4 финала",
            4: "1/2 финала",
            2: "Финал",
            1: "Финал",
        }

        round_text = str(round_info or '').strip()
        if not round_text:
            return ""

        if round_text.isdigit():
            round_num = int(round_text)
            return round_map.get(round_num, f"Раунд {round_num}")

        text_lc = round_text.lower()
        if "round of 32" in text_lc:
            return "1/16 финала"
        if "round of 16" in text_lc:
            return "1/8 финала"
        if "quarter" in text_lc:
            return "1/4 финала"
        if "semi" in text_lc:
            return "1/2 финала"
        if "final" in text_lc:
            return "Финал"

        # Удаляем шум вида "Round 32"
        cleaned = re.sub(r'^\s*round\s*', '', round_text, flags=re.IGNORECASE).strip()
        return cleaned or round_text

    def _format_league_display(self, league_name: str, league_id: str, round_info) -> str:
        """Формирует человекочитаемую строку турнира для карточки."""
        if not round_info:
            return league_name

        is_cup = any(cup['id'] == str(league_id) for cup in self.cups)
        if is_cup:
            round_label = self._format_cup_round(round_info)
            if round_label:
                return f"{league_name}. {round_label}"
            return league_name

        return f"{league_name}. {round_info} тур"

    def _remove_duplicates(self, matches: List[Dict]) -> List[Dict]:
        """Удалить дубликаты матчей (по api_event_id или team+date)"""
        unique_matches = []
        seen = set()
        for match in matches:
            key = match.get('api_event_id') or (
                match['team1'], match['team2'], str(match['match_date'])
            )
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)
        return unique_matches

    def save_matches_to_db(self, matches: List[Dict]) -> Dict:
        """Сохранить матчи в БД (idempotent: проверка по api_event_id)"""
        results = {
            'total': len(matches),
            'inserted': 0,
            'skipped': 0,
            'errors': 0
        }
        if not matches:
            return results
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            for i, match in enumerate(matches):
                try:
                    match_date_str = match['match_date'].strftime('%Y-%m-%d')
                    # Проверяем по api_event_id (приоритет)
                    api_eid = match.get('api_event_id')
                    existing = None
                    if api_eid:
                        cursor.execute(
                            'SELECT id FROM matches WHERE api_event_id = ?',
                            (api_eid,)
                        )
                        existing = cursor.fetchone()
                    # Fallback: проверка по team+date
                    if not existing:
                        cursor.execute('''
                            SELECT id FROM matches
                            WHERE team1 = ? AND team2 = ? AND match_date = ?
                        ''', (match['team1'], match['team2'], match_date_str))
                        existing = cursor.fetchone()
                    if existing:
                        results['skipped'] += 1
                        logger.debug(
                            f"Пропущен дубликат: "
                            f"{match['team1']} vs {match['team2']}"
                        )
                    else:
                        cursor.execute('''
                            INSERT INTO matches
                            (sport, team1, team2, match_date, match_time,
                             league, api_event_id, price, is_active,
                             source, home_team_id, away_team_id, match_datetime)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            match['sport'],
                            match['team1'],
                            match['team2'],
                            match_date_str,
                            match['match_time'],
                            match['league'],
                            match['api_event_id'],
                            match['price'],
                            match['is_active'],
                            match.get('source'),
                            match.get('home_team_id'),
                            match.get('away_team_id'),
                            match.get('match_datetime_utc'),
                        ))
                        results['inserted'] += 1
                        logger.info(
                            f"Добавлен: {match['team1']} vs "
                            f"{match['team2']} ({match['match_time']} МСК)"
                        )
                    conn.commit()
                    # Batch checkpoint
                    if (i + 1) % self.batch_size == 0:
                        logger.info(
                            f"Batch checkpoint: {i + 1}/{len(matches)}"
                        )
                except sqlite3.IntegrityError:
                    conn.rollback()
                    results['skipped'] += 1
                except Exception as e:
                    conn.rollback()
                    results['errors'] += 1
                    logger.error(f"Ошибка сохранения: {e}")
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка БД: {e}")
            if conn:
                conn.close()
        # Записываем timestamp последнего sync
        self._save_sync_timestamp()
        return results

    def _save_sync_timestamp(self):
        """Сохранить время последнего sync в sync_meta"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY, value TEXT
                )
            ''')
            conn.execute('''
                INSERT OR REPLACE INTO sync_meta (key, value)
                VALUES ('last_sync_at', datetime('now'))
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Не удалось сохранить timestamp sync: {e}")

    def get_seconds_since_last_sync(self) -> Optional[float]:
        """Сколько секунд прошло с последнего sync (None если не было)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT value FROM sync_meta WHERE key = 'last_sync_at'
            ''')
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            last_sync = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            now = datetime.utcnow()
            return (now - last_sync).total_seconds()
        except Exception:
            return None


def run_coverage_check(
    db_path: str = "sports_bot.db",
    min_rows: int = 3,
    max_missing_cells: int = 1,
    sleep_seconds: float = 0.8
) -> Dict[str, int]:
    """
    Проверяет coverage для матчей с coverage_ok IS NULL.
    Обновляет coverage_ok и coverage_checked_at для каждого матча.
    """
    from match_data_fetcher import MatchDataFetcher
    from analysis_formatter import build_table_data

    started_at = time.monotonic()
    results = {
        'checked': 0,
        'ok': 0,
        'hidden': 0,
        'errors': 0,
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    _ensure_coverage_columns(cursor)
    conn.commit()

    cursor.execute('''
        SELECT *
        FROM matches
        WHERE coverage_ok IS NULL
        ORDER BY match_date, match_time
    ''')
    matches = cursor.fetchall()

    if not matches:
        conn.close()
        logger.info("[COVERAGE] Нет матчей для проверки")
        return results

    logger.info(
        "[COVERAGE] Старт проверки: %s матчей (rows >= %s, missing <= %s)",
        len(matches), min_rows, max_missing_cells
    )

    fetcher = MatchDataFetcher()
    for idx, row in enumerate(matches, start=1):
        match = dict(row)
        checked_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        team1 = match.get('team1', '?')
        team2 = match.get('team2', '?')

        try:
            enriched_data = fetcher.fetch_match_data(
                match,
                include_h2h=False,
                include_standings=False,
                include_lineups=True,
                include_domestic_positions=False,
                include_last_match_events=True,
                include_event_stats=False,
                include_cup_context=False,
                lineup_scan_limit=2
            )
            table_data = build_table_data(match, enriched_data)
            rows_count, missing_cells = _extract_coverage_metrics(table_data)
            is_ok = int(rows_count >= min_rows and missing_cells <= max_missing_cells)

            cursor.execute(
                '''
                UPDATE matches
                SET coverage_ok = ?, coverage_checked_at = ?
                WHERE id = ?
                ''',
                (is_ok, checked_at, match['id'])
            )
            conn.commit()

            results['checked'] += 1
            if is_ok:
                results['ok'] += 1
                logger.info(
                    "[COVERAGE] ✓ %s vs %s — rows=%s, missing=%s",
                    team1, team2, rows_count, missing_cells
                )
            else:
                results['hidden'] += 1
                logger.info(
                    "[COVERAGE] ✗ %s vs %s — rows=%s, missing=%s → скрыт",
                    team1, team2, rows_count, missing_cells
                )
        except Exception as e:
            results['checked'] += 1
            results['errors'] += 1
            results['hidden'] += 1
            cursor.execute(
                '''
                UPDATE matches
                SET coverage_ok = 0, coverage_checked_at = ?
                WHERE id = ?
                ''',
                (checked_at, match['id'])
            )
            conn.commit()
            logger.warning(
                "[COVERAGE] ✗ %s vs %s — ошибка: %s → скрыт",
                team1, team2, e
            )

        if idx < len(matches) and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    conn.close()
    elapsed = time.monotonic() - started_at
    logger.info(
        "[COVERAGE] Проверка завершена за %.1fс: %s ОК, %s скрыты",
        elapsed, results['ok'], results['hidden']
    )
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Синхронизация матчей из TheSportsDB API'
    )
    parser.add_argument(
        '--mode',
        choices=['top3', 'all'],
        default='top3',
        help='Режим: top3 (по умолчанию) или all (bulk import)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=3,
        help='Макс. количество матчей в режиме top3 (по умолчанию: 3)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=15,
        help='Размер батча для сохранения (по умолчанию: 15)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Только просмотр, без сохранения в БД'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Подробный вывод'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Режим отладки'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='sports_bot.db',
        help='Путь к базе данных'
    )
    parser.add_argument(
        '--min-coverage-rows',
        type=int,
        default=0,
        help='Мягкий фильтр качества: минимум заполненных строк в карточке (например, 3)'
    )
    parser.add_argument(
        '--max-missing-cells',
        type=int,
        default=1,
        help='Мягкий фильтр качества: максимум ячеек "Недостаточно данных" в карточке'
    )
    parser.add_argument(
        '--check-coverage',
        action='store_true',
        help='Запустить проверку покрытия'
    )
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.check_coverage:
        print(f"Проверка покрытия (БД: {args.db})")
        print("=" * 60)
        results = run_coverage_check(
            db_path=args.db,
            min_rows=args.min_coverage_rows if args.min_coverage_rows > 0 else 3,
            max_missing_cells=args.max_missing_cells
        )
        print(f"Проверено: {results['checked']}")
        print(f"ОК: {results['ok']}")
        print(f"Скрыто: {results['hidden']}")
        print(f"Ошибок: {results['errors']}")
        return 0

    print(f"Синхронизация матчей (режим: {args.mode})")
    print("=" * 60)
    if args.mode == 'top3':
        print(f"Top-{args.limit} матчей из 3 лиг + 3 кубков")
    else:
        print("3 топ-лиги + 3 кубка (bulk)")
    if args.min_coverage_rows > 0:
        print(
            f"Включён мягкий фильтр: минимум {args.min_coverage_rows} "
            "заполненных строк в карточке"
        )
    print("На 3 дня вперед")
    print("Время показано в МСК (UTC+3)")
    print("=" * 60)
    syncer = SportsDBSyncer(
        db_path=args.db, mode=args.mode,
        limit=args.limit, batch_size=args.batch_size,
        min_coverage_rows=args.min_coverage_rows,
        max_missing_cells=args.max_missing_cells
    )
    print("Поиск матчей...")
    matches = syncer.sync()
    if not matches:
        print("\nНе удалось получить матчи")
        return 1
    print(f"Найдено {len(matches)} матчей")
    # Группируем по датам и лигам
    matches_by_date_league = defaultdict(lambda: defaultdict(list))
    for match in matches:
        date_str = match['match_date'].strftime('%Y-%m-%d')
        league = match['league']
        matches_by_date_league[date_str][league].append(match)
    # Показываем матчи
    print("\nМатчи (время в МСК):")
    print("=" * 70)
    total_matches = 0
    for date_str in sorted(matches_by_date_league.keys()):
        date_display = datetime.strptime(
            date_str, '%Y-%m-%d').strftime('%d.%m.%Y')
        date_matches = matches_by_date_league[date_str]
        date_total = sum(
            len(league_matches) for league_matches in date_matches.values()
        )
        total_matches += date_total
        print(f"\n{date_display} ({date_total} матчей):")
        print("-" * 50)
        for league in sorted(date_matches.keys()):
            league_matches = date_matches[league]
            print(f"\n  {league}:")
            for match in sorted(
                league_matches, key=lambda x: x['match_time']
            ):
                teams = f"{match['team1']} - {match['team2']}"
                time_display = match['match_time']
                print(f"    {teams:40} {time_display}")
                if (match.get('venue')
                        and match['venue'] != 'Unknown Stadium'):
                    print(f"      {match['venue'][:30]}")
    print("\n" + "=" * 70)
    print(f"Всего матчей: {total_matches}")
    print("=" * 70)
    # Сохраняем если не dry-run
    if not args.dry_run:
        print(f"\nСохранение в БД: {args.db}")
        results = syncer.save_matches_to_db(matches)
        print("\nРезультаты:")
        print("=" * 60)
        print(f"Всего обработано: {results['total']}")
        print(f"Новых добавлено: {results['inserted']}")
        print(f"Пропущено (дубли): {results['skipped']}")
        print(f"Ошибок: {results['errors']}")
        print("=" * 60)
        if results['inserted'] > 0:
            print("Матчи успешно сохранены в БД!")
        else:
            print("Новых матчей не найдено")
    else:
        print("Dry-run режим - матчи НЕ сохранены")
    return 0


if __name__ == "__main__":
    try:
        if not THESPORTSDB_VERIFY_TLS:
            urllib3.disable_warnings(InsecureRequestWarning)
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nПрервано")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        sys.exit(1)
