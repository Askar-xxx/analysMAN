# Manual QA: anti-hang (таблица/финал/progress UI)

## Включение флагов
Перед запуском установите нужные env-переменные (остальные оставьте `0`):

```powershell
$env:FORCE_PROGRESS_BADREQUEST="1"
$env:FORCE_TABLE_TIMEOUT="0"
$env:FORCE_TABLE_ERROR="0"
$env:FORCE_SEND_ERROR="0"
```

Доступные флаги:
- `FORCE_PROGRESS_BADREQUEST=1` — форсирует `BadRequest` на update progress.
- `FORCE_TABLE_TIMEOUT=1` — форсирует timeout в шаге `table_render`.
- `FORCE_TABLE_ERROR=1` — форсирует ошибку в шаге `table_render`.
- `FORCE_SEND_ERROR=1` — форсирует ошибку отправки финального экрана.

По умолчанию все флаги выключены (`0`).

## Что запускать
```powershell
python -m pytest -q
python -m pytest -q tests/test_webhook_server_anti_hang.py
```

## Что ожидать
- `FORCE_PROGRESS_BADREQUEST=1`:
  - pipeline не падает;
  - в логах есть `progress_update_end ... status=error`;
  - в итоговом логе `progress_ui_error_nonfatal=True`.
- `FORCE_TABLE_TIMEOUT=1`:
  - pipeline завершается;
  - в логах есть `event=table_stage_timeout`;
  - итог: `result_mode=text_only_table_timeout`.
- `FORCE_TABLE_ERROR=1`:
  - pipeline завершается;
  - итог: `result_mode=text_only_table_error`.
- `FORCE_SEND_ERROR=1`:
  - нет зависания;
  - отправляется fallback-текст;
  - в логе есть `result_mode=text_only_table_error`.
