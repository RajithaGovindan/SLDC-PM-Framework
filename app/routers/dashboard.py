"""Portfolio dashboard and project pipeline view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project
from app.services.traceability import build_matrix
from app.services.workflow import ensure_artifacts, next_project_code, progress, project_blockers
from app.web import get_project, redirect, render

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects = list(db.scalars(select(Project).order_by(Project.updated_at.desc())))
    cards = []
    for p in projects:
        ensure_artifacts(db, p)
        cards.append({"project": p, "progress": progress(p), "blockers": project_blockers(p)})
    db.commit()
    return render(request, "dashboard.html", cards=cards)


@router.post("/projects")
def create_project(name: str = Form(...), client: str = Form(""), description: str = Form(""),
                   raw_notes: str = Form(""), target_repo_path: str = Form(""), db: Session = Depends(get_db)):
    name = name.strip()
    if not name:
        return redirect("/", err="Project name is required.")
    p = Project(name=name, code=next_project_code(db, name), client=client.strip(), description=description.strip(),
                raw_notes=raw_notes, target_repo_path=target_repo_path.strip())
    db.add(p)
    db.flush()
    ensure_artifacts(db, p)
    db.commit()
    return redirect(f"/projects/{p.id}/stages/1", msg="Project created. Review the notes and generate requirements.")


@router.get("/projects/{pid}")
def project_view(pid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    db.commit()
    return render(request, "project.html", project=p, progress=progress(p), blockers=project_blockers(p),
                  stats=build_matrix(p).stats)


@router.post("/projects/{pid}/settings")
def update_project(pid: int, name: str = Form(...), client: str = Form(""), description: str = Form(""),
                   target_repo_path: str = Form(""), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    p.name, p.client, p.description = name.strip() or p.name, client.strip(), description.strip()
    p.target_repo_path = target_repo_path.strip()
    db.commit()
    return redirect(f"/projects/{pid}", msg="Project settings saved.")


@router.post("/projects/{pid}/delete")
def delete_project(pid: int, confirm: str = Form(""), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    if confirm.strip() != p.code:
        return redirect(f"/projects/{pid}", err=f"Type the project code {p.code} to confirm deletion.")
    db.delete(p)
    db.commit()
    return redirect("/", msg=f"Project {p.code} deleted.")
