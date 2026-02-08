import sys
import os
import argparse
import logging
from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict, Optional
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
    """Класс для работы с лимитированным API"""

    def __init__(self):
        self.api_key = "123"
        self.base_url = f"https://www.thesportsdb.com/api/v1/json/{self.api_key}"
        self.requests_per_minute = 28
        self.requests_made = []
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        self.session.verify = False

    def make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Выполнить запрос с учетом лимита"""
        self._check_rate_limit()
        try:
            url = f"{self.base_url}/{endpoint}"
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code != 200:
                logger.debug(f"Статус {response.status_code} для {endpoint}")
                return {}
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка запроса: {e}")
            return {}

    def _check_rate_limit(self):
        """Проверить и соблюдать лимит запросов"""
        now = time.time()
        minute_ago = now - 60
        self.requests_made = [t for t in self.requests_made if t > minute_ago]
        if len(self.requests_made) >= self.requests_per_minute:
            wait_time = 61
            logger.info(f"⚠️ Лимит запросов. Ждем {wait_time} секунд...")
            time.sleep(wait_time)
            self.requests_made = []


class SportsDBSyncer:
    """Синхронизатор для получения ВСЕХ матчей из топ-лиг и кубков на неделю"""

    def __init__(self, db_path: str = "sports_bot.db"):
        self.db_path = db_path
        self.api = RateLimitedAPI()
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

    def get_week_matches(self) -> List[Dict]:
        """
        Получить ВСЕ матчи из всех лиг и кубков на неделю вперед
        Используем два метода для получения полного расписания
        """
        all_matches = []
        all_leagues = self.top_leagues + self.cups
        logger.info(f"Поиск матчей из {len(all_leagues)} лиг/кубков на неделю...")
        # МЕТОД 1: Получение матчей по лигам (eventsnextleague.php)
        for league in all_leagues:
            try:
                logger.info(f"Метод 1: Получение матчей из: {league['name']}")
                data = self.api.make_request("eventsnextleague.php", {"id": league['id']})
                if not data or 'events' not in data:
                    logger.warning(f"Пустой ответ для {league['name']}")
                    continue
                events = data['events']
                if not events:
                    logger.info(f"Нет матчей для {league['name']}")
                    continue
                logger.info(f"Найдено {len(events)} событий в {league['name']}")
                for event in events:
                    match = self._parse_event(event)
                    if match and self._is_within_week(match['match_date']):
                        all_matches.append(match)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка для {league['name']}: {e}")
                continue
        # МЕТОД 2: Получение матчей по дням (eventsday.php)
        logger.info("Метод 2: Поиск матчей по дням недели...")
        today = datetime.now().date()
        for day_offset in range(8):  # Сегодня + 7 дней
            current_date = today + timedelta(days=day_offset)
            try:
                logger.info(f"Поиск матчей на {current_date}")
                # Ищем матчи на конкретную дату
                data = self.api.make_request("eventsday.php", {
                    "d": current_date.strftime('%Y-%m-%d')
                })
                if not data or 'events' not in data:
                    continue
                events = data['events']
                for event in events:
                    match = self._parse_event(event)
                    if match:
                        # Проверяем, что матч из нужных лиг/кубков
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
        # МЕТОД 3: Для АПЛ получаем матчи турнирного круга
        logger.info("Метод 3: Дополнительный поиск матчей АПЛ...")
        try:
            # Ищем матчи Premier League отдельно
            for round_num in range(25, 31):  # Примерно с 25 по 30 тур
                data = self.api.make_request("eventsround.php", {
                    "id": "4328",  # Premier League ID
                    "r": str(round_num)
                })
                if data and 'events' in data:
                    for event in data['events']:
                        match = self._parse_event(event)
                        if match and self._is_within_week(match['match_date']):
                            all_matches.append(match)
                time.sleep(0.3)
        except Exception as e:
            logger.error(f"Ошибка поиска по турам АПЛ: {e}")
        # Удаляем дубликаты
        unique_matches = self._remove_duplicates(all_matches)
        unique_matches.sort(key=lambda x: (x['match_date'], x['match_time']))
        logger.info(f"Итого найдено уникальных матчей на неделю: {
            len(unique_matches)}")
        return unique_matches

    def _is_within_week(self, match_date) -> bool:
        """Проверить, что матч в пределах недели"""
        today = datetime.now().date()
        week_later = today + timedelta(days=7)
        return today <= match_date <= week_later

    def _parse_event(self, event: Dict) -> Optional[Dict]:
        """Парсить событие с конвертацией времени в МСК"""
        try:
            date_str = event.get('dateEvent')
            time_str = event.get('strTime', '18:00:00')
            if not date_str:
                return None
            # Парсим дату и время
            try:
                if time_str:
                    dt_str = f"{date_str} {time_str}"
                    match_datetime = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                else:
                    match_datetime = datetime.strptime(date_str, '%Y-%m-%d')
                    match_datetime = match_datetime.replace(hour=18, minute=0)
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
                # Убираем приставки
                replacements = [
                    (' FC', ''),
                    (' AFC', ''),
                    (' CF', ''),
                    (' SS', ''),
                    (' Club', ''),
                    (' U19', ''),
                    (' U21', ''),
                    (' U23', ''),
                    (' B', ''),  # Убираем резервные команды
                    (' II', ''),
                ]
                for old, new in replacements:
                    name = name.replace(old, new)
                return name.strip()
            # Конвертируем время в МСК (UTC+3)
            # Время в API обычно в UTC, добавляем 3 часа для МСК
            match_datetime_msk = match_datetime + timedelta(hours=3)
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
                'match_datetime': match_datetime_msk,  # Сохраняем с МСК временем
                'match_time': match_datetime_msk.time().strftime('%H:%M'),  # Время в МСК
                'league': round_display,  # Включаем номер тура
                'venue': event.get('strVenue', 'Unknown Stadium'),
                'api_event_id': api_event_id,
                'status': event.get('strStatus', 'Scheduled'),
                'price': 150,
                'is_active': 1,
                'round': round_info
            }
        except Exception as e:
            logger.debug(f"Ошибка парсинга: {e}")
            return None

    def _remove_duplicates(self, matches: List[Dict]) -> List[Dict]:
        """Удалить дубликаты матчей"""
        unique_matches = []
        seen = set()
        for match in matches:
            key = (match['team1'], match['team2'], str(match['match_date']))
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)
        return unique_matches

    def save_matches_to_db(self, matches: List[Dict]) -> Dict:
        """Сохранить матчи в БД"""
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
            for match in matches:
                try:
                    # Форматируем дату как строку
                    match_date_str = match['match_date'].strftime('%Y-%m-%d')
                    # Проверяем существование по нескольким критериям
                    cursor.execute('''
                        SELECT id FROM matches
                        WHERE team1 = ? AND team2 = ? AND match_date = ?
                    ''', (match['team1'], match['team2'], match_date_str))
                    existing = cursor.fetchone()
                    if existing:
                        results['skipped'] += 1
                        logger.debug(f"Пропущен дубликат: {match['team1']} vs {match['team2']}")
                    else:
                        # Вставляем новый матч
                        cursor.execute('''
                            INSERT INTO matches
                            (sport, team1, team2, match_date, match_time,
                             league, venue, api_event_id, status, price,
                                        is_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            match['sport'],
                            match['team1'],
                            match['team2'],
                            match_date_str,
                            match['match_time'],  # Сохраняем время в МСК
                            match['league'],
                            match['venue'],
                            match['api_event_id'],
                            match['status'],
                            match['price'],
                            match['is_active']
                        ))
                        results['inserted'] += 1
                        logger.info(f"✅ Добавлен: {match['team1']} vs {match['team2']} ({match['match_time']} МСК)")
                    conn.commit()
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
        return results


def main():
    parser = argparse.ArgumentParser(
        description='Получение ВСЕХ матчей из 5 топ-лиг и кубков на неделю'
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
    print("🚀 ПОЛУЧЕНИЕ МАТЧЕЙ НА НЕДЕЛЮ")
    print("="*60)
    print("⚽ 5 топ-лиг + дополнительные кубки")
    print("📅 Строго на неделю вперед")
    print("🕐 Время показано в МСК (UTC+3)")
    print("="*60)
    syncer = SportsDBSyncer(db_path=args.db)
    print("🔄 Поиск матчей...")
    matches = syncer.get_week_matches()
    if not matches:
        print("\n❌ Не удалось получить матчи")
        return 1
    print(f"✅ Найдено {len(matches)} матчей")
    # Группируем по датам и лигам
    matches_by_date_league = defaultdict(lambda: defaultdict(list))
    for match in matches:
        date_str = match['match_date'].strftime('%Y-%m-%d')
        league = match['league']
        matches_by_date_league[date_str][league].append(match)
    # Показываем матчи
    print("\n📋 МАТЧИ НА НЕДЕЛЮ (время в МСК):")
    print("="*70)
    total_matches = 0
    for date_str in sorted(matches_by_date_league.keys()):
        date_display = datetime.strptime(
            date_str, '%Y-%m-%d').strftime('%d.%m.%Y')
        date_matches = matches_by_date_league[date_str]
        date_total = sum(len(league_matches) for league_matches
                         in date_matches.values())
        total_matches += date_total
        print(f"\n📅 {date_display} ({date_total} матчей):")
        print("-"*50)
        for league in sorted(date_matches.keys()):
            league_matches = date_matches[league]
            print(f"\n🏆 {league}:")
            for match in sorted(league_matches, key=lambda x: x['match_time']):
                # Форматируем вывод
                teams = f"{match['team1']} - {match['team2']}"
                time_display = match['match_time']
                print(f"  ⚽ {teams:40} 🕐 {time_display}")     
                # Если есть информация о стадионе
                if match.get('venue') and match['venue'] != 'Unknown Stadium':
                    print(f"    🏟 {match['venue'][:30]}")
    print("\n" + "="*70)
    print(f"📊 ВСЕГО МАТЧЕЙ НА НЕДЕЛЮ: {total_matches}")
    print("="*70)
    # Сохраняем если не dry-run
    if not args.dry_run:
        print(f"\n💾 Сохранение в БД: {args.db}")
        results = syncer.save_matches_to_db(matches)
        print("\n📊 РЕЗУЛЬТАТЫ:")
        print("="*60)
        print(f"📈 Всего обработано: {results['total']}")
        print(f"✅ Новых добавлено: {results['inserted']}")
        print(f"⏭️  Пропущено (дубли): {results['skipped']}")
        print(f"❌ Ошибок: {results['errors']}")
        print("="*60)
        if results['inserted'] > 0:
            print("🎉 Матчи успешно сохранены в БД!")
        else:
            print("ℹ️  Новых матчей не найдено")
    else:
        print("⚠️  Dry-run режим - матчи НЕ сохранены")
    return 0


if __name__ == "__main__":
    try:
        import urllib3
        urllib3.disable_warnings()
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Прервано")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        sys.exit(1)
