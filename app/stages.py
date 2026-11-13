"""The 10-stage SDLC pipeline registry."""
from __future__ import annotations

from dataclasses import dataclass


class Status:
    LOCKED = "Locked"
    NOT_STARTED = "Not Started"
    DRAFT = "Draft"
    IN_REVIEW = "In Review"
    APPROVED = "Approved"
    IN_PROGRESS = "In Progress"
    DONE = "Done"

    ALL = [LOCKED, NOT_STARTED, DRAFT, IN_REVIEW, APPROVED, IN_PROGRESS, DONE]
    # statuses that satisfy the approval gate for the next stage
    GATE_OPEN = {APPROVED, IN_PROGRESS, DONE}


@dataclass(frozen=True)
class Stage:
    no: int
    key: str
    slug: str
    title: str
    short: str
    output: str  # "json" | "markdown"
    roles: tuple[str, ...]
    description: str


STAGES: list[Stage] = [
    Stage(1, "requirements", "01-requirements", "Requirement Gathering", "Requirements", "json",
          ("Solution Architect",), "Extract FRs, NFRs, constraints, assumptions and open questions from raw notes."),
    Stage(2, "brd", "02-brd", "Business Requirements Document", "BRD", "markdown",
          ("Solution Architect",), "Executive summary, objectives, scope, process flows, business rules, success metrics."),
    Stage(3, "tsd", "03-tsd", "Technical Specification Document", "TSD", "markdown",
          ("Solution Architect", "Developer"), "Architecture, ERD (Mermaid), API endpoints, security, integrations, edge cases."),
    Stage(4, "features", "04-features", "Feature List", "Features", "json",
          ("Solution Architect", "Developer"), "Prioritised, dependency-ordered features mapped to REQ IDs with effort."),
    Stage(5, "user_stories", "05-user-stories", "User Stories", "Stories", "json",
          ("Solution Architect", "Developer", "QA"), "Role/Goal/Benefit stories with Gherkin acceptance criteria."),
    Stage(6, "dev_tasks", "06-dev-tasks", "Developer Instructions", "Dev Packs", "json",
          ("Developer",), "Per-feature execution packs with target files, steps, tests and Claude Code prompts."),
    Stage(7, "qa_plans", "07-qa-plans", "QA Instructions", "QA Plans", "json",
          ("QA",), "Per-feature test plans: positive, negative/boundary, regression, automation scaffolds."),
    Stage(8, "release_notes", "08-release-notes", "Release Notes", "Release", "markdown",
          ("DevOps/Release",), "New features, fixes, breaking changes, DB migrations, env var updates."),
    Stage(9, "runbook", "09-implementation-runbook", "Implementation & Deployment Runbook", "Runbook", "markdown",
          ("DevOps/Release",), "Role-assigned deployment checklist with smoke tests and rollback."),
    Stage(10, "user_manual", "10-user-manual", "User Manual", "Manual", "markdown",
          ("Solution Architect",), "End-user manual by persona/workflow with troubleshooting FAQs."),
]

STAGE_BY_NO: dict[int, Stage] = {s.no: s for s in STAGES}
STAGE_BY_KEY: dict[str, Stage] = {s.key: s for s in STAGES}

ROLES = ["All", "Solution Architect", "Developer", "QA", "DevOps/Release"]

REQ_TYPES = ["FR", "NFR", "CONSTRAINT", "ASSUMPTION", "OPEN_QUESTION"]
REQ_TYPE_LABELS = {
    "FR": "Functional",
    "NFR": "Non-Functional",
    "CONSTRAINT": "Constraint",
    "ASSUMPTION": "Assumption",
    "OPEN_QUESTION": "Open Question",
}

ITEM_STATUSES = ["To Do", "In Progress", "Blocked", "Done"]


def get_stage(no: int) -> Stage:
    if no not in STAGE_BY_NO:
        raise KeyError(f"Unknown stage {no}")
    return STAGE_BY_NO[no]
