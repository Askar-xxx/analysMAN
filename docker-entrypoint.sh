#!/bin/bash
# Точка входа: запускает бота и DA-listener в одном контейнере.
# Listener работает в фоне; при завершении бота контейнер останавливается.

set -e

run_da_polling_loop() {
    local child_pid=""

    trap 'if [ -n "$child_pid" ]; then kill "$child_pid" 2>/dev/null || true; wait "$child_pid" 2>/dev/null || true; fi; exit 0' TERM INT

    while true; do
        python da_polling.py &
        child_pid=$!

        if wait "$child_pid"; then
            echo "[entrypoint] da_polling.py завершился, перезапуск через 5 сек..."
        else
            exit_code=$?
            echo "[entrypoint] da_polling.py завершился с кодом ${exit_code}, перезапуск через 5 сек..."
        fi

        child_pid=""
        sleep 5
    done
}

echo "[entrypoint] Запуск DonationAlerts polling listener..."
run_da_polling_loop &
LISTENER_PID=$!

trap 'kill "$LISTENER_PID" 2>/dev/null || true; wait "$LISTENER_PID" 2>/dev/null || true' EXIT

echo "[entrypoint] Запуск Telegram бота..."
python main.py

# Если бот завершился — останавливаем listener
