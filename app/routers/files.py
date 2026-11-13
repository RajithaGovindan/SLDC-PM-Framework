"""Attachments (upload, download, use-in-AI toggle, delete) and the download-all ZIP."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Attachment
from app.services import attachments as att
from app.services.export import build_zip
from app.web import get_project, redirect

router = APIRouter()


def _back(pid: int, back: str) -> str:
    # Only redirect within this project's pages.
    return back if back.startswith(f"/projects/{pid}") and "//" not in back else f"/projects/{pid}"


def _attachment(db: Session, aid: int) -> Attachment:
    a = db.get(Attachment, aid)
    if not a:
        raise HTTPException(404, "Attachment not found")
    return a


@router.post("/projects/{pid}/attachments")
async def upload(pid: int, files: list[UploadFile] = File(...), stage_no: str = Form(""), note: str = Form(""),
                 back: str = Form(""), db: Session = Depends(get_db)):
    p = get_project(db, pid)
    stage = int(stage_no) if stage_no.isdigit() else None
    saved, errors = [], []
    for f in files:
        if not f.filename:
            continue
        try:
            a = att.save(db, p, f.filename, await f.read(), stage_no=stage, note=note)
            saved.append(a.filename)
        except att.AttachmentError as exc:
            errors.append(str(exc))
    db.commit()
    if errors:
        return redirect(_back(pid, back), err=" ".join(errors))
    return redirect(_back(pid, back), msg=f"Attached {', '.join(saved)}." if saved else "")


@router.get("/attachments/{aid}/download")
def download(aid: int, db: Session = Depends(get_db)):
    a = _attachment(db, aid)
    try:
        data = att.read_bytes(a)
    except Exception as exc:  # noqa: BLE001 - missing locally or in the bucket
        raise HTTPException(404, "File missing in storage") from exc
    return Response(data, media_type=a.mime,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(a.filename)}"})


@router.post("/attachments/{aid}/toggle")
def toggle(aid: int, back: str = Form(""), db: Session = Depends(get_db)):
    a = _attachment(db, aid)
    a.use_in_ai = not a.use_in_ai
    pid = a.project_id
    db.commit()
    return redirect(_back(pid, back))


@router.post("/attachments/{aid}/delete")
def remove(aid: int, back: str = Form(""), db: Session = Depends(get_db)):
    a = _attachment(db, aid)
    pid, name = a.project_id, a.filename
    att.delete(db, a)
    db.commit()
    return redirect(_back(pid, back), msg=f"Removed {name}.")


@router.get("/projects/{pid}/export.zip")
def export_zip(pid: int, attachments: int = 1, db: Session = Depends(get_db)):
    p = get_project(db, pid)
    data = build_zip(p, include_attachments=bool(attachments))
    name = f"{p.code}-sdlc-documents.zip"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})
