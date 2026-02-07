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
- ✅ База данных SQLite (таблицы: users, matches, purchases, admins)
- ✅ Система балансов и пополнения (ручной приём платежей)
- ✅ Возможность добавлять матчи вручную через скрипт `add_test_match.py`
- ✅ AI API интеграция: модуль `ai_generator.py` (DeepSeek API), промпт загружается из `ANALYSIS_PROMPT.md`
- ✅ Постобработка анализов: `clean_and_truncate()` — фильтрация запрещённых слов, лимит эмодзи, контроль длины
- ✅ Разбиение длинных текстов: `split_for_telegram()` — безопасное разбиение по границам абзацев/предложений
- ✅ Unit-тесты (pytest) и CI (GitHub Actions)
- ❌ НЕ реализовано: автоматическое обновление матчей через спортивный API
- ❌ НЕ реализовано: реальная выдача анализа пользователю после покупки (purchase flow)

**Выполненные спринты (см. ROADMAP.md):**
- ✅ Sprint 0 — Setup & Baseline: ревью кода, `ANALYSIS_PROMPT.md` как источник промпта, CI (pytest + flake8)
- ✅ Sprint 1 — Stable Generation & Postprocessing: `clean_and_truncate()`, контроль эмодзи, banned words, `split_for_telegram()`, тесты, логирование метрик

**Следующие этапы (см. ROADMAP.md):**
1. Sprint 2: Payment Flow Robustness & Caching — idempotency (purchase_state), кэширование анализов, интеграционные тесты покупки
2. Sprint 3: Source Automation — автоматический импорт матчей через спортивный API, `sync_matches.py`
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
```

## Architecture

**Entry point:** `main.py` — creates the `Application`, initializes the DB, registers handlers via `setup_user_handlers()` and `setup_payment_handlers()`, then starts polling.

**Core modules:**

- `ai_generator.py` — Генерация анализов через DeepSeek API (OpenAI-совместимый клиент). Промпт загружается из `ANALYSIS_PROMPT.md` при импорте. Результат проходит через `clean_and_truncate()` для постобработки.
- `database.py` — SQLite data layer. All DB functions open/close their own connections (`sports_bot.db`). Tables: `matches`, `users`, `purchases`, `admins`. Note: `init_db()` is called both at module import time and explicitly in `main.py`.
- `user_handlers.py` — Main callback query handler (`button_handler`) that routes all inline button presses via `callback_data` string patterns. Manages menu navigation history via `context.user_data['menu_history']` with constants like `MENU_MAIN`, `MENU_SPORT_SELECTION`, etc.
- `payment_handlers.py` — Deposit flow handlers. Uses a `ConversationHandler` for custom deposit amounts. Deposit tiers have bonus amounts (e.g., 300 RUB deposit gives +150 bonus). Payment is manual (bank transfer) — no payment gateway integration.
- `keyboards.py` — All `InlineKeyboardMarkup` builders. Returns keyboard layouts for menus, sport selection, date selection, match lists, deposit options, and purchased analyses navigation.
- `utils.py` — Утилиты: `safe_edit_message()` (безопасное редактирование с защитой от превышения лимита), `send_main_menu()`, `format_match_info()`, `clean_and_truncate()` (постобработка анализов: banned words, emoji limit, truncation), `split_for_telegram()` (разбиение длинных текстов на части ≤3800).
- `config.py` — Stores the bot `TOKEN` and `DEEPSEEK_API_KEY`. Listed in `.gitignore` but was committed — treat as a secret file.
- `ANALYSIS_PROMPT.md` — Источник истины для промпта генерации анализов. Изменяется без правки кода.

**Tests:**
- `tests/test_utils.py` — тесты `clean_and_truncate` и `split_for_telegram`
- `tests/test_ai_generator.py` — тесты постобработки и наличия файла промпта

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
- Анализы: целевая длина 1200–1800 символов, soft cap 2000, hard cap 3800
- Запрещённые слова в анализах: коэффициент, ставка, прогноз (и их формы)
- Эмодзи в анализах: макс 1 на раздел, макс 4 всего

## Important Notes for Development

- **Промпт анализа:** Хранится в `ANALYSIS_PROMPT.md`. Для изменения промпта — редактировать файл, перезапуск бота подхватит изменения.
- **Постобработка:** `clean_and_truncate()` в `utils.py` — обязательна после каждой генерации. Фильтрует запрещённые слова, контролирует эмодзи и длину.
- **Спортивный API:** Матчи добавляются только вручную через скрипт. Для продакшена нужна автоматизация (Sprint 3).
- **Purchase flow:** При покупке матча генерация и выдача анализа ещё не реализованы (Sprint 2).
- **Известные проблемы:** `database.py` — дублирование `add_match`/`create_match`, `init_db()` при импорте, bare except в `add_admin`, нет транзакций в `purchase_analysis`.
