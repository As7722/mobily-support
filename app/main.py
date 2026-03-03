from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings
from app.core.database import engine
from app.core.redis import close_redis_pool, get_redis_pool
from app.middleware.auth import AuthMiddleware
from app.middleware.language import LanguageMiddleware
from app.middleware.theme import ThemeMiddleware

# Import all models so SQLAlchemy registers them in Base.metadata
import app.models  # noqa: F401

logger = logging.getLogger(__name__)


# ─── Sentry Initialisation ───────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=f"mobily-support@{settings.APP_VERSION}",
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
    )


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    logger.info("Starting Mobily Support System v%s [%s]", settings.APP_VERSION, settings.ENVIRONMENT)

    # Warm up Redis pool
    await get_redis_pool()
    logger.info("Redis connection pool ready")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await close_redis_pool()
    await engine.dispose()
    logger.info("Cleanup complete")


# ─── FastAPI Application ──────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Mobily Internal Technical Support Request Management System",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ─── Static Files ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.CORS_ORIGINS] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Custom Middleware (order matters — outermost runs first) ─────────────────
# Auth must run before Language so user.preferred_language is available
app.add_middleware(LanguageMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(ThemeMiddleware)


# ─── Global Exception Handlers ───────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    from app.i18n import t
    return JSONResponse(
        status_code=404,
        content={"detail": t("errors.not_found", lang=lang)},
    )


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc: Exception) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    from app.i18n import t
    return JSONResponse(
        status_code=403,
        content={"detail": t("errors.permission_denied", lang=lang)},
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    from app.i18n import t
    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": t("errors.server_error", lang=lang)},
    )


# ─── Root + Health Check ──────────────────────────────────────────────────────
@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login")


@app.get("/health", tags=["System"], include_in_schema=False)
async def health_check() -> dict:
    return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}


@app.get("/login", response_class=HTMLResponse, include_in_schema=False, tags=["System"])
async def login_page(request: Request) -> HTMLResponse:
    from datetime import datetime, timezone
    from app.core.templates import templates
    from app.i18n import t
    lang = getattr(request.state, "lang", "ar")
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr",
            "dark_mode": request.cookies.get("dark_mode", "1") != "0",
            "now": datetime.now(tz=timezone.utc),
            "t": t,
        },
    )


# ─── API Routers ──────────────────────────────────────────────────────────────

# Phase 1 — Auth (live)
from app.api.auth import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])

# Phase 2 — Public Portal + Ticket System (live)
from app.api.portal import router as portal_router
from app.api.language import router as language_router
app.include_router(portal_router, tags=["Portal"])
app.include_router(language_router, tags=["Language"])

# Phase 3 — Dashboards, KB, SSE, Profile
from app.api.dashboard import router as dashboard_router
from app.api.tickets_internal import router as tickets_internal_router
from app.api.sse import router as sse_router
from app.api.kb import router as kb_router
from app.api.profile import router as profile_router
app.include_router(dashboard_router, tags=["Dashboard"])
app.include_router(tickets_internal_router, tags=["Tickets"])
app.include_router(sse_router, tags=["SSE"])
app.include_router(kb_router, tags=["Knowledge Base"])
app.include_router(profile_router, tags=["Profile"])

# Phase 4 — Supervisor & Manager
from app.api.supervisor import router as supervisor_router
from app.api.manager import router as manager_router
app.include_router(supervisor_router, tags=["Supervisor"])
app.include_router(manager_router, tags=["Manager"])

# Phase 5 — Admin Panel + Webhooks
from app.api.admin import router as admin_router
from app.api.webhooks import router as webhooks_router
app.include_router(admin_router, tags=["Admin"])
app.include_router(webhooks_router, tags=["Webhooks"])
