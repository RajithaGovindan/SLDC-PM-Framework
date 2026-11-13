"""Repo Sync & .claude/commands exporter."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.repo_sync import preview_files, sync_project
from app.web import get_project, redirect, render

router = APIRouter()


@router.get("/projects/{pid}/sync")
def sync_view(pid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    db.commit()
    return render(request, "sync.html", project=p, files=preview_files(p))


@router.post("/projects/{pid}/sync")
def sync_run(pid: int, target_repo_path: str = Form(""), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    if target_repo_path.strip():
        p.target_repo_path = target_repo_path.strip()
    log = sync_project(db, p)
    db.commit()
    if log.success:
        return redirect(f"/projects/{pid}/sync", msg=log.message)
    return redirect(f"/projects/{pid}/sync", err=f"Sync failed: {log.message}")
