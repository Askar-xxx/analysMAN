import logging
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import database
from config import TOKEN

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
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: ЗАПУСК синхронизации матчей...")
    logger.info("=" * 60)
    try:
        from sync_matches import SportsDBSyncer
        # Режим top3: берёт топ-15 матчей из топ-лиг (Premier League, La Liga, Bundesliga)
        # и топ-кубков (Champions League, Europa League) на ближайшие 3 дня
        syncer = SportsDBSyncer(mode='top3', limit=15)
        matches = syncer.sync()
        results = syncer.save_matches_to_db(matches)
        logger.info("=" * 60)
        logger.info(
            f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: синхронизация ЗАВЕРШЕНА"
        )
        logger.info(
            f"Найдено: {results['total']}, "
            f"Добавлено: {results['inserted']}, "
            f"Пропущено: {results['skipped']}"
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

    # Периодическая синхронизация каждые 3 часа
    scheduler.add_job(
        scheduled_sync_matches,
        trigger=IntervalTrigger(hours=3),
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
    logger.info("APScheduler запущен: синхронизация каждые 3 часа")
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
    from payment_handlers import setup_payment_handlers
    from admin_commands import setup_admin_handlers
    setup_user_handlers(application)
    setup_payment_handlers(application)
    setup_admin_handlers(application)

    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()
