"""Stage lifecycle: gating, content storage, approval & unlock, blockers."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ArtifactRevision, Project, StageArtifact
from app.services import ai_orchestrator
from app.services.parsers import OutputParseError, parse_stage_output
from app.services.renderers import render_stage_json
from app.services.traceability import sync_stage
from app.stages import STAGES, Status, get_stage


class WorkflowError(ValueError):
    pass


def ensure_artifacts(db: Session, project: Project) -> None:
    have = {a.stage_no for a in project.artifacts}
    for s in STAGES:
        if s.no not in have:
            project.artifacts.append(StageArtifact(stage_no=s.no, stage_key=s.key,
                                                   status=Status.NOT_STARTED if s.no == 1 else Status.LOCKED))
    db.flush()


def next_project_code(db: Session, name: str) -> str:
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name)[:4]).upper() or "PRJ"
    existing = set(db.scalars(select(Project.code)))
    n = 1
    while f"{letters}-{n:02d}" in existing:
        n += 1
    return f"{letters}-{n:02d}"


def gate_open(project: Project, stage_no: int) -> tuple[bool, str]:
    if stage_no == 1:
        if not (project.raw_notes or "").strip():
            return False, "Add raw client notes / transcripts before generating requirements."
        return True, ""
    prev = project.artifact(stage_no - 1)
    if not prev or prev.status not in Status.GATE_OPEN:
        return False, f"Stage {stage_no - 1} ({get_stage(stage_no - 1).title}) must be approved first."
    return True, ""


def _mark_downstream_stale(project: Project, stage_no: int) -> None:
    for a in project.artifacts:
        if a.stage_no > stage_no and a.has_content:
            a.blocker_note = (f"Upstream stage {stage_no} ({get_stage(stage_no).short}) changed after approval - "
                              "review and regenerate if impacted.")


def store_content(db: Session, project: Project, artifact: StageArtifact, md: str, doc: dict | None, source: str,
                  feedback: str = "") -> None:
    was_approved = artifact.status in Status.GATE_OPEN
    artifact.content_md, artifact.content_json = md, doc
    artifact.version = (artifact.version or 0) + 1
    artifact.status = Status.DRAFT
    artifact.approved_at, artifact.approved_by = None, ""
    artifact.last_error = ""
    artifact.revisions.append(ArtifactRevision(version=artifact.version, content_md=md, content_json=doc,
                                               feedback=feedback, source=source))
    if was_approved:
        _mark_downstream_stale(project, artifact.stage_no)
    db.flush()


def generate_stage(db: Session, project: Project, stage_no: int, feedback: str = "") -> StageArtifact:
    artifact = project.artifact(stage_no)
    ok, why = gate_open(project, stage_no)
    if not ok:
        raise WorkflowError(why)
    try:
        if feedback.strip() and artifact.has_content:
            # Feedback on an existing document is an edit request: revise it in place rather than regenerating.
            md, doc, source, files_read = ai_orchestrator.revise(project, stage_no, feedback.strip())
            if files_read:
                feedback = f"{feedback.strip()}\n\nCode read: {', '.join(files_read)}"
        else:
            md, doc, source = ai_orchestrator.generate(db, project, stage_no, feedback)
    except (ai_orchestrator.AIError, OutputParseError) as exc:
        if str(exc) == ai_orchestrator.MOCK_REVISE_MSG:
            raise WorkflowError(str(exc)) from exc  # a setup hint, not a failed generation
        artifact.last_error = str(exc)
        db.flush()
        raise WorkflowError(str(exc)) from exc
    store_content(db, project, artifact, md, doc, source, feedback)
    artifact.blocker_note = ""
    return artifact


def parse_manual(project: Project, stage_no: int, text: str) -> tuple[str, dict | None]:
    stage = get_stage(stage_no)
    known = {f.ref for f in project.features} if stage_no in (5, 6, 7) else None
    md, doc = parse_stage_output(stage_no, text, stage.output, known_feature_refs=known)
    if doc is not None:
        md = render_stage_json(stage_no, doc)
    return md, doc


def save_manual(db: Session, project: Project, stage_no: int, text: str) -> StageArtifact:
    artifact = project.artifact(stage_no)
    if artifact.status == Status.LOCKED:
        raise WorkflowError("Stage is locked until the previous stage is approved.")
    try:
        md, doc = parse_manual(project, stage_no, text)
    except OutputParseError as exc:
        raise WorkflowError(str(exc)) from exc
    unchanged = (doc == artifact.content_json) if doc is not None else (md.strip() == (artifact.content_md or "").strip())
    if unchanged:
        return artifact
    store_content(db, project, artifact, md, doc, "manual")
    return artifact


def set_status(db: Session, project: Project, stage_no: int, status: str) -> None:
    artifact = project.artifact(stage_no)
    allowed = {Status.DRAFT, Status.IN_REVIEW}
    if artifact.status in Status.GATE_OPEN:
        allowed |= {Status.APPROVED, Status.IN_PROGRESS, Status.DONE}
    if status not in allowed:
        raise WorkflowError(f"Cannot move from {artifact.status} to {status}. Use Approve to pass the gate.")
    if not artifact.has_content:
        raise WorkflowError("Generate or write content first.")
    artifact.status = status
    db.flush()


def approve(db: Session, project: Project, stage_no: int, approver: str = "reviewer") -> StageArtifact:
    artifact = project.artifact(stage_no)
    if not artifact.has_content:
        raise WorkflowError("Nothing to approve - generate or write content first.")
    if artifact.status == Status.LOCKED:
        raise WorkflowError("Stage is locked.")
    if get_stage(stage_no).output == "json":
        try:
            _, doc = parse_manual(project, stage_no, json.dumps(artifact.content_json))
        except OutputParseError as exc:
            raise WorkflowError(f"Cannot approve: {exc}") from exc
        sync_stage(db, project, stage_no, doc)
    artifact.status = Status.APPROVED
    artifact.approved_at = datetime.now(timezone.utc)
    artifact.approved_by = approver or "reviewer"
    artifact.blocker_note = ""
    if stage_no < len(STAGES):
        nxt = project.artifact(stage_no + 1)
        if nxt.status == Status.LOCKED:
            nxt.status = Status.NOT_STARTED
    db.flush()
    return artifact


def restore_revision(db: Session, project: Project, stage_no: int, revision_id: int) -> None:
    artifact = project.artifact(stage_no)
    rev = next((r for r in artifact.revisions if r.id == revision_id), None)
    if not rev:
        raise WorkflowError("Revision not found.")
    store_content(db, project, artifact, rev.content_md, rev.content_json, "manual", f"Restored v{rev.version}")


def project_blockers(project: Project) -> list[dict]:
    out = []
    for a in project.artifacts:
        s = get_stage(a.stage_no)
        if a.last_error:
            out.append({"stage": a.stage_no, "level": "error", "text": f"{s.short}: generation failed - {a.last_error}"})
        if a.blocker_note:
            out.append({"stage": a.stage_no, "level": "warn", "text": f"{s.short}: {a.blocker_note}"})
        if a.status == Status.IN_REVIEW:
            out.append({"stage": a.stage_no, "level": "info", "text": f"{s.short}: awaiting approval."})
    oq = [r for r in project.requirements if r.type == "OPEN_QUESTION"]
    if oq:
        out.append({"stage": 1, "level": "warn",
                    "text": f"{len(oq)} open question(s) awaiting client answers ({', '.join(r.ref for r in oq[:5])})."})
    return out


def progress(project: Project) -> dict:
    done = sum(1 for a in project.artifacts if a.status in Status.GATE_OPEN)
    current = next((a for a in project.artifacts if a.status not in Status.GATE_OPEN), None)
    return {"approved": done, "total": len(STAGES), "pct": round(100 * done / len(STAGES)),
            "current": current.stage_no if current else None}
