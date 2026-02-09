# Changelog: Sprint 2.5 - API Integration & Manual Sync

**Ветка:** `fix/sync-parametrize-and-trace`
**Дата:** 2026-02-09

---

## Что было сделано

### 1. CLI-параметризация sync_matches.py

**Проблема:** Скрипт всегда делал bulk-импорт всех матчей из 10 лиг/кубков. ROADMAP требовал default = top-3.

**Решение:** Добавлены CLI-флаги:
- `--mode {top3,all}` (default: `top3`) - режим синхронизации
- `--limit N` (default: 3) - макс. количество матчей в top3
- `--batch-size N` (default: 15) - размер батча
- `--cache-teams` - кэширование команд после sync
- `--only-cache-teams` - только кэширование (без sync)
- Существующие: `--dry-run`, `--verbose`, `--debug`, `--db`

**Файлы:** `sync_matches.py`

---

### 2. Новые столбцы в таблице matches (tracing)

**Проблема:** В БД не сохранялись исходные данные от API — невозможно отследить источник и отладить проблемы.

**Решение:** 7 новых столбцов:

| Столбец | Тип | Описание |
|---|---|---|
| `raw_json` | TEXT | Полный JSON ответа API для каждого матча |
| `source` | TEXT | Источник данных (e.g. "TheSportsDB") |
| `home_team_id` | TEXT | ID домашней команды в API |
| `away_team_id` | TEXT | ID гостевой команды в API |
| `home_score` | INTEGER | Счёт (заполняется после матча) |
| `away_score` | INTEGER | Счёт (заполняется после матча) |
| `match_datetime` | TEXT | UTC datetime в формате ISO8601 |

Миграция через ALTER TABLE в `init_db()` — безопасна для существующих БД.

**Файлы:** `database.py`

---

### 3. Таблица teams с кэшем

**Проблема:** Не было хранения данных о командах, каждый раз нужно было бы запрашивать API.

**Решение:** Таблица `teams` с полями:
- `team_id` (PK), `name`, `short_name`, `badge_url`, `sport`, `raw_json`, `source`, `cached_at`
- TTL: 24 часа (при запросе проверяется `cached_at`)
- Метод `cache_team()` — проверяет кэш, при промахе вызывает `lookupteam.php`
- `--only-cache-teams` для отложенного кэширования

**Файлы:** `database.py`, `sync_matches.py`

---

### 4. Token bucket rate limiter

**Проблема:** Старый лимитер (sleep-based, 28 req/min) не обрабатывал HTTP 429 и не имел backoff.

**Решение:**
- Token bucket: capacity=25, refill=25 tokens/min
- Exponential backoff при HTTP 429: 2s, 4s, 8s, 16s (до 3 retry)
- Thread-safe (Lock)

**Файлы:** `sync_matches.py` (класс `RateLimitedAPI`)

---

### 5. Idempotent вставка матчей

**Проблема:** Dedup был по `(team1, team2, match_date)` — ненадёжно (разные матчи тех же команд).

**Решение:**
- Первичная проверка по `api_event_id` (уникальный ID из API)
- Fallback по `(team1, team2, match_date)` для обратной совместимости
- Повторный sync безопасен: 0 дублей

**Файлы:** `sync_matches.py` (метод `save_matches_to_db`)

---

### 6. Режим top3

**Проблема:** ROADMAP требует default sync = top-3 матча.

**Решение:**
- Метод `get_top3_matches()` — обходит лиги по приоритету, собирает первые N матчей
- Метод `sync()` — роутер: `top3` -> `get_top3_matches()`, `all` -> `get_week_matches()`
- Bulk import сохранён и доступен через `--mode all`

**Файлы:** `sync_matches.py`

---

### 7. Cooldown tracking (sync_meta)

**Проблема:** При запуске `--cache-teams` сразу после sync — API возвращал 429 из-за исчерпанного лимита.

**Решение:**
- Таблица `sync_meta` (key-value) хранит `last_sync_at`
- При `--cache-teams` / `--only-cache-teams` — проверяется прошло ли 65с
- Если нет — скрипт автоматически ждёт нужное время и уведомляет пользователя
- Пауза 2.5с между каждым `lookupteam` API-вызовом

**Файлы:** `sync_matches.py`, `database.py`

---

### 8. Интеграционные тесты

6 тестов в `tests/test_sync_matches.py`:

| Тест | Что проверяет |
|---|---|
| `test_top3_inserts_exactly_3` | Top3 mode вставляет ровно 3 матча |
| `test_top3_respects_limit` | `--limit 2` возвращает ровно 2 |
| `test_no_duplicates_on_resync` | Повторный sync: 0 inserted, 3 skipped |
| `test_tracing_fields_present` | raw_json, source, team_ids заполнены |
| `test_team_ids_match_api` | home_team_id/away_team_id = данным API |
| `test_all_mode_saves_all` | Режим all сохраняет без ошибок |

Все тесты используют mock API + временные SQLite файлы.

**Файлы:** `tests/test_sync_matches.py`

---

### 9. Обновление документации

- `CLAUDE.md` — обновлено состояние разработки, архитектура, тесты, команды
- `ROADMAP.md` — Sprint 2.5 отмечен как выполненный
- `USER_MANUAL.md` — руководство по использованию (создано)
- `CHANGELOG_SPRINT_2_5.md` — этот документ

---

## Коммиты

```
ff1bd22 db: add raw_json, source, team_ids, scores, match_datetime columns + teams table
e313aa9 sync: add CLI flags, token bucket, top3 mode, tracing, team cache
a591d40 tests: add integration tests for sync top3, idempotence, and tracing
b783717 docs: update CLAUDE.md with Sprint 2.5 completion status
133fd52 db: fix init_db() — move index creation after ALTER TABLE migration
51f6cef sync: make team caching opt-in via --cache-teams flag
26b38d2 sync: add cooldown tracking and --only-cache-teams flag
```

---

## Тесты

```
28 passed (6 sync + 6 ai_generator + 16 utils)
flake8: clean (на изменённых файлах)
```
