"""Shared web helpers: templates, redirects, project lookup."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import DB_BACKEND
from app.models import Project
from app.services.workflow import ensure_artifacts
from app.stages import ITEM_STATUSES, REQ_TYPE_LABELS, ROLES, STAGES, Status

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

STATUS_CLASSES = {
    Status.LOCKED: "bg-slate-100 text-slate-400 ring-slate-200",
    Status.NOT_STARTED: "bg-white text-slate-500 ring-slate-300",
    Status.DRAFT: "bg-amber-50 text-amber-700 ring-amber-200",
    Status.IN_REVIEW: "bg-violet-50 text-violet-700 ring-violet-200",
    Status.APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    Status.IN_PROGRESS: "bg-sky-50 text-sky-700 ring-sky-200",
    Status.DONE: "bg-emerald-600 text-white ring-emerald-600",
    "To Do": "bg-slate-50 text-slate-600 ring-slate-200",
    "Blocked": "bg-rose-50 text-rose-700 ring-rose-200",
}
STATUS_DOT = {
    Status.LOCKED: "bg-slate-300", Status.NOT_STARTED: "bg-slate-300", Status.DRAFT: "bg-amber-400",
    Status.IN_REVIEW: "bg-violet-500", Status.APPROVED: "bg-emerald-500", Status.IN_PROGRESS: "bg-sky-500",
    Status.DONE: "bg-emerald-700",
}


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


templates.env.filters["dt"] = _fmt_dt
templates.env.globals.update(
    STAGES=STAGES, Status=Status, ROLES=ROLES, ITEM_STATUSES=ITEM_STATUSES, REQ_TYPE_LABELS=REQ_TYPE_LABELS,
    STATUS_CLASSES=STATUS_CLASSES, STATUS_DOT=STATUS_DOT, DB_BACKEND=DB_BACKEND, settings=get_settings(),
)


def render(request: Request, name: str, **ctx):
    ctx.setdefault("msg", request.query_params.get("msg", ""))
    ctx.setdefault("err", request.query_params.get("err", ""))
    return templates.TemplateResponse(request, name, ctx)


def redirect(url: str, msg: str = "", err: str = "") -> RedirectResponse:
    q = {k: v for k, v in {"msg": msg, "err": err}.items() if v}
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url + ((sep + urlencode(q)) if q else ""), status_code=303)


def get_project(db: Session, pid: int) -> Project:
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Project not found")
    ensure_artifacts(db, project)
    return project
