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


async def scheduled_expire_topups():
    """Периодическая установка статуса expired для просроченных pending топапов."""
    from datetime import datetime
    try:
        expired_count = database.expire_pending_topups()
        if expired_count > 0:
            logger.info(
                f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: "
                f"истекших топапов переведено в expired: {expired_count}"
            )
    except Exception as e:
        logger.error(
            f"[{datetime.now().strftime('%H:%M:%S')}] APScheduler: "
            f"ОШИБКА очистки истекших топапов: {e}",
            exc_info=True
        )


async def post_init(application):
    """Callback после инициализации бота (в контексте event loop)"""
    # Устанавливаем команды в меню Telegram для администраторов
    from admin_commands import setup_admin_commands_menu
    await setup_admin_commands_menu(application.bot)

    # Настройка APScheduler для периодической синхронизации
    scheduler = AsyncIOScheduler()

    # Периодическая синхронизация каждые 6 часов
    scheduler.add_job(
        scheduled_sync_matches,
        trigger=IntervalTrigger(hours=6),
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

    # Очистка истекших pending топапов каждые 15 минут
    scheduler.add_job(
        scheduled_expire_topups,
        trigger=IntervalTrigger(minutes=15),
        id='expire_pending_topups',
        name='Истечение pending топапов',
        replace_existing=True
    )

    scheduler.start()
    logger.info("=" * 60)
    logger.info("APScheduler запущен: синхронизация каждые 6 часов, очистка топапов каждые 15 минут")
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
    setup_user_handlers(application)
    setup_admin_handlers(application)

    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()
