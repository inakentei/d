#СБОРКА АРТЕФАКТА
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .

#Скачиваем и компилируем библиотеки (артефакт сборки)
RUN pip install --no-cache-dir --target=/build/dependencies -r requirements.txt

#УПАКОВКА В КОНТЕЙНЕР И ДЕПЛОЙ
FROM python:3.11-slim AS runner
WORKDIR /app

# Устанавливаем curl (нужен для health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

#Берем сохраненный артефакт (библиотеки) и упаковываем в контейнер
COPY --from=builder /build/dependencies /app
COPY app.py .

ENV PYTHONPATH=/app
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:10000/health || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
