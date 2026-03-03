# -*- coding: utf-8 -*-
"""
Polling listener для DonationAlerts (вместо WebSocket).

Периодически опрашивает API на предмет новых донатов.
Более надёжный метод чем WebSocket для малых нагрузок.
"""
import asyncio
import logging
import requests
import database
import config
from healthcheck_utils import remove_heartbeat, touch_heartbeat
from logging_utils import setup_logging
from utils import extract_token_from_message

setup_logging('da_polling')
logger = logging.getLogger(__name__)

# Храним ID последнего обработанного доната
last_processed_donation_id = None


def get_recent_donations(limit=10):
    """
    Получает список последних донатов через API.

    Args:
        limit: Количество донатов для получения

    Returns:
        list: Список донатов
    """
    headers = {
        'Authorization': f'Bearer {config.DA_ACCESS_TOKEN}'
    }

    response = requests.get(
        f'https://www.donationalerts.com/api/v1/alerts/donations?limit={limit}',
        headers=headers,
        timeout=15
    )
    response.raise_for_status()
    data = response.json()

    return data['data']


async def process_donation(donation_data):
    """
    Обрабатывает донат.

    Сначала ищет token в таблице purchases (прямая DA покупка анализа).
    Если не найдено — ищет в balance_topups (пополнение баланса).

    Args:
        donation_data: dict с данными доната
    """
    try:
        donation_id = donation_data['id']
        amount_str = str(donation_data['amount'])
        message = donation_data.get('message') or ''
        username = donation_data.get('username', 'Anonymous')

        logger.info(f"📥 Обработка доната ID={donation_id} от {username}: {amount_str} руб.")

        amount_rub = float(amount_str)

        # Извлекаем token из комментария
        token = extract_token_from_message(message)
        if not token:
            logger.warning(f"Token не найден в сообщении: '{message}'")
            return False
        logger.info(f"🔑 Извлечён token: {token}")

        # Актуальный сценарий: DonationAlerts используется только для пополнения баланса.
        topup = database.get_topup_by_token(token)

        if topup:
            return await _handle_topup_donation(topup, donation_id, amount_rub)

        # Не найдено нигде — проверяем идемпотентность
        if database.is_donation_event_used(str(donation_id)):
            logger.info(f"Donation {donation_id} уже засчитан ранее (идемпотентность)")
            return True

        logger.warning(f"Token {token} не найден в balance_topups")
        return False

    except Exception as e:
        logger.error(f"❌ Ошибка обработки доната: {e}", exc_info=True)
        return False


async def _handle_topup_donation(topup, donation_id, amount_rub):
    """Обрабатывает донат для пополнения баланса (balance_topups)."""
    topup_id = topup['id']
    user_id = topup['user_id']

    # Идемпотентность
    if database.is_donation_event_used(str(donation_id)):
        logger.info(f"Donation {donation_id} уже засчитан в balance_topups")
        return True

    received_rub = int(amount_rub)  # целые рубли
    ok = database.complete_balance_topup(topup_id, str(donation_id), received_rub)
    if not ok:
        logger.error(f"Ошибка complete_balance_topup для topup {topup_id}")
        return False

    new_balance = database.get_user_balance(user_id)
    logger.info(
        f"✅ Баланс user={user_id} пополнен на {received_rub} руб. "
        f"(donation {donation_id}), новый баланс: {new_balance}"
    )

    analyses_word = (
        "анализ" if received_rub == 1
        else "анализа" if 2 <= received_rub <= 4
        else "анализов"
    )

    text = (
        f"✅ <b>Баланс пополнен!</b>\n\n"
        f"💰 Зачислено: <b>+{received_rub} руб.</b> ({received_rub} {analyses_word})\n"
        f"💳 Ваш баланс: <b>{new_balance} руб.</b>\n\n"
        "Выберите матч для покупки анализа!"
    )

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from config import TOKEN
    bot = Bot(token=TOKEN)

    instruction_message_id = topup['instruction_message_id']
    topup_keys = topup.keys() if hasattr(topup, 'keys') else []
    return_match_id = topup['return_match_id'] if 'return_match_id' in topup_keys else None

    keyboard_rows = []
    if return_match_id:
        keyboard_rows.append([
            InlineKeyboardButton(
                "🎯 Вернуться к матчу",
                callback_data=f"return_to_match_{return_match_id}"
            )
        ])
    keyboard_rows.append([
        InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')
    ])
    keyboard = InlineKeyboardMarkup(keyboard_rows)

    # Редактируем сообщение с инструкцией (одно окно)
    edited = False
    if instruction_message_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=instruction_message_id,
                text=text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            edited = True
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")

    # Fallback: новое сообщение если редактирование не сработало
    if not edited:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")

    return True


async def poll_donations():
    """
    Периодически опрашивает API на предмет новых донатов.
    """

    logger.info("="*60)
    logger.info("DONATIONALERTS POLLING LISTENER")
    logger.info("="*60)
    logger.info("Режим: Polling API каждые 15 секунд")
    logger.info("="*60 + "\n")

    poll_interval = 15  # Опрос каждые 15 секунд
    processed_ids = set()  # Храним обработанные ID

    while True:
        try:
            touch_heartbeat('da_polling')
        except Exception as e:
            logger.warning("Не удалось обновить heartbeat da_polling в начале цикла: %s", e)

        try:
            # Получаем последние донаты
            donations = get_recent_donations(limit=10)

            if not donations:
                logger.debug("Нет новых донатов")
                await asyncio.sleep(poll_interval)
                continue

            # Обрабатываем новые донаты (от старых к новым)
            new_donations = []
            for donation in reversed(donations):
                donation_id = donation['id']

                # Пропускаем уже обработанные
                if donation_id in processed_ids:
                    continue

                new_donations.append(donation)

            if new_donations:
                logger.info(f"\n📬 Найдено новых донатов: {len(new_donations)}")

                for donation in new_donations:
                    donation_id = donation['id']
                    logger.info(f"\n{'='*60}")
                    logger.info(f"🔔 НОВЫЙ ДОНАТ ID={donation_id}")
                    logger.info(f"{'='*60}")

                    success = await process_donation(donation)

                    # Помечаем как обработанный
                    processed_ids.add(donation_id)

                    # Ограничиваем размер set (храним только последние 100)
                    if len(processed_ids) > 100:
                        processed_ids = set(list(processed_ids)[-100:])

                    if success:
                        logger.info(f"✅ Донат {donation_id} успешно обработан\n")
                    else:
                        logger.info(f"⚠️ Донат {donation_id} пропущен (код не найден или уже обработан)\n")

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                logger.warning("DA токен протух (401), пробуем обновить...")
                try:
                    from da_oauth import refresh_access_token
                    refresh_access_token()
                    logger.info("DA токен успешно обновлён")
                except Exception as refresh_err:
                    logger.error(f"Не удалось обновить DA токен: {refresh_err}")
            else:
                logger.error(f"❌ HTTP ошибка polling: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ Ошибка polling: {e}", exc_info=True)

        try:
            touch_heartbeat('da_polling')
        except Exception as e:
            logger.warning("Не удалось обновить heartbeat da_polling перед sleep: %s", e)

        # Ждём перед следующим опросом
        await asyncio.sleep(poll_interval)


async def main():
    """Главная функция polling listener"""
    if not config.DA_ACCESS_TOKEN:
        logger.error("❌ DA_ACCESS_TOKEN не настроен в config.py")
        logger.error("Запустите сначала: python da_oauth.py")
        return

    logger.info("🚀 Запуск polling listener...")
    try:
        touch_heartbeat('da_polling')
    except Exception as e:
        logger.warning("Не удалось создать стартовый heartbeat da_polling: %s", e)
    await poll_donations()


if __name__ == '__main__':
    """
    Запуск polling listener для обработки донатов.

    Usage:
        python da_polling.py
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Остановка polling listener...")
    finally:
        remove_heartbeat('da_polling')
