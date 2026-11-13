"""Write approved artifacts into <target_repo>/.sdlc/ and Claude Code slash commands into .claude/commands/."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Project, SyncLog
from app.services.renderers import render_dev_task, render_qa_plan
from app.services.traceability import matrix_markdown
from app.stages import STAGES, Status

MANIFEST = "manifest.json"
GENERATOR_TAG = "sdlc-orchestrator"


class SyncError(ValueError):
    pass


def _approved(project: Project):
    return [a for a in project.artifacts if a.status in Status.GATE_OPEN and a.has_content]


FILE_NAMES = {1: "requirements", 2: "brd", 3: "tsd", 4: "features", 5: "user-stories", 6: "dev-packs",
              7: "qa-plans", 8: "release-notes", 9: "runbook", 10: "user-manual"}


def preview_files(project: Project) -> list[str]:
    files = [".sdlc/README.md", ".sdlc/manifest.json", ".sdlc/traceability.md"]
    for a in _approved(project):
        st = STAGES[a.stage_no - 1]
        files.append(f".sdlc/{st.slug}/{FILE_NAMES[a.stage_no]}.md")
        if a.content_json is not None:
            files.append(f".sdlc/{st.slug}/{FILE_NAMES[a.stage_no]}.json")
        if a.stage_no == 6:
            files += [f".sdlc/{st.slug}/{t['ref']}-{t['feature_ref']}.md" for t in a.content_json.get("tasks", [])]
        if a.stage_no == 7:
            files += [f".sdlc/{st.slug}/{p['ref']}-{p['feature_ref']}.md" for p in a.content_json.get("plans", [])]
    files += [".claude/commands/sdlc-status.md", ".claude/commands/implement-feature.md",
              ".claude/commands/qa-feature.md"]
    return files


# ------------------------------------------------------------------------- slash command templates

def _cmd_status(project: Project) -> str:
    return f"""---
description: Show SDLC pipeline status, traceability and next actions for {project.name}
---

You are working inside the repository for **{project.name}** ({project.code}). The approved SDLC artifacts
exported by the SDLC Orchestrator live in `.sdlc/`.

1. Read `.sdlc/README.md` and `.sdlc/manifest.json` for the stage status table.
2. Read `.sdlc/traceability.md`.
3. Inspect the codebase to judge which features (FEAT-###) appear implemented, using the target files listed in
   each `.sdlc/06-dev-tasks/DEV-*.md` pack.

Report concisely:
- A table of the 10 SDLC stages with their status.
- A table of features: FEAT, title, DEV pack, QA plan, and your evidence-based implementation status
  (Not started / Partial / Implemented) with the files you checked.
- Requirement coverage gaps from the traceability matrix.
- The 3 most valuable next actions, naming the slash command to run (e.g. `/implement-feature FEAT-002`).

Do not modify any files.
"""


def _cmd_implement() -> str:
    return """---
description: Implement one approved feature from its SDLC Developer Execution Pack
argument-hint: FEAT-###
---

Implement feature **$ARGUMENTS** exactly as specified by the approved SDLC artifacts in `.sdlc/`.

1. Find the Developer Execution Pack for $ARGUMENTS: `.sdlc/06-dev-tasks/DEV-*-$ARGUMENTS.md`.
   If none exists, stop and say the Dev Pack for $ARGUMENTS has not been approved yet.
2. Read `.sdlc/03-tsd/tsd.md` for architecture, data model and API conventions.
3. Read the user stories for $ARGUMENTS and their Gherkin acceptance criteria in
   `.sdlc/05-user-stories/user-stories.md`.
4. Read the feature entry in `.sdlc/04-features/features.md` and confirm the features it depends on are already
   implemented. If not, stop and list the missing dependencies.
5. Follow the pack's **Claude Code execution prompt** and implementation steps. Touch only the target files listed
   in the pack unless a change elsewhere is strictly required; explain any deviation.
6. Write the unit tests listed in the pack, then run the project's test suite and fix failures.

Finish with: files changed, migrations added, tests added and their result, and any acceptance criterion
you could not satisfy.
"""


def _cmd_qa() -> str:
    return """---
description: Execute the approved SDLC QA plan for one feature
argument-hint: FEAT-###
---

Verify feature **$ARGUMENTS** against its approved QA plan.

1. Read the QA plan `.sdlc/07-qa-plans/QA-*-$ARGUMENTS.md`. If none exists, stop and say the QA plan for
   $ARGUMENTS has not been approved yet.
2. Read the acceptance criteria for the stories it covers in `.sdlc/05-user-stories/user-stories.md` and the
   Dev Pack `.sdlc/06-dev-tasks/DEV-*-$ARGUMENTS.md` to know which files implement it.
3. Implement the automated tests from the plan's scaffold under the project's test directory, matching the
   existing test conventions. Do not modify application code.
4. Run the tests. For manual-only cases, inspect the code paths and state whether they would pass.

Report a table: test case ID, story, type (positive/negative/regression), result (Pass/Fail/Blocked), notes.
List every failure as a defect with reproduction steps and the likely faulty file.
"""


def _readme(project: Project) -> str:
    rows = "\n".join(f"| {s.no:02d} | {s.title} | {project.artifact(s.no).status} | "
                     f"{'v' + str(project.artifact(s.no).version) if project.artifact(s.no).version else '-'} |"
                     for s in STAGES)
    return f"""# SDLC Artifacts - {project.name}

Exported by the SDLC Orchestrator on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.
Only **approved** artifacts are exported. Do not edit these files by hand; edit in the Orchestrator and re-sync.

| Stage | Name | Status | Version |
|---|---|---|---|
{rows}

## Claude Code commands

- `/sdlc-status` - pipeline status, coverage gaps, next actions
- `/implement-feature FEAT-###` - implement a feature from its Developer Execution Pack
- `/qa-feature FEAT-###` - execute the QA plan for a feature
"""


# ------------------------------------------------------------------------- sync

def stage_files(artifacts, base_dir: str = ".sdlc") -> dict[str, str]:
    """Markdown (and JSON) files for each stage artifact, plus one file per dev pack and QA plan."""
    out: dict[str, str] = {}
    for a in artifacts:
        st = STAGES[a.stage_no - 1]
        base = f"{base_dir}/{st.slug}/{FILE_NAMES[a.stage_no]}"
        out[base + ".md"] = a.content_md
        if a.content_json is not None:
            out[base + ".json"] = json.dumps(a.content_json, indent=2, ensure_ascii=False)
        if a.stage_no == 6:
            for t in a.content_json.get("tasks", []):
                out[f"{base_dir}/{st.slug}/{t['ref']}-{t['feature_ref']}.md"] = render_dev_task(t)
        if a.stage_no == 7:
            for p in a.content_json.get("plans", []):
                out[f"{base_dir}/{st.slug}/{p['ref']}-{p['feature_ref']}.md"] = render_qa_plan(p)
    return out


def manifest(project: Project) -> dict:
    return {"generator": GENERATOR_TAG, "project": project.name, "code": project.code,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "stages": [{"no": s.no, "slug": s.slug, "status": project.artifact(s.no).status,
                        "version": project.artifact(s.no).version} for s in STAGES],
            "features": [{"ref": f.ref, "title": f.title, "status": f.status,
                          "dev": [d.ref for d in f.dev_tasks], "qa": [q.ref for q in f.qa_plans],
                          "stories": [s.ref for s in f.stories]} for f in project.features]}


def export_files(project: Project) -> dict[str, str]:
    """Everything Repo Sync writes, as {relative path: content}. Approved stages only."""
    out = stage_files(_approved(project))
    out[".sdlc/traceability.md"] = matrix_markdown(project)
    out[".sdlc/README.md"] = _readme(project)
    out[".claude/commands/sdlc-status.md"] = _cmd_status(project)
    out[".claude/commands/implement-feature.md"] = _cmd_implement()
    out[".claude/commands/qa-feature.md"] = _cmd_qa()
    out[".sdlc/manifest.json"] = json.dumps(manifest(project), indent=2)
    return out


def sync_project(db: Session, project: Project, target: str | None = None) -> SyncLog:
    target = (target or project.target_repo_path or "").strip()
    log = SyncLog(project_id=project.id, target_path=target, files_written=[], success=False)
    try:
        if not target:
            raise SyncError("Set a target repository path on the project first.")
        if target.startswith(("https://", "http://", "git@")):
            raise SyncError("Repo Sync writes into a folder on this machine, and the repository is a URL. "
                            "Use Download all instead, or run the Orchestrator locally to sync.")
        root = Path(target).expanduser()
        if not root.is_absolute():
            raise SyncError("Target path must be absolute.")
        if not root.is_dir():
            raise SyncError(f"Directory does not exist: {root}")
        approved = _approved(project)
        if not approved:
            raise SyncError("No approved artifacts to export yet.")

        sdlc = root / ".sdlc"
        manifest_path = sdlc / MANIFEST
        if sdlc.exists():
            # Only clear a directory we generated previously, never a user-owned .sdlc folder.
            try:
                owned = json.loads(manifest_path.read_text(encoding="utf-8")).get("generator") == GENERATOR_TAG
            except (OSError, ValueError):
                owned = False
            if not owned:
                raise SyncError(f"{sdlc} exists and was not created by the SDLC Orchestrator; refusing to overwrite.")
            shutil.rmtree(sdlc)
        sdlc.mkdir(parents=True)
        written: list[str] = []

        def write(rel: str, content: str) -> None:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
            written.append(rel)

        for rel, content in export_files(project).items():
            write(rel, content)
        log.files_written, log.success = written, True
        log.message = f"Wrote {len(written)} files to {root}"
    except (SyncError, OSError) as exc:
        log.message = str(exc)
    project.sync_logs.append(log)
    db.flush()
    return log
