FROM python:3.11-slim

WORKDIR /app

# Системные зависимости: шрифты для PNG-рендеринга + curl для healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python (отдельным слоем для кэширования)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходники
COPY . .

# Директории для персистентных данных (монтируются как volume)
RUN mkdir -p analysis_cache temp logs

# По умолчанию запускаем бота; для listener переопределяется в docker-compose
CMD ["python", "main.py"]
