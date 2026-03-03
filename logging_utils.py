import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

import config


LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
MANAGED_HANDLER_ATTR = '_analysman_managed'


class TelegramLogHandler(logging.Handler):
    """Шлёт ERROR/CRITICAL в Telegram с защитой от спама."""

    def __init__(
        self,
        token=None,
        chat_id=None,
        min_interval_seconds=60,
        timeout=5,
    ):
        super().__init__(level=logging.ERROR)
        self.token = token if token is not None else config.TOKEN
        self.chat_id = chat_id if chat_id is not None else config.ALERT_CHAT_ID
        self.min_interval_seconds = max(0, int(min_interval_seconds))
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last_sent_at = 0.0

    def emit(self, record):
        if record.levelno < logging.ERROR or not self.token or not self.chat_id:
            return

        message = self._build_message(record)

        try:
            with self._lock:
                now = time.monotonic()
                if now - self._last_sent_at < self.min_interval_seconds:
                    return

                response = requests.post(
                    f'https://api.telegram.org/bot{self.token}/sendMessage',
                    json={
                        'chat_id': self.chat_id,
                        'text': message,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                self._last_sent_at = now
        except Exception:
            self.handleError(record)

    @staticmethod
    def _build_message(record):
        module_name = record.module or record.name
        message = record.getMessage().replace('\n', ' ').strip()[:500]
        return f'⚠️ [{record.levelname}] {module_name}: {message}'


def _mark_handler(handler):
    setattr(handler, MANAGED_HANDLER_ATTR, True)
    return handler


def setup_logging(name, level=logging.INFO, log_dir=None, token=None, alert_chat_id=None):
    """Настраивает консольный, файловый и Telegram handler для root logger."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        if getattr(handler, MANAGED_HANDLER_ATTR, False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    formatter = logging.Formatter(LOG_FORMAT)
    logs_dir = Path(log_dir) if log_dir is not None else config.BASE_DIR / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)

    console_handler = _mark_handler(logging.StreamHandler())
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = _mark_handler(
        RotatingFileHandler(
            logs_dir / f'{name}.log',
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        )
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    telegram_handler = _mark_handler(
        TelegramLogHandler(token=token, chat_id=alert_chat_id)
    )
    telegram_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(telegram_handler)
    return root_logger
