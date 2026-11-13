"""Project backup: one .zip holding a project with every stage, version, item, issue and attached file.

Used to move a project between installations (e.g. from a laptop to the cloud). Import always creates a new
project with fresh ids; nothing in the target database is changed or overwritten.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, insert, select
from sqlalchemy.orm import Session

from app.models import (ArtifactRevision, Attachment, DevTask, Feature, Issue, Project, QAPlan, Requirement,
                        StageArtifact, UserStory, feature_requirements)
from app.services import attachments as att_store

FORMAT = "sdlc-project-backup"
VERSION = 1
MAX_BACKUP_MB = 30  # Cloud Run caps a request at 32 MB


class BackupError(ValueError):
    pass


def _row(obj: Any) -> dict:
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.key)
        out[col.key] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _fields(model: type, data: dict, drop: tuple[str, ...] = ()) -> dict:
    """Column values for a new row of `model`: known columns only, no id, datetimes parsed."""
    out = {}
    for col in model.__table__.columns:
        k = col.key
        if k == "id" or k in drop or k not in data:
            continue
        v = data[k]
        if isinstance(col.type, DateTime) and isinstance(v, str):
            v = datetime.fromisoformat(v)
        out[k] = v
    return out


def export_project(db: Session, project: Project) -> bytes:
    pid = project.id
    links = db.execute(select(feature_requirements).join(
        Feature, Feature.id == feature_requirements.c.feature_id).where(Feature.project_id == pid)).all()
    doc = {
        "format": FORMAT, "version": VERSION, "exported_at": datetime.now().isoformat(timespec="seconds"),
        "project": _row(project),
        "artifacts": [{**_row(a), "revisions": [_row(r) for r in a.revisions]} for a in project.artifacts],
        "requirements": [_row(r) for r in project.requirements],
        "features": [_row(f) for f in project.features],
        "feature_requirements": [{"feature_id": l.feature_id, "requirement_id": l.requirement_id} for l in links],
        "stories": [_row(s) for f in project.features for s in f.stories],
        "dev_tasks": [_row(t) for f in project.features for t in f.dev_tasks],
        "qa_plans": [_row(q) for f in project.features for q in f.qa_plans],
        "issues": [_row(i) for i in project.issues],
        "attachments": [_row(a) for a in project.attachments],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(doc, ensure_ascii=False, indent=1))
        for a in project.attachments:
            try:
                z.writestr(f"files/{a.stored_name}", att_store.read_bytes(a))
            except Exception:  # noqa: BLE001 - a missing file is skipped; its record still travels
                pass
    return buf.getvalue()


def read_backup(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    if len(data) > MAX_BACKUP_MB * 1024 * 1024:
        raise BackupError(f"The backup is larger than {MAX_BACKUP_MB} MB.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = json.loads(z.read("project.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise BackupError("This is not a project backup (.zip with project.json).") from exc
    if doc.get("format") != FORMAT or doc.get("version") != VERSION:
        raise BackupError("Unsupported backup format or version.")
    return doc, z


def import_project(db: Session, data: bytes, *, code: str = "", repo: str | None = None) -> Project:
    """Create a new project from a backup. `code` overrides the project code; `repo` the repository."""
    doc, z = read_backup(data)
    p_data = doc["project"]
    new_code = (code or p_data.get("code") or "").strip()
    if not new_code:
        raise BackupError("The backup has no project code.")
    if db.scalar(select(Project.id).where(Project.code == new_code)):
        raise BackupError(f"A project with code {new_code} already exists. Delete it first or choose another code.")

    project = Project(**_fields(Project, {**p_data, "code": new_code}))
    if repo is not None:
        project.target_repo_path = repo.strip()
    db.add(project)
    db.flush()
    pid = project.id

    for a in doc["artifacts"]:
        art = StageArtifact(**_fields(StageArtifact, a, drop=("project_id",)), project_id=pid)
        db.add(art)
        db.flush()
        for r in a.get("revisions", []):
            db.add(ArtifactRevision(**_fields(ArtifactRevision, r, drop=("artifact_id",)), artifact_id=art.id))

    req_ids: dict[int, int] = {}
    for r in doc["requirements"]:
        obj = Requirement(**_fields(Requirement, r, drop=("project_id",)), project_id=pid)
        db.add(obj)
        db.flush()
        req_ids[r["id"]] = obj.id

    feat_ids: dict[int, int] = {}
    for f in doc["features"]:
        obj = Feature(**_fields(Feature, f, drop=("project_id",)), project_id=pid)
        db.add(obj)
        db.flush()
        feat_ids[f["id"]] = obj.id

    links = [{"feature_id": feat_ids[l["feature_id"]], "requirement_id": req_ids[l["requirement_id"]]}
             for l in doc["feature_requirements"] if l["feature_id"] in feat_ids and l["requirement_id"] in req_ids]
    if links:
        db.execute(insert(feature_requirements), links)

    for key, model in (("stories", UserStory), ("dev_tasks", DevTask), ("qa_plans", QAPlan)):
        for row in doc[key]:
            if row["feature_id"] in feat_ids:
                db.add(model(**_fields(model, row, drop=("project_id", "feature_id")), project_id=pid,
                             feature_id=feat_ids[row["feature_id"]]))

    issue_ids: dict[int, int] = {}
    for i in doc["issues"]:
        obj = Issue(**_fields(Issue, i, drop=("project_id",)), project_id=pid)
        db.add(obj)
        db.flush()
        issue_ids[i["id"]] = obj.id

    names = set(z.namelist())
    for a in doc["attachments"]:
        path = f"files/{a['stored_name']}"
        if path not in names:
            continue
        att_store._write(pid, a["stored_name"], z.read(path), a.get("mime") or "application/octet-stream")
        db.add(Attachment(**_fields(Attachment, a, drop=("project_id", "issue_id")), project_id=pid,
                          issue_id=issue_ids.get(a.get("issue_id"))))
    db.flush()
    return project


def summary(project: Project) -> str:
    return (f"{len(project.requirements)} requirements, {len(project.features)} features, "
            f"{sum(len(f.stories) for f in project.features)} stories, "
            f"{sum(len(f.dev_tasks) for f in project.features)} dev packs, {len(project.issues)} issues, "
            f"{len(project.attachments)} files")
