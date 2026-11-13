"""Import a folder of ready-made stage artifacts as a project (e.g. a reverse-engineered existing system).

Folder layout:
    project.json            {"name", "code", "client", "description", "raw_notes",
                             "target_repo_path"?, "approve_through"?}
    01-<anything>.json      stage 1 (JSON stages: 1, 4, 5, 6, 7)
    02-<anything>.md        stage 2 (Markdown stages: 2, 3, 8, 9, 10)
    ...

Optional "build_status" on feature / story / dev task / QA plan items sets the tracked item status after
import ("To Do", "In Progress", "Blocked", "Done"), so an as-built system shows what is already delivered.

Usage:
    python import_artifacts.py <folder> [--replace] [--approve-through N]

Stages are validated exactly like a manual save in the editor. Stages up to --approve-through (default: the
value in project.json, else none) are approved in order, which syncs the traceability tables.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Project
from app.services.parsers import LIST_KEY_BY_STAGE
from app.services.traceability import all_dev_tasks, all_qa_plans, all_stories
from app.services.workflow import (WorkflowError, approve, ensure_artifacts, parse_manual, store_content)
from app.stages import ITEM_STATUSES, STAGES

ITEM_SOURCES = {4: lambda p: p.features, 5: all_stories, 6: all_dev_tasks, 7: all_qa_plans}


def find_stage_file(folder: Path, stage_no: int, output: str) -> Path | None:
    ext = ".json" if output == "json" else ".md"
    hits = sorted(folder.glob(f"{stage_no:02d}-*{ext}"))
    return hits[0] if hits else None


def apply_build_status(project: Project, stage_no: int, raw: dict) -> int:
    if stage_no not in ITEM_SOURCES:
        return 0
    wanted = {i["ref"].upper(): i["build_status"] for i in raw.get(LIST_KEY_BY_STAGE[stage_no], [])
              if i.get("build_status") in ITEM_STATUSES and i.get("ref")}
    n = 0
    for item in ITEM_SOURCES[stage_no](project):
        if item.ref in wanted:
            item.status = wanted[item.ref]
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--replace", action="store_true", help="delete an existing project with the same code first")
    ap.add_argument("--approve-through", type=int, default=None)
    args = ap.parse_args()

    folder = args.folder.resolve()
    meta = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    approve_through = args.approve_through if args.approve_through is not None else int(meta.get("approve_through", 0))

    init_db()
    db = SessionLocal()
    try:
        existing = db.scalar(select(Project).where(Project.code == meta["code"]))
        if existing:
            if not args.replace:
                print(f"Project {meta['code']} already exists (id={existing.id}). Use --replace to overwrite it.")
                return 1
            db.delete(existing)
            db.commit()

        p = Project(name=meta["name"], code=meta["code"], client=meta.get("client", ""),
                    description=meta.get("description", ""), raw_notes=meta.get("raw_notes", ""),
                    target_repo_path=meta.get("target_repo_path", ""))
        db.add(p)
        db.flush()
        ensure_artifacts(db, p)

        for stage in STAGES:
            path = find_stage_file(folder, stage.no, stage.output)
            if not path:
                continue
            text = path.read_text(encoding="utf-8")
            artifact = p.artifact(stage.no)
            if artifact.status == "Locked":
                artifact.status = "Not Started"  # importing pre-existing work; gating applies to approval below
            md, doc = parse_manual(p, stage.no, text)
            store_content(db, p, artifact, md, doc, "manual", f"Imported from {path.name}")
            line = f"  stage {stage.no:02d} {stage.short:<10} v{artifact.version} from {path.name}"
            if stage.no <= approve_through:
                approve(db, p, stage.no, "Importer")
                n = apply_build_status(p, stage.no, json.loads(text)) if stage.output == "json" else 0
                line += " -> Approved" + (f" ({n} item statuses set)" if n else "")
            print(line)

        db.commit()
        print(f"Imported project {p.code} (id={p.id}). Open http://127.0.0.1:8000/projects/{p.id}")
        return 0
    except (WorkflowError, ValueError, KeyError) as exc:
        db.rollback()
        print(f"Import failed: {exc}")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
