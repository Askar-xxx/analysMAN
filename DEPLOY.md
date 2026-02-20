# Деплой Sports Bot — инструкция

## Архитектура

```
GitHub (код)
    │
    ├── push в main
    │       │
    │   GitHub Actions
    │       ├── CI: flake8 + pytest
    │       ├── Build Docker image
    │       ├── Push → Docker Hub
    │       └── SSH → сервер → docker compose up
    │
    └── VPS Timeweb Cloud (Нидерланды)
            └── Docker контейнер
                    ├── main.py          (Telegram бот)
                    └── da_polling.py    (DA listener, фоновый процесс)
```

---

## Сервер

- **Провайдер:** Timeweb Cloud
- **Локация:** Нидерланды (Амстердам)
- **ОС:** Ubuntu 22.04 LTS
- **IP:** 72.56.119.31
- **Пользователь:** root

### Подключение
```bash
ssh root@72.56.119.31
```

### Структура файлов на сервере
```
~/sports-bot/
    ├── docker-compose.yml   # конфигурация контейнера
    ├── .env                 # секреты (НЕ в git)
    └── sports_bot.db        # база данных SQLite (персистентная)
```

---

## Локальная разработка

### Установка
```bash
pip install -r requirements.txt
cp .env.example .env
# Заполнить .env реальными значениями
```

### Запуск
```bash
python main.py          # Telegram бот
python da_polling.py    # DonationAlerts listener (отдельный терминал)
```

### Получение/обновление DA токенов
```bash
python da_oauth.py
# Откроет браузер → авторизация → токены запишутся в .env автоматически
```

### Тесты и линтинг
```bash
python -m pytest tests/ -v
flake8 . --max-line-length=120 --exclude=.git,__pycache__,.venv,venv
```

---

## Docker (локальная сборка)

```bash
# Собрать образ
docker build -t sports-bot .

# Запустить
docker compose up -d

# Логи
docker compose logs -f

# Остановить
docker compose down

# Перезапустить с новым .env
docker compose up -d --force-recreate
```

---

## CI/CD (GitHub Actions)

### Как работает

**При каждом `git push` в `main`:**
1. `.github/workflows/deploy.yml` запускается автоматически
2. Вызывает `ci.yml` — lint + tests (если падают — деплой отменяется)
3. Логинится в Docker Hub
4. Собирает Docker образ и пушит на Docker Hub:
   - `xwavex2000/sports-bot:latest`
   - `xwavex2000/sports-bot:<sha коммита>`
5. По SSH заходит на сервер и выполняет:
   ```bash
   docker login
   docker compose pull
   docker compose up -d --remove-orphans
   docker image prune -f
   ```

**При pull request в `main`:**
- Запускается только `ci.yml` (lint + tests), деплоя нет

### GitHub Secrets (Settings → Secrets → Actions)

| Secret               | Описание                                      |
|----------------------|-----------------------------------------------|
| `TELEGRAM_TOKEN`     | Токен Telegram бота                           |
| `DEEPSEEK_API_KEY`   | Ключ DeepSeek API                             |
| `THESPORTSDB_KEY`    | Ключ TheSportsDB Premium API                  |
| `DA_CLIENT_ID`       | DonationAlerts Client ID                      |
| `DA_CLIENT_SECRET`   | DonationAlerts Client Secret                  |
| `DA_ACCESS_TOKEN`    | DonationAlerts Access Token                   |
| `DA_PROFILE_URL`     | Ссылка на страницу донатов                    |
| `ANALYSIS_PRICE_RUB` | Цена анализа в рублях                         |
| `ADMIN_ID`           | Telegram ID админа(ов), через запятую         |
| `SUPPORT_USERNAME`   | Username поддержки                            |
| `DOCKER_HUB_USERNAME`| Логин Docker Hub                              |
| `DOCKER_HUB_TOKEN`   | Access Token Docker Hub (Read & Write)        |
| `SSH_HOST`           | IP сервера (72.56.119.31)                     |
| `SSH_USERNAME`       | Пользователь SSH (root)                       |
| `SSH_PRIVATE_KEY`    | Приватный SSH ключ (без passphrase)           |

---

## Управление ботом на сервере

```bash
# Статус
docker compose -f ~/sports-bot/docker-compose.yml ps

# Логи в реальном времени
docker compose -f ~/sports-bot/docker-compose.yml logs -f

# Перезапуск
docker compose -f ~/sports-bot/docker-compose.yml restart

# Остановить
docker compose -f ~/sports-bot/docker-compose.yml down

# Обновить вручную (без CI/CD)
cd ~/sports-bot
docker compose pull
docker compose up -d --remove-orphans
```

---

## Обновление секретов (.env на сервере)

Если нужно изменить переменные (например обновить DA токены):

```bash
nano ~/sports-bot/.env
# Внести изменения, сохранить (Ctrl+O, Enter, Ctrl+X)

docker compose -f ~/sports-bot/docker-compose.yml up -d --force-recreate
```

---

## Обновление DA токенов (OAuth)

Токены DA живут ~1 год. Когда истекут:

```bash
# Локально
python da_oauth.py
# Откроет браузер → авторизация → .env обновится автоматически

# Затем скопировать новые токены на сервер
nano ~/sports-bot/.env
# Вставить новые DA_ACCESS_TOKEN и DA_REFRESH_TOKEN

docker compose -f ~/sports-bot/docker-compose.yml up -d --force-recreate
```
