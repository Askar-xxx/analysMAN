"""
Тестовый скрипт для проверки функционала составов.
"""
import logging
from match_data_fetcher import MatchDataFetcher
from analysis_formatter import build_table_data
from image_renderer import render_analysis_table

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_lineup_fetching():
    """Тест получения составов из API."""
    logger.info("=== Тест 1: Получение составов ===")

    fetcher = MatchDataFetcher()

    # Тестовый матч (используем известный event_id завершённого матча)
    # Например, матч из Premier League
    test_event_id = 2279632  # Пример event_id

    lineup = fetcher._fetch_lineup(test_event_id)

    if lineup:
        logger.info(f"✅ Получено {len(lineup)} игроков")

        # Проверяем структуру данных
        if len(lineup) > 0:
            sample = lineup[0]
            logger.info(f"Пример игрока: {sample.get('strPlayer')}, "
                       f"команда: {sample.get('strTeam')}, "
                       f"основной состав: {sample.get('strSubstitute')}")

        # Считаем основной состав
        starters = [p for p in lineup if p.get('strSubstitute') == 'No']
        logger.info(f"Основной состав: {len(starters)} игроков")

        return True
    else:
        logger.warning("⚠️ Составы не получены (возможно матч ещё не завершён)")
        return False


def test_lineup_comparison():
    """Тест сравнения составов."""
    logger.info("\n=== Тест 2: Сравнение составов ===")

    # Симулируем enriched_data с двумя составами
    lineup1 = [
        {'strPlayer': 'Player A', 'strTeam': 'Liverpool', 'strSubstitute': 'No'},
        {'strPlayer': 'Player B', 'strTeam': 'Liverpool', 'strSubstitute': 'No'},
        {'strPlayer': 'Player C', 'strTeam': 'Liverpool', 'strSubstitute': 'Yes'},
    ]

    lineup2 = [
        {'strPlayer': 'Player A', 'strTeam': 'Liverpool', 'strSubstitute': 'No'},
        {'strPlayer': 'Player D', 'strTeam': 'Liverpool', 'strSubstitute': 'No'},  # Замена B→D
        {'strPlayer': 'Player C', 'strTeam': 'Liverpool', 'strSubstitute': 'Yes'},
    ]

    enriched_data = {
        'team1_form': [
            {'event_id': '101'},  # Новый матч
            {'event_id': '100'}   # Старый матч
        ],
        'lineup_100': lineup1,
        'lineup_101': lineup2
    }

    from analysis_formatter import extract_lineup_changes

    result = extract_lineup_changes(enriched_data, 'Liverpool', is_home=True)
    logger.info(f"Результат: {result}")

    if "Замена" in result or "Изменений нет" in result:
        logger.info("✅ Сравнение работает корректно")
        return True
    else:
        logger.error("❌ Неожиданный результат сравнения")
        return False


def test_table_rendering():
    """Тест рендеринга таблицы с составами."""
    logger.info("\n=== Тест 3: Рендеринг таблицы ===")

    # Минимальные данные для теста
    match = {
        'id': 'test_lineup',
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-16',
        'league': 'Test League'
    }

    enriched_data = {
        'team1_form': [
            {'event_id': '101'},
            {'event_id': '100'}
        ],
        'team2_form': [
            {'event_id': '201'},
            {'event_id': '200'}
        ],
        'standings': {},
        'h2h': []
    }

    table_data = build_table_data(match, enriched_data)

    # Проверяем что lineup_changes присутствует
    if 'lineup_changes' in table_data:
        logger.info("✅ Поле lineup_changes присутствует в table_data")
        logger.info(f"Team A: {table_data['lineup_changes']['left']}")
        logger.info(f"Team B: {table_data['lineup_changes']['right']}")

        # Пробуем отрендерить PNG
        try:
            png_path = render_analysis_table(match, table_data)
            logger.info(f"✅ PNG таблица создана: {png_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка рендеринга PNG: {e}")
            return False
    else:
        logger.error("❌ Поле lineup_changes отсутствует")
        return False


if __name__ == '__main__':
    logger.info("Запуск тестов функционала составов\n")

    results = []

    # Запускаем тесты
    results.append(("Получение составов", test_lineup_fetching()))
    results.append(("Сравнение составов", test_lineup_comparison()))
    results.append(("Рендеринг таблицы", test_table_rendering()))

    # Итоги
    logger.info("\n" + "="*50)
    logger.info("ИТОГИ ТЕСТИРОВАНИЯ:")
    logger.info("="*50)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status} - {name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)
    logger.info(f"\nВсего: {passed}/{total} тестов пройдено")
