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

### Sprint 0 — Setup & Baseline
**Цели:**
- Текущий код: ревью `ai_generator.py`, `utils.py`, `database.py`.
- Внедрить `ANALYSIS_PROMPT.md` как источник истины.
- Настроить CI: pytest, basic lint.

**Deliverables:** PR с заменённым prompt, baseline tests (truncation + banned words).

---

### Sprint 1 — Stable Generation & Postprocessing
**Цели:**
- Жёсткая пост‑обработка (clean_and_truncate), контроль эмодзи, banned words.
- Улучшить split_for_telegram и тесты.
- Логирование метрик генерации (chars, truncated, model).

**Acceptance:** >95% тестов проходят; при запуске тестовой генерации 20 разных матчей — 95% в target.

---

### Sprint 2 — Payment Flow Robustness & Caching
**Цели:**
- Idempotency: purchase_state workflow (pending/paid/processing/done).
- Кэширование: сохранение анализа, get_cached_analysis, regen endpoint.
- Интеграционные тесты: симуляция покупки → генерация → выдача.

**Acceptance:** двойной callback не приводит к двойной генерации; пользователь получает один анализ.

---

### Sprint 3 — Source Automation
**Цели:**
- Implement `integrations/fetcher.py` adapter (Пока на этапе выбора спортивного API).
- `sync_matches.py` + APScheduler job (sync next 3 days).

**Acceptance:** автоматический import матчей; matches have `source` + `source_id` + `raw_json`.

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
