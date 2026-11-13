"""Structured entity sync (approved JSON -> tables), serializers and the traceability matrix."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import DevTask, Feature, Project, QAPlan, Requirement, UserStory


# ------------------------------------------------------------------ serializers (DB -> stage-shaped dicts)

def req_to_dict(r: Requirement) -> dict:
    return {"ref": r.ref, "type": r.type, "title": r.title, "description": r.description, "priority": r.priority}


def feature_to_dict(f: Feature) -> dict:
    return {"ref": f.ref, "title": f.title, "description": f.description, "module": f.module,
            "priority": f.priority, "depends_on": list(f.depends_on or []),
            "requirement_refs": sorted(r.ref for r in f.requirements),
            "effort_hours": {"solution_architect": f.effort_sa, "developer": f.effort_dev, "qa": f.effort_qa,
                             "docs": f.effort_docs},
            "status": f.status,
            "dev_ref": f.dev_tasks[0].ref if f.dev_tasks else None,
            "qa_ref": f.qa_plans[0].ref if f.qa_plans else None}


def story_to_dict(s: UserStory) -> dict:
    return {"ref": s.ref, "feature_ref": s.feature.ref, "role": s.role, "goal": s.goal, "benefit": s.benefit,
            "acceptance_criteria": s.acceptance_criteria, "ui_notes": s.ui_notes, "api_notes": s.api_notes,
            "edge_cases": list(s.edge_cases or [])}


def dev_to_dict(d: DevTask) -> dict:
    return {"ref": d.ref, "feature_ref": d.feature.ref, "title": d.title, "target_files": d.target_files or [],
            "migration_notes": d.migration_notes, "implementation_steps_md": d.implementation_steps_md,
            "unit_tests_md": d.unit_test_reqs_md, "status": d.status}


def all_stories(project: Project) -> list[UserStory]:
    return [s for f in project.features for s in f.stories]


def all_dev_tasks(project: Project) -> list[DevTask]:
    return [d for f in project.features for d in f.dev_tasks]


def all_qa_plans(project: Project) -> list[QAPlan]:
    return [q for f in project.features for q in f.qa_plans]


# ------------------------------------------------------------------ sync on approval

def _bullets(items: list[str], numbered: bool = False) -> str:
    return "\n".join(f"{i}. {s}" if numbered else f"- {s}" for i, s in enumerate(items, 1))


def _tests_md(tests: list[dict]) -> str:
    out = []
    for t in tests:
        steps = "; ".join(t.get("steps", []))
        out.append(f"- **{t.get('id', '')}** [{t.get('story_ref', '')}] {t['title']} - _Steps:_ {steps} "
                   f"- _Expected:_ {t.get('expected', '')}")
    return "\n".join(out)


def sync_stage(db: Session, project: Project, stage_no: int, doc: dict) -> None:
    """Upsert structured rows from an approved JSON artifact. Rows are matched by ref so IDs/statuses survive."""
    pid = project.id
    if stage_no == 1:
        existing = {r.ref: r for r in project.requirements}
        seen = set()
        for item in doc["requirements"]:
            r = existing.get(item["ref"]) or Requirement(project_id=pid, ref=item["ref"])
            r.type, r.title, r.description, r.priority = item["type"], item["title"], item["description"], item["priority"]
            if r.id is None:
                project.requirements.append(r)
            seen.add(item["ref"])
        for ref, r in existing.items():
            if ref not in seen:
                project.requirements.remove(r)

    elif stage_no == 4:
        reqs = {r.ref: r for r in project.requirements}
        existing = {f.ref: f for f in project.features}
        seen = set()
        for idx, item in enumerate(doc["features"]):
            f = existing.get(item["ref"]) or Feature(project_id=pid, ref=item["ref"])
            e = item.get("effort_hours", {})
            f.title, f.description, f.module, f.priority = item["title"], item["description"], item["module"], item["priority"]
            f.order_index, f.depends_on = idx, item["depends_on"]
            f.effort_sa, f.effort_dev = e.get("solution_architect", 0), e.get("developer", 0)
            f.effort_qa, f.effort_docs = e.get("qa", 0), e.get("docs", 0)
            f.requirements = [reqs[r] for r in item["requirement_refs"] if r in reqs]
            if f.id is None:
                project.features.append(f)
            seen.add(item["ref"])
        for ref, f in existing.items():
            if ref not in seen:
                project.features.remove(f)

    elif stage_no == 5:
        feats = {f.ref: f for f in project.features}
        existing = {s.ref: s for s in all_stories(project)}
        seen = set()
        for item in doc["stories"]:
            feat = feats.get(item["feature_ref"])
            if not feat:
                continue
            s = existing.get(item["ref"]) or UserStory(project_id=pid, ref=item["ref"])
            s.role, s.goal, s.benefit = item["role"], item["goal"], item["benefit"]
            s.acceptance_criteria, s.ui_notes, s.api_notes = item["acceptance_criteria"], item["ui_notes"], item["api_notes"]
            s.edge_cases = item["edge_cases"]
            if s.feature is not feat:
                if s.feature is not None:
                    s.feature.stories.remove(s)
                feat.stories.append(s)
            seen.add(item["ref"])
        for ref, s in existing.items():
            if ref not in seen:
                s.feature.stories.remove(s)

    elif stage_no == 6:
        feats = {f.ref: f for f in project.features}
        existing = {d.ref: d for d in all_dev_tasks(project)}
        seen = set()
        for item in doc["tasks"]:
            feat = feats.get(item["feature_ref"])
            if not feat:
                continue
            d = existing.get(item["ref"]) or DevTask(project_id=pid, ref=item["ref"], title=item["title"])
            d.title, d.target_files, d.migration_notes = item["title"], item["target_files"], item["migration_notes"]
            d.implementation_steps_md = _bullets(item["implementation_steps"], numbered=True)
            d.unit_test_reqs_md = _bullets(item["unit_tests"])
            d.claude_prompt = item["claude_prompt"]
            if d.feature is not feat:
                if d.feature is not None:
                    d.feature.dev_tasks.remove(d)
                feat.dev_tasks.append(d)
            seen.add(item["ref"])
        for ref, d in existing.items():
            if ref not in seen:
                d.feature.dev_tasks.remove(d)

    elif stage_no == 7:
        feats = {f.ref: f for f in project.features}
        existing = {q.ref: q for q in all_qa_plans(project)}
        seen = set()
        for item in doc["plans"]:
            feat = feats.get(item["feature_ref"])
            if not feat:
                continue
            q = existing.get(item["ref"]) or QAPlan(project_id=pid, ref=item["ref"])
            q.story_refs = item["story_refs"]
            q.positive_md, q.negative_md = _tests_md(item["positive_tests"]), _tests_md(item["negative_tests"])
            q.regression_md = _bullets(item["regression_checks"])
            q.automation_scaffold, q.claude_prompt = item["automation_scaffold"], item.get("claude_prompt", "")
            if q.feature is not feat:
                if q.feature is not None:
                    q.feature.qa_plans.remove(q)
                feat.qa_plans.append(q)
            seen.add(item["ref"])
        for ref, q in existing.items():
            if ref not in seen:
                q.feature.qa_plans.remove(q)
    db.flush()


# ------------------------------------------------------------------ matrix

@dataclass
class MatrixRow:
    requirement: Requirement | None
    feature: Feature | None
    stories: list[UserStory] = field(default_factory=list)
    dev_tasks: list[DevTask] = field(default_factory=list)
    qa_plans: list[QAPlan] = field(default_factory=list)

    @property
    def gap(self) -> str:
        if self.requirement is not None and self.feature is None:
            return "No feature covers this requirement"
        if self.feature is not None and self.requirement is None:
            return "Feature not mapped to a requirement"
        if self.feature is not None and not self.stories:
            return "No user stories"
        return ""


@dataclass
class Matrix:
    rows: list[MatrixRow]
    stats: dict


def build_matrix(project: Project) -> Matrix:
    rows: list[MatrixRow] = []
    traceable = [r for r in project.requirements if r.type in ("FR", "NFR", "CONSTRAINT")]
    for r in traceable:
        feats = sorted(r.features, key=lambda f: f.order_index)
        if not feats:
            rows.append(MatrixRow(r, None))
        for f in feats:
            rows.append(MatrixRow(r, f, list(f.stories), list(f.dev_tasks), list(f.qa_plans)))
    for f in project.features:
        if not f.requirements:
            rows.append(MatrixRow(None, f, list(f.stories), list(f.dev_tasks), list(f.qa_plans)))
    covered = sum(1 for r in traceable if r.features)
    stats = {
        "requirements": len(project.requirements),
        "traceable": len(traceable),
        "covered": covered,
        "coverage_pct": round(100 * covered / len(traceable)) if traceable else 0,
        "features": len(project.features),
        "stories": len(all_stories(project)),
        "dev_tasks": len(all_dev_tasks(project)),
        "qa_plans": len(all_qa_plans(project)),
        "gaps": sum(1 for row in rows if row.gap),
    }
    return Matrix(rows, stats)


def matrix_markdown(project: Project) -> str:
    m = build_matrix(project)
    out = [f"# Traceability Matrix - {project.name}", "",
           f"Coverage: {m.stats['covered']}/{m.stats['traceable']} traceable requirements "
           f"({m.stats['coverage_pct']}%)", "", "| REQ | Feature | User Stories | DEV | QA | Gap |",
           "|---|---|---|---|---|---|"]
    for row in m.rows:
        out.append("| {} | {} | {} | {} | {} | {} |".format(
            row.requirement.ref if row.requirement else "-",
            f"{row.feature.ref} {row.feature.title}" if row.feature else "-",
            ", ".join(s.ref for s in row.stories) or "-",
            ", ".join(f"{d.ref} ({d.status})" for d in row.dev_tasks) or "-",
            ", ".join(f"{q.ref} ({q.status})" for q in row.qa_plans) or "-",
            row.gap or ""))
    return "\n".join(out) + "\n"
