#!/bin/bash

# Issue #1: Review спецификации
gh issue create \
  --title "Прочитать спецификацию и ответить на 5 вопросов" \
  --body "## Что сделать

Прочитать файл \`API_FOOTBALL_SPEC.md\` и дать ответы на вопросы в конце:

1. **Injuries:** хранить для обеих команд в одном JSON или раздельно?
2. **Top scorers:** брать топ-10 лиги или топ-3 по каждой команде?
3. **Данные:** всё в JSON или ключевые поля отдельно?
4. **Team ID:** создать таблицу mapping или искать по названию?
5. **Приоритет:** если есть данные от TheSportsDB и API-Football — какие использовать?

## Зачем

От ответов зависит как делать Этап 2 (сохранение в БД).

## Файлы

- \`API_FOOTBALL_SPEC.md\` — основной документ
- \`IMPLEMENTATION_REPORT_API_FOOTBALL.md\` — детальный отчёт" \
  --label "documentation,question,priority-high" \
  --milestone "API-Football Phase 2"

# Issue #2: Миграция БД
gh issue create \
  --title "Добавить новые поля в БД для API-Football данных" \
  --body "## Что сделать

Добавить в таблицу \`matches\` новые поля:

\`\`\`sql
ALTER TABLE matches ADD COLUMN apif_stats_json TEXT;
ALTER TABLE matches ADD COLUMN apif_stats_fetched_at TEXT;
ALTER TABLE matches ADD COLUMN apif_injuries_json TEXT;
ALTER TABLE matches ADD COLUMN apif_injuries_fetched_at TEXT;
ALTER TABLE matches ADD COLUMN apif_full_standings_json TEXT;
ALTER TABLE matches ADD COLUMN apif_standings_fetched_at TEXT;
\`\`\`

## Чеклист

- [ ] Создать файл \`migrations/add_apif_fields.sql\`
- [ ] Протестировать на dev БД
- [ ] Обновить \`database.py\` (читать/писать новые поля)
- [ ] Добавить в \`init_db()\` для новых установок

## Зависимости

Ждём ответы на Issue #1" \
  --label "database,migration" \
  --milestone "API-Football Phase 2"

# Issue #3: Team ID mapping
gh issue create \
  --title "Сделать связку между ID команд TheSportsDB и API-Football" \
  --body "## Проблема

TheSportsDB и API-Football используют разные ID для команд:
- TheSportsDB: Chelsea = \`133612\`
- API-Football: Chelsea = \`49\`

Нужно научиться конвертировать.

## Варианты решения

**A) Таблица mapping:**
\`\`\`sql
CREATE TABLE team_id_mapping (
  sportsdb_team_id TEXT PRIMARY KEY,
  apif_team_id TEXT NOT NULL,
  team_name TEXT
);
\`\`\`

**B) Поиск по названию:** искать в API-Football по имени команды

**C) Гибрид:** сначала таблица, если нет — поиск

## Что выбрать

Зависит от ответа на вопрос 4 в Issue #1

## Чеклист

- [ ] Выбрать вариант
- [ ] Создать таблицу (если нужно)
- [ ] Написать функцию \`resolve_apif_team_id()\`
- [ ] Тесты" \
  --label "database,enhancement" \
  --milestone "API-Football Phase 2"

# Issue #4: DB integration
gh issue create \
  --title "Добавить сохранение данных API-Football в БД" \
  --body "## Что сделать

Дописать модуль \`sync_api_football.py\`:

### Новые функции

\`\`\`python
def enrich_match_with_api_football(match_id):
    \"\"\"
    Заполнить пробелы в данных для матча.
    1. Проверить что нужно (какие поля пустые)
    2. Запросить из API-Football
    3. Сохранить в БД
    \"\"\"
\`\`\`

### CLI

\`\`\`bash
python sync_api_football.py --fill-gaps
python sync_api_football.py --fill-gaps --dry-run
\`\`\`

## Чеклист

- [ ] Функции для сохранения: \`_save_team_stats_to_db()\`, \`_save_injuries_to_db()\`
- [ ] Основная функция \`enrich_match_with_api_football()\`
- [ ] TTL проверка (не запрашивать если данные свежие)
- [ ] CLI флаг \`--fill-gaps\`
- [ ] Тесты

## Зависимости

Issue #2, #3" \
  --label "feature,core" \
  --milestone "API-Football Phase 2"

# Issue #5: Team ID resolution
gh issue create \
  --title "Функция поиска API-Football team_id по названию команды" \
  --body "## Что сделать

Написать функцию:

\`\`\`python
def resolve_apif_team_id(sportsdb_team_id, team_name):
    \"\"\"
    Найти API-Football team_id.
    
    1. Проверить таблицу team_id_mapping
    2. Если нет → поиск по названию
    3. Сохранить в mapping
    \"\"\"
\`\`\`

## Проблемы

- Команда не найдена
- Несколько похожих (Manchester United vs Manchester City)
- Название изменилось

## Чеклист

- [ ] Реализовать функцию
- [ ] Обработка ошибок
- [ ] Кэширование результатов
- [ ] Тесты на edge cases

## Зависимости

Issue #3" \
  --label "feature,core" \
  --milestone "API-Football Phase 2"

# Issue #6: AI integration
gh issue create \
  --title "Добавить данные API-Football в промпт для AI" \
  --body "## Что сделать

Интегрировать новые данные в генерацию анализов.

### Новые функции в ai_generator.py

\`\`\`python
def _format_apif_stats(stats_json):
    \"\"\"Форматировать статистику: дома 12-5-2, в гостях 8-4-7\"\"\"

def _format_injuries(injuries_json):
    \"\"\"Форматировать травмы: R. Lavia (бедро), C. Gallagher\"\"\"
\`\`\`

### Изменить build_match_context()

- Читать поля \`apif_*\` из БД
- Добавлять в контекст
- Приоритет: API-Football > TheSportsDB (для standings)

## Чеклист

- [ ] Форматтеры для stats, injuries, top scorers
- [ ] Интеграция в \`build_match_context()\`
- [ ] Тестовая генерация с полными данными
- [ ] Проверить качество анализов

## Зависимости

Issue #4" \
  --label "feature,ai" \
  --milestone "API-Football Phase 2"

# Issue #7: Фикс тестов
gh issue create \
  --title "Исправить 6 провалившихся тестов в test_sync_matches.py" \
  --body "## Проблема

После изменений в \`sync_matches.py\` (фильтр today+tomorrow) провалились тесты:
- test_top3_inserts_exactly_3
- test_top3_respects_limit
- test_no_duplicates_on_resync
- test_tracing_fields_present
- test_team_ids_match_api
- test_enrich_h2h_saves_to_db

## Причина

Mock данные создаются со случайными датами, не попадают в фильтр.

## Решение

Обновить моки:
\`\`\`python
today = datetime.now().date()
mock_event['dateEvent'] = today.strftime('%Y-%m-%d')
\`\`\`

## Чеклист

- [ ] Исправить все 6 тестов
- [ ] Запустить: \`pytest tests/test_sync_matches.py -v\`
- [ ] Всё должно пройти ✅" \
  --label "tests,bug" \
  --milestone "API-Football Phase 2"

# Issue #8: Интеграционные тесты
gh issue create \
  --title "Создать интеграционные тесты для полного workflow" \
  --body "## Что сделать

Создать \`tests/test_api_football_integration.py\`:

### Тестовые сценарии

1. **Full flow:** sync матчей → enrich → проверка БД
2. **TTL кэш:** не запрашивать если данные свежие
3. **Team ID resolution:** mapping работает
4. **Quota tracking:** счётчик запросов
5. **Errors:** API недоступен, quota exceeded

### Запуск

\`\`\`bash
pytest tests/test_api_football_integration.py -v
\`\`\`

## Чеклист

- [ ] Написать 5 тестов
- [ ] Использовать моки (не реальный API)
- [ ] Все тесты проходят

## Зависимости

Issue #4" \
  --label "tests,integration" \
  --milestone "API-Football Phase 2"

# Issue #9: Документация
gh issue create \
  --title "Обновить документацию после интеграции" \
  --body "## Что обновить

### README.md
- Раздел \"API-Football Integration\"
- Новые команды: \`--fill-gaps\`
- Примеры использования

### CHANGELOG.md
- Добавить Sprint 2.8: API-Football Integration

### ROADMAP.md
- Отметить Sprint 2.7 как завершённый

## Чеклист

- [ ] README.md
- [ ] CHANGELOG.md
- [ ] ROADMAP.md" \
  --label "documentation" \
  --milestone "API-Football Phase 2"

# Issue #10: Метрики
gh issue create \
  --title "Измерить сколько запросов тратится и как изменилось качество" \
  --body "## Что измерить

### 1. API quota
- Сколько requests на матч? (worst/best/average)
- Работает ли кэш?
- Хватит ли 100 req/day?

### 2. AI costs
- Насколько вырос промпт?
- Стоимость генерации?

### 3. Качество
- Сравнить анализы до/после
- Меньше \"нет данных\"?

## Результат

Создать документ \`API_FOOTBALL_METRICS.md\` с цифрами.

## Чеклист

- [ ] Протестировать на 10+ матчах
- [ ] Собрать метрики
- [ ] Написать отчёт" \
  --label "analytics,documentation" \
  --milestone "API-Football Phase 2"

echo "✅ Все issues созданы!"
