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

**Текущее состояние разработки:**
- ✅ Базовый UI (главное меню, навигация по видам спорта, датам, матчам)
- ✅ База данных SQLite (таблицы: users, matches, purchases, admins, teams, sync_meta)
- ✅ Система балансов и пополнения (ручной приём платежей)
- ✅ Возможность добавлять матчи вручную через скрипт `add_test_match.py`
- ✅ AI API интеграция: модуль `ai_generator.py` (DeepSeek API), промпт загружается из `ANALYSIS_PROMPT.md`
- ✅ Постобработка анализов: `clean_and_truncate()` — фильтрация запрещённых слов, лимит эмодзи, контроль длины
- ✅ Разбиение длинных текстов: `split_for_telegram()` — безопасное разбиение по границам абзацев/предложений
- ✅ Unit-тесты (pytest) и CI (GitHub Actions) — 46 тестов
- ✅ Синхронизация матчей через TheSportsDB API: `sync_matches.py` (top3 default / bulk via --mode all)
- ✅ Tracing: raw_json, source, home_team_id, away_team_id, match_datetime для каждого матча
- ✅ Token bucket rate limiter (25 req/min) + exponential backoff на HTTP 429
- ✅ Таблица teams с кэшем lookupteam (TTL 24h)
- ✅ Интеграционные тесты sync (top3, idempotence, tracing, enrichment)
- ✅ H2H обогащение: история личных встреч (2-7 матчей с датами и счетами)
- ✅ Standings обогащение: турнирная таблица (позиция, очки, форма WWDWL, разница мячей)
- ✅ TTL-кэширование H2H/standings (24h), флаг `--enrich`
- ✅ Standings интегрированы в обзоры команд (секции 2-3 анализа)
- ❌ НЕ реализовано: реальная выдача анализа пользователю после покупки (purchase flow)

**Выполненные спринты (см. ROADMAP.md):**
- ✅ Sprint 0 — Setup & Baseline
- ✅ Sprint 1 — Stable Generation & Postprocessing
- ✅ Sprint 2 — Payment Flow (базовая часть)
- ✅ Sprint 2.5 — API Integration & Manual Sync
- ✅ Sprint 2.7 — H2H & Standings Enrichment

**Следующие этапы (см. ROADMAP.md):**
1. Sprint 3: Source Automation — APScheduler job, автоматический периодический sync + enrich
2. Sprint 4: Purchase Flow & Analysis Delivery — полный flow покупки с генерацией и выдачей
3. Stabilise & Launch Prep — end-to-end QA, документация, cost-per-analysis

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
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

# Sync matches from TheSportsDB API
python sync_matches.py                       # Default: top-3 matches
python sync_matches.py --mode all            # Bulk: all matches from 5 leagues + cups
python sync_matches.py --mode all --enrich   # Bulk + H2H + standings (recommended)
python sync_matches.py --mode top3 --limit 5 # Top-5 matches
python sync_matches.py --enrich              # Top-3 + enrich with H2H/standings
python sync_matches.py --dry-run             # Preview without saving to DB
```

## Architecture

**Entry point:** `main.py` — creates the `Application`, initializes the DB, registers handlers via `setup_user_handlers()` and `setup_payment_handlers()`, then starts polling.

**Core modules:**

- `ai_generator.py` — Генерация анализов через DeepSeek API (OpenAI-совместимый клиент). Промпт загружается из `ANALYSIS_PROMPT.md` при импорте. Форматтеры: `_format_h2h()`, `_format_standings()`, `_extract_team_standings()` — интегрируют реальные данные в контекст для AI. Standings данные подставляются прямо к названиям команд в контексте (например: "Chelsea (#5 место, 43 очка, форма WWWWL)"). Результат проходит через `clean_and_truncate()` для постобработки.
- `sync_matches.py` — Синхронизация матчей из TheSportsDB API (ключ "3" — test/dev key). Два режима: `--mode top3` (default) и `--mode all` (bulk import). Token bucket rate limiter (25 req/min), exponential backoff на 429. Флаг `--enrich` добавляет H2H и standings к матчам с TTL-кэшированием (24h). Функция `clean_team_name_for_h2h()` убирает суффиксы (United, City, FC и др.) для корректного поиска H2H.
- `database.py` — SQLite data layer. All DB functions open/close their own connections (`sports_bot.db`). Tables: `matches`, `users`, `purchases`, `admins`, `teams`, `sync_meta`. Поля обогащения в `matches`: `h2h_json`, `h2h_fetched_at`, `standings_json`, `standings_fetched_at`. Note: `init_db()` is called both at module import time and explicitly in `main.py`.
- `user_handlers.py` — Main callback query handler (`button_handler`) that routes all inline button presses via `callback_data` string patterns. Manages menu navigation history via `context.user_data['menu_history']` with constants like `MENU_MAIN`, `MENU_SPORT_SELECTION`, etc.
- `payment_handlers.py` — Deposit flow handlers. Uses a `ConversationHandler` for custom deposit amounts. Deposit tiers have bonus amounts (e.g., 300 RUB deposit gives +150 bonus). Payment is manual (bank transfer) — no payment gateway integration.
- `keyboards.py` — All `InlineKeyboardMarkup` builders. Returns keyboard layouts for menus, sport selection, date selection, match lists, deposit options, and purchased analyses navigation.
- `utils.py` — Утилиты: `safe_edit_message()` (безопасное редактирование с защитой от превышения лимита), `send_main_menu()`, `format_match_info()`, `clean_and_truncate()` (постобработка анализов: banned words, emoji limit, truncation), `split_for_telegram()` (разбиение длинных текстов на части ≤3800).
- `config.py` — Stores the bot `TOKEN` and `DEEPSEEK_API_KEY`. Listed in `.gitignore` but was committed — treat as a secret file.
- `ANALYSIS_PROMPT.md` — Источник истины для промпта генерации анализов. Изменяется без правки кода.

**Tests (46 тестов):**
- `tests/test_utils.py` — тесты `clean_and_truncate` и `split_for_telegram`
- `tests/test_ai_generator.py` — тесты постобработки, промпта, `_format_h2h()`, `_format_standings()`
- `tests/test_sync_matches.py` — интеграционные тесты: top3, idempotence, tracing, bulk mode, enrichment (H2H + standings)

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
- API ключ TheSportsDB: `"3"` (test/dev key, полные данные); НЕ использовать `"123"` (ограничен 2 результата)

## Important Notes for Development

- **Промпт анализа:** Хранится в `ANALYSIS_PROMPT.md`. Для изменения промпта — редактировать файл, перезапуск бота подхватит изменения.
- **Постобработка:** `clean_and_truncate()` в `utils.py` — обязательна после каждой генерации. Фильтрует запрещённые слова, контролирует эмодзи и длину.
- **Спортивный API:** `sync_matches.py --mode all --enrich` — основной способ наполнения БД матчами. Для продакшена нужна автоматизация (Sprint 3).
- **H2H обогащение:** `--enrich` добавляет H2H и standings. Standings доступны только для топ-5 команд лиги (ограничение бесплатного API). H2H работает для всех команд (2-7 матчей).
- **Purchase flow:** При покупке матча генерация и выдача анализа ещё не реализованы (Sprint 4).
- **Известные проблемы:** `database.py` — дублирование `add_match`/`create_match`, `init_db()` при импорте, bare except в `add_admin`, нет транзакций в `purchase_analysis`.
- **Ограничения API:** TheSportsDB бесплатный tier: `lookuptable` = топ-5, нет статистики игроков. Рассматривается гибридный подход с API-Football (см. ROADMAP.md backlog).
