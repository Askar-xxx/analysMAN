# -*- coding: utf-8 -*-
"""
Админские команды для управления ботом.

Команды доступны только пользователям из таблицы admins.
"""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import database

logger = logging.getLogger(__name__)


async def clean_matches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /clean_matches - полная очистка матчей и PNG файлов.

    Удаляет:
    - Все матчи без покупок
    - Все старые матчи (>1 день)
    - Все PNG файлы анализов

    Доступна только админам.
    """
    user_id = update.effective_user.id

    # Проверка прав администратора
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    await update.message.reply_text("🧹 Начинаю очистку данных...")

    try:
        # 1. Удаляем старые покупки (вызовет удаление PNG)
        deleted_purchases = database.cleanup_old_purchases()

        # 2. Удаляем старые матчи без покупок (вызовет удаление PNG)
        deleted_matches = database.delete_finished_matches_without_purchases()

        # 3. Удаляем осиротевшие PNG файлы (те, что остались в папке но нет в БД)
        orphaned_png = 0
        if os.path.exists('analysis_cache'):
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT analysis_png_path FROM matches WHERE analysis_png_path IS NOT NULL')
            db_png_paths = {row['analysis_png_path'] for row in cursor.fetchall()}
            conn.close()

            for filename in os.listdir('analysis_cache'):
                if filename.endswith('.png'):
                    file_path = os.path.join('analysis_cache', filename)
                    if file_path not in db_png_paths:
                        try:
                            os.remove(file_path)
                            orphaned_png += 1
                        except Exception as e:
                            logger.warning(f"Не удалось удалить осиротевший PNG {file_path}: {e}")

        result_text = (
            "✅ Очистка завершена:\n\n"
            f"🗑 Удалено покупок: {deleted_purchases}\n"
            f"🗑 Удалено матчей: {deleted_matches}\n"
            f"🗑 Удалено осиротевших PNG: {orphaned_png}"
        )

        await update.message.reply_text(result_text)
        logger.info(
            f"Admin {user_id} выполнил очистку: "
            f"{deleted_purchases} покупок, {deleted_matches} матчей, {orphaned_png} PNG"
        )

    except Exception as e:
        logger.error(f"Ошибка при очистке данных: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при очистке: {e}")


async def clean_all_matches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /clean_all_matches - ПОЛНАЯ очистка ВСЕХ матчей и PNG.

    ВНИМАНИЕ: Удаляет ВСЕ матчи и анализы, включая те, на которые есть покупки!
    Используйте с осторожностью.

    Доступна только админам.
    """
    user_id = update.effective_user.id

    # Проверка прав администратора
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    await update.message.reply_text("⚠️ ВНИМАНИЕ: Удаляю ВСЕ матчи и анализы...")

    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()

        # Получаем все PNG пути перед удалением
        cursor.execute('SELECT analysis_png_path FROM matches WHERE analysis_png_path IS NOT NULL')
        png_paths = [row['analysis_png_path'] for row in cursor.fetchall()]

        # Удаляем все покупки
        cursor.execute('DELETE FROM purchases')
        deleted_purchases = cursor.rowcount

        # Удаляем все матчи
        cursor.execute('DELETE FROM matches')
        deleted_matches = cursor.rowcount

        # Сбрасываем автоинкремент
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='matches'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='purchases'")

        conn.commit()
        conn.close()

        # Удаляем все PNG файлы
        deleted_png = 0
        for png_path in png_paths:
            if png_path and os.path.exists(png_path):
                try:
                    os.remove(png_path)
                    deleted_png += 1
                except Exception as e:
                    logger.warning(f"Не удалось удалить PNG {png_path}: {e}")

        # Удаляем папку analysis_cache (если пустая)
        if os.path.exists('analysis_cache'):
            try:
                # Удаляем все оставшиеся файлы в папке
                for filename in os.listdir('analysis_cache'):
                    file_path = os.path.join('analysis_cache', filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_png += 1
            except Exception as e:
                logger.warning(f"Ошибка очистки analysis_cache: {e}")

        result_text = (
            "✅ ПОЛНАЯ очистка завершена:\n\n"
            f"🗑 Удалено покупок: {deleted_purchases}\n"
            f"🗑 Удалено матчей: {deleted_matches}\n"
            f"🗑 Удалено PNG файлов: {deleted_png}\n\n"
            "♻️ Счётчики ID сброшены"
        )

        await update.message.reply_text(result_text)
        logger.warning(
            f"Admin {user_id} выполнил ПОЛНУЮ очистку БД: "
            f"{deleted_purchases} покупок, {deleted_matches} матчей, {deleted_png} PNG"
        )

    except Exception as e:
        logger.error(f"Ошибка при полной очистке данных: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при очистке: {e}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /stats - статистика по базе данных.

    Доступна только админам.
    """
    user_id = update.effective_user.id

    # Проверка прав администратора
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()

        # Статистика по матчам
        cursor.execute('SELECT COUNT(*) as total FROM matches')
        total_matches = cursor.fetchone()['total']

        cursor.execute('SELECT COUNT(*) as total FROM matches WHERE analysis_text IS NOT NULL')
        matches_with_analysis = cursor.fetchone()['total']

        cursor.execute('SELECT COUNT(*) as total FROM matches WHERE analysis_png_path IS NOT NULL')
        matches_with_png = cursor.fetchone()['total']

        # Статистика по покупкам
        cursor.execute('SELECT COUNT(*) as total FROM purchases')
        total_purchases = cursor.fetchone()['total']

        cursor.execute('SELECT COUNT(*) as total FROM purchases WHERE status = "paid"')
        paid_purchases = cursor.fetchone()['total']

        cursor.execute('SELECT COUNT(*) as total FROM purchases WHERE status = "pending"')
        pending_purchases = cursor.fetchone()['total']

        # Статистика по пользователям
        cursor.execute('SELECT COUNT(*) as total FROM users')
        total_users = cursor.fetchone()['total']

        conn.close()

        # Размер папки analysis_cache
        cache_size = 0
        png_count = 0
        if os.path.exists('analysis_cache'):
            for filename in os.listdir('analysis_cache'):
                file_path = os.path.join('analysis_cache', filename)
                if os.path.isfile(file_path):
                    cache_size += os.path.getsize(file_path)
                    if filename.endswith('.png'):
                        png_count += 1

        cache_size_mb = cache_size / (1024 * 1024)

        stats_text = (
            "📊 Статистика базы данных:\n\n"
            f"🏆 Матчи: {total_matches}\n"
            f"  ├─ С анализом: {matches_with_analysis}\n"
            f"  └─ С PNG: {matches_with_png}\n\n"
            f"💳 Покупки: {total_purchases}\n"
            f"  ├─ Оплачено: {paid_purchases}\n"
            f"  └─ Ожидает: {pending_purchases}\n\n"
            f"👥 Пользователи: {total_users}\n\n"
            f"💾 Кэш PNG: {png_count} файлов ({cache_size_mb:.2f} MB)"
        )

        await update.message.reply_text(stats_text)

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при получении статистики: {e}")


def setup_admin_handlers(application):
    """Регистрация админских команд"""
    application.add_handler(CommandHandler('clean_matches', clean_matches_command))
    application.add_handler(CommandHandler('clean_all_matches', clean_all_matches_command))
    application.add_handler(CommandHandler('stats', stats_command))
    logger.info("Админские команды зарегистрированы: /clean_matches, /clean_all_matches, /stats")
