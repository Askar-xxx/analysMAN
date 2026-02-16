# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Инструкции по работе с Claude

### Язык общения
- Всегда отвечай на русском языке
- Используй русский в комментариях к коду
- Объяснения и документация тоже на русском

### Честность и точность
- Если ты не знаешь ответ или не уверен - скажи "Я не знаю"
- НИКОГДА не выдумывай информацию
- Не строй догадки, если нет достоверных данных
- Лучше признать незнание, чем дать ложную информацию
- Если есть несколько вариантов решения - предложи варианты, не выбирай наугад
- При неуверенности используй фразы: "возможно", "вероятно", "не уверен"

## Project Overview

Telegram бот для продажи анализов спортивных матчей (футбол). Пользователи выбирают матчи, оплачивают через DonationAlerts и получают AI-генерированный анализ. Built with `python-telegram-bot` v22.6 (async) и SQLite.

**Концепция продукта:**
- Анализы генерируются нейросетью (DeepSeek API через OpenAI-совместимый клиент)
- Анализы НЕ содержат предсказания результата и коэффициенты букмекеров (только обзор команд, статистика, тренды)
- Оплата через DonationAlerts (донат с кодом покупки в комментарии)
- Купленные анализы доступны в разделе "Мои анализы" и хранятся 1 день после завершения матча

**Архитектура:**
- **On-demand data fetching** — H2H/standings/form запрашиваются при покупке, не хранятся в БД
- **Premium TheSportsDB API** ($9/мес) — полная таблица standings, 100 req/min
- **Упрощённая БД** — без полей кэширования
- **APScheduler** — автоматическая синхронизация матчей при старте + периодически
- **DonationAlerts** — оплата через донаты (WebSocket listener или polling API)

**Текущее состояние:**
- Базовый UI (главное меню, навигация по видам спорта, датам, матчам)
- БД SQLite (таблицы: users, matches, purchases, admins, teams, sync_meta)
- AI генерация + PNG таблица анализа
- DonationAlerts интеграция (OAuth + WebSocket/Polling listener)
- Синхронизация матчей: 3 лиги + 2 кубка, окно 3 дня
- Unit-тесты (pytest) и CI (GitHub Actions)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (includes APScheduler auto-sync)
python main.py

# DonationAlerts OAuth (перевыпуск токенов)
python da_oauth.py

# DonationAlerts listener (запускать отдельно от бота, в другом терминале)
python donationalerts_listener.py   # WebSocket (real-time)
python da_polling.py                # Polling (каждые 15 сек)

# Webhook сервер (для тестирования через curl)
python webhook_server.py

# DB migration for DonationAlerts (one-time)
python migrate_db_da.py

# Run tests
python -m pytest tests/ -v

# Lint
python -m flake8 . --max-line-length=120 --exclude=.git,__pycache__,.venv,venv

# Admin utilities
python add_balance_manually.py    # Добавить баланс пользователю
python add_test_match.py          # Добавить тестовый матч
python check_matches.py           # Просмотр матчей в БД

# Admin commands (в боте)
/stats                # Статистика БД (матчи, покупки, PNG кэш)
/clean_matches        # Очистка старых матчей и PNG (безопасно)
/clean_all_matches    # ПОЛНАЯ очистка ВСЕХ матчей и PNG (опасно!)

# Sync matches from TheSportsDB Premium API
python sync_matches.py                       # Default: top-3 matches, 3 days ahead
python sync_matches.py --mode all            # Bulk: all matches
python sync_matches.py --dry-run             # Preview without saving
```

## Architecture

**Entry point:** `main.py` — создаёт Application, инициализирует БД, настраивает APScheduler для периодической синхронизации, регистрирует handlers через `setup_user_handlers()`, запускает polling.

**Core modules:**

- `ai_generator.py` — Генерация анализов через DeepSeek API. Промпт из `ANALYSIS_PROMPT.md`. `generate_match_analysis_with_context()` — основная функция генерации с enriched_context.
- `match_data_fetcher.py` — On-demand fetching H2H/standings/form из TheSportsDB Premium API. `MatchDataFetcher` + `build_enriched_context()`.
- `sync_matches.py` — Синхронизация матчей из TheSportsDB Premium API. Два режима: top3 (default) и all (bulk). 3 лиги + 2 кубка. Rate limiter 100 req/min.
- `database.py` — SQLite data layer. Tables: matches, users, purchases, admins, teams, sync_meta. Purchases расширена полями для DA (token, status, amount, expires_at, donation_event_id).
- `user_handlers.py` — Telegram callback handlers. Purchase flow: создание pending purchase с token → инструкция пользователю → ожидание доната.
- `admin_commands.py` — Админские команды: `/stats`, `/clean_matches`, `/clean_all_matches`. Автоматическое удаление PNG файлов при очистке данных.
- `keyboards.py` — InlineKeyboardMarkup builders.
- `utils.py` — `safe_edit_message()`, `clean_and_truncate()`, `split_for_telegram()`.
- `analysis_formatter.py` — Подготовка данных для PNG-таблицы анализа.
- `image_renderer.py` — Рендеринг PNG-таблицы анализа.
- `config.py` — Все секреты (TOKEN, API keys, DA credentials). Gitignored.
- `ANALYSIS_PROMPT.md` — Промпт для AI генерации.

**DonationAlerts integration:**

- `da_oauth.py` — OAuth авторизация. Скоупы: oauth-donation-subscribe, oauth-donation-index, oauth-user-show. Локальный Flask на :8080 для callback. Сохраняет токены в config.py.
- `donationalerts_listener.py` — WebSocket listener через Centrifugo. Подключение: (1) get socket_connection_token, (2) WS connect, (3) API centrifuge/subscribe для токена канала, (4) WS subscribe с токеном. Real-time получение донатов.
- `da_polling.py` — Polling listener. Опрашивает `GET /api/v1/alerts/donations` каждые 15 сек. Требует скоуп oauth-donation-index.
- `webhook_server.py` — Flask сервер (:5000). `generate_and_send_analysis()` — генерация и отправка анализа через Telegram Bot API. Используется как модуль из listener'ов.
- `migrate_db_da.py` — Миграция БД: добавляет поля token, status, amount, expires_at, donation_event_id в purchases.

**Payment flow:**
1. Пользователь нажимает "Купить анализ" → создаётся pending purchase с 12-символьным token
2. Бот показывает инструкцию: перейти на DA страницу, отправить донат с кодом в комментарии
3. Listener (WebSocket или polling) получает донат → извлекает token из сообщения → находит pending purchase → проверяет сумму
4. При совпадении: status → paid → генерация анализа (on-demand fetch + AI) → отправка PNG в Telegram

**Tests:**
- `tests/test_utils.py` — тесты clean_and_truncate и split_for_telegram
- `tests/test_ai_generator.py` — тесты постобработки, промпта
- `tests/test_match_data_fetcher.py` — unit-тесты MatchDataFetcher
- `tests/test_sync_matches.py` — интеграционные тесты синхронизации

**CI:** `.github/workflows/ci.yml` — GitHub Actions: flake8 + pytest на ubuntu-latest, Python 3.11.

**Callback data routing:** `user_handlers.py:button_handler` — единый `CallbackQueryHandler`. Dispatches по префиксам: `sport_`, `choose_date_`, `match_`, `buy_`, `purchased_sport_`, `purchased_date_`, `deposit_`.

**Navigation:** Menu history — стек в `context.user_data['menu_history']`. `go_back()` — pop + re-render. `back_to_menu` — clear + main menu.

## Key Conventions

- All user-facing text is in Russian
- Messages use HTML parse mode by default
- Sports identified by string keys: `football`, `basketball`, `hockey`
- Match price: 2 RUB (тестовая), target 150 RUB
- Dates: `%Y-%m-%d` format
- SQLite database (`sports_bot.db`) is gitignored
- `config.py` is gitignored (contains secrets)
- Анализы: целевая длина 1400–1900 символов, soft cap 2200, hard cap 3800
- Запрещённые слова: коэффициент, ставка, прогноз (и их формы)

## Important Notes for Development

- **DonationAlerts OAuth:** Скоупы `oauth-donation-subscribe` (WebSocket), `oauth-donation-index` (polling API), `oauth-user-show` (user info). Перевыпуск: `python da_oauth.py`.
- **WebSocket подписка:** Обязательно вызвать `POST /api/v1/centrifuge/subscribe` с client_id для получения токена канала перед подпиской через WebSocket. Без этого шага — 403.
- **Listener запускается отдельно** от бота в другом терминале.
- **Промпт анализа:** `ANALYSIS_PROMPT.md`. Изменения подхватываются при следующей генерации.
- **Постобработка:** `clean_and_truncate()` обязательна после генерации.
- **On-demand fetching:** `match_data_fetcher.py` запрашивает данные при покупке. Если падает — генерация продолжается с пустым контекстом.
- **APScheduler:** Автосинхронизация матчей при старте бота + периодически. Также автоматическая очистка старых матчей и покупок.
- **PNG кэширование:** Анализы сохраняются в `analysis_cache/analysis_{match_id}.png`. При повторном просмотре — отправка готового PNG без API запросов. Автоудаление PNG при очистке старых матчей.
- **Админские команды:** `/stats` (статистика БД), `/clean_matches` (безопасная очистка старых данных), `/clean_all_matches` (ПОЛНАЯ очистка). Автоматическое удаление PNG файлов.
- **Payment handlers временно отключены** — логика баланса/пополнения закомментирована (MVP с DA вместо баланса).
