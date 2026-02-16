# ROADMAP — analysMAN (actionable, sprint-ready)

## Концепция (one-liner)
Короткие, факт-ориентированные аналитические обзоры спортивных матчей в Telegram — продаём качественный, прозрачный и быстрый контент, который генерируется на основе проверённых данных и аккуратно форматируется для мобильного чтения.

---

## Цели и метрики (OKR)
**Objective:** Выпустить рабочий MVP и проверить конверсию в оплату за анализы.

**Key Results:**
- KR1: 95% генераций укладываются в целевой диапазон 1200–1800 символов.
- KR2: 80% пользователей, просмотревших доступные матчи, нажимают «купить».
- KR3: Стоимость получения одного оплаченного анализа ≤ $0.5.
- KR4: Стабильность: error rate генерации < 2% за 7 дней.

---

## Целевая аудитория
- Пользователи Telegram, интересующиеся аналитикой (18–45 лет).
- География: СНГ/Россия — русскоязычная выдача.

---

## Выполненные спринты

### Sprint 0 — Setup & Baseline (DONE)
- Ревью кода, внедрение `ANALYSIS_PROMPT.md`, настройка CI (pytest, flake8).

### Sprint 1 — Stable Generation & Postprocessing (DONE)
- `clean_and_truncate()`, контроль эмодзи, banned words, `split_for_telegram()`.

### Sprint 2 — Payment Flow & Caching (DONE)
- Idempotency purchase state, кэширование анализа.

### Sprint 2.5 — API Integration & Manual Sync (DONE)
- `sync_matches.py`: top3/all режимы, 3 лиги + 2 кубка, rate limiter.

### Sprint 2.7 — H2H & Standings Enrichment (DONE)
- On-demand fetching H2H/standings/form через `match_data_fetcher.py`.

### Sprint 3 — Premium TheSportsDB + APScheduler (DONE)
- Миграция на Premium TheSportsDB API ($9/мес, 100 req/min).
- APScheduler: автосинхронизация матчей при старте + периодически.
- Упрощённая БД (убраны h2h_json, standings_json, raw_json).
- On-demand fetching при покупке (не кэшируется в БД).
- PNG-таблица анализа (analysis_formatter.py + image_renderer.py).

### Sprint 4 — DonationAlerts Payment Integration (IN PROGRESS)
- Миграция БД: поля token, status, amount, expires_at, donation_event_id в purchases.
- Упрощение UI: покупка без баланса, инструкция с кодом оплаты.
- OAuth авторизация (da_oauth.py) со скоупами: oauth-donation-subscribe, oauth-donation-index, oauth-user-show.
- Два варианта получения донатов:
  - WebSocket listener (donationalerts_listener.py) — real-time через Centrifugo.
  - Polling listener (da_polling.py) — опрос API каждые 15 сек.
- Webhook сервер (webhook_server.py) — генерация и отправка анализа.
- Админ команда /clean_purchases (pending/expired/all).

---

## Текущий спринт

### Sprint 5 — QA & Launch Prep
**Цели:**
- End-to-end тестирование DA payment flow с реальными донатами.
- Мониторинг стоимости генерации анализов.
- Финальная документация, настройка продакшен окружения.
- Автообновление OAuth токенов (refresh_token flow).

**Acceptance:** Реальный донат → автоматическая генерация → доставка анализа в Telegram.

---

## Backlog / Nice-to-have (после MVP)
- Telegram Stars как альтернативный платёжный метод.
- Subscription model, bulk purchases.
- Few-shot templates per sport.
- Multilanguage support.
- Статистика игроков (требует платного API).

---
