"""'What's left': the open work of a project in plain language, for people who don't read dev packs.

Open work = dev packs not Done, plus features not Done that have no open dev pack. Each item gets a short
plain-language summary written by Claude on request; a summary is kept until its source text changes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.models import DevTask, Feature, Project
from app.services import ai_orchestrator
from app.services.parsers import OutputParseError, extract_json

TYPES = [
    ("bug", "Bugs", "Things already built that don't work as they should."),
    ("feature", "Planned features not finished", "Work from the original plan that isn't done yet."),
    ("new", "New features", "New capabilities added after the original plan."),
    ("cr", "Change requests", "Changes the client asked for after scope was agreed."),
]
TYPE_LABEL = {k: label for k, label, _ in TYPES}
DONE = "Done"


@dataclass
class Item:
    ref: str
    kind: str                 # dev | feature (the status changes on this object)
    obj: DevTask | Feature
    feature: Feature
    tech_title: str
    source: str
    hours: float | None = None
    plain: dict | None = None     # the plain-language summary, when one has been written
    meta: dict = field(default_factory=dict)  # saved entry: summary and/or type chosen by the user
    stale: bool = False

    @property
    def type(self) -> str:
        t = self.meta.get("type")
        return t if t in TYPE_LABEL else ("bug" if self.feature.status == DONE else "feature")

    @property
    def type_by_user(self) -> bool:
        return bool(self.meta.get("type_by_user"))

    @property
    def origin(self) -> str:
        return self.meta.get("origin", "")

    @property
    def status(self) -> str:
        return self.obj.status

    @property
    def title(self) -> str:
        return (self.plain or {}).get("title") or self.tech_title


@dataclass
class WhatsLeft:
    groups: list[tuple[str, str, str, list[Item]]] = field(default_factory=list)
    finished: list = field(default_factory=list)    # features marked Done
    decisions: list = field(default_factory=list)   # open questions for the client
    open_issues: list = field(default_factory=list)
    hours: float = 0.0
    missing: int = 0                                 # items without an up-to-date plain summary

    @property
    def count(self) -> int:
        return sum(len(items) for *_, items in self.groups)


def _hours(f: Feature) -> float:
    return (f.effort_sa or 0) + (f.effort_dev or 0) + (f.effort_qa or 0) + (f.effort_docs or 0)


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def collect(project: Project) -> WhatsLeft:
    saved = project.plain_summaries or {}
    items: list[Item] = []
    for f in project.features:
        open_tasks = [t for t in f.dev_tasks if t.status != DONE]
        for t in open_tasks:
            src = f"{t.title}\nFeature: {f.title}\n{(t.implementation_steps_md or '')[:1500]}"
            items.append(Item(t.ref, "dev", t, f, t.title, src))
        if f.status != DONE and not open_tasks:
            src = f"{f.title}\n{f.description or ''}"
            items.append(Item(f.ref, "feature", f, f, f.title, src))

    # A feature's estimate is shown once, on its first open item; finished features carry no estimate.
    seen: set[int] = set()
    for it in items:
        if it.feature.status != DONE and it.feature.id not in seen:
            it.hours = _hours(it.feature) or None
            seen.add(it.feature.id)
        s = saved.get(it.ref)
        if s:
            it.meta = s
            if s.get("title"):
                it.plain, it.stale = s, s.get("src") != _digest(it.source)

    result = WhatsLeft()
    for key, label, hint in TYPES:
        result.groups.append((key, label, hint, [i for i in items if i.type == key]))
    result.finished = [f for f in project.features if f.status == DONE]
    result.decisions = [r for r in project.requirements if r.type == "OPEN_QUESTION"]
    result.open_issues = [i for i in project.issues if i.status in ("New", "Planned")]
    result.hours = sum(i.hours or 0 for i in items)
    result.missing = sum(1 for i in items if not i.plain or i.stale)
    return result


PROMPT = """You are explaining a software project's remaining work to the project owner, who is not a developer.

Below are the open work items. For each one write:
- "title": a short plain-English name for the work (at most 10 words), e.g. "Invoice page offers the wrong button".
- "what": one or two sentences on what will change, as the user or business will see it.
- "why": one sentence on why it matters (the problem it removes or the benefit).

- "type": exactly one of
    "bug"     - something already built that does not work as it should (a defect, wrong data, dead menu entry);
    "feature" - work from the original plan that is not finished yet;
    "new"     - a new capability added after the original plan, not asked for through a change request;
    "cr"      - a change the client asked for after scope was agreed (usually traceable to a change request below).
  An item on a finished feature is usually a bug, but a requested change to a finished feature is a cr.
- "origin": the ref of the reported issue it came from (from the list below), or "" if none.

Rules: no file names, function names, database tables, column names, code or ticket jargon. Name screens and
actions the way a user would ("the Goods Receipt form", "saving a project"). Keep each item's own facts;
do not invent scope. If an item is optional or waiting for a decision, say so.

Project: {project}

Reported issues (bugs, change requests, questions) for context:
{issues}

Items (JSON):
{items}

Return only JSON: {{"items": [{{"ref": "...", "title": "...", "what": "...", "why": "...", "type": "...", "origin": "..."}}]}}
with one entry per ref."""


def _mock_summary(it: Item) -> dict:
    title = re.sub(r"^(D-\d+( and D-\d+)?:\s*)", "", it.tech_title).strip()
    return {"title": title[:1].upper() + title[1:], "what": f"Part of: {it.feature.title}.", "why": "",
            "type": "bug" if it.feature.status == DONE else "feature", "origin": ""}


def set_type(db: Session, project: Project, ref: str, type_: str) -> None:
    if type_ not in TYPE_LABEL:
        raise ValueError("Unknown type.")
    saved = dict(project.plain_summaries or {})
    saved[ref] = {**saved.get(ref, {}), "type": type_, "type_by_user": True}
    project.plain_summaries = saved
    flag_modified(project, "plain_summaries")
    db.flush()


def explain(db: Session, project: Project, *, refresh_all: bool = False) -> int:
    """Write plain summaries for items that have none (or whose source changed). Returns how many were written."""
    wl = collect(project)
    todo = [i for _, _, _, items in wl.groups for i in items if refresh_all or not i.plain or i.stale]
    if not todo:
        return 0
    if get_settings().ai_is_live:
        payload = [{"ref": i.ref, "area": i.feature.title, "feature_finished": i.feature.status == DONE,
                    "details": i.source} for i in todo]
        issues = [{"ref": i.ref, "kind": i.kind, "status": i.status, "title": i.title,
                   "description": (i.description or "")[:800]} for i in project.issues]
        text = ai_orchestrator.call_claude(PROMPT.format(
            project=project.name, issues=json.dumps(issues, ensure_ascii=False, indent=1) if issues else "(none)",
            items=json.dumps(payload, ensure_ascii=False, indent=1)))
        try:
            rows = extract_json(text).get("items", [])
        except (OutputParseError, AttributeError) as exc:
            raise ai_orchestrator.AIError(f"Could not read Claude's answer: {exc}") from exc
        by_ref = {str(r.get("ref")): r for r in rows if isinstance(r, dict)}
    else:
        by_ref = {i.ref: _mock_summary(i) for i in todo}

    saved = dict(project.plain_summaries or {})
    written = 0
    for i in todo:
        r = by_ref.get(i.ref)
        if not r or not str(r.get("title", "")).strip():
            continue
        entry = {"title": str(r["title"]).strip(), "what": str(r.get("what", "")).strip(),
                 "why": str(r.get("why", "")).strip(), "src": _digest(i.source),
                 "type": r.get("type") if r.get("type") in TYPE_LABEL else i.type,
                 "origin": str(r.get("origin") or "").strip()}
        if i.type_by_user:  # a type the user chose is never overwritten
            entry.update(type=i.type, type_by_user=True)
        saved[i.ref] = entry
        written += 1
    project.plain_summaries = saved
    flag_modified(project, "plain_summaries")
    db.flush()
    return written
