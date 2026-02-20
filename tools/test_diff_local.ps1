param(
    [switch]$SkipPytest,
    [switch]$RunBot
)

$ErrorActionPreference = "Stop"

Write-Host "=== Локальная проверка diff ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Host "Файл .env не найден." -ForegroundColor Red
    Write-Host "Создайте его из .env.example и заполните TELEGRAM_TOKEN." -ForegroundColor Yellow
    exit 1
}

if (-not $SkipPytest) {
    Write-Host ""
    Write-Host "1) Запуск тестов pytest -q..." -ForegroundColor Cyan
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Тесты упали. Останавливаю сценарий." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "Тесты прошли успешно." -ForegroundColor Green
} else {
    Write-Host "pytest пропущен флагом -SkipPytest." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "2) Ручной smoke-check в Telegram:" -ForegroundColor Cyan
Write-Host "   - Спорт -> Футбол -> Дата -> Матч -> Назад -> Назад -> Назад"
Write-Host "   - Ожидается: детали -> список матчей -> выбор даты -> выбор спорта"
Write-Host "   - Ветка 'Мои анализы': спорт -> дата -> матч -> Назад (возврат в купленные экраны)"

if ($RunBot) {
    Write-Host ""
    Write-Host "3) Запуск бота (python main.py)..." -ForegroundColor Cyan
    python main.py
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Готово. Для запуска бота выполните: python main.py" -ForegroundColor Green
