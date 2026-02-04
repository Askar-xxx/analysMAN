import asyncio
import logging
from telegram.ext import Application
import database
from config import TOKEN
from user_handlers import setup_user_handlers
from admin_handlers import setup_admin_handlers
from payment_handlers import setup_payment_handlers

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Инициализируем базу данных
    database.init_db()
    
    # Настраиваем все обработчики
    setup_user_handlers(application)
    setup_admin_handlers(application)
    setup_payment_handlers(application)
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Ожидаем завершения (бесконечный цикл)
    await asyncio.get_event_loop().create_future()

if __name__ == '__main__':
    asyncio.run(main())
