# API-Football: Финальные решения по архитектуре (Этап 2)

**Контекст:** Ответы на вопросы из `API_FOOTBALL_SPEC.md`, раздел "Вопросы для обсуждения"

---

## Решение 1: Injuries — один JSON

**Выбор:** Вариант A — один объект `apif_injuries_json` для обеих команд.

**Формат хранения:**

```json
{
  "home_injuries": [
    {"player": "R. Lavia", "reason": "Thigh Injury", "type": "Missing Fixture"},
    {"player": "C. Gallagher", "reason": "Injury", "type": "Missing Fixture"}
  ],
  "away_injuries": [
    {"player": "K. De Bruyne", "reason": "Hamstring", "type": "Missing Fixture"}
  ]
}
```

**Почему:**
- Травмы привязаны к матчу, читаются вместе при генерации анализа
- Один TTL-timestamp (`apif_injuries_fetched_at`) — проще обновление
- Совпадает с паттерном проекта: `h2h_json`, `standings_json` — один тип данных = одно поле
- При генерации `ai_generator.py` парсит JSON целиком → удобно иметь оба списка рядом

**Важно при реализации:**
- Фильтровать по `type: "Missing Fixture"` — API возвращает историю (180+ записей)
- Лимит: максимум 5-7 травм на команду (самые свежие)

---

## Решение 2: Top Scorers — топ-10 лиги

**Выбор:** Вариант A — топ-10 бомбардиров лиги.

**Формат хранения:**

```json
{
  "league_id": "39",
  "season": "2024",
  "top_scorers": [
    {"player_name": "Mohamed Salah", "team_name": "Liverpool", "goals": 29, "assists": 0},
    {"player_name": "A. Isak", "team_name": "Newcastle", "goals": 23, "assists": 0}
  ]
}
```

**Почему:**
- 1 запрос на лигу vs 2 запроса на матч — экономия квоты (100 req/day)
- Кэшируется на 24h, переиспользуется для ВСЕХ матчей этой лиги
- Для секции "Ключевые игроки" достаточно проверить: участвует ли кто-то из топ-10 в данном матче
- `fetch_top_scorers()` уже реализован с `limit=10`

**Использование в `ai_generator.py`:**

```
Если Салах (топ-1, 29 голов) играет в матче Liverpool vs Chelsea →
  "М. Салах — лидер бомбардирской гонки EPL (29 голов)"
```

---

## Решение 3: Всё в JSON

**Выбор:** Вариант A — все данные API-Football хранить в JSON-полях.

**Схема БД (новые поля в таблице `matches`):**

```sql
-- Team statistics (home/away — дома/в гостях, форма)
apif_stats_json TEXT              -- {home_stats: {...}, away_stats: {...}}
apif_stats_fetched_at TEXT        -- ISO8601 timestamp

-- Injuries (травмированные игроки)
apif_injuries_json TEXT           -- {home_injuries: [...], away_injuries: [...]}
apif_injuries_fetched_at TEXT

-- Full standings (полная таблица, все команды)
apif_full_standings_json TEXT     -- {standings: [...], total_teams: 20}
apif_standings_fetched_at TEXT

-- Top scorers (бомбардиры лиги)
apif_top_scorers_json TEXT        -- {top_scorers: [...]}
apif_scorers_fetched_at TEXT
```

**Почему:**
- Данные **не используются в SQL-запросах** — только читаются в `ai_generator.py` для промпта
- 20+ отдельных колонок (`apif_home_wins`, `apif_home_losses`...) — раздувание без пользы
- Текущий паттерн: `h2h_json`, `standings_json`, `raw_json` — всё уже JSON
- SQLite не даёт выигрыша от типизированных колонок для данных, которые только читаются целиком
- Префикс `apif_` чётко отделяет от TheSportsDB полей (`h2h_json`, `standings_json`)

**Миграция (добавить в `init_db()`):**

```python
new_columns = [
    ('apif_stats_json', 'TEXT'),
    ('apif_stats_fetched_at', 'TEXT'),
    ('apif_injuries_json', 'TEXT'),
    ('apif_injuries_fetched_at', 'TEXT'),
    ('apif_full_standings_json', 'TEXT'),
    ('apif_standings_fetched_at', 'TEXT'),
    ('apif_top_scorers_json', 'TEXT'),
    ('apif_scorers_fetched_at', 'TEXT'),
]
```

---

## Решение 4: Team ID — колонка в таблице `teams` + гибридный поиск

**Выбор:** Гибридный подход, но БЕЗ отдельной таблицы `team_id_mapping`.

**Реализация:** Добавить колонку `apif_team_id` в существующую таблицу `teams`:

```sql
ALTER TABLE teams ADD COLUMN apif_team_id TEXT;
```

**Почему НЕ отдельная таблица:**
- Таблица `teams` уже хранит `team_id` (TheSportsDB), `name`, `sport`
- Одна колонка проще, чем JOIN с `team_id_mapping` при каждом запросе
- Меньше сущностей в БД

**Алгоритм сопоставления (при обогащении матча):**

```
1. Взять home_team_id матча → найти в teams → проверить apif_team_id
2. Если apif_team_id есть → использовать
3. Если apif_team_id = NULL →
   a. Поиск по названию в API-Football: GET /teams?search={team_name}
   b. Сохранить найденный ID в teams.apif_team_id
   c. Использовать для запросов
```

**Маппинг лиг (статический, хранить в коде):**

```python
LEAGUE_MAPPING = {
    "4328": "39",   # Premier League
    "4335": "140",  # La Liga
    "4331": "78",   # Bundesliga
    "4332": "135",  # Serie A
    "4334": "61",   # Ligue 1
}
```

Лиг мало (5 штук) — нет смысла в таблице, достаточно словаря.

---

## Решение 5: Приоритет данных — дифференцированный

**Выбор:** НЕ один источник для всего, а по типу данных.

| Тип данных | Источник | Причина |
|---|---|---|
| **Расписание матчей** | TheSportsDB | Бесплатный, без лимитов, уже работает |
| **H2H (личные встречи)** | TheSportsDB | Работает для всех команд, не тратит квоту API-Football |
| **Standings (команда в топ-5)** | TheSportsDB | Уже есть данные, не тратить квоту |
| **Standings (команда ВНЕ топ-5)** | API-Football | TheSportsDB не имеет этих данных |
| **Team stats (дома/в гостях)** | API-Football | TheSportsDB не предоставляет |
| **Injuries** | API-Football | TheSportsDB не предоставляет |
| **Top scorers** | API-Football | TheSportsDB не предоставляет |

**Логика в `sync_api_football.py --fill-gaps`:**

```
Для каждого матча:
1. Проверить standings_json (TheSportsDB):
   - Команда A в таблице? Команда B в таблице?
   - Если обе есть → НЕ запрашивать apif_full_standings
   - Если хотя бы одна отсутствует → запросить full standings из API-Football

2. Всегда запрашивать (если TTL истёк):
   - apif_stats_json (team stats — уникальные данные)
   - apif_injuries_json (травмы — уникальные данные)

3. Top scorers: 1 раз на лигу (не на матч), кэш 24h
```

**Экономия квоты:**
- Если standings уже есть от TheSportsDB → минус 1 запрос на матч
- Top scorers кэшируются по лиге → 1 запрос на лигу, не на матч
- Реальное потребление: ~2-4 req/матч (вместо 6 worst case)

---

## Итого: схема обогащения матча

```
sync_matches.py --enrich          ← TheSportsDB: расписание + H2H + standings (топ-5)
       ↓
sync_api_football.py --fill-gaps  ← API-Football: заполнение пробелов
       ↓
ai_generator.py                   ← Чтение ВСЕХ полей, генерация анализа
```

**Поля матча после полного обогащения:**

```
TheSportsDB:          API-Football:
├─ h2h_json           ├─ apif_stats_json
├─ h2h_fetched_at     ├─ apif_stats_fetched_at
├─ standings_json      ├─ apif_injuries_json
├─ standings_fetched_at├─ apif_injuries_fetched_at
                       ├─ apif_full_standings_json
                       ├─ apif_standings_fetched_at
                       ├─ apif_top_scorers_json
                       └─ apif_scorers_fetched_at
```

---

## TTL (без изменений, как в спецификации)

| Тип данных | TTL | Источник |
|---|---|---|
| H2H | 24h | TheSportsDB |
| Standings (топ-5) | 24h | TheSportsDB |
| Team stats | 12h | API-Football |
| Injuries | 12h | API-Football |
| Full standings | 24h | API-Football |
| Top scorers | 24h | API-Football |

---

## Что дальше

Эти решения фиксируют архитектуру для Этапа 2. Порядок реализации:

1. Миграция БД: добавить `apif_*` поля + `apif_team_id` в `teams`
2. `sync_api_football.py`: добавить `--fill-gaps`, `_save_to_db()`, gap detection
3. `ai_generator.py`: форматтеры `_format_apif_stats()`, `_format_injuries()`, `_format_top_scorers()`
4. Обновить тесты `test_sync_matches.py` (today+tomorrow)
5. Интеграционные тесты для fill-gaps