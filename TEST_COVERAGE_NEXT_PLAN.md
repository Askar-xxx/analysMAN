# План дальнейшего покрытия тестами после текущего этапа

## Кратко

Следующий этап делаем слоями по риску и по отдаче. После уже закрытых `database.py`, `da_polling.py` и базового слоя `match_signals.py` дальше идём так:

1. Добиваем оставшиеся read/query/helper-ветки в `database.py`
2. Добиваем живой runtime-контур в `da_polling.py`
3. Углубляем ветвления скоринга в `match_signals.py`
4. Только потом берём `user_handlers.py` как отдельный большой этап
5. `payment_handlers.py` пока не расширяем: модуль legacy, тестировать там кроме заглушки нечего

Цель этапа: поднять покрытие не "по файлам", а по реальным рискам регрессий в пользовательском и финансовом флоу.

## Что считаем уже закрытым

Текущий план исходит из того, что уже есть и не требует повторной работы:

- `database.py`
  - `purchase_analysis`
  - `refund_purchase`
  - `complete_balance_topup`
  - `get_or_create_user`
  - `add_balance`
  - `get_user_balance`
  - `acquire_generation_job`
  - `finish_generation_job`
  - `wait_for_match_analysis`
  - `expire_pending_topups`
  - `is_donation_event_used`
  - `cleanup_old_purchases`
  - `expire_old_pending_purchases`
- `da_polling.py`
  - `process_donation` для живого topup-flow
  - `_handle_topup_donation`
  - `_is_transient_http_error`
  - `_log_network_error` базово
- `match_signals.py`
  - базовые pure helpers
  - `build_match_signals()` на полном и пустом наборе данных
- `payment_handlers.py`
  - только smoke на active stub

## Этап 1. Добить оставшиеся ветки `database.py`

### Файлы

- `database.py`
- новый или расширяемый файл:
  - `tests/test_database_queries.py`

### Решение

Не раздувать текущий `tests/test_database.py` бесконечно. Следующий слой вынести в отдельный файл `tests/test_database_queries.py`, чтобы разделить:

- `test_database.py` -> финансовая/атомарная логика
- `test_database_queries.py` -> выборки, чтение, helper CRUD

### Что покрыть обязательно

#### 1. Матчевые выборки

- `get_match_by_id`
  - существующий матч
  - несуществующий матч -> `None`
- `get_all_matches`
  - возвращает список матчей по текущему контракту
- `get_matches_by_date`
  - фильтрация по `sport` и `match_date`
- `get_today_matches`
  - матч сегодня входит
  - матч не сегодня не входит
- `get_today_tomorrow_matches`
  - сегодня и завтра входят
  - более дальние даты не входят
- `get_available_dates_with_matches`
  - возвращает уникальные даты
  - сортировка корректная
- `get_matches_by_date_filtered`
  - только активные/релевантные записи по текущему контракту функции

#### 2. Данные по покупкам

- `get_purchased_matches_by_user`
  - возвращает только `paid`
  - содержит `purchase_date`
- `get_purchased_matches_by_sport`
  - фильтрация по спорту
- `get_purchased_dates_by_sport`
  - уникальные даты для купленных матчей по спорту
- `has_purchased_analysis`
  - `True` для `paid`
  - `False` для `pending`
  - `False` для отсутствующей покупки
- `get_last_paid_purchase_by_user`
  - берёт именно последнюю `paid`
  - игнорирует `pending/refunded`

#### 3. Пользовательские выборки

- `get_user_full_info`
  - пользователь с покупками и топапами
  - пользователь без данных
  - несуществующий пользователь -> `None`
- `find_users`
  - по части `username`
  - по `user_id` строкой
  - пустой результат
- `get_user_stats`
  - корректные агрегаты по балансу и числу покупок
- `get_all_users`
  - возвращает всех пользователей

#### 4. Topup helper-функции

- `update_topup_instruction_message`
  - `instruction_message_id` реально обновляется
- `update_topup_return_target`
  - `return_match_id` и `return_match_source` сохраняются
- `get_topup_by_token`
  - возвращает только актуальный `pending`
  - истёкший `pending` не возвращает
  - `paid` не возвращает
- `get_any_topup_by_token`
  - возвращает и `pending`, и `paid`
- `get_pending_topup_by_user`
  - берёт актуальный и последний по времени
- `get_all_pending_topups`
  - возвращает только актуальные `pending`
  - сортировка по `expires_at`, `created_at`, `id`

#### 5. Match CRUD/helper

- `sync_match_from_api`
  - новый матч создаётся
  - повтор по `api_event_id` не создаёт дубль
  - fallback по `team1/team2/date` тоже не создаёт дубль
- `update_match_analysis`
  - записывает `analysis_text`
  - записывает `analysis_png_path`
- `clear_match_analysis`
  - очищает поля и возвращает старый путь к PNG
- `delete_match`
  - удаляет существующий матч
  - не падает на несуществующем
- `delete_finished_matches_without_purchases`
  - удаляет завершённые без покупок
  - не трогает матч с покупкой
  - удаляет PNG только у реально удалённых матчей

#### 6. Admin helper-функции

- `add_admin`
  - запись создаётся
- `remove_admin`
  - запись удаляется
- `is_admin`
  - `True/False` корректно
- `get_all_admins`
  - возвращает список админов
- `reset_user_balance`
  - существующий пользователь -> `True`, баланс 0
  - отсутствующий пользователь -> `False`

### Тестовая инфраструктура

Использовать ту же схему, что уже применена:

- `tmp_path + sqlite3.connect(..., check_same_thread=False)`
- реальный вызов `database._init_db_tables(conn)`
- monkeypatch для `database.get_db_connection` и `database.get_db`
- одна компактная фикстура с helper-функциями создания пользователя/матча/покупки/topup

### Критерий готовности этапа

- Все перечисленные функции имеют отдельные тесты
- Нет смешения финансовой логики с query-тестами
- `pytest tests/test_database.py tests/test_database_queries.py -q` зелёный

## Этап 2. Добить runtime-контур `da_polling.py`

### Файлы

- `da_polling.py`
- расширяем:
  - `tests/test_da_polling.py`

### Решение

Тестируем только живой контур:

- topup-flow
- сетевые helper'ы
- polling loop
- `get_recent_donations`

Legacy purchase-flow через DA не расширяем, кроме минимальной smoke-защиты, потому что этот сценарий не является рабочим продуктовым флоу.

### Что покрыть обязательно

#### 1. `get_recent_donations`

- `limit` меньше 1 -> clamp к 1
- `limit` больше 30 -> clamp к 30
- `requests.get` вызывается с нужным URL и Bearer token
- `response.json()['data']` режется до `safe_limit`
- `raise_for_status()` действительно вызывается

#### 2. `process_donation`

Добавить ещё ветки:

- `donation_data` без `message` -> корректный `False`
- `donation_data` без `amount` или `id` -> `False`, без проброса исключения
- токен найден, но topup expired/не найден -> `False`
- purchase-ветку не развивать глубоко, но оставить один smoke-тест:
  - если `database.get_purchase_by_token()` вернул объект, вызывается `_handle_purchase_donation()`

#### 3. `_handle_topup_donation`

Добить детали:

- `instruction_message_id is None` -> только `send_message`
- `return_match_id` отсутствует -> кнопки возврата к матчу нет
- если и `edit_message_text`, и `send_message` кидают исключения, функция всё равно завершает без падения наружу и возвращает `True` только если `complete_balance_topup` был успешен
- проверить текст на правильное склонение: `1 анализ`, `2-4 анализа`, `5 анализов`

#### 4. `_log_network_error`

Покрыть реальное поведение функции:

- `count < threshold` -> `WARNING`
- `count == threshold` -> `ERROR`
- `count > threshold`, но не кратно `threshold * 4` -> `WARNING`
- `count % (threshold * 4) == 0` -> повторный `ERROR`

#### 5. `poll_donations`

Сделать управляемые тесты цикла через monkeypatch:

- happy path:
  - `get_recent_donations()` вернул список
  - обрабатываются только новые donation id
  - старые `processed_ids` повторно не идут в `process_donation`
- transient network error:
  - исключение `requests.HTTPError` со статусом `500`
  - идёт лог через `_log_network_error`
- `401`/refresh path:
  - вызывается `da_oauth.refresh_access_token`
- обычное исключение:
  - цикл не рушится
- чтобы тест не зависал:
  - monkeypatch `asyncio.sleep` на функцию, которая после первого/второго круга кидает `CancelledError`
  - в тесте `asyncio.run(...)` ожидать `CancelledError` как controlled stop

### Осознанно вне scope этого этапа

- Глубокая проверка `_handle_purchase_donation`
- Рефакторинг `da_polling.py`
- Удаление legacy purchase-ветки

### Критерий готовности этапа

- `tests/test_da_polling.py` покрывает живой topup-flow и polling loop
- Нет реальных сетевых вызовов
- Нет зависающих async-тестов

## Этап 3. Углубить ветки `match_signals.py`

### Файлы

- `match_signals.py`
- расширяем:
  - `tests/test_match_signals.py`

### Решение

Сохраняем подход “pure functions only”. Здесь нужны не smoke-тесты, а точечная проверка бизнес-эвристик по веткам скоринга.

### Что покрыть обязательно

#### 1. `_parse_date`

- `YYYY-MM-DD`
- `YYYY-MM-DD HH:MM:SS`
- мусор -> `None`

#### 2. `_detect_match_loser`

- home проиграл
- away проиграл
- ничья
- некорректный score

#### 3. `_build_derby_signal`

Отдельные тесты на вклад каждого признака:

- одна страна
- один город
- `len(h2h) >= 5`
- высокий `avg_cards`
- высокий `avg_fouls`
- пустые данные -> fallback reason

#### 4. `_build_motivation_signal`

Отдельные ветки:

- минимальный разрыв по очкам
- близость по рангу
- борьба за верх таблицы
- зона вылета
- cup mode
- поздняя стадия турнира
- серия без побед
- отсутствие данных -> fallback reason

#### 5. `_build_revenge_signal`

- нет `h2h`
- проигрыш в последней очной
- крупное поражение
- свежая очная в пределах 180 дней
- два подряд поражения одной команды
- нет сильного сигнала -> fallback reason

#### 6. `_build_confidence`

Пороговые значения:

- низкая
- средняя
- высокая

### Критерий готовности этапа

- Каждая private helper-функция, влияющая на score/reasons, имеет хотя бы один прямой тест
- `build_match_signals()` остаётся финальным интеграционным тестом поверх этих веток

## Этап 4. После этого брать `user_handlers.py` как отдельную задачу

### Файлы

- `user_handlers.py`
- будущий набор:
  - `tests/test_user_handlers_navigation.py`
  - `tests/test_user_handlers_purchase.py`
  - `tests/test_user_handlers_topup.py`

### Решение

Не начинать `user_handlers.py`, пока не завершены Этапы 1-3. Это слишком большой stateful-модуль, и туда надо заходить уже с хорошим фундаментом по БД и DA.

### Когда считать, что можно начинать `user_handlers.py`

После зелёного состояния:

- `tests/test_database.py`
- `tests/test_database_queries.py`
- `tests/test_da_polling.py`
- `tests/test_match_signals.py`

### Первый scope для `user_handlers.py`

Только high-risk сценарии:

- purchase with balance
- back/menu history
- purchased-flow
- topup/check_balance flow
- callback parsing на критичных `callback_data`

## Изменения в публичных интерфейсах

На этом этапе изменений в production API не планируется.

Допускаются только:

- новые тестовые helper-функции/фикстуры в `tests/`
- возможно новый файл `tests/test_database_queries.py`

Никаких изменений сигнатур production-функций:

- в `database.py`
- в `da_polling.py`
- в `match_signals.py`

## Порядок реализации

### Шаг 1

Добавить `tests/test_database_queries.py`

### Шаг 2

Прогон:

```bash
python -m pytest tests/test_database.py tests/test_database_queries.py -q
```

### Шаг 3

Расширить `tests/test_da_polling.py` по `get_recent_donations` и `poll_donations`

### Шаг 4

Прогон:

```bash
python -m pytest tests/test_da_polling.py -q
```

### Шаг 5

Расширить `tests/test_match_signals.py` по веткам скоринга

### Шаг 6

Прогон:

```bash
python -m pytest tests/test_match_signals.py -q
```

### Шаг 7

Полный прогон:

```bash
python -m pytest -q
```

## Приёмочные критерии

Этап считается выполненным, если одновременно соблюдены все условия:

- новые тесты не меняют production-код
- тесты не завязаны на интернет и внешние сервисы
- нет flaky async-тестов
- нет зависающих тестов polling-цикла
- все новые тесты проходят локально
- полный `pytest -q` остаётся зелёным

## Явные допущения и выбранные defaults

- Прямая покупка анализа через DA не является актуальным продуктовым флоу и не приоритизируется!! 
- `payment_handlers.py` остаётся вне углублённого тестирования, потому что сейчас это legacy-заглушка.
- `user_handlers.py` не берётся в этот этап.
- Для `poll_donations()` controlled stop через `CancelledError` является допустимым тестовым способом остановить бесконечный цикл.
- Новые query-тесты для БД выносятся в отдельный файл, а не дописываются в текущий финансовый набор.
