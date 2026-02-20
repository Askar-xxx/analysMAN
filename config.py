# Конфигурация бота — читается из переменных окружения.
# Для локальной разработки создай файл .env (см. .env.example).
# Для Docker — переменные передаются через docker-compose.yml / env_file.

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / '.env'


def _load_env_fallback(path: Path):
    """Простой загрузчик .env без внешних зависимостей."""
    if not path.exists():
        return

    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Не перезаписываем уже заданные переменные окружения.
        os.environ.setdefault(key, value)


try:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=False)
except ImportError:
    _load_env_fallback(ENV_PATH)

# === Telegram ===
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')

# === AI (DeepSeek) ===
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

# === TheSportsDB Premium API ===
THESPORTSDB_KEY = os.environ.get('THESPORTSDB_KEY', '')

# === DonationAlerts OAuth ===
DA_CLIENT_ID = os.environ.get('DA_CLIENT_ID', '')
DA_CLIENT_SECRET = os.environ.get('DA_CLIENT_SECRET', '')
DA_REDIRECT_URI = os.environ.get('DA_REDIRECT_URI', 'http://localhost:8080/callback')

# === DonationAlerts токены (обновляются через da_oauth.py → .env) ===
DA_ACCESS_TOKEN = os.environ.get('DA_ACCESS_TOKEN', '')
DA_REFRESH_TOKEN = os.environ.get('DA_REFRESH_TOKEN', '')

# === DonationAlerts настройки ===
DA_PROFILE_URL = os.environ.get('DA_PROFILE_URL', '')

# === Бизнес-параметры ===
ANALYSIS_PRICE_RUB = float(os.environ.get('ANALYSIS_PRICE_RUB', '150'))

# === Администратор ===
MAIN_ADMIN_ID = int(os.environ.get('MAIN_ADMIN_ID', '0'))
SUPPORT_USERNAME = os.environ.get('SUPPORT_USERNAME', '')
