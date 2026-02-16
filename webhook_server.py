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
    try:
        # Импортируем здесь, чтобы избежать циклических зависимостей
        from match_data_fetcher import MatchDataFetcher, build_enriched_context
        from ai_generator import generate_match_analysis_with_context
        from telegram import Bot

        bot = Bot(token=TOKEN)

        # Обновляем сообщение с инструкцией на статус генерации
        if instruction_message_id:
            try:
                progress_text = (
                    "⏳ <b>Создаётся анализ...</b>\n\n"
                    f"🏆 Матч: <b>{match_dict['team1']} vs {match_dict['team2']}</b>\n\n"
                    "🤖 Собираем данные и генерируем анализ...\n"
                    "⏱ Это займёт <b>30-60 секунд</b>, пожалуйста, подождите."
                )
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=instruction_message_id,
                    text=progress_text,
                    parse_mode='HTML'
                )
                logger.info(f"Сообщение обновлено на статус генерации (message_id={instruction_message_id})")
            except Exception as e:
                logger.warning(f"Не удалось обновить сообщение: {e}")

        # Этап 1: Сбор обогащённых данных
        logger.info(f"Сбор данных для матча {match_id}...")
        enriched_data = {}
        try:
            fetcher = MatchDataFetcher()
            enriched_data = fetcher.fetch_match_data(match_dict)
            enriched_context = build_enriched_context(match_dict, enriched_data)
            logger.info(f"Данные собраны. Ошибки: {enriched_data.get('errors', [])}")
        except Exception as e:
            logger.error(f"Ошибка сбора данных: {e}", exc_info=True)
            enriched_context = "Обогащённые данные недоступны."

        # Этап 2: Генерация анализа
        logger.info(f"Генерация анализа для матча {match_id}...")
        analysis_text = await generate_match_analysis_with_context(match_dict, enriched_context)

        # Этап 3: Рендеринг PNG таблицы
        logger.info("Рендеринг PNG таблицы...")
        png_path = None
        cached_png_path = None
        try:
            from analysis_formatter import build_table_data
            from image_renderer import render_analysis_table
            import os
            import shutil

            table_data = build_table_data(match_dict, enriched_data)
            temp_png = render_analysis_table(match_dict, table_data)

            # Сохраняем в постоянную папку
            target_path = f"analysis_cache/analysis_{match_id}.png"
            os.makedirs("analysis_cache", exist_ok=True)
            shutil.copy(temp_png, target_path)

            # Проверяем, что файл действительно скопирован
            if os.path.exists(target_path):
                cached_png_path = target_path
                png_path = cached_png_path
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

        # Сохраняем анализ и путь к PNG в БД
        database.update_match_analysis(match_id, analysis_text, cached_png_path)
        logger.info("Анализ и PNG путь сохранены в БД")

        # Этап 4: Отправка пользователю
        if png_path:
            # Отправляем PNG с caption
            from datetime import datetime as dt
            date_obj = dt.strptime(match_dict['match_date'], '%Y-%m-%d')
            date_formatted = date_obj.strftime('%d %B %Y года').replace(
                'January', 'января').replace('February', 'февраля').replace(
                'March', 'марта').replace('April', 'апреля').replace(
                'May', 'мая').replace('June', 'июня').replace(
                'July', 'июля').replace('August', 'августа').replace(
                'September', 'сентября').replace('October', 'октября').replace(
                'November', 'ноября').replace('December', 'декабря')

            intro_text = (
                f"{match_dict['team1']} примет {match_dict['team2']}. "
                f"Матч пройдёт {date_formatted} в {match_dict['match_time']} МСК "
                f"в рамках турнира {match_dict.get('league', 'N/A')}."
            )
            caption = f"✅ Анализ матча: {intro_text}"

            # Кнопки навигации
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [InlineKeyboardButton("◀️ Назад к матчам", callback_data='back')],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
            ]

            with open(png_path, 'rb') as photo:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            logger.info(f"Анализ (PNG) отправлен пользователю {user_id}")

            # Удаляем сообщение с прогрессом после успешной отправки
            if instruction_message_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=instruction_message_id)
                    logger.info(f"Удалено сообщение с прогрессом (message_id={instruction_message_id})")
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение с прогрессом: {e}")
        else:
            # Fallback: отправляем текстовый анализ
            text = "✅ Ваш анализ готов!\n\n"
            text += f"🏆 {match_dict['team1']} vs {match_dict['team2']}\n"
            text += f"📅 {match_dict['match_date']} в {match_dict['match_time']} МСК\n\n"
            text += f"📊 Анализ:\n{analysis_text}"

            # Кнопки навигации
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [InlineKeyboardButton("◀️ Назад к матчам", callback_data='back')],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
            ]

            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Анализ (текст) отправлен пользователю {user_id}")

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
