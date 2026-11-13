"""Stage editor: generate, edit, regenerate with feedback, review, approve & unlock."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import RenderRequest, RenderResponse
from app.services.diffing import diff_revisions
from app.services.parsers import OutputParseError
from app.services.workflow import (WorkflowError, approve, gate_open, generate_stage, parse_manual, restore_revision,
                                   save_manual, set_status)
from app.stages import STAGE_BY_NO, get_stage
from app.web import get_project, redirect, render

router = APIRouter()


def _stage_or_404(n: int):
    if n not in STAGE_BY_NO:
        raise HTTPException(404, "Unknown stage")
    return get_stage(n)


def _editor_text(artifact, stage) -> str:
    if stage.output == "json":
        return json.dumps(artifact.content_json, indent=2, ensure_ascii=False) if artifact.content_json else ""
    return artifact.content_md or ""


def _repo_ok(project) -> bool:
    path = (project.target_repo_path or "").strip()
    return bool(path) and Path(path).is_dir()


def _changes(artifact, stage, compare: int | None) -> dict | None:
    """Diff of the current version against `compare` (default: the version before it)."""
    revs = {r.version: r for r in artifact.revisions}
    new = revs.get(artifact.version)
    if not new or len(revs) < 2:
        return None
    older = sorted(v for v in revs if v < new.version)
    if compare not in revs or compare == new.version:
        compare = older[-1] if older else None
    if compare is None:
        return None
    return diff_revisions(stage.no, stage.output, revs[compare], new)


@router.get("/projects/{pid}/stages/{n}")
def stage_editor(pid: int, n: int, request: Request, compare: int | None = None, view: str = "",
                 db: Session = Depends(get_db)):
    stage = _stage_or_404(n)
    p = get_project(db, pid)
    db.commit()
    a = p.artifact(n)
    can_gen, gate_msg = gate_open(p, n)
    changes = _changes(a, stage, compare)
    layout = view if view in ("editor", "split", "preview") or (view == "changes" and changes) else "split"
    return render(request, "stage_editor.html", project=p, stage=stage, artifact=a,
                  editor_text=_editor_text(a, stage), can_generate=can_gen, gate_msg=gate_msg,
                  changes=changes, initial_layout=layout, repo_ok=_repo_ok(p))


@router.post("/projects/{pid}/stages/{n}/generate")
def stage_generate(pid: int, n: int, feedback: str = Form(""), raw_notes: str | None = Form(None),
                   db: Session = Depends(get_db)):
    _stage_or_404(n)
    p = get_project(db, pid)
    if n == 1 and raw_notes is not None:
        p.raw_notes = raw_notes
    try:
        a = generate_stage(db, p, n, feedback)
    except WorkflowError as exc:
        db.commit()
        return redirect(f"/projects/{pid}/stages/{n}", err=str(exc))
    db.commit()
    if feedback.strip():
        return redirect(f"/projects/{pid}/stages/{n}?view=changes",
                        msg=f"Revised as v{a.version}. The changes are highlighted below; review them, then approve.")
    return redirect(f"/projects/{pid}/stages/{n}", msg=f"Generated v{a.version}. Review, edit, then approve.")


@router.post("/projects/{pid}/stages/{n}/notes")
def stage_save_notes(pid: int, n: int, raw_notes: str = Form(""), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    p.raw_notes = raw_notes
    db.commit()
    return redirect(f"/projects/{pid}/stages/1", msg="Source notes saved.")


@router.post("/projects/{pid}/stages/{n}/save")
def stage_save(pid: int, n: int, request: Request, content: str = Form(""), db: Session = Depends(get_db)):
    stage = _stage_or_404(n)
    p = get_project(db, pid)
    try:
        a = save_manual(db, p, n, content)
    except WorkflowError as exc:
        db.rollback()
        p = get_project(db, pid)
        can_gen, gate_msg = gate_open(p, n)
        return render(request, "stage_editor.html", project=p, stage=stage, artifact=p.artifact(n),
                      editor_text=content, can_generate=can_gen, gate_msg=gate_msg, err=f"Not saved: {exc}")
    db.commit()
    return redirect(f"/projects/{pid}/stages/{n}", msg=f"Saved as v{a.version}.")


@router.post("/projects/{pid}/stages/{n}/status")
def stage_status(pid: int, n: int, status: str = Form(...), db: Session = Depends(get_db)):
    _stage_or_404(n)
    p = get_project(db, pid)
    try:
        set_status(db, p, n, status)
    except WorkflowError as exc:
        return redirect(f"/projects/{pid}/stages/{n}", err=str(exc))
    db.commit()
    return redirect(f"/projects/{pid}/stages/{n}", msg=f"Status set to {status}.")


@router.post("/projects/{pid}/stages/{n}/approve")
def stage_approve(pid: int, n: int, approver: str = Form("reviewer"), db: Session = Depends(get_db)):
    _stage_or_404(n)
    p = get_project(db, pid)
    try:
        approve(db, p, n, approver.strip())
    except WorkflowError as exc:
        db.rollback()
        return redirect(f"/projects/{pid}/stages/{n}", err=str(exc))
    db.commit()
    if n < 10:
        return redirect(f"/projects/{pid}/stages/{n + 1}",
                        msg=f"Stage {n} approved. Stage {n + 1} ({get_stage(n + 1).title}) is unlocked.")
    return redirect(f"/projects/{pid}", msg="Final stage approved - the SDLC pipeline is complete.")


@router.post("/projects/{pid}/stages/{n}/restore/{rev_id}")
def stage_restore(pid: int, n: int, rev_id: int, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    try:
        restore_revision(db, p, n, rev_id)
    except WorkflowError as exc:
        return redirect(f"/projects/{pid}/stages/{n}", err=str(exc))
    db.commit()
    return redirect(f"/projects/{pid}/stages/{n}", msg="Revision restored as a new draft.")


@router.post("/api/projects/{pid}/stages/{n}/render", response_model=RenderResponse)
def stage_render(pid: int, n: int, body: RenderRequest, db: Session = Depends(get_db)):
    """Live preview for JSON stages: validate the editor JSON and return rendered Markdown."""
    _stage_or_404(n)
    p = get_project(db, pid)
    try:
        md, _ = parse_manual(p, n, body.content)
        return RenderResponse(markdown=md)
    except OutputParseError as exc:
        return RenderResponse(markdown="", error=str(exc))


@router.get("/projects/{pid}/stages/{n}/export.md")
def stage_export(pid: int, n: int, db: Session = Depends(get_db)):
    stage = _stage_or_404(n)
    p = get_project(db, pid)
    a = p.artifact(n)
    return PlainTextResponse(a.content_md or "", media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{p.code}-{stage.slug}.md"'})
