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
                if filename.endswith(('.webp', '.png')):
                    file_path = os.path.join('analysis_cache', filename)
                    if file_path not in db_png_paths:
                        try:
                            os.remove(file_path)
                            orphaned_png += 1
                        except Exception as e:
                            logger.warning(f"Не удалось удалить осиротевший файл {file_path}: {e}")

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
                    if filename.endswith(('.webp', '.png')):
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


async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addbalance <user_id> <amount> — пополнить баланс пользователя вручную.

    Пример: /addbalance 123456789 50
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ Неверный формат.\n\nИспользование:\n/addbalance <user_id> <сумма>\n\nПример:\n/addbalance 123456789 50"
        )
        return

    try:
        target_user_id = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id и сумма должны быть целыми числами.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть положительной.")
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, balance FROM users WHERE user_id = ?', (target_user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        await update.message.reply_text(f"❌ Пользователь {target_user_id} не найден в БД.")
        return

    old_balance = user['balance'] or 0
    database.add_balance(target_user_id, amount)
    new_balance = database.get_user_balance(target_user_id)

    username_str = f"@{user['username']}" if user['username'] else "без username"
    await update.message.reply_text(
        f"✅ Баланс пополнен!\n\n"
        f"👤 Пользователь: {target_user_id} ({username_str})\n"
        f"💰 Добавлено: +{amount} руб.\n"
        f"💳 Было: {old_balance} руб. → Стало: {new_balance} руб."
    )
    logger.info(f"Admin {admin_id} пополнил баланс user={target_user_id} на {amount} руб. (было {old_balance})")


async def clear_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clearbalance <user_id> — обнулить баланс пользователя.

    Пример: /clearbalance 123456789
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ Неверный формат.\n\nИспользование:\n/clearbalance <user_id>\n\nПример:\n/clearbalance 123456789"
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть целым числом.")
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, balance FROM users WHERE user_id = ?', (target_user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        await update.message.reply_text(f"❌ Пользователь {target_user_id} не найден в БД.")
        return

    old_balance = user['balance'] or 0
    ok = database.reset_user_balance(target_user_id)

    username_str = f"@{user['username']}" if user['username'] else "без username"
    if ok:
        await update.message.reply_text(
            f"✅ Баланс обнулён!\n\n"
            f"👤 Пользователь: {target_user_id} ({username_str})\n"
            f"💳 Было: {old_balance} руб. → Стало: 0 руб."
        )
        logger.warning(f"Admin {admin_id} обнулил баланс user={target_user_id} (было {old_balance} руб.)")
    else:
        await update.message.reply_text("❌ Не удалось обнулить баланс.")


async def clear_purchases_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clearpurchases [user_id|all] — очистить таблицу purchases.

    /clearpurchases all       — удалить все записи
    /clearpurchases 123456789 — удалить покупки конкретного пользователя
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Укажите аргумент.\n\n"
            "Использование:\n"
            "/clearpurchases all — удалить все покупки\n"
            "/clearpurchases <user_id> — покупки пользователя"
        )
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()

    if args[0].lower() == 'all':
        cursor.execute('SELECT COUNT(*) FROM purchases')
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM purchases')
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Удалено всех покупок: {count}")
        logger.warning(f"Admin {admin_id} удалил ВСЕ покупки ({count} шт.)")
    else:
        try:
            target_user_id = int(args[0])
        except ValueError:
            conn.close()
            await update.message.reply_text("❌ Укажите 'all' или корректный user_id.")
            return

        cursor.execute('SELECT COUNT(*) FROM purchases WHERE user_id = ?', (target_user_id,))
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM purchases WHERE user_id = ?', (target_user_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ Удалено покупок пользователя {target_user_id}: {count}"
        )
        logger.info(f"Admin {admin_id} удалил {count} покупок user={target_user_id}")


async def clear_topups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cleartopups [user_id|all|pending] — очистить таблицу balance_topups.

    /cleartopups all       — удалить все записи
    /cleartopups pending   — удалить только pending записи
    /cleartopups 123456789 — удалить топапы конкретного пользователя
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Укажите аргумент.\n\n"
            "Использование:\n"
            "/cleartopups all — удалить все записи\n"
            "/cleartopups pending — только pending\n"
            "/cleartopups <user_id> — топапы пользователя"
        )
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()
    mode = args[0].lower()

    if mode == 'all':
        cursor.execute('SELECT COUNT(*) FROM balance_topups')
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM balance_topups')
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Удалено всех топапов: {count}")
        logger.warning(f"Admin {admin_id} удалил ВСЕ balance_topups ({count} шт.)")
    elif mode == 'pending':
        cursor.execute("SELECT COUNT(*) FROM balance_topups WHERE status = 'pending'")
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM balance_topups WHERE status = 'pending'")
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Удалено pending топапов: {count}")
        logger.info(f"Admin {admin_id} удалил {count} pending топапов")
    else:
        try:
            target_user_id = int(args[0])
        except ValueError:
            conn.close()
            await update.message.reply_text("❌ Укажите 'all', 'pending' или корректный user_id.")
            return

        cursor.execute('SELECT COUNT(*) FROM balance_topups WHERE user_id = ?', (target_user_id,))
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM balance_topups WHERE user_id = ?', (target_user_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ Удалено топапов пользователя {target_user_id}: {count}"
        )
        logger.info(f"Admin {admin_id} удалил {count} топапов user={target_user_id}")


async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /adminhelp — справочник всех административных команд.
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    text = (
        "📋 <b>АДМИНИСТРАТИВНЫЕ КОМАНДЫ</b>\n\n"
        "📊 <b>Статистика:</b>\n"
        "/stats — статистика БД (матчи, покупки, пользователи, PNG)\n\n"
        "💰 <b>Баланс пользователей:</b>\n"
        "/addbalance &lt;user_id&gt; &lt;сумма&gt; — пополнить баланс\n"
        "  <i>Пример: /addbalance 123456789 50</i>\n"
        "/clearbalance &lt;user_id&gt; — обнулить баланс\n"
        "  <i>Пример: /clearbalance 123456789</i>\n\n"
        "🛒 <b>Покупки анализов:</b>\n"
        "/clearpurchases all — удалить все покупки\n"
        "/clearpurchases &lt;user_id&gt; — покупки пользователя\n\n"
        "ℹ️ <b>Совместимость (legacy):</b>\n"
        "/clean_purchases pending|expired|all — старая команда из user_handlers\n"
        "  <i>Рекомендуется использовать /clearpurchases, чтобы не путаться.</i>\n\n"
        "💳 <b>Пополнения баланса:</b>\n"
        "/cleartopups all — удалить все топапы\n"
        "/cleartopups pending — только ожидающие\n"
        "/cleartopups &lt;user_id&gt; — топапы пользователя\n\n"
        "🧹 <b>Очистка матчей:</b>\n"
        "/clean_matches — удалить старые матчи (без покупок) + PNG\n"
        "/clean_all_matches — ⚠️ ПОЛНАЯ очистка всех матчей и анализов\n\n"
        "❓ <b>Помощь:</b>\n"
        "/adminhelp — эта справка"
    )
    await update.message.reply_text(text, parse_mode='HTML')


async def setup_admin_commands_menu(bot):
    """
    Устанавливает список команд в меню Telegram для каждого администратора.
    Вызывается при старте бота (post_init).
    """
    from telegram import (
        BotCommand,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeChat,
        BotCommandScopeDefault
    )

    admin_commands = [
        BotCommand('adminhelp', 'Справка по всем командам'),
        BotCommand('stats', 'Статистика БД'),
        BotCommand('addbalance', 'Пополнить баланс: /addbalance <user_id> <сумма>'),
        BotCommand('clearbalance', 'Обнулить баланс: /clearbalance <user_id>'),
        BotCommand('clearpurchases', 'Очистить покупки: /clearpurchases [all|user_id]'),
        BotCommand('cleartopups', 'Очистить топапы: /cleartopups [all|pending|user_id]'),
        BotCommand('clean_matches', 'Удалить старые матчи и PNG'),
        BotCommand('clean_all_matches', '⚠️ Удалить ВСЕ матчи и анализы'),
    ]

    # На случай если ранее команды были выставлены глобально:
    # очищаем их, чтобы обычные пользователи не видели админские команды.
    try:
        await bot.set_my_commands([], scope=BotCommandScopeDefault())
        await bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
        logger.info("Глобальные команды очищены (default/all_private_chats)")
    except Exception as e:
        logger.warning(f"Не удалось очистить глобальные команды: {e}")

    admins = database.get_all_admins()
    admin_ids = {admin['user_id'] for admin in admins}
    for admin in admins:
        try:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin['user_id'])
            )
            logger.info(f"Команды меню установлены для admin user_id={admin['user_id']}")
        except Exception as e:
            logger.warning(f"Не удалось установить команды для admin {admin['user_id']}: {e}")

    # Чистим персональные команды у всех не-админов (если ранее были выставлены)
    # чтобы бывшие админы не видели устаревшее меню.
    for user in database.get_all_users():
        user_id = user['user_id']
        if user_id in admin_ids:
            continue
        try:
            await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=user_id))
        except Exception as e:
            logger.debug(
                f"Не удалось очистить chat-scope команды для user_id={user_id}: {e}"
            )


def setup_admin_handlers(application):
    """Регистрация админских команд"""
    application.add_handler(CommandHandler('clean_matches', clean_matches_command))
    application.add_handler(CommandHandler('clean_all_matches', clean_all_matches_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('addbalance', add_balance_command))
    application.add_handler(CommandHandler('clearbalance', clear_balance_command))
    application.add_handler(CommandHandler('clearpurchases', clear_purchases_command))
    application.add_handler(CommandHandler('cleartopups', clear_topups_command))
    application.add_handler(CommandHandler('adminhelp', admin_help_command))
    logger.info(
        "Админские команды зарегистрированы: "
        "/clean_matches, /clean_all_matches, /stats, "
        "/addbalance, /clearbalance, /clearpurchases, /cleartopups, /adminhelp"
    )
