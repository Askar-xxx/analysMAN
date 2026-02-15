"""
End-to-end тест функционала составов с реальными данными из БД.
"""
import logging
import database
from match_data_fetcher import MatchDataFetcher
from analysis_formatter import build_table_data
from image_renderer import render_analysis_table

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def test_full_flow():
    """Полный тест: получение данных → форматирование → рендеринг PNG."""
    logger.info("=== END-TO-END ТЕСТ ФУНКЦИОНАЛА СОСТАВОВ ===\n")

    # Инициализируем БД
    database.init_db()

    # Получаем реальный матч из БД
    import sqlite3
    conn = sqlite3.connect('sports_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, team1, team2, home_team_id, away_team_id,
               api_event_id, league, match_date, match_time, price
        FROM matches
        LIMIT 1
    ''')
    match_row = cursor.fetchone()
    conn.close()

    if not match_row:
        logger.error("❌ В БД нет матчей для тестирования")
        return False

    # Конвертируем в dict
    match = dict(match_row)
    logger.info("📋 Тестовый матч:")
    logger.info(f"   {match['team1']} vs {match['team2']}")
    logger.info(f"   Дата: {match['match_date']} {match['match_time']}")
    logger.info(f"   Лига: {match.get('league', 'N/A')}")
    logger.info(f"   Home Team ID: {match.get('home_team_id')}")
    logger.info(f"   Away Team ID: {match.get('away_team_id')}\n")

    # Шаг 1: Получение обогащённых данных (включая составы)
    logger.info("🔄 Шаг 1: Получение обогащённых данных...")
    fetcher = MatchDataFetcher()
    enriched_data = fetcher.fetch_match_data(match)

    logger.info(f"   H2H: {len(enriched_data.get('h2h', []))} матчей")
    logger.info(f"   Standings: {'✅' if enriched_data.get('standings') else '❌'}")
    logger.info(f"   Team1 form: {len(enriched_data.get('team1_form', []))} матчей")
    logger.info(f"   Team2 form: {len(enriched_data.get('team2_form', []))} матчей")

    # Проверяем наличие составов
    lineup_keys = [k for k in enriched_data.keys() if k.startswith('lineup_')]
    logger.info(f"   Составы получены: {len(lineup_keys)} событий")
    for key in lineup_keys:
        lineup = enriched_data[key]
        logger.info(f"      {key}: {len(lineup)} игроков")

    if enriched_data.get('errors'):
        logger.warning(f"   ⚠️ Ошибки при получении данных: {enriched_data['errors']}")

    # Шаг 2: Форматирование данных для таблицы
    logger.info("\n🔄 Шаг 2: Форматирование данных для таблицы...")
    table_data = build_table_data(match, enriched_data)

    logger.info(f"   Title: {table_data['title']}")
    logger.info(f"   Team left: {table_data['team_left']}")
    logger.info(f"   Team right: {table_data['team_right']}")

    # Проверяем наличие lineup_changes
    if 'lineup_changes' in table_data:
        logger.info("   ✅ Поле lineup_changes присутствует")
        logger.info(f"      Left: {table_data['lineup_changes']['left']}")
        logger.info(f"      Right: {table_data['lineup_changes']['right']}")
    else:
        logger.error("   ❌ Поле lineup_changes отсутствует")
        return False

    # Шаг 3: Рендеринг PNG таблицы
    logger.info("\n🔄 Шаг 3: Рендеринг PNG таблицы...")
    try:
        png_path = render_analysis_table(match, table_data)
        logger.info(f"   ✅ PNG создана: {png_path}")

        # Проверяем размер файла
        import os
        file_size = os.path.getsize(png_path)
        logger.info(f"   Размер файла: {file_size / 1024:.1f} KB")

        return True

    except Exception as e:
        logger.error(f"   ❌ Ошибка рендеринга: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    success = test_full_flow()

    logger.info("\n" + "="*60)
    if success:
        logger.info("✅ END-TO-END ТЕСТ ПРОЙДЕН УСПЕШНО")
        logger.info("="*60)
        logger.info("\nСтрока 'Составы' успешно добавлена в таблицу!")
        logger.info("Функционал готов к использованию в боте.")
    else:
        logger.error("❌ END-TO-END ТЕСТ ПРОВАЛЕН")
        logger.error("="*60)
