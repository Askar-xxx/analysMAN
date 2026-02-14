Контекст (коротко)

------------------

Ты уже выполнил часть работ: изменил сигнатуру ai\_generator.generate\_match\_analysis(match\_data: dict), добавил dynamic CONTEXT\_FIELDS, поднял лимиты токенов, провёл миграцию столбца round, все тесты проходят. Текущая проблема — анализы выходят абстрактными потому, что в контексте нет реальных статистических данных (H2H, турнирная таблица, форма игроков и т.п.).



Цель этой сессии

----------------

Реализовать интеграцию H2H и standings (таблицы лиги) в пайплайн sync → DB → formatter → prompt, начиная с \*\*добавления столбцов в БД и миграции\*\* и заканчивая тестами и обновлением ANALYSIS\_PROMPT.md. Всё должно быть масштабируемо: adapter для API, каноническая модель, кеширование/TTL, и строгие правила для промпта (не выдумывать чисел, указывать источник).



Чего ожидают в результате (acceptance criteria)

------------------------------------------------

1\. В таблице `matches` добавлены колонки:

&nbsp;  - `h2h\_json` (TEXT, raw json от провайдера)

&nbsp;  - `h2h\_fetched\_at` (TEXT, ISO timestamp)

&nbsp;  - `standings\_json` (TEXT)

&nbsp;  - `standings\_fetched\_at` (TEXT)

&nbsp;  Миграция должна быть безопасной (backup БД, idempotent ALTER TABLE).



2\. В `sync\_matches.py` реализованы:

&nbsp;  - `fetch\_h2h(match\_row\_or\_dict) -> dict|None`: вызывает TheSportsDB (или адаптер), возвращает нормализованный raw json и сохраняет `h2h\_json` + `h2h\_fetched\_at` в БД.

&nbsp;  - `fetch\_standings(match\_row\_or\_dict) -> dict|None`: вызывает lookuptable для лиги/сезона, сохраняет `standings\_json` + `standings\_fetched\_at`.

&nbsp;  - `enrich\_matches()` интегрирует вызовы и вызывает `enrich\_matches()` для всех матчей без `h2h\_json`/`standings\_json` либо устаревших по TTL.



&nbsp;  Основные контрактные правила:

&nbsp;  - fetch\_\* не должен ломать sync в случае ошибок сети — логировать и возвращать None.

&nbsp;  - Учитывать rate limit: throttle / backoff (экспоненциальный), и использовать кеш/TTL.

&nbsp;  - Если provider возвращает пустой результат — сохранить пустой JSON и пометку `table\_missing=true` в соответствующем поле метаданных.



3\. В `ai\_generator.py` реализованы:

&nbsp;  - `\_format\_h2h(h2h\_json) -> str` — компактный человекочитаемый блок: последние N (по умолчанию 5) матчей с датой, счётом и турниром, плюс агрегаты (wins/draws/losses, avg goals). Указывать источник и fetched\_at.

&nbsp;  - `\_format\_standings(standings\_json, team\_id) -> str` — строка: position, points, goal\_diff, played, last\_5\_form (W-L-D...). Указывать источник и fetched\_at.

&nbsp;  - Обновить `CONTEXT\_FIELDS` чтобы включать `h2h\_summary`, `standings\_summary`, `h2h\_fetched\_at`, `standings\_fetched\_at`.



4\. Обновления ANALYSIS\_PROMPT.md:

&nbsp;  - Секции 4 (H2H) и 6 (таблица/положение) обязаны выводиться только на основе данных из DB. Если данных нет — прямо указывать: "Данных не предоставлено: lookuptable.php для l={idLeague}".

&nbsp;  - Добавить правила: `DO NOT INVENT NUMBERS`, `CITE SOURCE for each numeric fact`.



5\. Тесты:

&nbsp;  - Unit-тесты для миграции (проверка добавления колонок idempotent).

&nbsp;  - Mock-тесты fetch\_h2h/fetch\_standings (используя фиктивные JSON) — проверяют сохранение в БД и правильность fetched\_at.

&nbsp;  - Тесты форматтеров — входной фиктивный JSON → ожидаемый краткий блок строки.

&nbsp;  - Интеграционный тест: запустить enrich\_matches на тестовой БД и проверить, что `h2h\_json` и `standings\_json` появились и что `generate\_match\_analysis` использует `\_format\_\*` и добавляет реальные данные в контекст.



Технические детали / пример миграции SQL

---------------------------------------

(в sqlite можно добавлять колонки)

1\) Сделай backup: `cp sports\_bot.db sports\_bot.db.bak`

2\) ALTER (idempotent): для каждого столбца выполнить команду, если столбца нет:

```sql

ALTER TABLE matches ADD COLUMN h2h\_json TEXT;

ALTER TABLE matches ADD COLUMN h2h\_fetched\_at TEXT;

ALTER TABLE matches ADD COLUMN standings\_json TEXT;

ALTER TABLE matches ADD COLUMN standings\_fetched\_at TEXT;



