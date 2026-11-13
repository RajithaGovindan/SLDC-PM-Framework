"""Render structured (JSON) stage content as readable Markdown."""
from __future__ import annotations

from app.stages import REQ_TYPE_LABELS, REQ_TYPES


def _cell(s: object) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def render_requirements(doc: dict, title: str = "Requirements") -> str:
    out = [f"# {title}", ""]
    if doc.get("summary"):
        out += ["## Summary", "", doc["summary"], ""]
    reqs = doc.get("requirements", [])
    for t in REQ_TYPES:
        group = [r for r in reqs if r["type"] == t]
        if not group:
            continue
        out += [f"## {REQ_TYPE_LABELS[t]} ({len(group)})", "", "| ID | Title | Description | Priority |",
                "|---|---|---|---|"]
        out += [f"| {r['ref']} | {_cell(r['title'])} | {_cell(r['description'])} | {r['priority']} |" for r in group]
        out.append("")
    return "\n".join(out)


def render_features(doc: dict) -> str:
    feats = doc.get("features", [])
    out = ["# Feature List", "", "| ID | Feature | Module | Priority | Depends on | REQs | SA | Dev | QA | Docs |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"solution_architect": 0.0, "developer": 0.0, "qa": 0.0, "docs": 0.0}
    for f in feats:
        e = f.get("effort_hours", {})
        for k in tot:
            tot[k] += float(e.get(k, 0) or 0)
        out.append(f"| {f['ref']} | {_cell(f['title'])} | {f['module']} | {f['priority']} | "
                   f"{', '.join(f['depends_on']) or '-'} | {', '.join(f['requirement_refs']) or '-'} | "
                   f"{e.get('solution_architect', 0)} | {e.get('developer', 0)} | {e.get('qa', 0)} | {e.get('docs', 0)} |")
    out.append(f"| **Total** | | | | | | **{tot['solution_architect']:g}** | **{tot['developer']:g}** | "
               f"**{tot['qa']:g}** | **{tot['docs']:g}** |")
    out.append("")
    for f in feats:
        out += [f"## {f['ref']} - {f['title']}", "", f.get("description", ""), ""]
    return "\n".join(out)


def render_stories(doc: dict) -> str:
    out = ["# User Stories", ""]
    current = None
    for s in doc.get("stories", []):
        if s["feature_ref"] != current:
            current = s["feature_ref"]
            out += [f"## {current}", ""]
        out += [f"### {s['ref']}", "",
                f"**As a** {s['role']}, **I want** {s['goal']}, **so that** {s['benefit']}.", "",
                "**Acceptance criteria**", "", "```gherkin", s["acceptance_criteria"].strip(), "```", ""]
        if s.get("ui_notes"):
            out += [f"**UI notes:** {s['ui_notes']}", ""]
        if s.get("api_notes"):
            out += [f"**API notes:** {s['api_notes']}", ""]
        if s.get("edge_cases"):
            out += ["**Edge cases**", ""] + [f"- {e}" for e in s["edge_cases"]] + [""]
    return "\n".join(out)


def render_dev_task(t: dict) -> str:
    out = [f"# {t['ref']} - {t['title']}", "", f"**Feature:** {t['feature_ref']}", "", "## Target files", "",
           "| Action | Path | Purpose |", "|---|---|---|"]
    out += [f"| {f['action']} | `{f['path']}` | {_cell(f.get('purpose', ''))} |" for f in t.get("target_files", [])]
    out += ["", "## Database migration notes", "", t.get("migration_notes") or "_None._", "",
            "## Implementation steps", ""]
    out += [f"{i}. {s}" for i, s in enumerate(t.get("implementation_steps", []), 1)]
    out += ["", "## Unit test requirements", ""] + [f"- [ ] {u}" for u in t.get("unit_tests", [])]
    out += ["", "## Claude Code execution prompt", "", "```text", (t.get("claude_prompt") or "").strip(), "```", ""]
    return "\n".join(out)


def render_dev_tasks(doc: dict) -> str:
    return "\n---\n\n".join(render_dev_task(t) for t in doc.get("tasks", []))


def _tests_table(tests: list[dict]) -> list[str]:
    if not tests:
        return ["_None._", ""]
    out = ["| ID | Story | Test | Steps | Expected |", "|---|---|---|---|---|"]
    for t in tests:
        steps = "<br>".join(f"{i}. {_cell(s)}" for i, s in enumerate(t.get("steps", []), 1))
        out.append(f"| {t.get('id', '')} | {t.get('story_ref', '')} | {_cell(t['title'])} | {steps} | "
                   f"{_cell(t.get('expected', ''))} |")
    return out + [""]


def render_qa_plan(p: dict) -> str:
    out = [f"# {p['ref']} - QA Plan for {p['feature_ref']}", "",
           f"**Stories covered:** {', '.join(p.get('story_refs', [])) or '-'}", "", "## Positive tests", ""]
    out += _tests_table(p.get("positive_tests", []))
    out += ["## Negative & boundary tests", ""] + _tests_table(p.get("negative_tests", []))
    out += ["## Regression checks", ""] + [f"- [ ] {r}" for r in p.get("regression_checks", [])]
    out += ["", "## Automated test scaffold", "", "```python", (p.get("automation_scaffold") or "").strip(), "```", ""]
    if p.get("claude_prompt"):
        out += ["## Claude Code QA prompt", "", "```text", p["claude_prompt"].strip(), "```", ""]
    return "\n".join(out)


def render_qa_plans(doc: dict) -> str:
    return "\n---\n\n".join(render_qa_plan(p) for p in doc.get("plans", []))


RENDERERS = {1: render_requirements, 4: render_features, 5: render_stories, 6: render_dev_tasks, 7: render_qa_plans}


def render_stage_json(stage_no: int, doc: dict) -> str:
    return RENDERERS[stage_no](doc)
