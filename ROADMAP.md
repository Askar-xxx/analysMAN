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

### Sprint 2.7 — H2H & Standings Enrichment (DONE)
**Цели:**
- Обогащение матчей данными H2H (история личных встреч) и standings (турнирная таблица).
- Интеграция реальных данных в AI-промпт: форма (WWDWL), позиция, очки, разница мячей.
- Устранение «абстрактных» анализов — AI пишет с реальными фактами, а не домыслами.

**Deliverables:**
- `fetch_h2h()`, `fetch_standings()`, `enrich_matches()` в `sync_matches.py`.
- Флаг `--enrich` для sync_matches.py.
- `_format_h2h()`, `_format_standings()`, `_extract_team_standings()` в `ai_generator.py`.
- DB migration: `h2h_json`, `h2h_fetched_at`, `standings_json`, `standings_fetched_at`.
- TTL‑кэширование (24h) — повторный enrich не перезапрашивает свежие данные.
- 12 новых тестов (9 unit + 3 integration), итого 46 тестов.
- Обновлённый `ANALYSIS_PROMPT.md` с правилами DO NOT INVENT NUMBERS / CITE SOURCE.

**Баги исправлены:**
- Пробелы в названиях команд для H2H запросов (`Leeds United` → `Leeds`).
- Суффиксы в названиях (`United`, `City`, `FC`, `Wanderers` и др.) убираются при поиске H2H.
- API ключ: `"123"` (ограничен 2 результата) → `"3"` (полные данные, 20+ H2H).
- Standings данные интегрированы в обзоры команд (секции 2-3), а не отдельным блоком.

**Acceptance:**
- Анализы для команд в топ-5 содержат реальную форму, позицию, очки.
- H2H содержит 2-7 матчей с датами и счетами (вместо 0-1).
- 46/46 тестов проходят.

**Известные ограничения (бесплатный API):**
- `lookuptable` — только топ-5 команд лиги.
- Нет статистики игроков.

---

### Sprint 3 — Source Automation
**Цели:**
- APScheduler job для автоматического периодического sync + enrich (cron).
- Telegram admin‑команда `/sync` для ручного запуска из бота.
- Обновление счёта завершённых матчей (home_score, away_score).
- Автоматическая очистка устаревших матчей (> 2 дней после завершения).

**Acceptance:** автоматический периодический import + enrich матчей; admin может запустить sync из Telegram.

---

### Sprint 4 — Purchase Flow & Analysis Delivery
**Цели:**
- Реализовать полный flow: покупка → генерация анализа → выдача пользователю.
- Idempotency: `purchase_state` workflow (pending → paid → processing → done).
- Кэширование: повторная покупка отдаёт готовый анализ без повторной генерации.
- Интеграционные тесты покупки.

**Acceptance:** двойной callback не приводит к двойной генерации; пользователь получает анализ.

---

### Stabilise & Launch Prep
**Цели:**
- End‑to‑end QA (20 real match flows).
- Документация: README, runbook for ops.
- Денежный расчёт: cost-per-analysis estimator.
- Рассмотреть гибридный подход (API-Football для полных standings).

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

## Быстрые wins (все выполнены)
1. ~~Подменить prompt на `ANALYSIS_PROMPT.md`.~~
2. ~~Добавить unit тесты на очистку текста.~~
3. ~~Включить логирование длины и truncated флага.~~
4. ~~Обогащение H2H и standings для качественных анализов.~~

---

## Backlog / Nice‑to‑have (после MVP)
- Hybrid API: API-Football для полных standings (все команды, не только топ-5).
- Hybrid source: scraper fallback.
- Few‑shot templates per sport.
- Multilanguage support.
- Subscription model, bulk purchases.
- Статистика игроков (требует платного API или парсинг).

---
