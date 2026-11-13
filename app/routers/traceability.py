"""Traceability matrix view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.traceability import build_matrix, matrix_markdown
from app.web import get_project, render

router = APIRouter()


@router.get("/projects/{pid}/traceability")
def traceability(pid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    db.commit()
    return render(request, "traceability.html", project=p, matrix=build_matrix(p))


@router.get("/projects/{pid}/traceability.md")
def traceability_md(pid: int, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    return PlainTextResponse(matrix_markdown(p), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{p.code}-traceability.md"'})
