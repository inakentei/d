FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для сборки некоторых пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем список зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY app.py .

# Порт по умолчанию для Render
EXPOSE 10000

# Команда запуска веб-сервера
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
