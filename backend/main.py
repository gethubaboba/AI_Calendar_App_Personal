"""
main.py — точка входа FastAPI-приложения.

Подключает все роутеры, настраивает CORS.
Swagger UI доступен на http://localhost:8000/docs
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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


@app.exception_handler(RequestValidationError)
async def private_password_validation(request, exc):
    # Pydantic validation details otherwise echo input values, including secrets.
    if request.url.path.startswith("/api/auth/password/"):
        return JSONResponse(status_code=422, content={
            "detail": "Проверьте адрес, ссылку и новый пароль. Пароль должен содержать от 12 символов "
                      "и занимать не более 72 байт UTF-8."
        })
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def auth_no_store(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


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
