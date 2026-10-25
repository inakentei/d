import os
import time
import psutil
import psycopg2
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from prometheus_client import generate_latest, Counter, Gauge, REGISTRY

# ----------------- БАЗА ДАННЫХ (СОХРАНЕНИЕ) -----------------
DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    """Создает таблицу для кликов, если её нет."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicks_store (
            id SERIAL PRIMARY KEY,
            count INT NOT NULL
        );
    """)
    # Инициализируем счетчик нулем, если таблица пустая
    cursor.execute("SELECT COUNT(*) FROM clicks_store;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO clicks_store (count) VALUES (0);")
    conn.commit()
    cursor.close()
    conn.close()

def get_clicks():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT count FROM clicks_store WHERE id = 1;")
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return res[0] if res else 0

def increment_clicks():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("UPDATE clicks_store SET count = count + 1 WHERE id = 1 RETURNING count;")
    res = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return res[0] if res else 0

# ----------------- СОВРЕМЕННЫЙ LIFESPAN (ВМЕСТО ON_EVENT) -----------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Логика при старте приложения (STARTUP)
    init_db()
    yield
    # Логика при остановке приложения (SHUTDOWN) если нужна, пишется тут
    pass

# Передаем lifespan в инициализацию FastAPI
app = FastAPI(lifespan=lifespan)

# ----------------- ПРОМЕТЕУС МЕТРИКИ -----------------
# 1. Системные ресурсы
CPU_GAUGE = Gauge("process_cpu_usage_percent", "Текущее потребление CPU в %")
RAM_GAUGE = Gauge("process_ram_usage_bytes", "Текущее потребление RAM в байтах")

# 2. Бизнес-метрика (клики в час / всего кликов)
CLICK_COUNTER = Counter("total_clicks_pressed", "Общее количество кликов по кнопке")

@app.get("/metrics")
def metrics():
    # Обновляем метрики ресурсов перед отдачей
    CPU_GAUGE.set(psutil.cpu_percent())
    RAM_GAUGE.set(psutil.Process(os.getpid()).memory_info().rss)
    
    # Синхронизируем Прометеус-счетчик с реальной БД
    current_db_clicks = get_clicks()
    CLICK_COUNTER._value.set(current_db_clicks)
    
    return Response(content=generate_latest(REGISTRY), media_type="text/plain")

@app.get("/health")
def health_check():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return Response(content=f"unhealthy: {str(e)}", status_code=500)

# ----------------- ИНТЕРФЕЙС (HTML) -----------------
@app.get("/", response_class=HTMLResponse)
def read_root():
    clicks = get_clicks()
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Clicker Web App</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 100px; background-color: #f4f4f9; }}
            .btn {{ padding: 15px 30px; font-size: 24px; color: white; background-color: #007bff; border: none; border-radius: 5px; cursor: pointer; }}
            .btn:active {{ background-color: #0056b3; }}
            h1 {{ color: #333; }}
        </style>
    </head>
    <body>
        <h1>Тыкалка для лабораторной</h1>
        <p>Всего нажатий сохранено в БД: <strong id="counter">{clicks}</strong></p>
        <button class="btn" onclick="clickMe()">ТЫК!</button>

        <script>
            async function clickMe() {{
                const response = await fetch('/click', {{ method: 'POST' }});
                const data = await response.json();
                document.getElementById('counter').innerText = data.clicks;
            }}
        </script>
    </body>
    </html>
    """

@app.post("/click")
def click_endpoint():
    new_count = increment_clicks()
    return {"clicks": new_count}
