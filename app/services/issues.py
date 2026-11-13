"""Issues: report in plain words -> Claude triages (bug / CR / question) -> impact plan -> apply stage by stage."""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Issue, Project
from app.services import ai_orchestrator, attachments
from app.services.parsers import OutputParseError, extract_json
from app.stages import STAGES, Status

log = logging.getLogger("sdlc.issues")

PREFIX = {"bug": "BUG", "cr": "CR", "question": "Q"}
KIND_LABEL = {"bug": "Bug", "cr": "Change request", "question": "Question", "": "Not triaged"}
MOCK_MSG = ("Triage needs live Claude: mock mode cannot read a report. Set MOCK_AI=false and ANTHROPIC_API_KEY in "
            ".env and restart.")


class IssueError(ValueError):
    pass


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    stage_no: int = Field(ge=1, le=10)
    instruction: str = Field(min_length=3)


class Triage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal["bug", "cr", "question"]
    title: str = ""
    reasoning: str = ""
    related_refs: list[str] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)


def next_ref(project: Project, kind: str) -> str:
    prefix = PREFIX.get(kind, "ISS")
    used = {i.ref for i in project.issues}
    n = 1 + sum(1 for i in project.issues if i.ref.startswith(prefix + "-"))
    while f"{prefix}-{n:03d}" in used:
        n += 1
    return f"{prefix}-{n:03d}"


def create(db: Session, project: Project, description: str, reporter: str = "") -> Issue:
    if not description.strip():
        raise IssueError("Describe the issue or change first.")
    issue = Issue(project_id=project.id, ref=next_ref(project, ""), description=description.strip(),
                  reporter=reporter.strip(), status="New")
    project.issues.append(issue)
    db.flush()
    return issue


def stages_with_content(project: Project) -> list[int]:
    return [a.stage_no for a in project.artifacts if a.has_content and a.status != Status.LOCKED]


def triage(db: Session, project: Project, issue: Issue) -> Issue:
    """Ask Claude to classify the report and plan the stage edits. Code-aware when the project has a repo."""
    from app.prompts import triage as triage_prompt

    if not get_settings().ai_is_live:
        raise IssueError(MOCK_MSG)
    have = stages_with_content(project)
    if not have:
        raise IssueError("No stage has content yet - generate the pipeline before reporting changes against it.")
    reader = ai_orchestrator.repo_reader(project, 6)
    files = attachments.content_blocks(list(issue.attachments))
    prompt = triage_prompt.build(ai_orchestrator.base_context(project), issue.description, have, reader is not None)
    raw = ""
    try:
        raw = (ai_orchestrator.call_claude_with_repo(prompt, reader, files) if reader
               else ai_orchestrator.call_claude(prompt, files))
        result = _parse(raw)
    except (OutputParseError, ValidationError) as first:
        log.warning("Triage output invalid (%s); retrying once", first)
        try:
            raw = ai_orchestrator.call_claude(ai_orchestrator._repair_prompt(prompt, raw, str(first)))
            result = _parse(raw)
        except (OutputParseError, ValidationError) as second:
            raise IssueError(f"Claude's triage could not be read: {second}") from second
    except ai_orchestrator.AIError as exc:
        raise IssueError(str(exc)) from exc

    steps, seen = [], set()
    for st in sorted(result.plan, key=lambda s: s.stage_no):
        if st.stage_no in have and st.stage_no not in seen:
            seen.add(st.stage_no)
            steps.append({"stage_no": st.stage_no, "instruction": st.instruction.strip(), "selected": True,
                          "result": "", "version": None})
    set_kind(project, issue, result.kind)
    issue.title = result.title.strip()[:300] or issue.description[:80]
    issue.reasoning = (result.reasoning.strip()
                       + (f"\n\nRelated: {', '.join(result.related_refs)}" if result.related_refs else ""))
    issue.plan = steps
    issue.files_read = list(reader.files_read) if reader else []
    issue.status = "Planned"
    db.flush()
    return issue


def _parse(raw: str) -> Triage:
    data = extract_json(raw)
    return Triage.model_validate(data)


def set_kind(project: Project, issue: Issue, kind: str) -> None:
    if kind not in PREFIX:
        raise IssueError("Unknown kind.")
    if issue.kind != kind:
        issue.kind = kind
        issue.ref = next_ref(project, kind)


def update_plan(issue: Issue, selected: set[int], instructions: dict[int, str]) -> None:
    steps = []
    for st in issue.plan or []:
        st = dict(st)
        n = st["stage_no"]
        st["selected"] = n in selected
        if instructions.get(n, "").strip():
            st["instruction"] = instructions[n].strip()
        steps.append(st)
    issue.plan = steps


def apply(db: Session, project: Project, issue: Issue) -> list[dict]:
    """Revise each selected stage in order, as a new draft version. Commits after every stage, so a failure part
    way through keeps the stages already done."""
    from app.services.workflow import store_content

    if issue.status not in ("Planned", "Applied"):
        raise IssueError("Triage the issue first.")
    steps = [dict(s) for s in issue.plan or []]
    if not any(s.get("selected") for s in steps):
        raise IssueError("Select at least one stage to update.")
    label = {s.no: s.title for s in STAGES}
    for st in steps:
        if not st.get("selected") or st.get("version"):
            continue
        n = st["stage_no"]
        artifact = project.artifact(n)
        if not artifact or not artifact.has_content or artifact.status == Status.LOCKED:
            st["result"] = "Skipped: this stage has no content yet."
            continue
        feedback = (f"{issue.ref} ({KIND_LABEL[issue.kind].lower()}): {st['instruction']}\n\n"
                    f"Original report: {issue.description}")
        try:
            md, doc, source, files_read = ai_orchestrator.revise(project, n, feedback, list(issue.attachments))
        except (ai_orchestrator.AIError, OutputParseError) as exc:
            st["result"] = f"Failed: {exc}"
            issue.plan = steps
            db.commit()
            raise IssueError(f"Stage {n} ({label[n]}) failed: {exc}. Stages before it were updated; "
                             "fix the instruction and apply again to continue.") from exc
        note = f"{issue.ref}: {st['instruction']}" + (f"\n\nCode read: {', '.join(files_read)}" if files_read else "")
        store_content(db, project, artifact, md, doc, source, note)
        st["version"], st["result"] = artifact.version, f"Updated to v{artifact.version}"
        issue.plan = steps
        db.commit()
    issue.status = "Applied"
    issue.plan = steps
    db.flush()
    return steps
