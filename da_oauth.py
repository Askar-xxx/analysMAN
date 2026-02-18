# -*- coding: utf-8 -*-
"""
OAuth авторизация для DonationAlerts API.

Получает access_token и refresh_token для доступа к API.
"""
import os
import requests
from flask import Flask, request
import webbrowser
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Глобальные переменные для хранения токенов
tokens = {}


@app.route('/callback')
def oauth_callback():
    """Callback endpoint для OAuth авторизации"""
    code = request.args.get('code')
    if not code:
        return "❌ Ошибка: код авторизации не получен", 400

    logger.info(f"Получен authorization code: {code[:10]}...")

    # Обмен кода на токены
    from config import DA_CLIENT_ID, DA_CLIENT_SECRET, DA_REDIRECT_URI

    token_url = "https://www.donationalerts.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": DA_CLIENT_ID,
        "client_secret": DA_CLIENT_SECRET,
        "redirect_uri": DA_REDIRECT_URI,
        "code": code
    }

    try:
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        token_data = response.json()

        tokens['access_token'] = token_data['access_token']
        tokens['refresh_token'] = token_data['refresh_token']
        tokens['expires_in'] = token_data['expires_in']

        logger.info("✅ Токены успешно получены")
        logger.info(f"Access token: {tokens['access_token'][:20]}...")
        logger.info(f"Refresh token: {tokens['refresh_token'][:20]}...")

        return """
        <html>
            <body style="font-family: Arial; padding: 50px; text-align: center;">
                <h1 style="color: green;">✅ Авторизация успешна!</h1>
                <p>Access token получен. Можете закрыть это окно.</p>
                <p style="color: gray; font-size: 12px;">Вернитесь в терминал.</p>
            </body>
        </html>
        """
    except Exception as e:
        logger.error(f"Ошибка получения токенов: {e}")
        return f"❌ Ошибка: {str(e)}", 500


def start_oauth_flow():
    """
    Запускает OAuth flow для получения токенов.

    Returns:
        dict: {'access_token': '...', 'refresh_token': '...', 'expires_in': 3600}
    """
    from config import DA_CLIENT_ID, DA_REDIRECT_URI

    if not DA_CLIENT_ID:
        raise ValueError("DA_CLIENT_ID не настроен в config.py")

    # URL для авторизации
    auth_url = (
        "https://www.donationalerts.com/oauth/authorize"
        f"?client_id={DA_CLIENT_ID}"
        f"&redirect_uri={DA_REDIRECT_URI}"
        "&response_type=code"
        "&scope=oauth-donation-subscribe oauth-donation-index oauth-user-show"
    )

    logger.info("="*60)
    logger.info("OAUTH АВТОРИЗАЦИЯ DONATIONALERTS")
    logger.info("="*60)
    logger.info("\n1. Запускаю локальный сервер на http://localhost:8080")
    logger.info("2. Открываю браузер для авторизации...")
    logger.info("3. После авторизации вернётесь сюда\n")

    # Запускаем Flask сервер в отдельном потоке
    server_thread = threading.Thread(
        target=lambda: app.run(host='localhost', port=8080, debug=False, use_reloader=False)
    )
    server_thread.daemon = True
    server_thread.start()

    # Открываем браузер
    webbrowser.open(auth_url)

    # Ждём получения токенов
    logger.info("Ожидание авторизации...")
    import time
    timeout = 120  # 2 минуты
    elapsed = 0
    while not tokens and elapsed < timeout:
        time.sleep(1)
        elapsed += 1

    if not tokens:
        raise TimeoutError("Timeout: авторизация не завершена за 2 минуты")

    logger.info("\n" + "="*60)
    logger.info("✅ АВТОРИЗАЦИЯ ЗАВЕРШЕНА")
    logger.info("="*60)
    logger.info(f"Access token: {tokens['access_token'][:30]}...")
    logger.info(f"Refresh token: {tokens['refresh_token'][:30]}...")
    logger.info(f"Expires in: {tokens['expires_in']} секунд")
    logger.info("="*60 + "\n")

    return tokens


def save_tokens_to_env(tokens):
    """
    Сохраняет токены в файл .env.

    Если .env не существует — создаёт его.
    Если строки DA_ACCESS_TOKEN / DA_REFRESH_TOKEN уже есть — обновляет их.

    Args:
        tokens: dict с ключами access_token, refresh_token
    """
    import re

    env_path = '.env'

    # Читаем текущее содержимое .env (или создаём пустой файл)
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = ''

    # Обновляем или добавляем DA_ACCESS_TOKEN
    if re.search(r'^DA_ACCESS_TOKEN=', content, re.MULTILINE):
        content = re.sub(
            r'^DA_ACCESS_TOKEN=.*',
            f'DA_ACCESS_TOKEN={tokens["access_token"]}',
            content,
            flags=re.MULTILINE
        )
    else:
        content += f'\nDA_ACCESS_TOKEN={tokens["access_token"]}'

    # Обновляем или добавляем DA_REFRESH_TOKEN
    if re.search(r'^DA_REFRESH_TOKEN=', content, re.MULTILINE):
        content = re.sub(
            r'^DA_REFRESH_TOKEN=.*',
            f'DA_REFRESH_TOKEN={tokens["refresh_token"]}',
            content,
            flags=re.MULTILINE
        )
    else:
        content += f'\nDA_REFRESH_TOKEN={tokens["refresh_token"]}'

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + '\n')

    logger.info(f"✅ Токены сохранены в {env_path}")


if __name__ == '__main__':
    """
    Запуск OAuth авторизации вручную.

    Usage:
        python da_oauth.py
    """
    try:
        tokens_data = start_oauth_flow()
        save_tokens_to_env(tokens_data)
        print("\n✅ Готово! Токены сохранены в .env")
        print("Теперь можно запустить: python da_polling.py")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
