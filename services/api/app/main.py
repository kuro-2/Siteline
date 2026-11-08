"""Nukkad API. Run locally:  uv run fastapi dev app/main.py"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app import errors
from app.limits import limiter
from app.routers import admin, me, public, review, surveys
from engine.db import close_pool
from engine.log import configure
from engine.settings import get_settings

settings = get_settings()
configure(json=settings.app_env != "local")

if settings.sentry_dsn:  # optional, free tier
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    close_pool()


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Locality opportunity reports for small businesses. Every number is traceable.",
    lifespan=lifespan,
)
app.state.limiter = limiter
errors.install(app)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        errors.body(
            "rate_limited", "That's a lot of requests in a short time. Wait a minute and try again."
        ),
        status_code=429,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.web_origin.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    max_age=600,
)

for r in (public.router, me.router, surveys.router, review.router, admin.router):
    app.include_router(r, prefix="/v1")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": "/v1/health"}
