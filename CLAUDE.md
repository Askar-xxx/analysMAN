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

Telegram bot for selling sports match analyses (football, basketball, hockey). Users browse matches by sport/date, purchase analyses with an in-app balance, and view purchased analyses. Built with `python-telegram-bot` v22.6 (async) and SQLite.

**Концепция продукта:**
- Анализы генерируются нейросетью (DeepSeek API через OpenAI-совместимый клиент)
- Анализы НЕ содержат предсказания результата и коэффициенты букмекеров (только обзор команд, статистика, тренды)
- Новые пользователи получают стартовый баланс для первой покупки
- Купленные анализы доступны в разделе "Мои анализы" и хранятся 1 день после завершения матча

**Архитектура v2.0 (Premium TheSportsDB):**
- ✅ **On-demand data fetching** — H2H/standings/form запрашиваются при покупке, не хранятся в БД
- ✅ **Premium TheSportsDB API** ($9/мес) — полная таблица standings, 100 req/min, V2 API
- ✅ **Упрощённая БД** — убраны поля кэширования (h2h_json, standings_json, raw_json)
- ✅ **APScheduler** — автоматическая синхронизация матчей каждые 6 часов
- ✅ **Двухэтапный purchase flow** — (1) сбор данных → (2) генерация анализа

**Текущее состояние разработки:**
- ✅ Базовый UI (главное меню, навигация по видам спорта, датам, матчам)
- ✅ База данных SQLite (таблицы: users, matches, purchases, admins, teams, sync_meta)
- ✅ Система балансов и пополнения (ручной приём платежей)
- ✅ AI API интеграция: `ai_generator.py` (DeepSeek API), промпт из `ANALYSIS_PROMPT.md`
- ✅ Постобработка: `clean_and_truncate()` — фильтрация запрещённых слов, лимит эмодзи, контроль длины
- ✅ Разбиение длинных текстов: `split_for_telegram()` — безопасное разбиение по границам абзацев/предложений
- ✅ Unit-тесты (pytest) и CI (GitHub Actions) — 45 тестов
- ✅ Синхронизация: `sync_matches.py` — 3 лиги + 2 кубка, окно 3 дня, rate limiter 100 req/min
- ✅ Tracing: source, home_team_id, away_team_id, match_datetime для каждого матча
- ✅ On-demand fetcher: `match_data_fetcher.py` — получение H2H/standings/form при покупке
- ✅ Purchase flow: двухэтапный процесс с индикацией прогресса
- ✅ APScheduler: автосинхронизация матчей каждые 6 часов + при старте бота

**Выполненные спринты:**
- ✅ Sprint 0 — Setup & Baseline
- ✅ Sprint 1 — Stable Generation & Postprocessing
- ✅ Sprint 2 — Payment Flow
- ✅ Sprint 2.5 — API Integration & Manual Sync
- ✅ Sprint 2.7 — H2H & Standings Enrichment
- ✅ **Premium TheSportsDB Migration** — v2.0 архитектура с on-demand fetching

**Следующие этапы:**
1. End-to-end QA — полное тестирование purchase flow в продакшене
2. Cost monitoring — мониторинг стоимости генерации анализов
3. Launch prep — финальная документация, настройка продакшен окружения

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Database migration (one-time, if upgrading from v1)
python migrate_db_v2.py

# Run the bot (includes APScheduler auto-sync every 6h)
python main.py

# Run tests
pip install pytest flake8
python -m pytest tests/ -v

# Lint
python -m flake8 . --max-line-length=120 --exclude=.git,__pycache__,.venv,venv

# Admin utilities (run standalone)
python add_balance_manually.py    # Manually add balance to a user
python add_test_match.py          # Insert a test match for today
python check_matches.py           # Inspect all matches in the database

# Sync matches from TheSportsDB Premium API
python sync_matches.py                       # Default: top-3 matches, 3 days ahead
python sync_matches.py --mode all            # Bulk: all matches from 3 leagues + 2 cups
python sync_matches.py --mode top3 --limit 5 # Top-5 matches
python sync_matches.py --dry-run             # Preview without saving to DB
```

## Architecture

**Entry point:** `main.py` — creates the `Application`, initializes the DB, sets up APScheduler for periodic sync (every 6h + startup), registers handlers via `setup_user_handlers()` and `setup_payment_handlers()`, then starts polling.

**Core modules:**

- `ai_generator.py` — Генерация анализов через DeepSeek API. Промпт из `ANALYSIS_PROMPT.md`. Две функции генерации: (1) `generate_match_analysis()` — старая версия с чтением из БД, (2) `generate_match_analysis_with_context()` — новая версия с готовым enriched_context. Результат проходит через `clean_and_truncate()`.
- `match_data_fetcher.py` — **[NEW v2.0]** On-demand fetching H2H/standings/form из TheSportsDB Premium API. Класс `MatchDataFetcher`: методы `_fetch_h2h()`, `_fetch_standings()`, `_fetch_team_last_matches()`, `_fetch_event_details()`. Функция `build_enriched_context()` форматирует данные в текст для AI промпта.
- `sync_matches.py` — Синхронизация матчей из TheSportsDB Premium API. Два режима: `--mode top3` (default) и `--mode all` (bulk). 3 лиги (Premier League, La Liga, Bundesliga) + 2 кубка (CL, EL). Окно синхронизации 3 дня. Rate limiter 100 req/min (premium). НЕТ флага `--enrich` (on-demand вместо кэширования).
- `database.py` — SQLite data layer. Tables: `matches`, `users`, `purchases`, `admins`, `teams`, `sync_meta`. Упрощённая схема `matches` (убраны h2h_json, standings_json, raw_json). `init_db()` called in `main.py`.
- `main.py` — **[UPDATED v2.0]** Entry point с APScheduler. Функция `scheduled_sync_matches()` запускается каждые 6 часов + при старте бота. Scheduler управляется в `main()` с graceful shutdown.
- `user_handlers.py` — **[UPDATED v2.0]** Callback handler с обновлённым `handle_purchase()`: двухэтапный процесс (1) on-demand fetching через `MatchDataFetcher`, (2) генерация через `generate_match_analysis_with_context()`. Индикация прогресса "Этап 1/2" и "Этап 2/2".
- `payment_handlers.py` — Deposit flow с бонусами. Manual payment (bank transfer).
- `keyboards.py` — InlineKeyboardMarkup builders для всех меню.
- `utils.py` — `safe_edit_message()`, `clean_and_truncate()`, `split_for_telegram()`.
- `config.py` — `TOKEN`, `DEEPSEEK_API_KEY`, `THESPORTSDB_KEY` (premium). Treat as secret.
- `ANALYSIS_PROMPT.md` — Промпт для AI генерации.
- `migrate_db_v2.py` — **[NEW v2.0]** Скрипт миграции БД: удаляет h2h/standings/raw_json поля, создаёт бэкап.

**Tests (45 тестов):**
- `tests/test_utils.py` — тесты `clean_and_truncate` и `split_for_telegram`
- `tests/test_ai_generator.py` — тесты постобработки, промпта, `_build_match_context()`
- `tests/test_match_data_fetcher.py` — **[NEW v2.0]** unit-тесты MatchDataFetcher и build_enriched_context
- `tests/test_sync_matches.py` — интеграционные тесты: top3, idempotence, tracing, bulk mode

**CI:** `.github/workflows/ci.yml` — GitHub Actions: flake8 + pytest на ubuntu-latest, Python 3.11.

**Callback data routing pattern:** `user_handlers.py:button_handler` is the single `CallbackQueryHandler` that matches all callbacks. It dispatches based on string prefixes: `sport_`, `choose_date_`, `match_`, `buy_`, `purchased_sport_`, `purchased_date_`, `deposit_`.

**Navigation:** Menu history is a stack in `context.user_data['menu_history']`. The `go_back()` function pops from this stack and re-renders the previous menu. `back_to_menu` always clears history and returns to main menu.

## Key Conventions

- All user-facing text is in Russian
- Messages use HTML parse mode by default (`safe_edit_message` defaults to `parse_mode='HTML'`), but some handlers pass Markdown-formatted text — be aware of mixed parse mode usage
- Sports are identified by string keys: `football`, `basketball`, `hockey`
- Match prices default to 150 RUB
- Dates use `%Y-%m-%d` format throughout
- The SQLite database file (`sports_bot.db`) is gitignored
- Анализы: целевая длина 1400–1900 символов, soft cap 2200, hard cap 3800
- Анализы состоят из 5 секций: введение, обзор команды A (с формой/позицией если есть), обзор команды B, H2H, ключевые игроки
- Запрещённые слова в анализах: коэффициент, ставка, прогноз (и их формы)
- Эмодзи в анализах: макс 1 на раздел, макс 4 всего
- API ключ TheSportsDB: `"913569"` (premium $9/мес, полные данные, 100 req/min)

## Important Notes for Development

- **Промпт анализа:** Хранится в `ANALYSIS_PROMPT.md`. Для изменения — редактировать файл, перезапуск бота подхватит изменения.
- **Постобработка:** `clean_and_truncate()` в `utils.py` — обязательна после каждой генерации. Фильтрует запрещённые слова, контролирует эмодзи и длину.
- **On-demand fetching:** `match_data_fetcher.py` запрашивает H2H/standings/form при покупке. Не сохраняется в БД. Premium API даёт полную таблицу standings + до 10 H2H матчей.
- **APScheduler:** `main.py` автоматически синхронизирует матчи каждые 6 часов. Первая синхронизация при старте бота. Для разработки можно временно изменить интервал на 2 минуты.
- **Purchase flow:** Двухэтапный процесс с индикацией. Если on-demand fetching падает с ошибкой — генерация продолжается с пустым контекстом.
- **Premium API:** TheSportsDB key `913569` ($9/мес). 100 req/min, полная таблица standings, V2 API. 3 лиги + 2 кубка, окно 3 дня.
- **Миграция БД:** Для существующих БД — запустить `migrate_db_v2.py` один раз. Создаёт бэкап перед изменениями.
- **Известные проблемы:** `database.py` — дублирование `add_match`/`create_match`, `init_db()` при импорте, bare except в `add_admin`, нет транзакций в `purchase_analysis`.
