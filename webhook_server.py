# -*- coding: utf-8 -*-
"""
Webhook сервер для приёма уведомлений от DonationAlerts.

Обрабатывает оплату анализов:
1. Получает POST от DonationAlerts с данными о донате
2. Извлекает token из комментария
3. Находит pending purchase по token
4. Проверяет сумму
5. Генерирует анализ
6. Отправляет пользователю через Telegram
"""
import logging
import re
import hmac
import hashlib
import time
from datetime import datetime
from flask import Flask, request, jsonify
import asyncio
import database
from config import DA_CLIENT_SECRET, TOKEN

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _stage_icon(status: str) -> str:
    """Иконка состояния шага прогресса."""
    if status == 'done':
        return "✅"
    if status == 'run':
        return "⏳"
    if status == 'error':
        return "❌"
    return "▫️"


def _build_generation_progress_text(match_dict: dict, statuses: dict) -> str:
    """Формирует текст прогресса генерации для пользователя."""
    team1 = match_dict.get('team1', 'Команда 1')
    team2 = match_dict.get('team2', 'Команда 2')
    match_date = match_dict.get('match_date', '')
    match_time = match_dict.get('match_time', '')

    return (
        "⏳ <b>Генерируем анализ...</b>\n\n"
        f"🏆 {team1} vs {team2}\n"
        f"📅 {match_date} {match_time} МСК\n\n"
        "<b>Текстовый анализ</b>\n"
        f"{_stage_icon(statuses.get('text_data'))} 1/2 Сбор и обогащение данных\n"
        f"{_stage_icon(statuses.get('text_generate'))} 2/2 Генерация текста\n\n"
        "<b>Таблица</b>\n"
        f"{_stage_icon(statuses.get('table_prepare'))} 1/2 Подготовка таблицы\n"
        f"{_stage_icon(statuses.get('table_render'))} 2/2 Рендер изображения\n\n"
        "<b>Финал</b>\n"
        f"{_stage_icon(statuses.get('send'))} Отправка результата"
    )


async def _update_generation_progress(
    bot,
    user_id: int,
    instruction_message_id: int,
    match_dict: dict,
    statuses: dict
) -> None:
    """Безопасно обновляет сообщение прогресса генерации."""
    if not instruction_message_id:
        return

    text = _build_generation_progress_text(match_dict, statuses)
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=instruction_message_id,
            text=text,
            parse_mode='HTML'
        )
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        logger.warning(
            "Не удалось обновить сообщение прогресса (message_id=%s): %s",
            instruction_message_id,
            e
        )


def _build_enriched_data_summary(data: dict) -> dict:
    """Краткая сводка по собранным enriched-данным для логов."""
    if not isinstance(data, dict):
        return {'type': str(type(data))}

    standings = data.get('standings') or {}
    table = standings.get('table') or []
    team1_events = data.get('team1_last_match_events') or {}
    team2_events = data.get('team2_last_match_events') or {}

    return {
        'h2h': len(data.get('h2h') or []),
        'standings_rows': len(table),
        'team1_form': len(data.get('team1_form') or []),
        'team2_form': len(data.get('team2_form') or []),
        'team1_lineup': len(data.get('team1_last_match_lineup') or []),
        'team2_lineup': len(data.get('team2_last_match_lineup') or []),
        'team1_events': len(team1_events.get('subs', [])) + len(team1_events.get('cards', [])),
        'team2_events': len(team2_events.get('subs', [])) + len(team2_events.get('cards', [])),
        'current_event_stats': len(data.get('current_event_stats') or {}),
        'h2h_recent_stats': len(data.get('h2h_recent_stats') or []),
        'errors': len(data.get('errors') or []),
    }


def _count_context_blocks(enriched_context: str) -> int:
    """Считает количество секций в текстовом контексте."""
    return sum(1 for line in (enriched_context or '').splitlines() if line.strip().startswith("==="))


def verify_signature(payload_body, signature_header):
    """
    Проверка подписи webhook от DonationAlerts (HMAC SHA256).

    Args:
        payload_body: Тело запроса (bytes)
        signature_header: Подпись из заголовка X-Signature

    Returns:
        bool: True если подпись валидна
    """
    if not DA_CLIENT_SECRET:
        logger.warning("DA_CLIENT_SECRET не настроен, пропускаем проверку подписи")
        return True

    expected_signature = hmac.new(
        DA_CLIENT_SECRET.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


def extract_token_from_message(message):
    """
    Извлекает token из комментария к донату.

    Token - это 12-символьный код в uppercase (например: ABC123XYZ456)

    Args:
        message: Комментарий к донату

    Returns:
        str or None: Извлечённый token или None
    """
    if not message:
        return None

    # Ищем 12-символьный код (буквы и цифры, uppercase)
    match = re.search(r'\b([A-Z0-9]{12})\b', message.upper())
    return match.group(1) if match else None


async def generate_and_send_analysis(user_id, match_id, match_dict, instruction_message_id=None):
    """
    Генерирует анализ и отправляет пользователю через Telegram.

    Args:
        user_id: Telegram user ID
        match_id: ID матча
        match_dict: Данные матча (dict)
        instruction_message_id: ID сообщения с инструкцией (для удаления)

    Returns:
        bool: True если успешно
    """
    total_started_at = time.monotonic()
    try:
        # Импортируем здесь, чтобы избежать циклических зависимостей
        from match_data_fetcher import MatchDataFetcher, build_enriched_context
        from ai_generator import generate_match_text_analysis
        from telegram import Bot

        bot = Bot(token=TOKEN)
        progress_statuses = {
            'text_data': 'run',
            'text_generate': 'pending',
            'table_prepare': 'pending',
            'table_render': 'pending',
            'send': 'pending',
        }
        await _update_generation_progress(
            bot, user_id, instruction_message_id, match_dict, progress_statuses
        )

        # Этап 1: Сбор обогащённых данных
        logger.info(f"Сбор данных для матча {match_id}...")
        enriched_data = {}
        enriched_context = "Обогащённые данные недоступны."
        data_started_at = time.monotonic()
        try:
            fetcher = MatchDataFetcher()
            enriched_data = fetcher.fetch_match_data(match_dict)
            enriched_context = build_enriched_context(match_dict, enriched_data)
            data_elapsed = time.monotonic() - data_started_at
            data_summary = _build_enriched_data_summary(enriched_data)
            context_chars = len(enriched_context or "")
            context_blocks = _count_context_blocks(enriched_context)
            logger.info(
                "Данные собраны за %.1fs. summary=%s, context_chars=%s, context_blocks=%s",
                data_elapsed,
                data_summary,
                context_chars,
                context_blocks,
            )
            if enriched_data.get('errors'):
                logger.warning("Ошибки enriched_data: %s", enriched_data.get('errors'))
        except Exception as e:
            data_elapsed = time.monotonic() - data_started_at
            logger.error(f"Ошибка сбора данных: {e}", exc_info=True)
            logger.error("Этап сбора данных завершился с ошибкой за %.1fs", data_elapsed)
            progress_statuses['text_data'] = 'error'
            await _update_generation_progress(
                bot, user_id, instruction_message_id, match_dict, progress_statuses
            )
            raise

        progress_statuses['text_data'] = 'done'
        progress_statuses['text_generate'] = 'run'
        await _update_generation_progress(
            bot, user_id, instruction_message_id, match_dict, progress_statuses
        )

        # Этап 2: Генерация текстового анализа
        logger.info(f"Генерация анализа для матча {match_id}...")
        text_started_at = time.monotonic()
        analysis_text = await generate_match_text_analysis(match_dict, enriched_context)
        text_elapsed = time.monotonic() - text_started_at
        logger.info(
            "Текстовый анализ сгенерирован за %.1fs (%s символов)",
            text_elapsed,
            len(analysis_text or "")
        )
        progress_statuses['text_generate'] = 'done'
        progress_statuses['table_prepare'] = 'run'
        await _update_generation_progress(
            bot, user_id, instruction_message_id, match_dict, progress_statuses
        )

        # Этап 3: Рендеринг PNG таблицы
        logger.info("Рендеринг PNG таблицы...")
        cached_png_path = None
        render_started_at = time.monotonic()
        try:
            from analysis_formatter import build_table_data
            from image_renderer import render_analysis_table
            import os
            import shutil

            table_data = build_table_data(match_dict, enriched_data)
            rows_count = int(
                table_data.get(
                    'raw_coverage_rows_count',
                    table_data.get('coverage_rows_count', 0)
                )
            )
            missing_cells = int(table_data.get('raw_missing_cells_count', 0))
            logger.info(
                "Таблица данных собрана: coverage_rows=%s, missing_cells=%s",
                rows_count,
                missing_cells
            )
            progress_statuses['table_prepare'] = 'done'
            progress_statuses['table_render'] = 'run'
            await _update_generation_progress(
                bot, user_id, instruction_message_id, match_dict, progress_statuses
            )
            temp_png = render_analysis_table(match_dict, table_data)

            # Сохраняем в постоянную папку
            target_path = f"analysis_cache/analysis_{match_id}.webp"
            os.makedirs("analysis_cache", exist_ok=True)
            shutil.copy(temp_png, target_path)

            # Проверяем, что файл действительно скопирован
            if os.path.exists(target_path):
                cached_png_path = target_path
                logger.info(f"PNG таблица сохранена: {cached_png_path}")
            else:
                logger.error(f"Файл не был скопирован: {target_path}")

            # Удаляем временный файл
            try:
                os.remove(temp_png)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Ошибка рендеринга PNG: {e}", exc_info=True)
            cached_png_path = None  # Обнуляем путь при ошибке
            progress_statuses['table_render'] = 'error'
            await _update_generation_progress(
                bot, user_id, instruction_message_id, match_dict, progress_statuses
            )
        finally:
            render_elapsed = time.monotonic() - render_started_at
            logger.info(
                "Этап рендеринга PNG завершён за %.1fs (cached=%s)",
                render_elapsed,
                bool(cached_png_path)
            )
        if progress_statuses.get('table_render') != 'error':
            progress_statuses['table_render'] = 'done'
        progress_statuses['send'] = 'run'
        await _update_generation_progress(
            bot, user_id, instruction_message_id, match_dict, progress_statuses
        )

        # Сохраняем результаты в БД
        db_started_at = time.monotonic()
        if cached_png_path:
            database.update_match_analysis(match_id, analysis_text, cached_png_path)
        else:
            database.update_match_analysis(match_id, analysis_text)
        db_elapsed = time.monotonic() - db_started_at
        logger.info("Анализ и PNG путь сохранены в БД за %.1fs", db_elapsed)

        # Этап 4: Отправка пользователю (выбор формата просмотра)
        send_started_at = time.monotonic()
        sport = match_dict.get('sport')
        match_date = match_dict.get('match_date')
        back_callback_data = (
            f"analysis_back_{sport}_{match_date}"
            if sport and match_date
            else 'back'
        )
        callback_suffix = f"_{sport}_{match_date}" if sport and match_date else ""

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton(
                    "📋 Таблица",
                    callback_data=f"show_table_{match_id}{callback_suffix}"
                ),
                InlineKeyboardButton(
                    "📝 Текст",
                    callback_data=f"show_text_{match_id}{callback_suffix}"
                ),
            ],
            [InlineKeyboardButton("◀️ Назад", callback_data=back_callback_data)],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ]

        ready_text = (
            "✅ <b>Анализ готов</b>\n\n"
            f"🏆 {match_dict['team1']} vs {match_dict['team2']}\n"
            f"📅 {match_dict['match_date']} в {match_dict['match_time']} МСК\n\n"
            "Выберите формат просмотра:"
        )
        await bot.send_message(
            chat_id=user_id,
            text=ready_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

        send_elapsed = time.monotonic() - send_started_at
        total_elapsed = time.monotonic() - total_started_at
        logger.info(
            "Экран выбора формата отправлен пользователю %s за %.1fs (полный pipeline %.1fs)",
            user_id,
            send_elapsed,
            total_elapsed
        )
        progress_statuses['send'] = 'done'
        await _update_generation_progress(
            bot, user_id, instruction_message_id, match_dict, progress_statuses
        )

        # Удаляем сообщение с прогрессом после успешной отправки
        if instruction_message_id:
            try:
                await bot.delete_message(chat_id=user_id, message_id=instruction_message_id)
                logger.info(f"Удалено сообщение с прогрессом (message_id={instruction_message_id})")
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение с прогрессом: {e}")

        return True

    except Exception as e:
        logger.error(f"Ошибка генерации/отправки анализа: {e}", exc_info=True)
        # Отправляем сообщение об ошибке пользователю
        try:
            from telegram import Bot
            bot = Bot(token=TOKEN)

            error_text = (
                "❌ <b>Ошибка генерации анализа</b>\n\n"
                "К сожалению, произошла техническая ошибка при создании анализа. "
                "Ваш заказ остаётся активным — попробуйте получить анализ через "
                "раздел «Мои анализы» через несколько минут.\n\n"
                "Если проблема повторится, обратитесь в поддержку."
            )

            await bot.send_message(
                chat_id=user_id,
                text=error_text,
                parse_mode='HTML'
            )

            # Удаляем сообщение с прогрессом, если есть
            if instruction_message_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=instruction_message_id)
                except Exception:
                    pass
        except Exception:
            pass
        return False


@app.route('/webhook/donationalerts', methods=['POST'])
def donationalerts_webhook():
    """
    Webhook endpoint для приёма уведомлений от DonationAlerts.

    Ожидаемый формат JSON:
    {
        "id": "123456",           # ID события в DA
        "amount": "150.00",       # Сумма в рублях (string)
        "message": "ABC123XYZ",   # Комментарий с token
        "username": "User",       # Имя донатера (опционально)
        ...
    }
    """
    try:
        # Логируем запрос
        logger.info("Получен webhook от DonationAlerts")
        logger.info(f"Headers: {dict(request.headers)}")

        # Проверка подписи (если настроена)
        signature = request.headers.get('X-Signature')
        if signature:
            if not verify_signature(request.data, signature):
                logger.warning("Неверная подпись webhook")
                return jsonify({'error': 'Invalid signature'}), 403

        # Парсинг JSON
        data = request.get_json()
        if not data:
            logger.error("Пустой JSON в запросе")
            return jsonify({'error': 'Empty JSON'}), 400

        logger.info(f"Данные webhook: {data}")

        # Извлекаем данные
        donation_id = data.get('id')
        amount_str = data.get('amount')  # "150.00"
        message = data.get('message', '')

        if not donation_id or not amount_str:
            logger.error("Отсутствуют обязательные поля (id, amount)")
            return jsonify({'error': 'Missing required fields'}), 400

        # Конвертируем сумму в копейки (integer)
        try:
            amount_rub = float(amount_str)
            amount_kopeks = int(amount_rub * 100)
        except (ValueError, TypeError):
            logger.error(f"Неверный формат суммы: {amount_str}")
            return jsonify({'error': 'Invalid amount format'}), 400

        logger.info(f"Donation ID: {donation_id}, Amount: {amount_kopeks} копеек, Message: {message}")

        # Извлекаем token из комментария
        token = extract_token_from_message(message)
        if not token:
            logger.warning(f"Не найден token в сообщении: {message}")
            return jsonify({'error': 'Token not found in message'}), 400

        logger.info(f"Извлечён token: {token}")

        # Ищем pending purchase по token
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, match_id, amount, status, donation_event_id
            FROM purchases
            WHERE token = ? AND status = 'pending'
        ''', (token,))
        purchase = cursor.fetchone()

        if not purchase:
            # Проверяем, может быть уже обработан (идемпотентность)
            cursor.execute('''
                SELECT donation_event_id, status FROM purchases WHERE token = ?
            ''', (token,))
            existing = cursor.fetchone()
            conn.close()

            if existing and existing['donation_event_id'] == donation_id:
                logger.info(f"Donation {donation_id} уже обработан (идемпотентность)")
                return jsonify({'status': 'ok', 'message': 'Already processed'}), 200

            logger.warning(f"Pending purchase с token {token} не найден")
            return jsonify({'error': 'Purchase not found or already paid'}), 404

        purchase_id = purchase['id']
        user_id = purchase['user_id']
        match_id = purchase['match_id']
        expected_amount = purchase['amount']

        logger.info(
            f"Найден purchase ID={purchase_id}, user={user_id},"
            f" match={match_id}, expected_amount={expected_amount}"
        )

        # Проверяем сумму
        if amount_kopeks != expected_amount:
            conn.close()
            logger.warning(f"Сумма не совпадает: получено {amount_kopeks}, ожидалось {expected_amount}")
            return jsonify({'error': 'Amount mismatch', 'expected': expected_amount, 'received': amount_kopeks}), 400

        logger.info(f"Сумма совпадает: {amount_kopeks} копеек")

        # Обновляем purchase: status='paid', donation_event_id
        cursor.execute('''
            UPDATE purchases
            SET status = 'paid', donation_event_id = ?
            WHERE id = ?
        ''', (donation_id, purchase_id))
        conn.commit()
        conn.close()

        logger.info(f"Purchase {purchase_id} обновлён: status='paid', donation_event_id={donation_id}")

        # Получаем данные матча
        match = database.get_match_by_id(match_id)
        if not match:
            logger.error(f"Матч {match_id} не найден в БД")
            return jsonify({'error': 'Match not found'}), 404

        match_dict = dict(match) if not isinstance(match, dict) else match

        # Генерируем анализ и отправляем пользователю (асинхронно)
        logger.info(f"Запуск генерации анализа для матча {match_id}...")

        # Запускаем async функцию в новом event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(generate_and_send_analysis(user_id, match_id, match_dict))
        loop.close()

        if success:
            logger.info(f"✅ Webhook обработан успешно. Purchase {purchase_id} оплачен и анализ отправлен.")
            return jsonify({'status': 'ok', 'purchase_id': purchase_id}), 200
        else:
            logger.error(f"❌ Ошибка генерации анализа для purchase {purchase_id}")
            return jsonify({'status': 'error', 'message': 'Analysis generation failed'}), 500

    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()}), 200


if __name__ == '__main__':
    logger.info("Запуск webhook сервера на порту 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
