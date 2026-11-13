"""FastAPI application entry point.

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.database import DB_BACKEND, init_db
from app.routers import dashboard, stages, sync, team, traceability

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sdlc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.auto_create_tables:
        init_db()
    log.info("Database backend: %s | AI mode: %s (%s)", DB_BACKEND, "LIVE" if s.ai_is_live else "MOCK",
             s.claude_model if s.ai_is_live else "offline generator")
    yield


app = FastAPI(title=get_settings().app_name, version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

for r in (dashboard.router, stages.router, traceability.router, team.router, sync.router):
    app.include_router(r)


@app.get("/healthz")
def healthz():
    s = get_settings()
    return {"status": "ok", "db": DB_BACKEND, "ai": "live" if s.ai_is_live else "mock", "version": __version__}
