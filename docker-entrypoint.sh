#!/bin/bash
# Точка входа: запускает бота и DA-listener в одном контейнере.
# Listener работает в фоне; при завершении бота контейнер останавливается.

set -e

echo "[entrypoint] Запуск DonationAlerts polling listener..."
python da_polling.py &
LISTENER_PID=$!

echo "[entrypoint] Запуск Telegram бота..."
python main.py

# Если бот завершился — останавливаем listener
kill "$LISTENER_PID" 2>/dev/null || true
