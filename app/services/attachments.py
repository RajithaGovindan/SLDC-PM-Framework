"""Attachments: store uploaded files, extract readable text, and turn them into Claude content blocks.

Images and PDFs are sent to Claude as they are (Claude reads screenshots and PDF pages directly). Word, Excel,
CSV and plain-text files are converted to text locally first. Files are kept under ATTACHMENTS_DIR, which is
gitignored, and are only sent to the API when "use in AI" is ticked.
"""
from __future__ import annotations

import base64
import csv
import io
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Attachment, Issue, Project

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".sql", ".log"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024       # larger images are stored but not sent to Claude
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 60_000                 # per attachment, after extraction
MAX_SHEET_ROWS = 500


class AttachmentError(ValueError):
    pass


def kind_for(filename: str) -> tuple[str, str]:
    """(kind, mime) from the file extension."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_TYPES:
        return "image", IMAGE_TYPES[ext]
    if ext == ".pdf":
        return "pdf", "application/pdf"
    if ext == ".docx":
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext in (".xlsx", ".xlsm"):
        return "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext in TEXT_SUFFIXES:
        return "text", "text/csv" if ext == ".csv" else "text/plain"
    return "other", "application/octet-stream"


def storage_dir(project_id: int) -> Path:
    d = Path(get_settings().attachments_dir) / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_of(att: Attachment) -> Path:
    return Path(get_settings().attachments_dir) / str(att.project_id) / att.stored_name


def _safe_name(name: str) -> str:
    name = Path(name or "file").name
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "file"


def save(db: Session, project: Project, filename: str, data: bytes, *, stage_no: int | None = None,
         issue: Issue | None = None, note: str = "") -> Attachment:
    limit = get_settings().max_attachment_mb * 1024 * 1024
    if not data:
        raise AttachmentError(f"{filename}: the file is empty.")
    if len(data) > limit:
        raise AttachmentError(f"{filename}: larger than {get_settings().max_attachment_mb} MB.")
    name = _safe_name(filename)
    kind, mime = kind_for(name)
    stored = f"{uuid.uuid4().hex[:12]}_{name}"
    (storage_dir(project.id) / stored).write_bytes(data)
    att = Attachment(project_id=project.id, stage_no=stage_no, issue=issue, filename=name, stored_name=stored,
                     mime=mime, kind=kind, size=len(data), note=note.strip(), use_in_ai=kind != "other")
    project.attachments.append(att)
    db.flush()
    return att


def delete(db: Session, att: Attachment) -> None:
    try:
        path_of(att).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(att)
    db.flush()


# --------------------------------------------------------------------------- text extraction

def _docx_text(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    out = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = docx.text.paragraph.Paragraph(block, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            level = re.search(r"heading (\d)", style)
            out.append(("#" * int(level.group(1)) + " " + text) if level else text)
        elif tag == "tbl":
            table = docx.table.Table(block, doc)
            rows = [[c.text.strip().replace("\n", " ") for c in r.cells] for r in table.rows]
            out.append(_md_table(rows))
    return "\n\n".join(out)


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            if row is None or all(v in (None, "") for v in row):
                continue
            rows.append(["" if v is None else str(v).replace("\n", " ") for v in row])
            if len(rows) > MAX_SHEET_ROWS:
                break
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        more = f"\n(first {MAX_SHEET_ROWS} rows shown)" if len(rows) > MAX_SHEET_ROWS else ""
        parts.append(f"## Sheet: {ws.title}\n\n{_md_table(rows[:MAX_SHEET_ROWS + 1])}{more}")
    wb.close()
    return "\n\n".join(parts)


def _csv_text(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))[:MAX_SHEET_ROWS + 1]
    return _md_table(rows) if rows else ""


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[c.replace("|", "\\|") for c in r] + [""] * (width - len(r)) for r in rows]
    head, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def extract_text(att: Attachment) -> str:
    """Readable text for Word, Excel, CSV and text attachments ('' for images, PDFs and other files)."""
    data = path_of(att).read_bytes()
    try:
        if att.kind == "docx":
            text = _docx_text(data)
        elif att.kind == "xlsx":
            text = _xlsx_text(data)
        elif att.kind == "text" and att.filename.lower().endswith(".csv"):
            text = _csv_text(data)
        elif att.kind == "text":
            text = data.decode("utf-8", errors="replace")
        else:
            return ""
    except Exception as exc:  # a corrupt or password-protected file should not break generation
        return f"[Could not read {att.filename}: {exc}]"
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + "\n[truncated]"


# --------------------------------------------------------------------------- Claude content blocks

def sendable(att: Attachment) -> tuple[bool, str]:
    """Whether this attachment can be sent to Claude, and why not."""
    if not att.use_in_ai:
        return False, "not ticked for AI"
    if att.kind == "other":
        return False, "file type Claude can't read"
    if att.kind == "image" and att.size > MAX_IMAGE_BYTES:
        return False, "image over 5 MB"
    if att.kind == "pdf" and att.size > MAX_PDF_BYTES:
        return False, "PDF over 30 MB"
    return True, ""


def content_blocks(atts: list[Attachment]) -> list[dict]:
    blocks: list[dict] = []
    for att in atts:
        ok, _ = sendable(att)
        if not ok:
            continue
        label = att.filename + (f" - {att.note}" if att.note else "")
        if att.kind in ("image", "pdf"):
            data = base64.standard_b64encode(path_of(att).read_bytes()).decode("ascii")
            blocks.append({"type": "text", "text": f"<attachment name=\"{label}\"> follows:"})
            if att.kind == "image":
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": att.mime, "data": data}})
            else:
                blocks.append({"type": "document", "title": att.filename,
                               "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
        else:
            blocks.append({"type": "text",
                           "text": f"<attachment name=\"{label}\">\n{extract_text(att)}\n</attachment>"})
    return blocks


def for_stage(project: Project, stage_no: int, *, include_project: bool = True) -> list[Attachment]:
    """Attachments that feed a stage: project-level ones (optional) plus the stage's own."""
    return [a for a in project.attachments if a.issue_id is None
            and ((a.stage_no is None and include_project) or a.stage_no == stage_no)]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
