"""Issues: report a bug or change in plain words, review Claude's triage and impact plan, apply it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Issue
from app.services import attachments as att
from app.services import issues as svc
from app.stages import STAGE_BY_NO
from app.web import get_project, redirect, render

router = APIRouter()


def _issue(db: Session, pid: int, iid: int) -> Issue:
    i = db.get(Issue, iid)
    if not i or i.project_id != pid:
        raise HTTPException(404, "Issue not found")
    return i


@router.get("/projects/{pid}/issues")
def issue_list(pid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    db.commit()
    return render(request, "issues.html", project=p, kinds=svc.KIND_LABEL)


@router.post("/projects/{pid}/issues")
async def issue_create(pid: int, description: str = Form(""), reporter: str = Form(""),
                       files: list[UploadFile] = File(default=[]), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    try:
        issue = svc.create(db, p, description, reporter)
        for f in files:
            if f.filename:
                att.save(db, p, f.filename, await f.read(), issue=issue)
    except (svc.IssueError, att.AttachmentError) as exc:
        db.rollback()
        return redirect(f"/projects/{pid}/issues", err=str(exc))
    db.commit()
    try:
        svc.triage(db, p, issue)
    except svc.IssueError as exc:
        db.commit()
        return redirect(f"/projects/{pid}/issues/{issue.id}", err=f"Saved as {issue.ref}, but triage failed: {exc}")
    db.commit()
    return redirect(f"/projects/{pid}/issues/{issue.id}",
                    msg=f"Triaged as {svc.KIND_LABEL[issue.kind].lower()} {issue.ref}. Review the plan, then apply it.")


@router.get("/projects/{pid}/issues/{iid}")
def issue_view(pid: int, iid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    i = _issue(db, pid, iid)
    db.commit()
    return render(request, "issue.html", project=p, issue=i, kinds=svc.KIND_LABEL, stage_by_no=STAGE_BY_NO)


@router.post("/projects/{pid}/issues/{iid}/triage")
def issue_retriage(pid: int, iid: int, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    i = _issue(db, pid, iid)
    if i.status == "Applied":
        return redirect(f"/projects/{pid}/issues/{iid}", err="Already applied; report a new issue for further changes.")
    try:
        svc.triage(db, p, i)
    except svc.IssueError as exc:
        return redirect(f"/projects/{pid}/issues/{iid}", err=str(exc))
    db.commit()
    return redirect(f"/projects/{pid}/issues/{iid}", msg=f"Re-triaged as {svc.KIND_LABEL[i.kind].lower()} {i.ref}.")


@router.post("/projects/{pid}/issues/{iid}/apply")
async def issue_apply(pid: int, iid: int, request: Request, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    i = _issue(db, pid, iid)
    form = await request.form()
    kind = str(form.get("kind") or "")
    try:
        if kind and kind != i.kind and i.status != "Applied":
            svc.set_kind(p, i, kind)
        selected = {int(v) for v in form.getlist("stages") if str(v).isdigit()}
        instructions = {int(k[12:]): str(v) for k, v in form.items() if k.startswith("instruction_") and k[12:].isdigit()}
        svc.update_plan(i, selected, instructions)
        db.commit()
        if form.get("action") == "save":
            return redirect(f"/projects/{pid}/issues/{iid}", msg="Plan saved.")
        steps = svc.apply(db, p, i)
    except svc.IssueError as exc:
        db.commit()
        return redirect(f"/projects/{pid}/issues/{iid}", err=str(exc))
    db.commit()
    done = [s for s in steps if s.get("version")]
    return redirect(f"/projects/{pid}/issues/{iid}",
                    msg=f"{i.ref} applied to {len(done)} stage(s) as new draft versions. Review and approve each.")


@router.post("/projects/{pid}/issues/{iid}/reject")
def issue_reject(pid: int, iid: int, db: Session = Depends(get_db)):
    i = _issue(db, pid, iid)
    i.status = "Rejected"
    db.commit()
    return redirect(f"/projects/{pid}/issues/{iid}", msg=f"{i.ref} rejected.")
