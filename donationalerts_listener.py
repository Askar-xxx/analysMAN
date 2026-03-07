# -*- coding: utf-8 -*-
"""
WebSocket listener для прослушивания донатов от DonationAlerts.

Подключается к Centrifugo WebSocket и обрабатывает события donation.
"""
import json
import logging
import asyncio
import ssl
import websockets
import requests
import database
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_socket_connection_token():
    """
    Получает socket_connection_token из DonationAlerts API.

    Returns:
        dict: {'token': '...', 'user_id': 123456}
    """
    headers = {
        'Authorization': f'Bearer {config.DA_ACCESS_TOKEN}'
    }

    response = requests.get(
        'https://www.donationalerts.com/api/v1/user/oauth',
        headers=headers
    )
    response.raise_for_status()
    data = response.json()

    return {
        'token': data['data']['socket_connection_token'],
        'user_id': data['data']['id']
    }


def get_centrifuge_subscribe_token(client_id, channel):
    """
    Получает токен подписки на канал через DonationAlerts API.
    Обязательный шаг перед подпиской на Centrifugo канал.

    Args:
        client_id: ID клиента из ответа connect команды Centrifugo
        channel: Название канала (например $alerts:donation_12345)

    Returns:
        str: Токен для подписки на канал
    """
    headers = {
        'Authorization': f'Bearer {config.DA_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }

    response = requests.post(
        'https://www.donationalerts.com/api/v1/centrifuge/subscribe',
        headers=headers,
        json={
            'channels': [channel],
            'client': client_id
        }
    )
    response.raise_for_status()
    data = response.json()

    # Ответ содержит список каналов с токенами
    channels = data.get('channels', [])
    for ch in channels:
        if ch.get('channel') == channel:
            return ch.get('token')

    raise ValueError(f"Токен для канала {channel} не найден в ответе API")


async def _process_topup(topup, amount_kopeks, donation_id):
    """Обрабатывает пополнение баланса по найденному топапу."""
    topup_id = topup['id']
    user_id = topup['user_id']
    is_flexible = (topup['amount_rub'] == 0)  # любая сумма

    if is_flexible:
        # Гибкий топап — зачисляем ровно столько, сколько пришло (целые рубли)
        received_rub = int(amount_kopeks / 100)
        if received_rub <= 0:
            logger.warning(
                f"⚠️ Получена нулевая сумма для гибкого топапа {topup_id}"
            )
            return
        ok = database.complete_balance_topup(
            topup_id, str(donation_id), received_rub
        )
        amount_rub = received_rub
    else:
        # Фиксированный топап — проверяем с допуском на комиссию DA (15%)
        expected_kopeks = topup['amount_kopeks']
        min_acceptable = int(expected_kopeks * 0.85)
        if amount_kopeks < min_acceptable:
            logger.warning(
                f"⚠️ Сумма слишком мала для топапа {topup_id}: "
                f"получено {amount_kopeks} коп., минимум {min_acceptable} коп."
            )
            return
        ok = database.complete_balance_topup(topup_id, str(donation_id))
        amount_rub = topup['amount_rub']

    if not ok:
        logger.error(f"❌ Ошибка complete_balance_topup для топапа {topup_id}")
        return

    new_balance = database.get_user_balance(user_id)
    logger.info(
        f"✅ Баланс пользователя {user_id} пополнен на {amount_rub} руб. "
        f"(топап {topup_id}). Новый баланс: {new_balance} руб."
    )
    # Уведомление не отправляем: пользователь получит результат
    # при нажатии кнопки «Проверить баланс» в меню пополнения.


async def process_donation(donation_data):
    """
    Обрабатывает полученный донат (аналогично webhook_server.py).

    Args:
        donation_data: dict с данными доната от DonationAlerts
    """
    try:
        donation_id = donation_data['id']
        amount_str = str(donation_data['amount'])  # "150.00"
        message = donation_data.get('message', '')
        username = donation_data.get('username', 'Anonymous')

        logger.info(f"📥 Получен донат от {username}: {amount_str} руб., сообщение: {message}")

        # Конвертируем сумму в копейки
        amount_rub = float(amount_str)
        amount_kopeks = int(amount_rub * 100)

        # Извлекаем token из комментария
        import re
        match = re.search(r'\b([A-Z0-9]{12})\b', (message or '').upper())
        if not match:
            logger.warning(f"Token не найден в сообщении: {message!r} — донат без кода, пропускаем")
            return

        token = match.group(1)
        logger.info(f"🔑 Извлечён token: {token}")

        # 1. Проверяем balance_topups (пополнение баланса)
        topup = database.get_topup_by_token(token)
        if topup:
            logger.info(f"💰 Найден топап ID={topup['id']} для user={topup['user_id']}")
            await _process_topup(topup, amount_kopeks, donation_id)
            return

        logger.warning(f"Token {token} не найден в balance_topups")
        return

    except Exception as e:
        logger.error(f"❌ Ошибка обработки доната: {e}", exc_info=True)


async def listen_donations():
    """
    Подключается к Centrifugo WebSocket и слушает события donation.
    """
    logger.info("="*60)
    logger.info("DONATIONALERTS LISTENER")
    logger.info("="*60)

    # Получаем socket_connection_token
    logger.info("Получение socket_connection_token...")
    socket_data = get_socket_connection_token()
    socket_token = socket_data['token']
    user_id = socket_data['user_id']

    logger.info("✅ Socket token получен")
    logger.info(f"User ID: {user_id}")

    # Подключаемся к Centrifugo WebSocket
    ws_url = "wss://centrifugo.donationalerts.com/connection/websocket"
    channel = f"$alerts:donation_{user_id}"

    logger.info(f"Подключение к WebSocket: {ws_url}")
    logger.info(f"Канал: {channel}")
    logger.info("="*60 + "\n")

    ssl_context = ssl.create_default_context()
    async with websockets.connect(
        ws_url,
        ssl=ssl_context,
        open_timeout=30,
        ping_interval=20,
        ping_timeout=20
    ) as websocket:
        logger.info("WebSocket подключен")

        # Шаг 1: Отправляем команду connect с socket_connection_token
        connect_cmd = {
            "params": {
                "token": socket_token
            },
            "id": 1
        }
        await websocket.send(json.dumps(connect_cmd))
        logger.info("Отправлена команда connect")

        # Получаем ответ и извлекаем client ID
        response = await websocket.recv()
        connect_response = json.loads(response)
        logger.info(f"Ответ connect: {response[:200]}...")

        # Извлекаем client ID из ответа connect
        client_id = connect_response.get('result', {}).get('client', '')
        if not client_id:
            logger.error(f"Не удалось извлечь client ID из ответа: {response}")
            return
        logger.info(f"Client ID: {client_id}")

        # Шаг 2: Получаем токен подписки через DonationAlerts API
        logger.info("Получение токена подписки через API...")
        subscribe_token = get_centrifuge_subscribe_token(client_id, channel)
        logger.info("Токен подписки получен")

        # Шаг 3: Подписываемся на канал с токеном
        subscribe_cmd = {
            "params": {
                "channel": channel,
                "token": subscribe_token
            },
            "method": 1,  # subscribe
            "id": 2
        }
        await websocket.send(json.dumps(subscribe_cmd))
        logger.info(f"Подписка на канал: {channel}")

        # Получаем ответ подписки
        response = await websocket.recv()
        subscribe_response = json.loads(response)
        logger.info(f"Ответ подписки: {response[:200]}...")

        # Проверяем успешность подписки
        if 'error' in subscribe_response:
            logger.error(f"Ошибка подписки: {subscribe_response['error']}")
            return

        logger.info("Слушаем донаты... (Ctrl+C для остановки)\n")

        # Слушаем события
        while True:
            try:
                message = await websocket.recv()
                data = json.loads(message)
                logger.debug(f"WS сообщение: {message[:300]}")

                # Centrifugo push-формат (без id — это серверное событие)
                if 'result' in data:
                    result = data['result']

                    # Формат: {"result": {"channel": "...", "data": {"data": {...}}}}
                    if 'channel' in result and 'data' in result:
                        pub_data = result['data'].get('data')
                        if pub_data:
                            logger.info(f"\n{'='*60}")
                            logger.info("НОВЫЙ ДОНАТ!")
                            logger.info(f"{'='*60}")
                            await process_donation(pub_data)
                            continue

                    # Формат: {"result": {"type": 0/1, "data": ...}}
                    if 'type' in result:
                        msg_type = result['type']
                        if msg_type == 'publication' or msg_type == 1:
                            channel_data = result.get('data', {})
                            pub_data = channel_data.get('data')
                            if pub_data:
                                logger.info(f"\n{'='*60}")
                                logger.info("НОВЫЙ ДОНАТ!")
                                logger.info(f"{'='*60}")
                                await process_donation(pub_data)
                                continue

                # Пустые пинги от Centrifugo
                if data == {} or data == '':
                    continue

                logger.debug(f"Необработанное сообщение: {message[:200]}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket соединение закрыто. Переподключение...")
                break
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)


async def main():
    """Главная функция listener"""
    if not config.DA_ACCESS_TOKEN:
        logger.error("❌ config.DA_ACCESS_TOKEN не настроен в config.py")
        logger.error("Запустите сначала: python da_oauth.py")
        return

    while True:
        try:
            await listen_donations()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                logger.warning("DA токен протух (401), пробуем обновить...")
                try:
                    from da_oauth import refresh_access_token
                    refresh_access_token()
                    logger.info("DA токен успешно обновлён, переподключение...")
                except Exception as refresh_err:
                    logger.error(f"Не удалось обновить DA токен: {refresh_err}")
            else:
                logger.error(f"❌ HTTP ошибка: {e}", exc_info=True)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}", exc_info=True)
            logger.info("Переподключение через 5 секунд...")
            await asyncio.sleep(5)


if __name__ == '__main__':
    """
    Запуск listener для прослушивания донатов.

    Usage:
        python donationalerts_listener.py
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Остановка listener...")
