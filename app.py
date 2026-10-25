import os
import time
import shutil
import psutil
import psycopg2
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from fastapi.responses import HTMLResponse
from prometheus_client import generate_latest, Counter, Gauge, REGISTRY

DATABASE_URL = os.getenv("DATABASE_URL")

# Начало замера CPU времени для метрики cpu_usage_seconds_total
START_TIME = time.time()
START_CPU_TIME = psutil.Process(os.getpid()).cpu_times().user + psutil.Process(os.getpid()).cpu_times().system

# БАЗА ДАННЫХ (СОХРАНЕНИЕ)
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    # Таблица для хранения общего счетчика
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicks_store (
            id SERIAL PRIMARY KEY,
            count INT NOT NULL
        );
    """)
    # Таблица для логирования каждого клика (нужно для расчета кликов в час)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicks_log (
            id SERIAL PRIMARY KEY,
            click_time TIMESTAMP NOT NULL
        );
    """)
    cursor.execute("SELECT COUNT(*) FROM clicks_store;")
    if cursor.fetchone() == 0:
        cursor.execute("INSERT INTO clicks_store (count) VALUES (0);")
    conn.commit()
    cursor.close()
    conn.close()

def get_clicks():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT count FROM clicks_store WHERE id = 1;")
        res = cursor.fetchone()
        cursor.close()
        conn.close()
        return res[0] if res else 0
    except:
        return 0

def increment_clicks():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    # Обновляем общий счетчик
    cursor.execute("UPDATE clicks_store SET count = count + 1 WHERE id = 1 RETURNING count;")
    res = cursor.fetchone()
    # Логируем текущий клик для почасовой статистики
    cursor.execute("INSERT INTO clicks_log (click_time) VALUES (%s);", (datetime.now(),))
    conn.commit()
    cursor.close()
    conn.close()
    return res[0] if res else 0

def get_hourly_stats():
    """Возвращает статистику кликов по часам за последние 24 часа для таблицы."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE_TRUNC('hour', click_time) as hour, COUNT(*) 
        FROM clicks_log 
        WHERE click_time >= NOW() - INTERVAL '24 hours'
        GROUP BY hour
        ORDER BY hour DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_clicks_count_inside_interval(hours_interval: int):
    """Считает количество кликов за последние X часов."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM clicks_log WHERE click_time >= NOW() - INTERVAL '%s hours';", 
        (hours_interval,)
    )
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return res[0] if res else 0

# LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# ПРОМЕТЕУС МЕТРИКИ
MEM_USAGE = Gauge("app_container_memory_usage_bytes", "Потребляемая память контейнера в байтах")
CPU_USAGE_TOTAL = Gauge("app_container_cpu_usage_seconds_total", "Общее потребленное CPU время в секундах")

# Доступные ресурсы
MEM_LIMIT = Gauge("app_container_memory_limit_bytes", "Лимит памяти контейнера (всего доступно)")
MEM_HOST_AVAILABLE = Gauge("app_host_memory_available_bytes", "Доступная память на хосте")
DISK_FREE = Gauge("app_disk_free_bytes", "Свободное место на диске")

# Посещения (клики)
VISITS_1H = Gauge("app_visits_last_hour", "Количество кликов за последний час")
VISITS_24H = Gauge("app_visits_last_24h", "Количество кликов за последние 24 часа")

@app.get("/metrics")
def metrics():
    process = psutil.Process(os.getpid())
    
    # Считаем потребляемые ресурсы
    MEM_USAGE.set(process.memory_info().rss)
    current_cpu_time = process.cpu_times().user + process.cpu_times().system
    CPU_USAGE_TOTAL.set(current_cpu_time)
    
    # Считаем доступные ресурсы
    virtual_mem = psutil.virtual_memory()
    MEM_LIMIT.set(virtual_mem.total)
    MEM_HOST_AVAILABLE.set(virtual_mem.available)
    
    _, _, free_disk = shutil.disk_usage("/")
    DISK_FREE.set(free_disk)
    
    # Бизнес-метрики из БД
    VISITS_1H.set(get_clicks_count_inside_interval(1))
    VISITS_24H.set(get_clicks_count_inside_interval(24))
    
    return Response(content=generate_latest(REGISTRY), media_type="text/plain")

# HEALTH CHECK
@app.get("/health")
def health_check():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return Response(
            content=f"unhealthy: {str(e)}", 
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )

# ОБЩИЙ ШАБЛОН ДЛЯ НАВИГАЦИИ 
def get_layout(content: str, active_tab: str) -> str:
    main_active = "active" if active_tab == "main" else ""
    status_active = "active" if active_tab == "status" else ""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Лабораторная работа</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; margin: 0; padding-top: 50px; background-color: #f4f7f6; color: #333; }}
            .nav-bar {{ margin-bottom: 40px; }}
            .nav-btn {{ padding: 10px 20px; font-size: 16px; margin: 0 10px; color: #007bff; background: white; border: 2px solid #007bff; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; transition: 0.3s; }}
            .nav-btn:hover {{ background-color: #007bff; color: white; }}
            .nav-btn.active {{ background-color: #007bff; color: white; }}
            .container {{ max-width: 650px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: left; }}
            .center {{ text-align: center; }}
            .btn-click {{ padding: 15px 35px; font-size: 24px; color: white; background-color: #28a745; border: none; border-radius: 5px; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
            .btn-click:active {{ transform: scale(0.98); background-color: #218838; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #f8f9fa; }}
            .metrics-grid {{ text-align: left; margin-top: 15px; }}
            .metrics-item {{ margin-bottom: 8px; font-size: 15px; }}
        </style>
    </head>
    <body>
        <div class="nav-bar">
            <a href="/" class="nav-btn {main_active}">Главная</a>
            <a href="/status" class="nav-btn {status_active}">Метрики статус</a>
        </div>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """

# ИНТЕРФЕЙС

@app.get("/", response_class=HTMLResponse)
def read_root():
    clicks = get_clicks()
    content = f"""
        <div class="center">
            <h1>Кликер для лабораторной</h1>
            <p>Всего нажатий сохранено в базе данных: <strong id="counter" style="font-size: 24px; color: #28a745;">{clicks}</strong></p>
            <br>
            <button class="btn-click" onclick="clickMe()">ТЫК!</button>
        </div>

        <script>
            async function clickMe() {{
                const response = await fetch('/click', {{ method: 'POST' }});
                const data = await response.json();
                document.getElementById('counter').innerText = data.clicks;
            }}
        </script>
    """
    return get_layout(content, active_tab="main")

@app.post("/click")
def click_endpoint():
    new_count = increment_clicks()
    return {"clicks": new_count}

@app.get("/status", response_class=HTMLResponse)
def status_page():
    process = psutil.Process(os.getpid())
    
    # Расчет ресурсов
    ram_used = process.memory_info().rss / (1024 * 1024)
    ram_total = psutil.virtual_memory().total / (1024 * 1024)
    ram_host_avail = psutil.virtual_memory().available / (1024 * 1024)
    _, _, disk_free = shutil.disk_usage("/")
    disk_free_gb = disk_free / (1024 * 1024 * 1024)
    
    clicks_1h = get_clicks_count_inside_interval(1)
    clicks_24h = get_clicks_count_inside_interval(24)
    
    # Сборка таблицы кликов по часам
    hourly_rows = get_hourly_stats()
    table_html = ""
    if not hourly_rows:
        table_html = "<p style='color: #777;'>За последние 24 часа кликов не зафиксировано.</p>"
    else:
        table_html = "<table><tr><th>Час</th><th>Количество кликов</th></tr>"
        for row in hourly_rows:
            formatted_hour = row[0].strftime("%Y-%m-%d %H:00")
            table_html += f"<tr><td>{formatted_hour}</td><td>{row[1]}</td></tr>"
        table_html += "</table>"

    content = f"""
        <h2>Мониторинг и статус системы</h2>
        
        <div class="metrics-grid">
            <h3>📊 Ресурсы</h3>
            <div class="metrics-item"><b>Потребляемая память приложения:</b> {ram_used:.2f} MB</div>
            <div class="metrics-item"><b>Доступный лимит памяти контейнера:</b> {ram_total:.2f} MB</div>
            <div class="metrics-item"><b>Доступная память на хосте:</b> {ram_host_avail:.2f} MB</div>
            <div class="metrics-item"><b>Свободное место на диске:</b> {disk_free_gb:.2f} GB</div>
            
            <h3>📈 Статистика кликов</h3>
            <h3>Кликов за последний час: {clicks_1h}<h3>
            <h3>Кликов за 24 часа: {clicks_24h}<h3>
            """
    return get_layout(content, active_tab="status")