"""Download all documents of a project as one ZIP: every stage with content, traceability, issues, attachments."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

from app.models import Project
from app.services import attachments as att_service
from app.services.issues import KIND_LABEL
from app.services.docx_export import markdown_to_docx
from app.services.repo_sync import FILE_NAMES, stage_files
from app.services.traceability import matrix_markdown
from app.stages import STAGES, Status


def _readme(project: Project) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for s in STAGES:
        a = project.artifact(s.no)
        approved = f"{a.approved_by} · {a.approved_at:%Y-%m-%d}" if a and a.approved_at else ""
        rows.append(f"| {s.no:02d} | {s.title} | {a.status if a else '-'} | "
                    f"{('v' + str(a.version)) if a and a.version else '-'} | {approved} |")
    drafts = [s.no for s in STAGES if project.artifact(s.no) and project.artifact(s.no).has_content
              and project.artifact(s.no).status not in Status.GATE_OPEN]
    note = (f"\n> Stages {', '.join(f'{n:02d}' for n in drafts)} are not approved yet; their files are the current "
            "draft.\n" if drafts else "")
    return (f"# {project.name} ({project.code})\n\nClient: {project.client or '-'}  \nExported: {now}\n\n"
            f"{project.description or ''}\n\n## Stages\n\n| # | Stage | Status | Version | Approved |\n"
            f"|---|---|---|---|---|\n" + "\n".join(rows) + "\n" + note
            + "\nFolders: one per stage (`NN-name/`), each with the document as Word (.docx) and Markdown and, for structured stages, "
              "the JSON. Dev packs and QA plans also have one file each. `traceability.md` is the REQ -> FEAT -> US "
              "-> DEV -> QA matrix and `issues.md` the bug / change request register.\n")


def _issues_md(project: Project) -> str:
    if not project.issues:
        return "# Issues\n\nNo issues reported.\n"
    lines = ["# Issues", "", "| Ref | Kind | Title | Status | Stages updated | Reported |", "|---|---|---|---|---|---|"]
    for i in sorted(project.issues, key=lambda x: x.id):
        done = ", ".join(f"{s['stage_no']:02d}→v{s['version']}" for s in (i.plan or []) if s.get("version")) or "-"
        lines.append(f"| {i.ref} | {KIND_LABEL.get(i.kind, i.kind)} | {i.title or i.description[:60]} | {i.status} | "
                     f"{done} | {i.created_at:%Y-%m-%d}{(' · ' + i.reporter) if i.reporter else ''} |")
    for i in sorted(project.issues, key=lambda x: x.id):
        lines += ["", f"## {i.ref} - {i.title or 'Untitled'}", "", f"**Report:** {i.description}", ""]
        if i.reasoning:
            lines += [f"**Why it is a {KIND_LABEL.get(i.kind, i.kind).lower()}:** {i.reasoning}", ""]
        for s in i.plan or []:
            mark = "x" if s.get("version") else " "
            lines.append(f"- [{mark}] Stage {s['stage_no']:02d}: {s['instruction']}"
                         + (f" ({s['result']})" if s.get("result") else ""))
    return "\n".join(lines) + "\n"


def build_zip(project: Project, include_attachments: bool = True) -> bytes:
    root = f"{project.code}-sdlc"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{root}/README.md", _readme(project))
        artifacts = [a for a in project.artifacts if a.has_content]
        for rel, content in stage_files(artifacts, base_dir=root).items():
            z.writestr(rel, content)
        for a in artifacts:  # a Word copy of every stage document, for people who don't use Markdown
            st = STAGES[a.stage_no - 1]
            z.writestr(f"{root}/{st.slug}/{FILE_NAMES[a.stage_no]}.docx",
                       markdown_to_docx(a.content_md, title=f"{st.no:02d} · {st.title}",
                                        subtitle=f"{project.name} ({project.code}) · v{a.version} · {a.status}"))
        z.writestr(f"{root}/traceability.md", matrix_markdown(project))
        z.writestr(f"{root}/issues.md", _issues_md(project))
        if include_attachments:
            for a in project.attachments:
                try:
                    data = att_service.read_bytes(a)
                except Exception:  # noqa: BLE001 - a missing file is skipped, not fatal
                    continue
                where = (f"issues/{a.issue.ref}" if a.issue is not None
                         else f"stage-{a.stage_no:02d}" if a.stage_no else "project")
                z.writestr(f"{root}/attachments/{where}/{a.id}-{a.filename}", data)
    return buf.getvalue()
