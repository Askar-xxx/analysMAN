import sys
import argparse
import json
import logging
from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict, Optional
from threading import Lock
import requests
import time
from collections import defaultdict

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RateLimitedAPI:
    """Класс для работы с лимитированным API (token bucket)"""

    def __init__(self, capacity=25, refill_rate=25):
        # API key "3" - test/development key (возвращает полные данные)
        # API key "123" - public patreon key (ограничен: searchevents=2, lookuptable=top5, eventslast=1)
        self.api_key = "3"
        self.base_url = f"https://www.thesportsdb.com/api/v1/json/{self.api_key}"
        # Token bucket
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
        self.session.verify = False

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
                 limit: int = 3, batch_size: int = 15):
        self.db_path = db_path
        self.api = RateLimitedAPI()
        self.mode = mode
        self.limit = limit
        self.batch_size = batch_size
        self.source = "TheSportsDB"
        # 5 популярных лиг
        self.top_leagues = [
            {'id': '4328', 'name': 'Premier League'},
            {'id': '4335', 'name': 'La Liga'},
            {'id': '4331', 'name': 'Bundesliga'},
            {'id': '4332', 'name': 'Serie A'},
            {'id': '4334', 'name': 'Ligue 1'},
        ]
        # Дополнительные кубки
        self.cups = [
            {'id': '4480', 'name': 'UEFA Champions League'},
            {'id': '4481', 'name': 'UEFA Europa League'},
            {'id': '4485', 'name': 'FA Cup'},
            {'id': '4486', 'name': 'EFL Cup'},
            {'id': '4487', 'name': 'Copa del Rey'},
        ]

    def sync(self) -> List[Dict]:
        """Основной метод: выбирает режим sync"""
        if self.mode == "top3":
            return self.get_top3_matches()
        else:
            return self.get_week_matches()

    def get_top3_matches(self) -> List[Dict]:
        """Получить top-N матчей ТОЛЬКО НА СЕГОДНЯ + ЗАВТРА (default mode) из первых лиг"""
        all_matches = []
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        logger.info(f"Режим top3: получение {self.limit} матчей только на {today} и {tomorrow}...")

        for league in self.top_leagues:
            if len(all_matches) >= self.limit:
                break
            try:
                logger.info(f"Получение матчей из: {league['name']}")
                data = self.api.make_request(
                    "eventsnextleague.php", {"id": league['id']}
                )
                if not data or 'events' not in data or not data['events']:
                    continue
                for event in data['events']:
                    if len(all_matches) >= self.limit:
                        break
                    match = self._parse_event(event)
                    if not match:
                        continue

                    # ФИЛЬТР: только сегодня + завтра
                    match_date = match['match_date']
                    if match_date not in [today, tomorrow]:
                        continue

                    all_matches.append(match)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка для {league['name']}: {e}")
                continue
        unique = self._remove_duplicates(all_matches)
        unique.sort(key=lambda x: (x['match_date'], x['match_time']))
        return unique[:self.limit]

    def get_week_matches(self) -> List[Dict]:
        """
        Получить ВСЕ матчи из всех лиг и кубков ТОЛЬКО НА СЕГОДНЯ + ЗАВТРА
        Используем два метода для получения полного расписания
        """
        all_matches = []
        all_leagues = self.top_leagues + self.cups
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        logger.info(
            f"Поиск матчей из {len(all_leagues)} лиг/кубков только на {today} и {tomorrow}..."
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

                    # ФИЛЬТР: только сегодня + завтра
                    match_date = match['match_date']
                    if match_date not in [today, tomorrow]:
                        continue

                    all_matches.append(match)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка для {league['name']}: {e}")
                continue
        # МЕТОД 2: Получение матчей по дням (eventsday.php) - ТОЛЬКО сегодня + завтра
        logger.info("Метод 2: Поиск матчей по дням (сегодня + завтра)...")
        for day_offset in range(2):  # Сегодня + завтра (0, 1)
            current_date = today + timedelta(days=day_offset)
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
        # МЕТОД 3: Для АПЛ получаем матчи турнирного круга (с фильтром today+tomorrow)
        logger.info("Метод 3: Дополнительный поиск матчей АПЛ...")
        try:
            for round_num in range(25, 31):
                data = self.api.make_request("eventsround.php", {
                    "id": "4328",
                    "r": str(round_num)
                })
                if data and 'events' in data:
                    for event in data['events']:
                        match = self._parse_event(event)
                        if not match:
                            continue

                        # ФИЛЬТР: только сегодня + завтра
                        match_date = match['match_date']
                        if match_date not in [today, tomorrow]:
                            continue

                        all_matches.append(match)
                time.sleep(0.3)
        except Exception as e:
            logger.error(f"Ошибка поиска по турам АПЛ: {e}")
        # Удаляем дубликаты
        unique_matches = self._remove_duplicates(all_matches)
        unique_matches.sort(key=lambda x: (x['match_date'], x['match_time']))
        logger.info(
            f"Итого найдено уникальных матчей на сегодня+завтра: "
            f"{len(unique_matches)}"
        )
        return unique_matches

    def _is_within_week(self, match_date) -> bool:
        """Проверить, что матч в пределах недели"""
        today = datetime.now().date()
        week_later = today + timedelta(days=7)
        return today <= match_date <= week_later

    def _parse_event(self, event: Dict) -> Optional[Dict]:
        """Парсить событие с конвертацией времени в МСК"""
        try:
            # Сохраняем raw JSON
            raw_json = json.dumps(event, ensure_ascii=False)

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
                replacements = [
                    (' FC', ''),
                    (' AFC', ''),
                    (' CF', ''),
                    (' SS', ''),
                    (' Club', ''),
                    (' U19', ''),
                    (' U21', ''),
                    (' U23', ''),
                    (' B', ''),
                    (' II', ''),
                ]
                for old, new in replacements:
                    name = name.replace(old, new)
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
            # Получаем тур (если есть)
            round_info = event.get('intRound', '')
            if round_info:
                league_name = event.get('strLeague', '')
                round_display = f"{league_name}. {round_info} тур"
            else:
                round_display = event.get('strLeague', 'Unknown League')
            return {
                'sport': 'football',
                'team1': clean_name(home_team),
                'team2': clean_name(away_team),
                'match_date': match_datetime.date(),
                'match_datetime': match_datetime_msk,
                'match_time': match_datetime_msk.time().strftime('%H:%M'),
                'league': round_display,
                'venue': event.get('strVenue', 'Unknown Stadium'),
                'api_event_id': api_event_id,
                'status': event.get('strStatus', 'Scheduled'),
                'price': 150,
                'is_active': 1,
                'round': round_info,
                # Новые поля для tracing
                'raw_json': raw_json,
                'source': self.source,
                'home_team_id': str(home_team_id),
                'away_team_id': str(away_team_id),
                'home_score': event.get('intHomeScore'),
                'away_score': event.get('intAwayScore'),
                'match_datetime_utc': match_datetime_utc,
            }
        except Exception as e:
            logger.debug(f"Ошибка парсинга: {e}")
            return None

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
                             league, venue, api_event_id, status, price,
                             is_active, raw_json, source, home_team_id,
                             away_team_id, home_score, away_score,
                             match_datetime, round)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                    ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            match['sport'],
                            match['team1'],
                            match['team2'],
                            match_date_str,
                            match['match_time'],
                            match['league'],
                            match['venue'],
                            match['api_event_id'],
                            match['status'],
                            match['price'],
                            match['is_active'],
                            match.get('raw_json'),
                            match.get('source'),
                            match.get('home_team_id'),
                            match.get('away_team_id'),
                            match.get('home_score'),
                            match.get('away_score'),
                            match.get('match_datetime_utc'),
                            match.get('round'),
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

    def cache_teams_from_matches(self, matches: List[Dict]) -> Dict:
        """Кэшировать все команды из списка матчей (отдельный шаг)"""
        cooldown = 65  # секунд после sync перед кэшированием
        results = {'cached': 0, 'already_cached': 0, 'errors': 0}

        # Проверяем cooldown после последнего sync
        elapsed = self.get_seconds_since_last_sync()
        if elapsed is not None and elapsed < cooldown:
            wait = int(cooldown - elapsed)
            print(
                f"Последний sync был {int(elapsed)}с назад. "
                f"Ожидание {wait}с для сброса API лимита..."
            )
            time.sleep(wait)
            print("Готово, начинаю кэширование.")

        seen_ids = set()
        for match in matches:
            for tid in (match.get('home_team_id'), match.get('away_team_id')):
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
        total = len(seen_ids)
        logger.info(f"Кэширование {total} уникальных команд...")
        for i, tid in enumerate(seen_ids, 1):
            try:
                result = self.cache_team(tid)
                if result:
                    from_cache = result.pop('_from_cache', False)
                    name = result.get('strTeam', result.get('name', tid))
                    if from_cache:
                        results['already_cached'] += 1
                        logger.debug(f"[{i}/{total}] Из кэша: {name}")
                    else:
                        results['cached'] += 1
                        logger.info(
                            f"[{i}/{total}] Закэширована: {name}"
                        )
                        # Пауза только после реального API-вызова
                        if i < total:
                            time.sleep(2.5)
                else:
                    results['errors'] += 1
                    logger.warning(f"[{i}/{total}] Не удалось: {tid}")
            except Exception as e:
                logger.error(f"Ошибка кэширования команды {tid}: {e}")
                results['errors'] += 1
        return results

    def cache_team(self, team_id: str) -> Optional[Dict]:
        """Кэшировать команду из lookupteam API (TTL 24h).
        Возвращает dict с ключом '_from_cache'=True если из кэша."""
        if not team_id:
            return None
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Проверяем кэш (TTL 24 часа)
        cursor.execute('''
            SELECT team_id, name, short_name, badge_url, sport, raw_json,
                   source, cached_at
            FROM teams WHERE team_id = ? AND
            datetime(cached_at, '+24 hours') > datetime('now')
        ''', (team_id,))
        cached = cursor.fetchone()
        if cached:
            conn.close()
            cols = ['team_id', 'name', 'short_name', 'badge_url',
                    'sport', 'raw_json', 'source', 'cached_at']
            result = dict(zip(cols, cached))
            result['_from_cache'] = True
            return result
        # Запрос к API
        data = self.api.make_request("lookupteam.php", {"id": team_id})
        if data and 'teams' in data and data['teams']:
            team = data['teams'][0]
            cursor.execute('''
                INSERT OR REPLACE INTO teams
                (team_id, name, short_name, badge_url, sport,
                 raw_json, source, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                team.get('idTeam'),
                team.get('strTeam'),
                team.get('strTeamShort', ''),
                team.get('strBadge', ''),
                'football',
                json.dumps(team, ensure_ascii=False),
                self.source,
            ))
            conn.commit()
            conn.close()
            return team
        conn.close()
        return None

    def fetch_h2h(self, match_id: int, team1: str, team2: str) -> Optional[Dict]:
        """
        Получить историю личных встреч (H2H) через searchevents.php.

        Args:
            match_id: ID матча в БД для обновления h2h_json
            team1: Название команды-хозяина
            team2: Название команды-гостя

        Returns:
            Dict с raw JSON от API или None при ошибке

        Примечание:
            - Сохраняет результат в БД (h2h_json, h2h_fetched_at)
            - При ошибках API не прерывает выполнение, логирует и возвращает None
            - Rate limiting: задержка 2.5s после вызова API
        """
        try:
            # searchevents.php принимает формат: "Team1_vs_Team2"
            # Пример: "Arsenal_vs_Chelsea"
            # ВАЖНО: очищаем названия команд от суффиксов и заменяем пробелы
            def clean_team_name_for_h2h(name: str) -> str:
                """Очистка названия команды для H2H запроса."""
                # Убираем распространенные суффиксы
                suffixes = [
                    ' United', ' City', ' FC', ' AFC', ' CF',
                    ' Wanderers', ' Rovers', ' Town', ' County',
                    ' Athletic', ' Albion', ' Villa'
                ]
                cleaned = name
                for suffix in suffixes:
                    if cleaned.endswith(suffix):
                        cleaned = cleaned[:-len(suffix)]
                        break
                # Заменяем пробелы на подчеркивания
                return cleaned.replace(' ', '_')

            team1_clean = clean_team_name_for_h2h(team1)
            team2_clean = clean_team_name_for_h2h(team2)
            search_query = f"{team1_clean}_vs_{team2_clean}"

            logger.info(f"Получение H2H для {search_query} (оригинал: {team1} vs {team2})")
            data = self.api.make_request("searchevents.php", {"e": search_query})

            # Задержка после API вызова (rate limiting)
            time.sleep(2.5)

            if not data:
                logger.warning(f"Пустой ответ H2H для {search_query}")
                # Сохраняем пустой JSON чтобы не запрашивать повторно
                self._save_h2h_to_db(match_id, json.dumps({"events": []}, ensure_ascii=False))
                return None

            # API возвращает {"event": [...]} для searchevents
            events = data.get('event', [])
            if not events:
                logger.info(f"H2H не найдено для {search_query}")
                self._save_h2h_to_db(match_id, json.dumps({"events": []}, ensure_ascii=False))
                return None

            logger.debug(f"API вернул событий: {len(events)}")

            # Фильтруем только завершённые матчи (intHomeScore != None)
            completed_events = [
                e for e in events
                if e.get('intHomeScore') is not None
            ]

            logger.debug(f"Завершенных матчей после фильтрации: {len(completed_events)}")

            # Берём последние 5-7 матчей
            h2h_data = {
                "events": completed_events[:7],
                "total": len(completed_events)
            }

            h2h_json = json.dumps(h2h_data, ensure_ascii=False)
            self._save_h2h_to_db(match_id, h2h_json)

            logger.info(f"H2H сохранено: {len(completed_events[:7])} матчей для {search_query}")
            return h2h_data

        except Exception as e:
            logger.error(f"Ошибка при получении H2H для match_id={match_id}: {e}")
            return None

    def _save_h2h_to_db(self, match_id: int, h2h_json: str):
        """Сохранить H2H JSON в БД с timestamp"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE matches
                SET h2h_json = ?, h2h_fetched_at = datetime('now')
                WHERE id = ?
            ''', (h2h_json, match_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка сохранения H2H для match_id={match_id}: {e}")

    def fetch_standings(self, match_id: int, league_id: str, season: str,
                        home_team_id: str, away_team_id: str) -> Optional[Dict]:
        """
        Получить турнирную таблицу через lookuptable.php.

        Args:
            match_id: ID матча в БД для обновления standings_json
            league_id: ID лиги (из raw_json → idLeague)
            season: Сезон (из raw_json → strSeason, например "2025-2026")
            home_team_id: ID команды-хозяина (для фильтрации в таблице)
            away_team_id: ID команды-гостя (для фильтрации в таблице)

        Returns:
            Dict с raw JSON от API или None при ошибке

        Примечание:
            - Бесплатный ключ: только топ-5 команд в таблице
            - Сохраняет результат в БД (standings_json, standings_fetched_at)
            - При ошибках API не прерывает выполнение
            - Rate limiting: задержка 2.5s после вызова API
        """
        try:
            if not league_id or not season:
                logger.warning(f"Пропуск standings для match_id={match_id}: league_id или season отсутствуют")
                return None

            logger.info(f"Получение таблицы для league_id={league_id}, season={season}")
            data = self.api.make_request("lookuptable.php", {"l": league_id, "s": season})

            # Задержка после API вызова (rate limiting)
            time.sleep(2.5)

            if not data:
                logger.warning(f"Пустой ответ standings для league={league_id}")
                # Сохраняем маркер что таблица недоступна
                self._save_standings_to_db(
                    match_id,
                    json.dumps({"table": [], "table_missing": True}, ensure_ascii=False)
                )
                return None

            # API возвращает {"table": [...]}
            table = data.get('table', [])
            if not table:
                logger.info(f"Таблица пуста для league={league_id}, season={season}")
                self._save_standings_to_db(
                    match_id,
                    json.dumps({"table": [], "table_missing": True}, ensure_ascii=False)
                )
                return None

            # Фильтруем только команды из этого матча (для экономии места)
            # Но сохраняем всю таблицу для контекста позиций
            standings_data = {
                "table": table,
                "league_id": league_id,
                "season": season,
                "total_teams": len(table)
            }

            standings_json = json.dumps(standings_data, ensure_ascii=False)
            self._save_standings_to_db(match_id, standings_json)

            logger.info(f"Standings сохранено: {len(table)} команд для league={league_id}")
            return standings_data

        except Exception as e:
            logger.error(f"Ошибка при получении standings для match_id={match_id}: {e}")
            return None

    def _save_standings_to_db(self, match_id: int, standings_json: str):
        """Сохранить standings JSON в БД с timestamp"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE matches
                SET standings_json = ?, standings_fetched_at = datetime('now')
                WHERE id = ?
            ''', (standings_json, match_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка сохранения standings для match_id={match_id}: {e}")

    def enrich_matches(self, ttl_hours: int = 24) -> Dict:
        """
        Обогатить матчи данными H2H и standings.

        Для каждого матча без h2h_json/standings_json или с устаревшими данными
        (старше ttl_hours часов) вызывает fetch_h2h() и fetch_standings().

        Args:
            ttl_hours: TTL кэша в часах (по умолчанию 24)

        Returns:
            Dict со статистикой: {"h2h_enriched": N, "standings_enriched": M, "errors": K}

        Примечание:
            - Не прерывает выполнение при ошибках API
            - Rate limiting встроен в fetch_h2h/fetch_standings (2.5s каждый)
        """
        stats = {
            "h2h_enriched": 0,
            "standings_enriched": 0,
            "errors": 0
        }

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Получаем матчи требующие обогащения
            # h2h_json IS NULL OR h2h_fetched_at устарел (> ttl_hours)
            # standings_json IS NULL OR standings_fetched_at устарел
            cursor.execute(f'''
                SELECT id, team1, team2, home_team_id, away_team_id,
                       raw_json, h2h_json, h2h_fetched_at,
                       standings_json, standings_fetched_at
                FROM matches
                WHERE is_active = 1
                AND (
                    h2h_json IS NULL
                    OR datetime(h2h_fetched_at, '+{ttl_hours} hours') < datetime('now')
                    OR standings_json IS NULL
                    OR datetime(standings_fetched_at, '+{ttl_hours} hours') < datetime('now')
                )
                ORDER BY match_date, match_time
            ''')

            matches_to_enrich = cursor.fetchall()
            conn.close()

            if not matches_to_enrich:
                logger.info("Все матчи уже обогащены актуальными данными")
                return stats

            logger.info(f"Найдено {len(matches_to_enrich)} матчей для обогащения")

            for match_row in matches_to_enrich:
                # Конвертируем sqlite3.Row в dict для использования .get()
                match = dict(match_row)
                match_id = match['id']
                team1 = match['team1']
                team2 = match['team2']

                # Проверка H2H
                needs_h2h = (
                    match['h2h_json'] is None or
                    self._is_data_stale(match['h2h_fetched_at'], ttl_hours)
                )

                if needs_h2h:
                    logger.info(f"Обогащение H2H для match_id={match_id}: {team1} vs {team2}")
                    try:
                        result = self.fetch_h2h(match_id, team1, team2)
                        if result is not None:
                            stats["h2h_enriched"] += 1
                    except Exception as e:
                        logger.error(f"Ошибка H2H для match_id={match_id}: {e}")
                        stats["errors"] += 1

                # Проверка standings
                needs_standings = (
                    match['standings_json'] is None or
                    self._is_data_stale(match['standings_fetched_at'], ttl_hours)
                )

                if needs_standings:
                    # Извлекаем league_id и season из raw_json
                    raw_json = match.get('raw_json')
                    if raw_json:
                        try:
                            event_data = json.loads(raw_json)
                            league_id = event_data.get('idLeague')
                            season = event_data.get('strSeason')
                            home_team_id = match['home_team_id']
                            away_team_id = match['away_team_id']

                            if league_id and season:
                                logger.info(
                                    f"Обогащение standings для match_id={match_id}: "
                                    f"league={league_id}, season={season}"
                                )
                                result = self.fetch_standings(
                                    match_id, league_id, season,
                                    home_team_id, away_team_id
                                )
                                if result is not None:
                                    stats["standings_enriched"] += 1
                            else:
                                logger.warning(
                                    f"Пропуск standings для match_id={match_id}: "
                                    f"нет league_id или season в raw_json"
                                )
                        except json.JSONDecodeError as e:
                            logger.error(f"Ошибка парсинга raw_json для match_id={match_id}: {e}")
                            stats["errors"] += 1
                        except Exception as e:
                            logger.error(f"Ошибка standings для match_id={match_id}: {e}")
                            stats["errors"] += 1

            logger.info(
                f"Обогащение завершено: H2H={stats['h2h_enriched']}, "
                f"Standings={stats['standings_enriched']}, Ошибки={stats['errors']}"
            )
            return stats

        except Exception as e:
            logger.error(f"Критическая ошибка enrich_matches: {e}")
            stats["errors"] += 1
            return stats

    def _is_data_stale(self, fetched_at: Optional[str], ttl_hours: int) -> bool:
        """Проверить устарели ли данные (fetched_at старше ttl_hours)"""
        if not fetched_at:
            return True
        try:
            fetched_time = datetime.fromisoformat(fetched_at)
            now = datetime.now()
            age = (now - fetched_time).total_seconds() / 3600  # в часах
            return age >= ttl_hours
        except Exception:
            return True  # Если ошибка парсинга — считаем устаревшим


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
        '--cache-teams',
        action='store_true',
        help='После sync кэшировать данные команд (доп. API запросы)'
    )
    parser.add_argument(
        '--only-cache-teams',
        action='store_true',
        help='Только кэшировать команды (без sync матчей)'
    )
    parser.add_argument(
        '--enrich',
        action='store_true',
        help='Обогатить матчи данными H2H и standings после sync'
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
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Режим: только кэширование команд (без sync)
    if args.only_cache_teams:
        syncer = SportsDBSyncer(db_path=args.db)
        # Загружаем team_id из существующих матчей в БД
        conn = sqlite3.connect(args.db)
        rows = conn.execute(
            'SELECT DISTINCT home_team_id, away_team_id FROM matches '
            'WHERE home_team_id IS NOT NULL'
        ).fetchall()
        conn.close()
        if not rows:
            print("В БД нет матчей с team_id. Сначала запустите sync.")
            return 1
        # Собираем фейковый список матчей для cache_teams_from_matches
        fake_matches = [
            {'home_team_id': r[0], 'away_team_id': r[1]} for r in rows
        ]
        print(f"Кэширование команд из {len(rows)} матчей в БД...")
        team_results = syncer.cache_teams_from_matches(fake_matches)
        print(f"Команд закэшировано: {team_results['cached']}")
        if team_results['errors'] > 0:
            print(f"Ошибок (429/timeout): {team_results['errors']}")
        return 0

    print(f"Синхронизация матчей (режим: {args.mode})")
    print("=" * 60)
    if args.mode == 'top3':
        print(f"Top-{args.limit} матчей из топ-лиг")
    else:
        print("5 топ-лиг + дополнительные кубки (bulk)")
    print("На неделю вперед")
    print("Время показано в МСК (UTC+3)")
    print("=" * 60)
    syncer = SportsDBSyncer(
        db_path=args.db, mode=args.mode,
        limit=args.limit, batch_size=args.batch_size
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
        # Кэшируем команды если запрошено
        if args.cache_teams:
            print("\nКэширование данных команд...")
            team_results = syncer.cache_teams_from_matches(matches)
            print(f"Команд закэшировано: {team_results['cached']}")
            if team_results['errors'] > 0:
                print(f"Ошибок (429/timeout): {team_results['errors']}")
        # Обогащаем H2H и standings если запрошено
        if args.enrich:
            print("\nОбогащение матчей данными H2H и standings...")
            enrich_results = syncer.enrich_matches()
            print(f"H2H обогащено: {enrich_results['h2h_enriched']}")
            print(f"Standings обогащено: {enrich_results['standings_enriched']}")
            if enrich_results['errors'] > 0:
                print(f"Ошибок: {enrich_results['errors']}")
    else:
        print("Dry-run режим - матчи НЕ сохранены")
    return 0


if __name__ == "__main__":
    try:
        import urllib3
        urllib3.disable_warnings()
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nПрервано")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        sys.exit(1)
