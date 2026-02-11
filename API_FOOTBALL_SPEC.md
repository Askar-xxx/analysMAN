# API-Football Integration Specification

## Overview

Этот документ описывает интеграцию API-Football v3 для заполнения пробелов в данных от TheSportsDB.

**Проблема:** Текущие анализы содержат много "нет данных" из-за ограничений бесплатного API TheSportsDB:
- Standings только для топ-5 команд лиги
- Нет статистики игроков (травмы, бомбардиры)
- Нет детальной статистики команд (форма дома/в гостях, голы, тренды)

**Решение:** Гибридный подход с двумя API:

```
1. TheSportsDB (unlimited) → базовая инфа, H2H, standings (топ-5)
   ↓
2. API-Football (100 req/day) → заполнение пробелов
   - Full standings (все команды, не только топ-5)
   - Team statistics (форма дома/в гостях, голы)
   - Injuries (травмированные игроки)
   - Top scorers (бомбардиры лиги)
```

**Статус:** Этап 1 - Исследование (fetch функции, примеры JSON, БЕЗ сохранения в БД)

---

## API Credentials

- **API Key:** `6d1cd670204b0309db23b217ddf33d5a` (хранится в `config.py`)
- **Base URL:** `https://v3.football.api-sports.io`
- **Free Tier Limits:**
  - 100 requests/day (сброс в полночь UTC)
  - Rate limit: минимум 1 req/sec (в коде используем для безопасности)

**Документация:** https://www.api-football.com/documentation-v3

---

## Endpoints

### 1. Team Statistics

**Endpoint:** `GET /teams/statistics`

**Query Parameters:**
- `team`: ID команды (например, `49` для Chelsea)
- `league`: ID лиги (например, `39` для Premier League)
- `season`: Год сезона (например, `2024`)

**Пример запроса:**
```
GET https://v3.football.api-sports.io/teams/statistics?team=49&league=39&season=2024
Headers:
  x-apisports-key: {API_KEY}
  Accept: application/json
```

**Пример ответа:** См. `api_examples/team_stats_49.json`

**Ключевые данные:**

```json
{
  "team_id": "49",
  "team_name": "Chelsea",
  "home_wins": 12,
  "home_draws": 5,
  "home_losses": 2,
  "home_goals_for": 35,
  "home_goals_against": 18,
  "away_wins": 8,
  "away_draws": 4,
  "away_losses": 7,
  "away_goals_for": 29,
  "away_goals_against": 25,
  "form": "LWDWWWDLWDDWWWWWDLLDDWLWLLWWLWDDWWWLWW"
}
```

**Что это даёт:**
- Детальная статистика дома/в гостях (wins/draws/losses, голы)
- Форма команды (последние 40 матчей)
- Более точные данные чем TheSportsDB

**Использование в анализе:**
- Секция 2-3: "Обзор команды" — статистика дома/в гостях, тренды
- "Chelsea дома: 12-5-2 (80% побед), забивают в среднем 1.8 гола"

---

### 2. Injuries

**Endpoint:** `GET /injuries`

**Query Parameters:**
- `team`: ID команды
- `league`: ID лиги
- `season`: Сезон

**Пример запроса:**
```
GET https://v3.football.api-sports.io/injuries?team=49&league=39&season=2024
```

**Пример ответа:** См. `api_examples/injuries_49.json`

**Ключевые данные:**

```json
{
  "team_id": "49",
  "team_name": "Chelsea",
  "injuries_count": 180,
  "injuries": [
    {
      "player_name": "C. Gallagher",
      "reason": "Injury",
      "type": "Missing Fixture"
    },
    {
      "player_name": "R. Lavia",
      "reason": "Thigh Injury",
      "type": "Missing Fixture"
    }
  ]
}
```

**Что это даёт:**
- Список травмированных игроков
- Причина травмы
- Статус (Missing Fixture / Doubtful)

**Использование в анализе:**
- Секция 2-3: "Обзор команды" — список травм
- Секция 5: "Ключевые игроки" — отметка если ключевой игрок травмирован
- "Chelsea: без R. Lavia (бедро), C. Gallagher (травма)"

**ВАЖНО:** API возвращает ИСТОРИЮ травм (180 записей для Chelsea), нужна фильтрация по актуальным.

---

### 3. Top Scorers

**Endpoint:** `GET /players/topscorers`

**Query Parameters:**
- `league`: ID лиги
- `season`: Сезон

**Пример запроса:**
```
GET https://v3.football.api-sports.io/players/topscorers?league=39&season=2024
```

**Пример ответа:** См. `api_examples/top_scorers_39.json`

**Ключевые данные:**

```json
{
  "league_id": "39",
  "season": "2024",
  "top_scorers": [
    {
      "player_name": "Mohamed Salah",
      "team_name": "Liverpool",
      "goals": 29,
      "assists": 0
    },
    {
      "player_name": "A. Isak",
      "team_name": "Newcastle",
      "goals": 23,
      "assists": 0
    }
  ]
}
```

**Что это даёт:**
- Топ-бомбардиры лиги
- Голы + ассисты
- Команда игрока

**Использование в анализе:**
- Секция 5: "Ключевые игроки" — если игрок в топ-10, указать "М. Салах (топ-1 в лиге, 29 голов)"
- Контекст для важности игроков

**Оптимизация:** Запрашивать 1 раз на лигу (не на матч), кэшировать на 24h.

---

### 4. Full Standings

**Endpoint:** `GET /standings`

**Query Parameters:**
- `league`: ID лиги
- `season`: Сезон

**Пример запроса:**
```
GET https://v3.football.api-sports.io/standings?league=39&season=2024
```

**Пример ответа:** См. `api_examples/standings_39.json`

**Ключевые данные:**

```json
{
  "league_id": "39",
  "season": "2024",
  "total_teams": 20,
  "standings": [
    {
      "rank": 1,
      "team_name": "Liverpool",
      "team_id": "42",
      "points": 84,
      "played": 37,
      "win": 27,
      "draw": 3,
      "lose": 7,
      "goals_for": 97,
      "goals_against": 48,
      "goal_diff": 49,
      "form": "DLDLW"
    },
    {
      "rank": 4,
      "team_name": "Chelsea",
      "team_id": "49",
      "points": 69,
      "form": "WWLWW"
    }
  ]
}
```

**Что это даёт:**
- ПОЛНАЯ таблица всех команд (vs TheSportsDB топ-5)
- Позиция, очки, форма для ЛЮБОЙ команды
- Разница мячей, голы за/против

**Использование в анализе:**
- Секция 2-3: "Обзор команды" — позиция в таблице, очки, форма
- Заполнение gaps когда команда ВНЕ топ-5 TheSportsDB
- "Fulham (#10 место, 45 очков, форма DWLWD)"

**Оптимизация:** Запрашивать 1 раз на матч (если лига одна), кэшировать на 24h.

---

## Предлагаемая схема БД

### Новые поля в таблице `matches`

**Префикс `apif_` для ясного разделения от TheSportsDB данных.**

```sql
-- Team statistics (home/away)
apif_stats_json TEXT              -- JSON: {home_stats: {...}, away_stats: {...}}
apif_stats_fetched_at TEXT        -- Timestamp получения (ISO8601)

-- Injuries
apif_injuries_json TEXT           -- JSON: {home_injuries: [...], away_injuries: [...]}
apif_injuries_fetched_at TEXT     -- Timestamp

-- Full standings (если команды вне топ-5 TheSportsDB)
apif_full_standings_json TEXT     -- JSON: полная таблица лиги
apif_standings_fetched_at TEXT    -- Timestamp

-- Top scorers лиги (опционально, можно в отдельную таблицу)
apif_top_scorers_json TEXT        -- JSON: топ-10 бомбардиров
apif_scorers_fetched_at TEXT      -- Timestamp
```

**Обоснование структуры:**

1. **JSON storage:** Гибкость, без добавления 20+ колонок
2. **Независимый TTL:** Каждый тип данных имеет свой timestamp
3. **Префикс `apif_`:** Явное разделение от `h2h_json`, `standings_json` (TheSportsDB)
4. **Nullable:** Поля заполняются только при необходимости

**Альтернатива:** Отдельная таблица `api_football_enrichment` с foreign key на `matches.id`.

**Рекомендация:** Начать с полей в `matches` (проще), перенести в отдельную таблицу если размер БД станет проблемой.

---

## Rate Limiting Strategy

### Daily Quota: 100 requests/day

**Расчёт потребления:**

Для 1 матча (2 команды):
- Team stats: 2 requests (home + away)
- Injuries: 2 requests (home + away)
- Standings: 1 request (лига)
- Top scorers: 1 request (лига)

**Итого:** 6 requests/матч (worst case, без кэширования)

**С кэшированием (TTL 24h):**
- Standings: 1 request/лигу (переиспользуется для всех матчей лиги)
- Top scorers: 1 request/лигу
- Team stats: кэшируется для команды (переиспользуется если команда играет несколько матчей)
- Injuries: кэшируется для команды

**Реальное потребление:** ~2-3 requests/матч (с умным кэшированием)

**Вывод:** 100 requests/day достаточно для 30-50 матчей/день (в зависимости от overlap).

### TTL рекомендации

| Тип данных       | TTL   | Причина                                      |
|------------------|-------|----------------------------------------------|
| Team stats       | 12h   | Меняется после каждого матча                 |
| Injuries         | 12h   | Актуальность критична                        |
| Standings        | 24h   | Обновляется реже                             |
| Top scorers      | 24h   | Меняется медленно                            |

### Min interval

**Текущая реализация:** 1 req/sec (для безопасности)

**API-Football ограничение:** Не указано явно, но 1 req/sec безопасно.

---

## Стратегия использования (Workflow)

### Этап 2: Smart Gap Filling (будет реализовано после утверждения спецификации)

```
1. TheSportsDB sync:
   - Базовая инфа (team1, team2, date, league)
   - H2H через searchevents
   - Standings через lookuptable (только топ-5)

2. Проверка gaps:
   - Команда ВНЕ топ-5? → apif_full_standings_json = NULL
   - Нет injuries? → apif_injuries_json = NULL
   - Нужна детальная статистика? → apif_stats_json = NULL

3. API-Football fill:
   - Заполнить ТОЛЬКО пустые поля
   - Проверить TTL перед запросом
   - Обновить *_fetched_at timestamps

4. AI генерация:
   - Использовать ВСЕ доступные данные (TheSportsDB + API-Football)
   - Приоритет: API-Football данные (если есть) > TheSportsDB
```

### CLI Usage (после Этапа 2)

```bash
# Шаг 1: TheSportsDB sync (как обычно)
python sync_matches.py --mode top3 --enrich

# Шаг 2: API-Football gap filling (НОВОЕ)
python sync_api_football.py --fill-gaps
# или
python sync_api_football.py --fill-gaps --dry-run  # Preview

# Шаг 3: Проверка обогащения
python check_matches.py --show-enrichment
```

---

## Mapping: TheSportsDB ↔ API-Football

**Проблема:** Разные ID систем для команд и лиг.

### Лиги (Top 5)

| Название          | TheSportsDB ID | API-Football ID |
|-------------------|----------------|-----------------|
| Premier League    | 4328           | 39              |
| La Liga           | 4335           | 140             |
| Bundesliga        | 4331           | 78              |
| Serie A           | 4332           | 135             |
| Ligue 1           | 4334           | 61              |

### Команды (примеры)

**Mapping нужно создать через lookup:**

1. TheSportsDB: `home_team_id = "133612"` → название "Chelsea"
2. API-Football: искать "Chelsea" → `team_id = "49"`

**Решение (Этап 2):** Создать mapping таблицу `team_id_mapping`:

```sql
CREATE TABLE team_id_mapping (
  sportsdb_team_id TEXT PRIMARY KEY,
  apif_team_id TEXT NOT NULL,
  team_name TEXT,
  last_verified TEXT
);
```

**Альтернатива:** Использовать названия команд для поиска (менее надёжно).

---

## Примеры данных

**Все примеры JSON собраны и сохранены в папке `api_examples/`:**

- `team_stats_49.json` — статистика Chelsea (home/away wins/losses, форма)
- `injuries_49.json` — травмы Chelsea (180 записей, нужна фильтрация)
- `top_scorers_39.json` — топ-10 бомбардиров EPL
- `standings_39.json` — полная таблица EPL (20 команд)

**Тестовые параметры:**
- Chelsea (API-Football team_id=49, TheSportsDB team_id=133612)
- Man City (API-Football team_id=50)
- English Premier League (API-Football league_id=39, TheSportsDB league_id=4328)
- Season: 2024

---

## Вопросы для обсуждения

### 1. Формат JSON для injuries

**Вариант A:** Один объект для обеих команд

```json
{
  "home_injuries": [{"player": "R. Lavia", "reason": "Thigh Injury"}],
  "away_injuries": [{"player": "K. De Bruyne", "reason": "Hamstring"}]
}
```

**Вариант B:** Раздельные поля `apif_home_injuries_json` и `apif_away_injuries_json`

**Рекомендация:** Вариант A (компактнее, логичнее для матча)

---

### 2. Top scorers: лига vs команды

**Вариант A:** Топ-10 лиги (как сейчас)
- Запрос: 1 на лигу
- Использование: "М. Салах играет (топ-1 в лиге, 29 голов)"

**Вариант B:** Топ-3 по каждой команде
- Запрос: 2 на матч (более затратно)
- Использование: более релевантные данные для команды

**Рекомендация:** Вариант A (экономия запросов + достаточно информации)

---

### 3. Отдельные поля vs JSON

**Вариант A:** Всё в JSON (как предложено)
- Гибкость, не раздувает схему
- Парсинг в Python при использовании

**Вариант B:** Ключевые поля отдельно
```sql
apif_home_wins INT
apif_home_losses INT
apif_away_wins INT
...
```
- Быстрее запросы (SELECT без JSON парсинга)
- 20+ новых колонок

**Рекомендация:** Вариант A (JSON) для Этапа 1-2, можем оптимизировать позже.

---

### 4. Team ID Mapping

**Вопрос:** Как строить mapping TheSportsDB ↔ API-Football?

**Вариант A:** Таблица `team_id_mapping`
- Явное хранение
- Нужно заполнять вручную или через script

**Вариант B:** Поиск по названию команды
- Автоматический
- Может ошибаться ("Manchester United" vs "Manchester City")

**Рекомендация:** Гибридный подход:
1. Попытка поиска в `team_id_mapping`
2. Если нет → поиск по названию + сохранение в mapping

---

### 5. Приоритет данных

**Вопрос:** Если есть standings от ОБОИХ источников, какой использовать?

**Вариант A:** API-Football приоритет (более детальные данные)

**Вариант B:** TheSportsDB приоритет (уже есть, зачем тратить quota)

**Рекомендация:** Вариант B для standings (TheSportsDB достаточно если команда в топ-5), Вариант A для остальных данных.

---

## Ограничения и известные проблемы

### 1. API-Football показывает только TODAY + TOMORROW

**Проблема:** Endpoint `/fixtures` возвращает матчи только на сегодня и завтра (free tier).

**Решение (Этап 2):** Ограничить `sync_matches.py` на today+tomorrow тоже (см. задача #6).

```python
def get_top3_matches(self) -> List[Dict]:
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    # Фильтр: только сегодня + завтра
    for event in data['events']:
        match_date = datetime.strptime(match['match_date'], '%Y-%m-%d').date()
        if match_date not in [today, tomorrow]:
            continue
```

---

### 2. Injuries: история vs актуальные

**Проблема:** API возвращает историю травм (180 записей для Chelsea).

**Решение:** Фильтровать по полю `type: "Missing Fixture"` (актуально сейчас).

---

### 3. Team ID Mapping

**Проблема:** Нет прямого mapping между TheSportsDB и API-Football ID.

**Решение:** Создать mapping таблицу или искать по названию (см. вопрос #4).

---

## Next Steps (Этап 2)

**После утверждения этой спецификации:**

1. ✅ Миграция БД: добавить поля `apif_*`
2. ✅ Модуль `sync_api_football.py`:
   - Добавить функции `_save_to_db()`
   - Добавить `enrich_match_with_api_football(match_id)`
   - CLI флаг `--fill-gaps`
3. ✅ Team ID mapping: таблица или search logic
4. ✅ Интеграция в `ai_generator.py`:
   - Читать `apif_*` поля из БД
   - Добавить в промпт
5. ✅ Ограничить `sync_matches.py` на today+tomorrow
6. ✅ Тесты: `tests/test_api_football_integration.py`

---

## Changelog

- **2026-02-11:** Этап 1 завершён — исследование, fetch функции, примеры JSON
- **TBD:** Этап 2 — DB integration, gap filling, AI integration
