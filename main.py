import asyncio
import logging
import time

import database
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.error import NetworkError
from telegram.ext import Application

from bot_profile import update_dynamic_description
from config import TOKEN
from healthcheck_utils import (
    HEARTBEAT_INTERVAL_SECONDS,
    remove_heartbeat,
    touch_heartbeat,
)
from logging_utils import setup_logging


setup_logging('bot')
logger = logging.getLogger(__name__)
logging.getLogger('match_data_fetcher').setLevel(logging.WARNING)

PTB_NET_ERROR_ESCALATE_AFTER = 5
PTB_NET_ERROR_WINDOW_SECONDS = 180
PTB_NET_ERROR_REMIND_EVERY = PTB_NET_ERROR_ESCALATE_AFTER * 4
_ptb_net_error_state = {
    'count': 0,
    'last_at': 0.0,
}


def _reset_ptb_network_error_state():
    _ptb_net_error_state['count'] = 0
    _ptb_net_error_state['last_at'] = 0.0


def _register_ptb_network_error(now: float) -> int:
    last_at = float(_ptb_net_error_state.get('last_at', 0.0) or 0.0)
    if not last_at or (now - last_at) > PTB_NET_ERROR_WINDOW_SECONDS:
        _ptb_net_error_state['count'] = 0

    _ptb_net_error_state['count'] = int(_ptb_net_error_state.get('count', 0)) + 1
    _ptb_net_error_state['last_at'] = now
    return _ptb_net_error_state['count']


def _ptb_monotonic() -> float:
    return time.monotonic()


async def error_handler(update, context):
    """Глобальный обработчик необработанных исключений PTB."""
    update_repr = repr(update)
    if len(update_repr) > 1000:
        update_repr = f"{update_repr[:997]}..."

    error = context.error
    if isinstance(error, NetworkError):
        count = _register_ptb_network_error(_ptb_monotonic())
        if count == PTB_NET_ERROR_ESCALATE_AFTER:
            logger.error(
                "Сетевая ошибка PTB. update=%s | Telegram API недоступен уже %s ошибок подряд в пределах %s сек",
                update_repr,
                count,
                PTB_NET_ERROR_WINDOW_SECONDS,
                exc_info=error,
            )
        elif count % PTB_NET_ERROR_REMIND_EVERY == 0:
            logger.error(
                "Сетевая ошибка PTB. update=%s | Telegram API всё ещё недоступен: %s ошибок подряд",
                update_repr,
                count,
                exc_info=error,
            )
        else:
            logger.warning(
                "Сетевая ошибка PTB. update=%s | попытка %s: %s",
                update_repr,
                count,
                error,
            )
        return

    _reset_ptb_network_error_state()
    logger.error(
        "Необработанное исключение PTB. update=%s",
        update_repr,
        exc_info=error,
    )


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
        limit=15,
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


async def _refresh_dynamic_description(bot, reason):
    try:
        await update_dynamic_description(bot)
    except Exception as e:
        logger.warning("Не удалось обновить Description бота (%s): %s", reason, e)


async def scheduled_sync_matches(application, refresh_description=True):
    """Периодическая синхронизация матчей из TheSportsDB."""
    from datetime import datetime

    logger.info("=" * 60)
    logger.info(
        f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК синхронизации матчей..."
    )
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
        if refresh_description:
            await _refresh_dynamic_description(application.bot, "scheduled_sync_matches")
        logger.info("=" * 60)
    except Exception as e:
        logger.error("=" * 60)
        logger.error(
            f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ОШИБКА синхронизации: {e}"
        )
        logger.error("=" * 60, exc_info=True)


async def scheduled_cleanup(application, refresh_description=True):
    """Периодическая очистка старых покупок и матчей."""
    from datetime import datetime

    logger.info(
        f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК очистки старых анализов..."
    )
    try:
        expired_topups, expired_pending_purchases, deleted_purchases, deleted_matches = (
            await asyncio.to_thread(_cleanup_job)
        )
        logger.info(f"expired_pending_purchases={expired_pending_purchases}")
        logger.info(
            f"Очистка завершена: expired_topups={expired_topups}, "
            f"покупок={deleted_purchases}, матчей={deleted_matches}"
        )
        if refresh_description:
            await _refresh_dynamic_description(application.bot, "scheduled_cleanup")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}", exc_info=True)


async def post_init(application):
    """Callback после инициализации бота."""
    try:
        touch_heartbeat('main')
    except Exception as e:
        logger.warning("Не удалось создать стартовый heartbeat main.py: %s", e)
    application.bot_data['main_heartbeat_task'] = asyncio.create_task(
        main_heartbeat_loop()
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_sync_matches,
        args=[application],
        trigger=IntervalTrigger(hours=3),
        id='sync_matches',
        name='Синхронизация матчей TheSportsDB',
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_cleanup,
        args=[application],
        trigger=IntervalTrigger(hours=6),
        id='cleanup_old',
        name='Очистка старых анализов',
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_sync_matches,
        args=[application, True],
        id='sync_matches_startup',
        name='Синхронизация при старте',
    )
    scheduler.add_job(
        scheduled_cleanup,
        args=[application, False],
        id='cleanup_startup',
        name='Очистка при старте',
    )

    scheduler.start()
    logger.info("=" * 60)
    logger.info(
        "APScheduler запущен: синхронизация каждые 3 часа, очистка каждые 6 часов"
    )
    logger.info("=" * 60)
    application.bot_data['scheduler'] = scheduler

    try:
        from admin_commands import setup_admin_commands_menu

        await setup_admin_commands_menu(application.bot)
    except Exception as e:
        logger.warning("Не удалось настроить меню админских команд: %s", e)


async def post_shutdown(application):
    """Callback перед остановкой бота."""
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
    """Запуск бота."""
    application = Application.builder().token(TOKEN).build()
    database.init_db()

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    from admin_commands import setup_admin_handlers
    from user_handlers import setup_user_handlers

    setup_user_handlers(application)
    setup_admin_handlers(application)
    application.add_error_handler(error_handler)

    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()
