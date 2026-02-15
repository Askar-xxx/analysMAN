"""
Единый скрипт синхронизации матчей через API-Football.

Заменяет sync_matches.py (TheSportsDB) как основной источник данных.
Поддерживает 3 лиги: EPL, La Liga, Bundesliga.

Расчёт запросов (из 100/day):
- Fixtures: 3 лиги x 2 дня = 6 запросов
- С enrich (~10 матчей): +20 stats/injuries + 3 standings + 3 scorers + ~10 h2h = ~42
- Итого: ~48 запросов

Использование:
    python sync_football.py                    # Sync матчей (6 запросов)
    python sync_football.py --enrich           # Sync + enrich (~48 запросов)
    python sync_football.py --dry-run          # Preview
    python sync_football.py --enrich --force   # Игнорировать TTL
"""

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from sync_api_football import (
    APIFootballClient, enrich_match, QuotaExceededError
)
from database import sync_match_from_api, get_db_connection

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))

# 3 лиги для экономии запросов
TOP_LEAGUES = [
    {'id': 39, 'name': 'Premier League', 'country': 'England'},
    {'id': 140, 'name': 'La Liga', 'country': 'Spain'},
    {'id': 78, 'name': 'Bundesliga', 'country': 'Germany'},
]


def get_season_for_date(date: datetime) -> int:
    """
    Определить сезон по дате матча.

    Европейские лиги: сезон начинается в июле/августе.
    Если месяц >= 7, сезон = год. Иначе сезон = год - 1.

    Args:
        date: Дата матча

    Returns:
        Год начала сезона (например, 2025 для сезона 2025/26)
    """
    if date.month >= 7:
        return date.year
    return date.year - 1


def utc_to_msk(utc_str: str) -> tuple:
    """
    Конвертировать UTC datetime строку в дату и время МСК.

    Args:
        utc_str: ISO8601 строка (например, "2026-02-11T19:30:00+00:00")

    Returns:
        Tuple (date_str "YYYY-MM-DD", time_str "HH:MM") в МСК
    """
    try:
        dt = datetime.fromisoformat(utc_str)
        # Если нет timezone info, считаем UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        msk_dt = dt.astimezone(MSK)
        return msk_dt.strftime('%Y-%m-%d'), msk_dt.strftime('%H:%M')
    except Exception as e:
        logger.error(f"Ошибка конвертации времени '{utc_str}': {e}")
        return None, None


def parse_fixture(fixture: Dict, league_name: str) -> Optional[Dict]:
    """
    Парсинг одного fixture из API-Football в формат БД.

    Args:
        fixture: Raw fixture dict от API-Football
        league_name: Название лиги

    Returns:
        Dict с полями для sync_match_from_api или None при ошибке
    """
    try:
        fixture_data = fixture.get('fixture', {})
        teams = fixture.get('teams', {})
        league = fixture.get('league', {})
        goals = fixture.get('goals', {})

        fixture_id = fixture_data.get('id')
        date_str = fixture_data.get('date', '')

        home_team = teams.get('home', {}).get('name', '')
        away_team = teams.get('away', {}).get('name', '')
        home_team_id = str(teams.get('home', {}).get('id', ''))
        away_team_id = str(teams.get('away', {}).get('id', ''))

        venue_data = fixture_data.get('venue', {})
        venue_name = venue_data.get('name', '') if venue_data else ''

        round_str = league.get('round', '')
        status = fixture_data.get('status', {}).get('long', 'Scheduled')

        # Конвертация времени UTC → МСК
        match_date, match_time = utc_to_msk(date_str)
        if not match_date:
            logger.warning(f"Не удалось конвертировать дату: {date_str}")
            return None

        # Счёт (может быть None для будущих матчей)
        home_score = goals.get('home')
        away_score = goals.get('away')

        return {
            'sport': 'football',
            'team1': home_team,
            'team2': away_team,
            'match_date': match_date,
            'match_time': match_time,
            'league': league_name,
            'venue': venue_name,
            'api_event_id': str(fixture_id),
            'status': status,
            'home_team_id': home_team_id,
            'away_team_id': away_team_id,
            'home_score': home_score,
            'away_score': away_score,
            'match_datetime': date_str,
            'round': round_str,
            'source': 'api-football',
            'raw_json': json.dumps(fixture, ensure_ascii=False),
            'price': 150,
        }

    except Exception as e:
        logger.error(f"Ошибка парсинга fixture: {e}")
        return None


def save_match_to_db(match_data: Dict) -> tuple:
    """
    Сохранить матч в БД с расширенными полями.

    Использует sync_match_from_api для idempotent вставки,
    затем обновляет дополнительные поля (source, team IDs, raw_json и т.д.)

    Returns:
        Tuple (match_id, is_new)
    """
    match_id, is_new = sync_match_from_api(match_data)

    if is_new:
        # Обновляем дополнительные поля, которые sync_match_from_api не сохраняет
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE matches
            SET source = ?, home_team_id = ?, away_team_id = ?,
                home_score = ?, away_score = ?, match_datetime = ?,
                round = ?, raw_json = ?
            WHERE id = ?
        ''', (
            match_data.get('source'),
            match_data.get('home_team_id'),
            match_data.get('away_team_id'),
            match_data.get('home_score'),
            match_data.get('away_score'),
            match_data.get('match_datetime'),
            match_data.get('round'),
            match_data.get('raw_json'),
            match_id
        ))
        conn.commit()
        conn.close()

    return match_id, is_new


def fetch_fixtures(client: APIFootballClient,
                   dates: List[str] = None) -> List[Dict]:
    """
    Получить fixtures для всех лиг на указанные даты.

    Args:
        client: APIFootballClient
        dates: Список дат в формате "YYYY-MM-DD" (по умолчанию: сегодня + завтра)

    Returns:
        Список parsed match dicts
    """
    if dates is None:
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        dates = [today.strftime('%Y-%m-%d'), tomorrow.strftime('%Y-%m-%d')]

    all_matches = []

    for league in TOP_LEAGUES:
        for date in dates:
            # Определяем сезон
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            season = get_season_for_date(date_obj)

            logger.info(
                f"Запрос fixtures: {league['name']} на {date} "
                f"(сезон {season})"
            )

            data = client.make_request("fixtures", {
                "league": str(league['id']),
                "date": date,
                "season": str(season)
            })

            if not data or 'response' not in data:
                logger.warning(
                    f"Пустой ответ для {league['name']} на {date}"
                )
                continue

            fixtures = data['response']
            logger.info(
                f"Получено {len(fixtures)} fixtures для "
                f"{league['name']} на {date}"
            )

            for fixture in fixtures:
                parsed = parse_fixture(fixture, league['name'])
                if parsed:
                    all_matches.append(parsed)

    return all_matches


def sync_fixtures(client: APIFootballClient,
                  dates: List[str] = None,
                  dry_run: bool = False) -> Dict:
    """
    Основной flow синхронизации: fetch + save.

    Args:
        client: APIFootballClient
        dates: Список дат (по умолчанию: сегодня + завтра)
        dry_run: Если True, не сохранять в БД

    Returns:
        Dict со статистикой: {total, new, existing, errors}
    """
    stats = {'total': 0, 'new': 0, 'existing': 0, 'errors': 0}

    matches = fetch_fixtures(client, dates)
    stats['total'] = len(matches)

    print(f"\nНайдено матчей: {len(matches)}")

    for match in matches:
        team1 = match['team1']
        team2 = match['team2']
        date = match['match_date']
        time = match['match_time']

        if dry_run:
            print(
                f"  [DRY RUN] {date} {time} | "
                f"{match['league']}: {team1} vs {team2}"
            )
            continue

        try:
            match_id, is_new = save_match_to_db(match)
            if is_new:
                stats['new'] += 1
                print(
                    f"  [NEW] #{match_id}: {date} {time} | "
                    f"{match['league']}: {team1} vs {team2}"
                )
            else:
                stats['existing'] += 1
                logger.debug(
                    f"Матч уже существует: {team1} vs {team2} ({date})"
                )
        except Exception as e:
            stats['errors'] += 1
            logger.error(f"Ошибка сохранения {team1} vs {team2}: {e}")

    return stats


def enrich_synced_matches(client: APIFootballClient,
                          force: bool = False,
                          dry_run: bool = False) -> Dict:
    """
    Обогатить матчи на сегодня+завтра через API-Football.

    Args:
        client: APIFootballClient
        force: Игнорировать TTL
        dry_run: Preview без сохранения

    Returns:
        Dict со статистикой обогащения
    """
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM matches
        WHERE match_date IN (?, ?) AND is_active = 1
        ORDER BY match_date, match_time
    ''', (today, tomorrow))
    matches = cursor.fetchall()
    conn.close()

    if not matches:
        print("Нет матчей для обогащения")
        return {'total': 0}

    print(f"\nМатчей для обогащения: {len(matches)}")

    total_stats = {
        'total': len(matches),
        'processed': 0,
        'stats_added': 0,
        'injuries_added': 0,
        'standings_added': 0,
        'scorers_added': 0,
        'h2h_added': 0,
        'errors': 0,
    }

    for i, match in enumerate(matches, 1):
        home = match['team1']
        away = match['team2']
        print(f"  [{i}/{len(matches)}] {home} vs {away}")

        if dry_run:
            print("    [DRY RUN] Будет обогащено")
            total_stats['processed'] += 1
            continue

        try:
            # Конвертируем Row в dict для enrich_match
            match_dict = dict(match)

            # Подставляем league_id для маппинга в enrich_match
            # enrich_match использует LEAGUE_MAPPING (TheSportsDB → API-Football)
            # Для матчей из API-Football нам нужно передать league напрямую
            match_stats = enrich_match(match_dict, client, force=force)

            for key in ('stats_added', 'injuries_added', 'standings_added',
                        'scorers_added', 'h2h_added', 'errors'):
                total_stats[key] += match_stats.get(key, 0)
            total_stats['processed'] += 1

            added = sum(v for k, v in match_stats.items() if k != 'errors')
            print(f"    [OK] Обогащено полей: {added}")

        except QuotaExceededError as e:
            print(f"    [ERROR] Квота исчерпана: {e}")
            print("\nОстановка: достигнут дневной лимит API")
            break

        except Exception as e:
            logger.error(f"Ошибка обогащения {home} vs {away}: {e}")
            total_stats['errors'] += 1
            print(f"    [ERROR] {e}")

    return total_stats


def main():
    parser = argparse.ArgumentParser(
        description="Синхронизация матчей через API-Football (единый источник)"
    )
    parser.add_argument(
        '--enrich',
        action='store_true',
        help='Обогатить матчи (stats, injuries, standings, scorers, H2H)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Игнорировать TTL и обновить всё'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview без сохранения в БД'
    )
    parser.add_argument(
        '--dates',
        nargs='+',
        help='Даты для синхронизации (YYYY-MM-DD), по умолчанию: сегодня + завтра'
    )

    args = parser.parse_args()

    print("=" * 70)
    print("API-Football: Синхронизация матчей")
    print("=" * 70)
    print(f"Лиги: {', '.join(lg['name'] for lg in TOP_LEAGUES)}")
    print(f"Режим: {'DRY RUN' if args.dry_run else 'LIVE'}")
    if args.enrich:
        print(f"Обогащение: ДА (force={args.force})")
    print()

    client = APIFootballClient()

    # Шаг 1: Синхронизация fixtures
    print("--- Шаг 1: Получение fixtures ---")
    sync_stats = sync_fixtures(client, dates=args.dates, dry_run=args.dry_run)

    print(f"\nFixtures: всего {sync_stats['total']}, "
          f"новых {sync_stats['new']}, "
          f"уже в БД {sync_stats['existing']}, "
          f"ошибок {sync_stats['errors']}")

    # Шаг 2: Обогащение (если --enrich)
    enrich_stats = {}
    if args.enrich:
        print()
        print("--- Шаг 2: Обогащение матчей ---")
        enrich_stats = enrich_synced_matches(
            client, force=args.force, dry_run=args.dry_run
        )

    # Итого
    print()
    print("=" * 70)
    print("ИТОГО:")
    print("=" * 70)
    print(f"Fixtures: {sync_stats['total']} найдено, {sync_stats['new']} новых")
    if enrich_stats:
        print(f"Обогащено матчей: {enrich_stats.get('processed', 0)}/{enrich_stats.get('total', 0)}")
        print(f"  Team stats:    {enrich_stats.get('stats_added', 0)}")
        print(f"  Injuries:      {enrich_stats.get('injuries_added', 0)}")
        print(f"  Standings:     {enrich_stats.get('standings_added', 0)}")
        print(f"  Top scorers:   {enrich_stats.get('scorers_added', 0)}")
        print(f"  H2H:           {enrich_stats.get('h2h_added', 0)}")
        print(f"  Ошибок:        {enrich_stats.get('errors', 0)}")
    print(f"Использовано запросов: {client.requests_made}/{client.daily_limit}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
