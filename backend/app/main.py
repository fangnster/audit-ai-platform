import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.logging_config import configure_logging
from app.models import *  # register all models with SQLAlchemy

from app.routers import auth, orgs, cases, documents, facts, drafts, tasks, translation, sessions, ws, knowledge

configure_logging()
logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    if not settings.REQUEST_LOG_ENABLED:
        return await call_next(request)
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "request_failed request_id=%s method=%s path=%s elapsed_ms=%s",
            request_id,
            request.method,
            request.url.path,
            elapsed,
        )
        raise
    elapsed = int((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response

# Routers
API = "/api/v1"
app.include_router(auth.router,        prefix=f"{API}/auth",        tags=["Auth"])
app.include_router(orgs.router,        prefix=f"{API}/orgs",        tags=["Organizations"])
app.include_router(cases.router,       prefix=f"{API}/cases",       tags=["Cases"])
app.include_router(documents.router,   prefix=f"{API}/documents",   tags=["Documents"])
app.include_router(facts.router,       prefix=f"{API}/facts",       tags=["Facts"])
app.include_router(drafts.router,      prefix=f"{API}/drafts",      tags=["Drafts"])
app.include_router(tasks.router,       prefix=f"{API}/tasks",       tags=["Tasks"])
app.include_router(translation.router, prefix=f"{API}/translate",   tags=["Translation"])
app.include_router(sessions.router,    prefix=f"{API}/sessions",    tags=["Sessions"])
app.include_router(knowledge.router,   prefix=f"{API}/knowledge",   tags=["Knowledge"])
app.include_router(ws.router,          tags=["WebSockets"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/health/ready")
async def readiness():
    checks = {"db": "unknown", "redis": "unknown"}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {str(exc)[:120]}"
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await client.ping()
        finally:
            await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {str(exc)[:120]}"
    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, "version": settings.APP_VERSION, "checks": checks}
