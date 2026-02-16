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
from config import DA_ACCESS_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        'Authorization': f'Bearer {DA_ACCESS_TOKEN}'
    }

    response = requests.get(
        f'https://www.donationalerts.com/api/v1/alerts/donations?limit={limit}',
        headers=headers
    )
    response.raise_for_status()
    data = response.json()

    return data['data']


async def process_donation(donation_data):
    """
    Обрабатывает донат (аналогично donationalerts_listener.py).

    Args:
        donation_data: dict с данными доната
    """
    try:
        donation_id = donation_data['id']
        amount_str = str(donation_data['amount'])
        message = donation_data.get('message', '')
        username = donation_data.get('username', 'Anonymous')

        logger.info(f"📥 Обработка доната ID={donation_id} от {username}: {amount_str} руб.")

        # Конвертируем сумму в копейки
        amount_rub = float(amount_str)
        amount_kopeks = int(amount_rub * 100)

        # Извлекаем token из комментария
        import re
        match = re.search(r'\b([A-Z0-9]{12})\b', message.upper())
        if not match:
            logger.warning(f"Token не найден в сообщении: {message}")
            return False

        token = match.group(1)
        logger.info(f"🔑 Извлечён token: {token}")

        # Ищем pending purchase по token
        purchase = database.get_purchase_by_token(token)

        if not purchase:
            # Проверяем идемпотентность
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT donation_event_id, status FROM purchases WHERE token = ?
            ''', (token,))
            existing = cursor.fetchone()
            conn.close()

            if existing and existing['donation_event_id'] == str(donation_id):
                logger.info(f"Donation {donation_id} уже обработан (идемпотентность)")
                return True

            logger.warning(f"Pending purchase с token {token} не найден")
            return False

        purchase_id = purchase['id']
        user_id = purchase['user_id']
        match_id = purchase['match_id']
        expected_amount = purchase['amount']
        # sqlite3.Row не поддерживает .get(), используем прямую индексацию
        instruction_message_id = purchase['instruction_message_id']

        logger.info(f"✅ Найден purchase ID={purchase_id}, user={user_id}, match={match_id}")

        # Проверяем сумму
        if amount_kopeks != expected_amount:
            conn.close()
            logger.warning(f"⚠️ Сумма не совпадает: получено {amount_kopeks}, ожидалось {expected_amount}")

            # Отправляем уведомление пользователю о недостаточной сумме
            from telegram import Bot
            from config import TOKEN
            bot = Bot(token=TOKEN)

            expected_rub = expected_amount / 100
            received_rub = amount_kopeks / 100

            error_text = (
                "❌ <b>Недостаточно средств</b>\n\n"
                f"Получено: <b>{received_rub:.0f} руб.</b>\n"
                f"Требуется: <b>{expected_rub:.0f} руб.</b>\n\n"
                "Ваш заказ остаётся активным. Пожалуйста, отправьте донат "
                f"на правильную сумму (<b>{expected_rub:.0f} руб.</b>) с тем же кодом."
            )

            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=error_text,
                    parse_mode='HTML'
                )
                logger.info(f"Отправлено уведомление о недостаточной сумме пользователю {user_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление о недостаточной сумме: {e}")

            return False

        logger.info(f"💰 Сумма совпадает: {amount_kopeks} копеек")

        # Получаем данные матча
        match = database.get_match_by_id(match_id)
        if not match:
            logger.error(f"❌ Матч {match_id} не найден в БД")
            return False

        match_dict = dict(match) if not isinstance(match, dict) else match

        # Генерируем анализ и отправляем пользователю
        logger.info(f"🤖 Запуск генерации анализа для матча {match_id}...")

        from webhook_server import generate_and_send_analysis
        success = await generate_and_send_analysis(
            user_id, match_id, match_dict, instruction_message_id
        )

        if success:
            # Обновляем purchase на status='paid' ТОЛЬКО после успешной генерации
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE purchases
                SET status = 'paid', donation_event_id = ?
                WHERE id = ?
            ''', (str(donation_id), purchase_id))
            conn.commit()
            conn.close()

            logger.info(f"✅ Донат обработан успешно! Purchase {purchase_id} оплачен и анализ отправлен.")
            return True
        else:
            logger.error(f"❌ Ошибка генерации анализа для purchase {purchase_id}")

            # Отправляем уведомление пользователю об ошибке
            from telegram import Bot
            from config import TOKEN
            bot = Bot(token=TOKEN)

            error_text = (
                "❌ <b>Ошибка генерации анализа</b>\n\n"
                f"🏆 Матч: <b>{match_dict['team1']} vs {match_dict['team2']}</b>\n\n"
                "К сожалению, произошла ошибка при создании анализа. "
                "Ваш заказ остаётся активным — попробуйте получить анализ через "
                "раздел «Мои анализы» через несколько минут.\n\n"
                "Если проблема повторится, обратитесь в поддержку."
            )

            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=error_text,
                    parse_mode='HTML'
                )
                logger.info(f"Отправлено уведомление об ошибке генерации пользователю {user_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление об ошибке: {e}")

            return False

    except Exception as e:
        logger.error(f"❌ Ошибка обработки доната: {e}", exc_info=True)
        return False


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

        except Exception as e:
            logger.error(f"❌ Ошибка polling: {e}", exc_info=True)

        # Ждём перед следующим опросом
        await asyncio.sleep(poll_interval)


async def main():
    """Главная функция polling listener"""
    if not DA_ACCESS_TOKEN:
        logger.error("❌ DA_ACCESS_TOKEN не настроен в config.py")
        logger.error("Запустите сначала: python da_oauth.py")
        return

    logger.info("🚀 Запуск polling listener...")
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
