"""
main.py — точка входа FastAPI-приложения.

Подключает все роутеры, настраивает CORS.
Swagger UI доступен на http://localhost:8000/docs
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metrics import RequestMetricsMiddleware, render_metrics
from routers import auth, events, notes, templates, analytics, notifications, ai, mcp_calendar

# ── Создание приложения ────────────────────────────────────────────────────────

app = FastAPI(
    title="Smart Planner API",
    description="REST API для курсового проекта «Умный планировщик задач»",
    version="1.0.0",
)

# ── CORS ───────────────────────────────────────────────────────────────────────
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestMetricsMiddleware)


# ── Подключение роутеров ────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(notes.router)
app.include_router(templates.router)
app.include_router(analytics.router)
app.include_router(notifications.router)
app.include_router(ai.router)
app.include_router(mcp_calendar.router)


# ── Health-check ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
def health_check():
    """Проверка работоспособности сервера."""
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    """Expose aggregate HTTP metrics for Prometheus-compatible scrapers."""
    return render_metrics()
