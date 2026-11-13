"""Team Instruction Center: role-filtered instructions, checklists and Claude Code prompts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DevTask, Feature, QAPlan, UserStory
from app.services.traceability import all_dev_tasks, all_qa_plans
from app.stages import ITEM_STATUSES, ROLES
from app.web import get_project, redirect, render

router = APIRouter()

ITEM_MODELS = {"feature": Feature, "story": UserStory, "dev": DevTask, "qa": QAPlan}


@router.get("/projects/{pid}/team")
def team_center(pid: int, request: Request, role: str = "All", db: Session = Depends(get_db)):
    p = get_project(db, pid)
    db.commit()
    role = role if role in ROLES else "All"
    show = {
        "architect": role in ("All", "Solution Architect"),
        "dev": role in ("All", "Developer"),
        "qa": role in ("All", "QA"),
        "release": role in ("All", "DevOps/Release"),
    }
    open_questions = [r for r in p.requirements if r.type == "OPEN_QUESTION"]
    migrations = [d for d in all_dev_tasks(p) if (d.migration_notes or "").strip()]
    return render(request, "team_center.html", project=p, role=role, show=show, open_questions=open_questions,
                  dev_tasks=all_dev_tasks(p), qa_plans=all_qa_plans(p), migrations=migrations,
                  tsd=p.artifact(3), release=p.artifact(8), runbook=p.artifact(9))


@router.post("/projects/{pid}/items/{kind}/{item_id}/status")
def item_status(pid: int, kind: str, item_id: int, status: str = Form(...), back: str = Form(""),
                db: Session = Depends(get_db)):
    model = ITEM_MODELS.get(kind)
    target = back if back.startswith("/") else f"/projects/{pid}/team"
    if not model or status not in ITEM_STATUSES:
        return redirect(target, err="Invalid item or status.")
    item = db.get(model, item_id)
    if not item or item.project_id != pid:
        return redirect(target, err="Item not found.")
    item.status = status
    db.commit()
    return redirect(target, msg=f"{item.ref} -> {status}")
