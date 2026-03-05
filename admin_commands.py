# -*- coding: utf-8 -*-
"""
Админские команды для управления ботом.

Команды доступны только пользователям из таблицы admins.
"""
import logging
import os
import asyncio
from datetime import datetime
from html import escape
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import database

logger = logging.getLogger(__name__)

MAX_ADMIN_MESSAGE_LEN = 3500


def _format_username(username):
    if username:
        return f"@{escape(str(username))}"
    return "без username"


def _parse_datetime(raw_value):
    if not raw_value:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(raw_value), fmt)
        except ValueError:
            continue
    return None


def _format_datetime(raw_value):
    dt_value = _parse_datetime(raw_value)
    if not dt_value:
        return escape(str(raw_value or '—'))
    return dt_value.strftime('%d.%m.%Y %H:%M')


def _format_remaining_time(raw_value):
    expires_at = _parse_datetime(raw_value)
    if not expires_at:
        return "неизвестно"

    seconds_left = int((expires_at - datetime.now()).total_seconds())
    if seconds_left <= 0:
        return "истекло"

    hours, remainder = divmod(seconds_left, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м"
    if minutes > 0:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"


def _mask_token(token):
    t = str(token or '—')
    if len(t) < 8:
        return t
    return escape(t[:4] + "…" + t[-4:])


def _truncate_text(value, limit=80):
    text = str(value or '').strip()
    if len(text) <= limit:
        return text or '—'
    return f"{text[:limit - 1]}…"


def _format_match_brief(match_like):
    if not match_like:
        return "неизвестный матч"
    if hasattr(match_like, 'keys'):
        team1 = (
            str(match_like['team1'])
            if 'team1' in match_like.keys() and match_like['team1']
            else '?'
        )
        team2 = (
            str(match_like['team2'])
            if 'team2' in match_like.keys() and match_like['team2']
            else '?'
        )
        match_date = (
            str(match_like['match_date'])
            if 'match_date' in match_like.keys() and match_like['match_date']
            else '—'
        )
        match_time = (
            str(match_like['match_time'])
            if 'match_time' in match_like.keys() and match_like['match_time']
            else '—'
        )
    else:
        team1 = str(match_like.get('team1') or '?')
        team2 = str(match_like.get('team2') or '?')
        match_date = str(match_like.get('match_date') or '—')
        match_time = str(match_like.get('match_time') or '—')
    return f"{team1} vs {team2} ({match_date} {match_time})"


async def _reply_text_chunks(message, text, parse_mode=None):
    text = str(text or '').strip()
    if not text:
        return

    chunks = []
    current = ''
    for line in text.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > MAX_ADMIN_MESSAGE_LEN:
            if current:
                chunks.append(current)
                current = line
            else:
                chunks.append(line[:MAX_ADMIN_MESSAGE_LEN])
                current = line[MAX_ADMIN_MESSAGE_LEN:]
        else:
            current = candidate

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.reply_text(chunk, parse_mode=parse_mode)


async def _run_regen_flow(update, context, admin_id, match_id, target_user_id=None):
    match = database.get_match_by_id(match_id)
    if not match:
        await update.message.reply_text(f"❌ Матч {match_id} не найден.")
        return

    match_dict = dict(match) if not isinstance(match, dict) else match
    owner = f"admin:{admin_id}"
    if not database.acquire_generation_job(match_id, owner=owner, stale_after_seconds=300):
        await update.message.reply_text(
            "❌ Для этого матча уже идёт генерация. Попробуйте ещё раз позже."
        )
        return

    await update.message.reply_text(
        "🔄 Перегенерирую анализ:\n"
        f"{_format_match_brief(match_dict)}"
    )

    try:
        old_png_path = database.clear_match_analysis(match_id)
        if old_png_path and os.path.exists(old_png_path):
            try:
                os.remove(old_png_path)
            except Exception as remove_error:
                logger.warning("Не удалось удалить старый PNG %s: %s", old_png_path, remove_error)

        refreshed_match = database.get_match_by_id(match_id)
        match_dict = dict(refreshed_match) if not isinstance(refreshed_match, dict) else refreshed_match

        from user_handlers import (
            _fetch_enriched_data,
            _build_analysis_context,
            _ensure_analysis_text,
            _ensure_analysis_table_png,
        )

        enriched_data = await asyncio.to_thread(_fetch_enriched_data, match_dict)
        _build_analysis_context(match_dict, enriched_data)
        analysis_text, enriched_data = await _ensure_analysis_text(
            match_id,
            match_dict,
            enriched_data=enriched_data
        )
        png_path, _ = await asyncio.to_thread(
            _ensure_analysis_table_png,
            match_id,
            match_dict,
            enriched_data
        )

        if not png_path or not os.path.exists(png_path):
            raise RuntimeError("PNG анализа не был создан")

        sent_notice = ""
        if target_user_id is not None:
            with open(png_path, 'rb') as image_file:
                await context.bot.send_photo(
                    chat_id=target_user_id,
                    photo=image_file,
                    caption=(
                        "Перегенерированный анализ\n"
                        f"{match_dict.get('team1', '?')} vs {match_dict.get('team2', '?')}"
                    )
                )
            sent_notice = f"\n👤 Пользователю {target_user_id} PNG отправлен."

        database.finish_generation_job(match_id, status='done')
        await update.message.reply_text(
            "✅ Перегенерация завершена.\n\n"
            f"🆔 match_id: {match_id}\n"
            f"📝 текст: {len(analysis_text or '')} символов\n"
            f"🖼 png: {png_path}{sent_notice}"
        )
    except Exception as e:
        database.finish_generation_job(match_id, status='error', error=str(e))
        logger.error("Ошибка regen match_id=%s: %s", match_id, e, exc_info=True)
        await update.message.reply_text(f"❌ Ошибка перегенерации: {e}")


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

    if not context.args or context.args[0].strip() != "CONFIRM":
        await update.message.reply_text(
            "⚠️ Команда разрушительная и требует подтверждения.\n\n"
            "Использование:\n"
            "/clean_all_matches CONFIRM"
        )
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
    try:
        if args[0].lower() == 'all':
            cursor.execute('SELECT COUNT(*) FROM purchases')
            count = cursor.fetchone()[0]
            cursor.execute('DELETE FROM purchases')
            conn.commit()
            await update.message.reply_text(f"✅ Удалено всех покупок: {count}")
            logger.warning(f"Admin {admin_id} удалил ВСЕ покупки ({count} шт.)")
        else:
            try:
                target_user_id = int(args[0])
            except ValueError:
                await update.message.reply_text("❌ Укажите 'all' или корректный user_id.")
                return

            cursor.execute('SELECT COUNT(*) FROM purchases WHERE user_id = ?', (target_user_id,))
            count = cursor.fetchone()[0]
            cursor.execute('DELETE FROM purchases WHERE user_id = ?', (target_user_id,))
            conn.commit()
            await update.message.reply_text(
                f"✅ Удалено покупок пользователя {target_user_id}: {count}"
            )
            logger.info(f"Admin {admin_id} удалил {count} покупок user={target_user_id}")
    finally:
        conn.close()


async def clear_user_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clearuseranalysis <user_id> — удалить покупки пользователя и его анализы.

    Логика:
    1) Удаляем все покупки пользователя из purchases.
    2) Для матчей из этих покупок, где больше нет покупок других пользователей:
       очищаем analysis_text и analysis_png_path.
    3) Пытаемся удалить соответствующие PNG-файлы с диска.
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "❌ Неверный формат.\n\n"
            "Использование:\n"
            "/clearuseranalysis <user_id>\n\n"
            "Пример:\n"
            "/clearuseranalysis 123456789"
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом.")
        return

    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT DISTINCT match_id FROM purchases WHERE user_id = ?', (target_user_id,))
        user_match_ids = [row[0] for row in cursor.fetchall()]

        cursor.execute('SELECT COUNT(*) FROM purchases WHERE user_id = ?', (target_user_id,))
        purchases_count = cursor.fetchone()[0]

        if purchases_count == 0:
            await update.message.reply_text(
                f"ℹ️ У пользователя {target_user_id} нет покупок. Удалять нечего."
            )
            return

        cursor.execute('DELETE FROM purchases WHERE user_id = ?', (target_user_id,))
        deleted_purchases = cursor.rowcount

        cleared_match_ids = []
        png_paths = []
        if user_match_ids:
            placeholders = ','.join('?' for _ in user_match_ids)
            cursor.execute(
                f'''
                SELECT id, analysis_png_path
                FROM matches
                WHERE id IN ({placeholders})
                  AND id NOT IN (SELECT DISTINCT match_id FROM purchases)
                  AND (analysis_text IS NOT NULL OR analysis_png_path IS NOT NULL)
                ''',
                user_match_ids
            )
            rows_to_clear = cursor.fetchall()
            cleared_match_ids = [row[0] for row in rows_to_clear]
            png_paths = [row[1] for row in rows_to_clear if row[1]]

            if cleared_match_ids:
                placeholders_clear = ','.join('?' for _ in cleared_match_ids)
                cursor.execute(
                    f'''
                    UPDATE matches
                    SET analysis_text = NULL,
                        analysis_png_path = NULL
                    WHERE id IN ({placeholders_clear})
                    ''',
                    cleared_match_ids
                )

        conn.commit()
    finally:
        conn.close()

    deleted_png = 0
    for png_path in png_paths:
        if png_path and os.path.exists(png_path):
            try:
                os.remove(png_path)
                deleted_png += 1
            except Exception as e:
                logger.warning(f"Не удалось удалить PNG {png_path}: {e}")

    await update.message.reply_text(
        "✅ Очистка пользователя завершена:\n\n"
        f"👤 user_id: {target_user_id}\n"
        f"🗑 Удалено покупок: {deleted_purchases}\n"
        f"🧹 Очищено анализов матчей: {len(cleared_match_ids)}\n"
        f"🖼 Удалено PNG: {deleted_png}"
    )
    logger.warning(
        f"Admin {admin_id} выполнил clearuseranalysis user={target_user_id}: "
        f"purchases={deleted_purchases}, cleared_matches={len(cleared_match_ids)}, png={deleted_png}"
    )


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
    try:
        if mode == 'all':
            cursor.execute('SELECT COUNT(*) FROM balance_topups')
            count = cursor.fetchone()[0]
            cursor.execute('DELETE FROM balance_topups')
            conn.commit()
            await update.message.reply_text(f"✅ Удалено всех топапов: {count}")
            logger.warning(f"Admin {admin_id} удалил ВСЕ balance_topups ({count} шт.)")
        elif mode == 'pending':
            cursor.execute("SELECT COUNT(*) FROM balance_topups WHERE status = 'pending'")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM balance_topups WHERE status = 'pending'")
            conn.commit()
            await update.message.reply_text(f"✅ Удалено pending топапов: {count}")
            logger.info(f"Admin {admin_id} удалил {count} pending топапов")
        else:
            try:
                target_user_id = int(args[0])
            except ValueError:
                await update.message.reply_text("❌ Укажите 'all', 'pending' или корректный user_id.")
                return

            cursor.execute('SELECT COUNT(*) FROM balance_topups WHERE user_id = ?', (target_user_id,))
            count = cursor.fetchone()[0]
            cursor.execute('DELETE FROM balance_topups WHERE user_id = ?', (target_user_id,))
            conn.commit()
            await update.message.reply_text(
                f"✅ Удалено топапов пользователя {target_user_id}: {count}"
            )
            logger.info(f"Admin {admin_id} удалил {count} топапов user={target_user_id}")
    finally:
        conn.close()


async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает расширенную информацию по пользователю."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Использование:\n/userinfo <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть целым числом.")
        return

    info = database.get_user_full_info(target_user_id)
    if not info:
        await update.message.reply_text(f"❌ Пользователь {target_user_id} не найден.")
        return

    user = info['user']
    purchases = info['purchases']
    topups = info['topups']

    purchase_lines = []
    for purchase in purchases:
        purchase_date = purchase['created_at'] or purchase['purchase_date']
        purchase_lines.append(
            f"• #{purchase['id']} | match={purchase['match_id']} | "
            f"{escape(str(purchase['status'] or '—'))} | {_format_datetime(purchase_date)}"
        )
    if not purchase_lines:
        purchase_lines.append("• Нет покупок")

    topup_lines = []
    for topup in topups:
        topup_lines.append(
            f"• #{topup['id']} | {topup['amount_rub']} RUB | "
            f"{escape(str(topup['status'] or '—'))} | "
            f"{_mask_token(topup['token'])} | {_format_datetime(topup['created_at'])}"
        )
    if not topup_lines:
        topup_lines.append("• Нет пополнений")

    text = (
        f"<b>UserInfo</b>\n\n"
        f"<b>user_id:</b> <code>{user['user_id']}</code>\n"
        f"<b>username:</b> {_format_username(user['username'])}\n"
        f"<b>баланс:</b> {int(user['balance'] or 0)} RUB\n"
        f"<b>куплено анализов:</b> {int(user['total_analysis_bought'] or 0)}\n"
        f"<b>зарегистрирован:</b> {_format_datetime(user['created_at'])}\n\n"
        f"<b>Последние покупки:</b>\n" + "\n".join(purchase_lines) + "\n\n"
        "<b>Последние topups:</b>\n" + "\n".join(topup_lines)
    )
    await _reply_text_chunks(update.message, text, parse_mode='HTML')


async def finduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ищет пользователя по username или user_id."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if not context.args:
        await update.message.reply_text("❌ Использование:\n/finduser <username или user_id>")
        return

    query = " ".join(context.args).strip()
    found_users = database.find_users(query, limit=10)
    if not found_users:
        await update.message.reply_text(
            f"🔎 Никого не нашёл по запросу: {escape(query)}",
            parse_mode='HTML'
        )
        return

    lines = ["<b>🔎 Результаты поиска</b>\n"]
    for user in found_users:
        lines.append(
            f"👤 <b>{_format_username(user['username'])}</b>\n"
            f"   id: <code>{user['user_id']}</code>\n"
            f"   баланс: <b>{int(user['balance'] or 0)} RUB</b>\n"
            f"   куплено анализов: {int(user['total_analysis_bought'] or 0)}\n"
            f"   регистрация: {_format_datetime(user['created_at'])}\n"
            f"   дальше: <code>/userinfo {user['user_id']}</code> | "
            f"<code>/refund_last {user['user_id']}</code> | "
            f"<code>/regen_last {user['user_id']}</code>"
        )

    await _reply_text_chunks(update.message, "\n".join(lines), parse_mode='HTML')


async def topups_pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все актуальные pending topups."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    pending_topups = database.get_all_pending_topups()
    if not pending_topups:
        await update.message.reply_text("ℹ️ Актуальных pending topups нет.")
        return

    lines = ["<b>Pending topups</b>\n"]
    for topup in pending_topups:
        lines.append(
            f"• user_id=<code>{topup['user_id']}</code> | {_format_username(topup['username'])}\n"
            f"  сумма: <b>{int(topup['amount_rub'] or 0)} RUB</b> | "
            f"token: <code>{_mask_token(topup['token'])}</code>\n"
            f"  создано: {_format_datetime(topup['created_at'])} | "
            f"осталось: {_format_remaining_time(topup['expires_at'])}"
        )

    await _reply_text_chunks(update.message, "\n".join(lines), parse_mode='HTML')


async def recent_donations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последние донаты из DonationAlerts."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ N должен быть целым числом.")
            return

    limit = max(1, min(limit, 30))
    await update.message.reply_text(f"Запрашиваю последние донаты (limit={limit})...")

    try:
        from da_polling import get_recent_donations

        donations = await asyncio.to_thread(get_recent_donations, limit)
        donations = list(donations or [])[:limit]
        if not donations:
            await update.message.reply_text("ℹ️ DonationAlerts не вернул донаты.")
            return

        lines = [f"<b>Последние донаты</b> (до {limit})\n"]
        for donation in donations:
            donation_id = donation.get('id', '—')
            amount = donation.get('amount', '—')
            username = donation.get('username') or donation.get('name') or 'Anonymous'
            comment = _truncate_text(donation.get('message') or donation.get('comment') or '—', 120)
            created_at = (
                donation.get('created_at')
                or donation.get('createdAt')
                or donation.get('date')
            )
            lines.append(
                f"• ID=<code>{escape(str(donation_id))}</code> | "
                f"{escape(str(amount))} RUB | {escape(str(username))}\n"
                f"  comment: <code>{escape(comment)}</code>\n"
                f"  дата: {_format_datetime(created_at)}"
            )

        await _reply_text_chunks(update.message, "\n".join(lines), parse_mode='HTML')
    except Exception as e:
        logger.error("Ошибка recent_donations: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ Ошибка запроса DonationAlerts: {e}")


async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает средства за покупку на баланс пользователя."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Использование:\n/refund <purchase_id>")
        return

    try:
        purchase_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ purchase_id должен быть целым числом.")
        return

    result = database.refund_purchase(purchase_id)
    if not result[0]:
        await update.message.reply_text(f"❌ Возврат не выполнен: {result[1]}")
        return

    _, user_id, amount = result
    user_info = database.get_user_full_info(user_id)
    username = _format_username(user_info['user']['username']) if user_info else '—'
    balance = user_info['user']['balance'] if user_info else database.get_user_balance(user_id)

    await update.message.reply_text(
        "Возврат выполнен.\n\n"
        f"purchase_id: {purchase_id}\n"
        f"user_id: {user_id} ({username})\n"
        f"сумма возврата: +{amount} RUB\n"
        f"новый баланс: {int(balance or 0)} RUB",
        parse_mode='HTML'
    )
    logger.warning(
        "Admin %s выполнил refund purchase_id=%s user_id=%s amount=%s",
        admin_id, purchase_id, user_id, amount
    )


async def refund_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает средства за последнюю paid-покупку пользователя."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Использование:\n/refund_last <user_id>")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть целым числом.")
        return

    purchase = database.get_last_paid_purchase_by_user(user_id)
    if not purchase:
        await update.message.reply_text(
            f"ℹ️ У пользователя {user_id} нет оплаченных покупок для возврата."
        )
        return

    result = database.refund_purchase(int(purchase['id']))
    if not result[0]:
        await update.message.reply_text(f"❌ Возврат не выполнен: {result[1]}")
        return

    user_info = database.get_user_full_info(user_id)
    username = _format_username(user_info['user']['username']) if user_info else '—'
    balance = user_info['user']['balance'] if user_info else database.get_user_balance(user_id)

    await update.message.reply_text(
        "✅ Возврат выполнен.\n\n"
        f"👤 Пользователь: {user_id} ({username})\n"
        f"🧾 Покупка: {purchase['id']}\n"
        f"🏟 Матч: {_format_match_brief(purchase)}\n"
        f"💰 Возврат: +{result[2]} RUB\n"
        f"💳 Новый баланс: {int(balance or 0)} RUB",
        parse_mode='HTML'
    )
    logger.warning(
        "Admin %s выполнил refund_last user_id=%s purchase_id=%s amount=%s",
        admin_id, user_id, purchase['id'], result[2]
    )


async def force_sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно запускает синхронизацию матчей и coverage check."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    await update.message.reply_text("Запускаю принудительную синхронизацию матчей...")

    def _run_sync_job():
        from sync_matches import SportsDBSyncer, run_coverage_check

        syncer = SportsDBSyncer(mode='top3', limit=15)
        matches = syncer.sync()
        sync_results = syncer.save_matches_to_db(matches)
        coverage_results = run_coverage_check()
        return sync_results, coverage_results

    try:
        sync_results, coverage_results = await asyncio.to_thread(_run_sync_job)
        text = (
            "Синхронизация завершена.\n\n"
            f"найдено: {sync_results['total']}\n"
            f"сохранено: {sync_results['inserted']}\n"
            f"обновлено: 0\n"
            f"пропущено: {sync_results['skipped']}\n"
            f"ошибок: {sync_results['errors']}\n\n"
            "Покрытие:\n"
            f"проверено: {coverage_results['checked']}\n"
            f"ok: {coverage_results['ok']}\n"
            f"скрыто: {coverage_results['hidden']}\n"
            f"ошибок: {coverage_results['errors']}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logger.error("Ошибка force_sync: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ Ошибка синхронизации: {e}")


async def regen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно перегенерирует анализ и PNG по матчу."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) not in (1, 2):
        await update.message.reply_text("❌ Использование:\n/regen <match_id> [user_id]")
        return

    try:
        match_id = int(context.args[0])
        target_user_id = int(context.args[1]) if len(context.args) == 2 else None
    except ValueError:
        await update.message.reply_text("❌ match_id и user_id должны быть целыми числами.")
        return

    await _run_regen_flow(update, context, admin_id, match_id, target_user_id=target_user_id)


async def regen_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перегенерирует анализ по последней paid-покупке пользователя."""
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) not in (1, 2):
        await update.message.reply_text("❌ Использование:\n/regen_last <user_id> [кому_отправить_png]")
        return

    try:
        user_id = int(context.args[0])
        target_user_id = int(context.args[1]) if len(context.args) == 2 else None
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть целым числом.")
        return

    purchase = database.get_last_paid_purchase_by_user(user_id)
    if not purchase:
        await update.message.reply_text(
            f"ℹ️ У пользователя {user_id} нет оплаченных покупок для перегенерации."
        )
        return

    await update.message.reply_text(
        "🧾 Нашёл последнюю покупку пользователя.\n"
        f"purchase_id: {purchase['id']}\n"
        f"match_id: {purchase['match_id']}\n"
        f"матч: {_format_match_brief(purchase)}"
    )
    await _run_regen_flow(update, context, admin_id, int(purchase['match_id']), target_user_id=target_user_id)


async def matchinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /matchinfo <match_id> — подробная информация о матче.
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Использование: <code>/matchinfo &lt;match_id&gt;</code>",
            parse_mode='HTML'
        )
        return

    match_id = int(args[0])
    match = database.get_match_by_id(match_id)
    if not match:
        await update.message.reply_text(f"❌ Матч #{match_id} не найден.")
        return

    # Покупки на этот матч
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT p.id, p.user_id, u.username, p.status,
                   COALESCE(p.created_at, p.purchase_date) AS date
            FROM purchases p
            LEFT JOIN users u ON u.user_id = p.user_id
            WHERE p.match_id = ?
            ORDER BY p.id DESC
            LIMIT 20
            ''',
            (match_id,)
        )
        purchases = cursor.fetchall()
        cursor.execute(
            'SELECT COUNT(*) as cnt FROM purchases WHERE match_id = ? AND status = ?',
            (match_id, 'paid')
        )
        paid_count = cursor.fetchone()['cnt']

    has_analysis = bool((match['analysis_text'] or '').strip())
    has_png = bool(match['analysis_png_path'])
    coverage = match['coverage_ok']
    coverage_str = {1: 'да', 0: 'нет', None: 'не проверен'}.get(coverage, str(coverage))

    lines = [
        f"⚽ <b>Матч #{match_id}</b>",
        f"<b>{escape(match['team1'])} — {escape(match['team2'])}</b>",
        f"Дата: {match['match_date']} {match['match_time']}",
        f"Лига: {escape(match['league'] or '—')}",
        f"Спорт: {escape(match['sport'] or '—')}",
        f"api_event_id: <code>{escape(str(match['api_event_id'] or '—'))}</code>",
        f"active: {'да' if match['is_active'] else 'нет'}",
        f"coverage_ok: {coverage_str}",
        f"Анализ: {'есть' if has_analysis else 'нет'}"
        + (f" | PNG: {'есть' if has_png else 'нет'}" if has_analysis else ""),
        f"Цена: {match['price'] or 150} руб.",
        "",
        f"<b>Покупки:</b> {paid_count} paid"
        + (f" ({len(purchases)} всего)" if len(purchases) != paid_count else ""),
    ]

    if purchases:
        for p in purchases[:10]:
            uname = _format_username(p['username'])
            date_str = _format_datetime(p['date'])
            lines.append(
                f"  • #{p['id']} {uname} (id={p['user_id']}) "
                f"— {p['status']} {date_str}"
            )
        if len(purchases) > 10:
            lines.append(f"  ... и ещё {len(purchases) - 10}")
    else:
        lines.append("  Покупок нет")

    await update.message.reply_text("\n".join(lines), parse_mode='HTML')


async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /adminhelp — справочник всех административных команд.
    """
    admin_id = update.effective_user.id
    if not database.is_admin(admin_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    text = (
        "🛠 <b>АДМИН-ПОМОЩНИК</b>\n\n"
        "👋 Если не знаете внутренние ID, начинайте с этих команд:\n"
        "🔎 <code>/finduser username</code> — найти пользователя по username или user_id\n"
        "↩️ <code>/refund_last user_id</code> — вернуть деньги за последнюю покупку\n"
        "🔄 <code>/regen_last user_id</code> — заново собрать последний анализ\n\n"
        "👤 <b>Работа с пользователем</b>\n"
        "• <code>/finduser username</code> — найти человека\n"
        "• <code>/userinfo user_id</code> — полная информация по человеку\n"
        "• <code>/addbalance user_id сумма</code> — пополнить баланс вручную\n"
        "• <code>/clearbalance user_id</code> — обнулить баланс\n\n"
        "💸 <b>Возвраты</b>\n"
        "• <code>/refund_last user_id</code> — простой возврат за последнюю покупку\n"
        "• <code>/refund purchase_id</code> — точечный возврат, если знаете ID покупки\n\n"
        "🧠 <b>Анализы</b>\n"
        "• <code>/regen_last user_id</code> — перегенерировать последний анализ пользователя\n"
        "• <code>/regen match_id [user_id]</code> — перегенерировать анализ по ID матча\n"
        "• <code>/clearuseranalysis user_id</code> — удалить покупки и анализы пользователя\n\n"
        "💳 <b>Пополнения и донаты</b>\n"
        "• <code>/topups_pending</code> — кто сейчас ждёт пополнение\n"
        "• <code>/recent_donations [N]</code> — последние донаты из DonationAlerts\n"
        "• <code>/cleartopups all|pending|user_id</code> — очистка topups\n\n"
        "⚽ <b>Матчи и синхронизация</b>\n"
        "• <code>/matchinfo match_id</code> — подробная информация о матче\n"
        "• <code>/force_sync</code> — вручную обновить список матчей\n"
        "• <code>/stats</code> — общая статистика бота\n"
        "• <code>/clean_matches</code> — удалить старые матчи без покупок и PNG\n"
        "• <code>/clean_all_matches CONFIRM</code> — полная очистка матчей и анализов\n\n"
        "🧰 <b>Технические legacy-команды</b>\n"
        "• <code>/clearpurchases all|user_id</code>\n"
        "• <code>/clean_purchases pending|expired|all</code>\n\n"
        "💡 Обычный порядок работы:\n"
        "1. Найти человека через <code>/finduser</code>\n"
        "2. Посмотреть детали через <code>/userinfo</code>\n"
        "3. Сделать <code>/refund_last</code> или <code>/regen_last</code>"
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
        BotCommand('finduser', 'Найти пользователя'),
        BotCommand('stats', 'Статистика БД'),
        BotCommand('userinfo', 'Диагностика по user_id'),
        BotCommand('topups_pending', 'Все актуальные pending topups'),
        BotCommand('recent_donations', 'Последние донаты DonationAlerts'),
        BotCommand('addbalance', 'Пополнить баланс: /addbalance <user_id> <сумма>'),
        BotCommand('clearbalance', 'Обнулить баланс: /clearbalance <user_id>'),
        BotCommand('refund_last', 'Вернуть деньги за последнюю покупку'),
        BotCommand('refund', 'Возврат за покупку: /refund <purchase_id>'),
        BotCommand('clearuseranalysis', 'Удалить покупки + анализы: /clearuseranalysis <user_id>'),
        BotCommand('regen_last', 'Перегенерировать последний анализ'),
        BotCommand('regen', 'Перегенерация: /regen <match_id> [user_id]'),
        BotCommand('cleartopups', 'Очистить топапы: /cleartopups [all|pending|user_id]'),
        BotCommand('matchinfo', 'Информация о матче: /matchinfo <match_id>'),
        BotCommand('force_sync', 'Принудительный sync_matches'),
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
    application.add_handler(CommandHandler('finduser', finduser_command))
    application.add_handler(CommandHandler('userinfo', userinfo_command))
    application.add_handler(CommandHandler('topups_pending', topups_pending_command))
    application.add_handler(CommandHandler('recent_donations', recent_donations_command))
    application.add_handler(CommandHandler('refund_last', refund_last_command))
    application.add_handler(CommandHandler('refund', refund_command))
    application.add_handler(CommandHandler('force_sync', force_sync_command))
    application.add_handler(CommandHandler('regen_last', regen_last_command))
    application.add_handler(CommandHandler('regen', regen_command))
    application.add_handler(CommandHandler('clean_matches', clean_matches_command))
    application.add_handler(CommandHandler('clean_all_matches', clean_all_matches_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('addbalance', add_balance_command))
    application.add_handler(CommandHandler('clearbalance', clear_balance_command))
    application.add_handler(CommandHandler('clearpurchases', clear_purchases_command))
    application.add_handler(CommandHandler('clearuseranalysis', clear_user_analysis_command))
    application.add_handler(CommandHandler('cleartopups', clear_topups_command))
    application.add_handler(CommandHandler('matchinfo', matchinfo_command))
    application.add_handler(CommandHandler('adminhelp', admin_help_command))
    logger.info(
        "Админские команды зарегистрированы: "
        "/finduser, /userinfo, /topups_pending, /recent_donations, /refund_last, /refund, "
        "/force_sync, /regen_last, /regen, "
        "/clean_matches, /clean_all_matches, /stats, /addbalance, /clearbalance, "
        "/clearpurchases, /clearuseranalysis, /cleartopups, /matchinfo, /adminhelp"
    )
