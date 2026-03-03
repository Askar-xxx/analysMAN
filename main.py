import logging
import asyncio
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import database
from config import TOKEN
from healthcheck_utils import (
    HEARTBEAT_INTERVAL_SECONDS,
    remove_heartbeat,
    touch_heartbeat,
)
from logging_utils import setup_logging

# Настройка логирования
setup_logging('bot')
logger = logging.getLogger(__name__)
# Подавляем шумные per-match логи, чтобы консоль не засорялась.
logging.getLogger('match_data_fetcher').setLevel(logging.WARNING)


async def main_heartbeat_loop():
    """Отдельный heartbeat loop для liveliness-check Docker."""
    while True:
        try:
            touch_heartbeat('main')
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Не удалось обновить heartbeat main.py: %s", e)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def _sync_matches_job():
    """Синхронный job для запуска в отдельном потоке."""
    from sync_matches import SportsDBSyncer, run_coverage_check

    syncer = SportsDBSyncer(
        mode='top3',
        limit=15
    )
    matches = syncer.sync()
    results = syncer.save_matches_to_db(matches)
    coverage_results = run_coverage_check()
    return results, coverage_results


def _cleanup_job():
    """Синхронный job очистки для запуска в отдельном потоке."""
    expired_topups = database.expire_pending_topups()
    expired_pending_purchases = database.expire_old_pending_purchases()
    deleted_purchases = database.cleanup_old_purchases()
    deleted_matches = database.delete_finished_matches_without_purchases()
    return expired_topups, expired_pending_purchases, deleted_purchases, deleted_matches


async def scheduled_sync_matches():
    """Периодическая синхронизация матчей из TheSportsDB"""
    from datetime import datetime
    logger.info("=" * 60)
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК синхронизации матчей...")
    logger.info("=" * 60)
    try:
        results, coverage_results = await asyncio.to_thread(_sync_matches_job)
        logger.info("=" * 60)
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: синхронизация ЗАВЕРШЕНА"
        )
        logger.info(
            f"Найдено: {results['total']}, "
            f"Добавлено: {results['inserted']}, "
            f"Пропущено: {results['skipped']}"
        )
        logger.info(
            f"Покрытие: проверено={coverage_results['checked']}, "
            f"ok={coverage_results['ok']}, "
            f"скрыто={coverage_results['hidden']}"
        )
        logger.info("=" * 60)
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ОШИБКА синхронизации: {e}")
        logger.error("=" * 60, exc_info=True)


async def scheduled_cleanup():
    """Периодическая очистка старых покупок и матчей (1 день после матча)"""
    from datetime import datetime
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК очистки старых анализов...")
    try:
        expired_topups, expired_pending_purchases, deleted_purchases, deleted_matches = await asyncio.to_thread(
            _cleanup_job
        )
        logger.info(f"expired_pending_purchases={expired_pending_purchases}")
        logger.info(
            f"Очистка завершена: expired_topups={expired_topups}, "
            f"покупок={deleted_purchases}, матчей={deleted_matches}"
        )
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}", exc_info=True)


async def post_init(application):
    """Callback после инициализации бота (в контексте event loop)"""
    try:
        touch_heartbeat('main')
    except Exception as e:
        logger.warning("Не удалось создать стартовый heartbeat main.py: %s", e)
    application.bot_data['main_heartbeat_task'] = asyncio.create_task(
        main_heartbeat_loop()
    )

    # Настройка APScheduler для периодической синхронизации
    scheduler = AsyncIOScheduler()

    # Периодическая синхронизация каждые 3 часа
    scheduler.add_job(
        scheduled_sync_matches,
        trigger=IntervalTrigger(hours=3),
        id='sync_matches',
        name='Синхронизация матчей TheSportsDB',
        replace_existing=True
    )

    # Очистка старых анализов каждые 6 часов
    scheduler.add_job(
        scheduled_cleanup,
        trigger=IntervalTrigger(hours=6),
        id='cleanup_old',
        name='Очистка старых анализов',
        replace_existing=True
    )

    # Немедленная синхронизация при старте бота
    scheduler.add_job(
        scheduled_sync_matches,
        id='sync_matches_startup',
        name='Синхронизация при старте'
    )

    # Немедленная очистка при старте
    scheduler.add_job(
        scheduled_cleanup,
        id='cleanup_startup',
        name='Очистка при старте'
    )

    scheduler.start()
    logger.info("=" * 60)
    logger.info("APScheduler запущен: синхронизация каждые 3 часа, очистка каждые 6 часов")
    logger.info("=" * 60)

    # Сохраняем scheduler в bot_data для graceful shutdown
    application.bot_data['scheduler'] = scheduler

    # Выставляем меню команд только для админов.
    try:
        from admin_commands import setup_admin_commands_menu
        await setup_admin_commands_menu(application.bot)
    except Exception as e:
        logger.warning(f"Не удалось настроить меню админских команд: {e}")


async def post_shutdown(application):
    """Callback перед остановкой бота"""
    heartbeat_task = application.bot_data.get('main_heartbeat_task')
    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        application.bot_data.pop('main_heartbeat_task', None)

    scheduler = application.bot_data.get('scheduler')
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler остановлен")

    remove_heartbeat('main')


def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    # Инициализируем базу данных
    database.init_db()

    # Регистрируем callbacks для инициализации и остановки
    application.post_init = post_init
    application.post_shutdown = post_shutdown

    # Импортируем и настраиваем обработчики
    from user_handlers import setup_user_handlers
    from payment_handlers import setup_payment_handlers
    from admin_commands import setup_admin_handlers
    setup_user_handlers(application)
    setup_payment_handlers(application)
    setup_admin_handlers(application)

    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()
