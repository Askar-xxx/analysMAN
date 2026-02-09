# ROADMAP — analysMAN (actionable, sprint-ready)

## Концепция (one‑liner)
Короткие, факт‑ориентированные аналитические обзоры спортивных матчей в Telegram — продаём качественный, прозрачный и быстрый контент, который генерируется на основе проверённых данных и аккуратно форматируется для мобильного чтения.

---

## Цели и метрики (OKR)
**Objective:** Выпустить рабочий MVP и проверить конверсию в оплату за анализы.

**Key Results:**
- KR1: 95% генераций укладываются в целевой диапазон 1200–1800 символов.
- KR2: 80% пользователей, просмотревших доступные матчи, нажимают «купить» (A/B тест на UI).
- KR3: Стоимость получения одного оплаченного анализа ≤ $0.5 (API + AI cost amortized).
- KR4: Стабильность: error rate генерации < 2% за 7 дней.

---

## Целевая аудитория
- Пользователи Telegram, интересующиеся аналитикой (18–45 лет), не ставят на ставках, хотят глубокий но краткий обзор.
- География: СНГ/Россия — русскоязычная выдача.

---

## Риски (топ‑3) и меры
1. **Стоимость API / AI** — кеширование анализов, batch‑fetch матчей, выбор дешёвых планов.
2. **LLM‑галлюцинации** — строгий prompt + post‑filtering + валидация входных данных.
3. **Юридический момент (скрейпинг / данные)** — использовать официальные API, вести лог источников.

---

### Sprint 0 — Setup & Baseline (DONE)
**Цели:**
- Текущий код: ревью `ai_generator.py`, `utils.py`, `database.py`.
- Внедрить `ANALYSIS_PROMPT.md` как источник истины.
- Настроить CI: pytest, basic lint.

**Deliverables:** PR с заменённым prompt, baseline tests (truncation + banned words).

---

### Sprint 1 — Stable Generation & Postprocessing (DONE)
**Цели:**
- Жёсткая пост‑обработка (clean_and_truncate), контроль эмодзи, banned words.
- Улучшить split_for_telegram и тесты.
- Логирование метрик генерации (chars, truncated, model).

**Acceptance:** >95% тестов проходят; при запуске тестовой генерации 20 разных матчей — 95% в target.

---

### Sprint 2 — Payment Flow Robustness & Caching (DONE)
**Цели:**
- Idempotency: purchase_state workflow (pending/paid/processing/done).
- Кэширование: сохранение анализа, get_cached_analysis, regen endpoint.
- Интеграционные тесты: симуляция покупки → генерация → выдача.

**Acceptance:** двойной callback не приводит к двойной генерации; пользователь получает один анализ.

---

### Sprint 2.5 — API Integration Testing & Manual Sync (DONE)
**Цели:**
- Создать admin‑команду: `/sync_sport <sport_type>` — получить топ‑3 актуальных матчей из спортивного API.
- Проверить полный flow: API → парсинг → запись в БД (matches table) → отображение в UI.
- Валидация данных: все обязательные поля заполнены (home_team, away_team, match_date, ect.).
- UI smoke‑test: корректное отображение списка матчей, цены, кнопок покупки.

**Deliverables:**
- `python sync_matches.py` возвращает top‑3 матча + подтверждение записи в БД.
- `python sync_matches.py --mode all` — bulk import всех матчей из 10 лиг/кубков.
- UI показывает новые матчи с актуальными данными (команды, дата, время).
- Интеграционные тесты: mock API → assert DB records (6 тестов).

**Acceptance:**
- Ручной запуск корректно заполняет БД без дублей (idempotent по api_event_id).
- UI отображает все поля без ошибок.
- Логируются source, raw_json, home_team_id, away_team_id, match_datetime для каждого матча.
- Token bucket rate limiter (25 req/min) + exponential backoff.
- Таблица teams с кэшем lookupteam (TTL 24h).
- Cooldown tracking: скрипт автоматически ждёт сброса API лимита.

**Реализовано в:** ветка `fix/sync-parametrize-and-trace`, подробности в `CHANGELOG_SPRINT_2_5.md`.

---

### Sprint 3 — Source Automation
**Цели:**
- APScheduler job для автоматического периодического sync (cron).
- Telegram admin‑команда `/sync_sport <sport_type>` для ручного запуска из бота.
- Обновление счёта завершённых матчей (home_score, away_score).

**Acceptance:** автоматический периодический import матчей; admin может запустить sync из Telegram.

---

### Stabilise & Launch Prep 
**Цели:**
- End‑to‑end QA (20 real match flows).
- Документация: README, prompts, runbook for ops.
- Денежный расчёт: cost-per-analysis estimator.

**Go/No‑Go критерии:** 95% KR1 выполнен; error rate <2%; минимум 50 тестовых пользователей в пилоте.

---

## Operational playbook (кратко)
- Мониторинг: отправлять в Slack/Webhook при error rate > 1% или при превышении hard cap.
- Rollback: при критической ошибке — выключить генерации (флаг в config), переключиться на ручную выдачу.
- Cost control: daily report по количеству генераций и прогноз расходов.

---

## KPI & A/B идеи
- A/B тест: «короткий» vs «детальный» анализ в UI — тест на конверсию.
- KPI: CR (view→purchase), Retention, Avg Revenue per User.

---

## Definition of Done (DoD) для релиза MVP
- Код покрыт тестами (unit + minimal integration).  
- Генерация стабильно укладывается в целевой диапазон (95%).  
- Ключевые ошибки логируются и алертятся.  
- Документация для запуска в README есть.  

---

## Быстрые wins
1. Подменить prompt на `ANALYSIS_PROMPT.md`.  
2. Добавить один‑два unit теста на очистку текста.  
3. Включить логирование длины и truncated флага.

---

## Backlog / Nice‑to‑have (после MVP)
- Hybrid source: scraper fallback.  
- Few‑shot templates per sport.  
- Multilanguage support.  
- Subscription model, bulk purchases.

---
