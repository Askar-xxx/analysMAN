import logging
# import subprocess  # Было для автозапуска da_polling.py (теперь отключено)
# import atexit  # Было для graceful shutdown listener (теперь отключено)
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import database
from config import TOKEN  # DA_ACCESS_TOKEN больше не нужен для автозапуска

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def scheduled_sync_matches():
    """Периодическая синхронизация матчей из TheSportsDB"""
    from datetime import datetime
    logger.info("=" * 60)
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК синхронизации...")
    logger.info("=" * 60)
    try:
        # 1. Синхронизация новых матчей
        from sync_matches import SportsDBSyncer
        logger.info("Шаг 1/3: Синхронизация новых матчей...")
        syncer = SportsDBSyncer(mode='top3', limit=15)
        matches = syncer.sync()
        results = syncer.save_matches_to_db(matches)
        logger.info(
            f"Найдено: {results['total']}, "
            f"Добавлено: {results['inserted']}, "
            f"Пропущено: {results['skipped']}"
        )

        # 2. Удаление старых матчей без покупок
        logger.info("Шаг 2/3: Удаление старых матчей...")
        deleted_matches = database.delete_finished_matches_without_purchases()
        if deleted_matches > 0:
            logger.info(f"Удалено старых матчей: {deleted_matches}")

        # 3. Очистка старых покупок (анализы хранятся 1 день после матча)
        logger.info("Шаг 3/3: Очистка старых покупок...")
        deleted = database.cleanup_old_purchases()
        if deleted > 0:
            logger.info(f"Удалено старых покупок: {deleted}")
        else:
            logger.info("Старых покупок для удаления не найдено")

        logger.info("=" * 60)
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: синхронизация ЗАВЕРШЕНА"
        )
        logger.info("=" * 60)
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ОШИБКА синхронизации: {e}")
        logger.error("=" * 60, exc_info=True)


async def post_init(application):
    """Callback после инициализации бота (в контексте event loop)"""
    # Настройка APScheduler для периодической синхронизации
    scheduler = AsyncIOScheduler()

    # Периодическая синхронизация каждую минуту (для теста)
    # TODO: В продакшене изменить на hours=6
    scheduler.add_job(
        scheduled_sync_matches,
        trigger=IntervalTrigger(minutes=1),
        id='sync_matches',
        name='Синхронизация матчей TheSportsDB',
        replace_existing=True
    )

    # Немедленная синхронизация при старте бота
    scheduler.add_job(
        scheduled_sync_matches,
        id='sync_matches_startup',
        name='Синхронизация при старте'
    )

    scheduler.start()
    logger.info("=" * 60)
    logger.info("APScheduler запущен: синхронизация каждую МИНУТУ (тестовый режим)")
    logger.info("=" * 60)

    # Сохраняем scheduler в bot_data для graceful shutdown
    application.bot_data['scheduler'] = scheduler


async def post_shutdown(application):
    """Callback перед остановкой бота"""
    scheduler = application.bot_data.get('scheduler')
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler остановлен")


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
    from admin_commands import setup_admin_handlers
    # START TEMPORARY DISABLE BALANCE LOGIC — MVP PURCHASE FLOW (2026-02-16)
    # from payment_handlers import setup_payment_handlers
    # END TEMPORARY DISABLE BALANCE LOGIC
    setup_user_handlers(application)
    setup_admin_handlers(application)
    # START TEMPORARY DISABLE BALANCE LOGIC — MVP PURCHASE FLOW (2026-02-16)
    # setup_payment_handlers(application)
    # END TEMPORARY DISABLE BALANCE LOGIC

    # START TEMPORARY DISABLE AUTO-START POLLING LISTENER (2026-02-16)
    # Теперь da_polling.py и webhook_server.py нужно запускать отдельно
    # Запуск: python da_polling.py (или python webhook_server.py)
    #
    # listener_process = None
    # if DA_ACCESS_TOKEN:
    #     try:
    #         logger.info("Запуск DonationAlerts polling listener...")
    #         listener_process = subprocess.Popen(
    #             ['python', 'da_polling.py'],
    #             stdout=subprocess.PIPE,
    #             stderr=subprocess.STDOUT,
    #             universal_newlines=True,
    #             bufsize=1
    #         )
    #         logger.info("✅ DonationAlerts polling listener запущен (PID: {})".format(listener_process.pid))
    #
    #         # Остановка listener при выходе
    #         def stop_listener():
    #             if listener_process and listener_process.poll() is None:
    #                 logger.info("Остановка DonationAlerts listener...")
    #                 listener_process.terminate()
    #                 try:
    #                     listener_process.wait(timeout=5)
    #                 except subprocess.TimeoutExpired:
    #                     listener_process.kill()
    #                 logger.info("DonationAlerts listener остановлен")
    #
    #         atexit.register(stop_listener)
    #     except Exception as e:
    #         logger.error(f"Ошибка запуска listener: {e}")
    # else:
    #     logger.warning("DA_ACCESS_TOKEN не настроен, DonationAlerts listener не запущен")
    #     logger.warning("Запустите: python da_oauth.py для получения токенов")
    # END TEMPORARY DISABLE AUTO-START POLLING LISTENER

    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()
