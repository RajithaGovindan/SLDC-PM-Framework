"""Turn a stage's Markdown into a Word document (.docx).

Handles what the stage documents use: headings, paragraphs, bullet and numbered lists, task lists, tables,
block quotes, fenced code (Mermaid diagrams are kept as their source, labelled), horizontal rules, and inline
**bold**, *italic* and `code`.
"""
from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\([^)]+\))")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _runs(par, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            r = par.add_run(part[1:-1])
            r.font.name = "Consolas"
            r.font.size = Pt(9)
        elif (part.startswith("*") and part.endswith("*")) or (part.startswith("_") and part.endswith("_")):
            par.add_run(part[1:-1]).italic = True
        elif part.startswith("[") and "](" in part:
            label, url = part[1:-1].split("](", 1)
            par.add_run(label)
            r = par.add_run(f" ({url})")
            r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        else:
            par.add_run(part)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _shade(cell, hex_fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _table(doc, rows: list[list[str]]) -> None:
    width = max(len(r) for r in rows)
    t = doc.add_table(rows=len(rows), cols=width)
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        for j in range(width):
            cell = t.cell(i, j)
            cell.paragraphs[0].text = ""
            _runs(cell.paragraphs[0], row[j] if j < len(row) else "")
            for r in cell.paragraphs[0].runs:
                r.font.size = Pt(9)
                if i == 0:
                    r.bold = True
            if i == 0:
                _shade(cell, "E2E8F0")
    doc.add_paragraph()


def markdown_to_docx(md: str, title: str = "", subtitle: str = "") -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    if title:
        doc.add_heading(title, level=0)
    if subtitle:
        p = doc.add_paragraph(subtitle)
        p.runs[0].italic = True

    lines = (md or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            if lang == "mermaid":
                note = doc.add_paragraph()
                note.add_run("Diagram (Mermaid source; view it rendered in the SDLC Orchestrator):").italic = True
            p = doc.add_paragraph()
            r = p.add_run("\n".join(body))
            r.font.name = "Consolas"
            r.font.size = Pt(8.5)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            doc.add_heading(re.sub(r"[*`]", "", m.group(2)), level=min(len(m.group(1)), 4))
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            rows = [_cells(stripped)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            _table(doc, rows)
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run("* * *").font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
            i += 1
            continue
        if stripped.startswith(">"):
            p = doc.add_paragraph(style="Intense Quote")
            _runs(p, stripped.lstrip("> ").strip())
            i += 1
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$", line)
        if m:
            indent = len(m.group(1).expandtabs(4)) // 2
            numbered = m.group(2)[0].isdigit()
            base = "List Number" if numbered else "List Bullet"
            p = doc.add_paragraph(style=base + (f" {min(indent, 2) + 1}" if indent else ""))
            if m.group(3):
                p.add_run("☑ " if m.group(3).strip().lower() == "[x]" else "☐ ")
            _runs(p, m.group(4))
            i += 1
            continue
        # paragraph: join following plain lines
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^\s*(#|\||```|>|[-*+]\s|\d+[.)]\s)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        _runs(doc.add_paragraph(), " ".join(para))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
