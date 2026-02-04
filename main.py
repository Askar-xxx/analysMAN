import logging
from telegram.ext import Application
import database
from config import TOKEN

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    # Инициализируем базу данных
    database.init_db()
    # Импортируем и настраиваем обработчики
    from user_handlers import setup_user_handlers
    from payment_handlers import setup_payment_handlers
    setup_user_handlers(application)
    setup_payment_handlers(application)
    print("🤖 Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
