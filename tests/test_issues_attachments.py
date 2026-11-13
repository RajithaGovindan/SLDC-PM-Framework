"""Attachments (store, extract, send to Claude, export) and issues (triage, plan, apply). Runs after test_e2e,
which points the database and attachment folder at a temp directory."""
from __future__ import annotations

import io
import json
import re
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Project
from app.services import ai_orchestrator, attachments, issues

NOTES = "- Guests book tables online\n- Staff see tonight's bookings\n- Do large groups pay a deposit?"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _pid(resp) -> int:
    return int(re.search(r"/projects/(\d+)", str(resp.url)).group(1))


def _docx_bytes() -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Client BRD", level=1)
    d.add_paragraph("Deposits apply to groups of 8 or more.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Rule", "Value", "Deposit", "20%"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Requirements"
    ws.append(["ID", "Need"])
    ws.append(["R1", "Online booking"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def project_id():
    with TestClient(app) as c:
        pid = _pid(c.post("/projects", data={"name": "Files Test", "client": "Bistro", "raw_notes": NOTES}))
        for n in range(1, 3):
            c.post(f"/projects/{pid}/stages/{n}/generate", data={"raw_notes": NOTES} if n == 1 else {})
            c.post(f"/projects/{pid}/stages/{n}/approve", data={"approver": "Tester"})
    return pid


def test_attachments_upload_extract_send_export(project_id):
    pid = project_id
    with TestClient(app) as c:
        files = [("files", ("brd.docx", _docx_bytes())), ("files", ("reqs.xlsx", _xlsx_bytes())),
                 ("files", ("screen.png", PNG)), ("files", ("notes.csv", b"a,b\n1,2\n")),
                 ("files", ("tool.exe", b"MZ"))]
        r = c.post(f"/projects/{pid}/attachments", files=files, data={"note": "from client", "back": f"/projects/{pid}"})
        assert "Attached brd.docx, reqs.xlsx, screen.png, notes.csv, tool.exe" in r.text
        r = c.post(f"/projects/{pid}/attachments", files=[("files", ("s2.md", b"# stage two notes"))],
                   data={"stage_no": "2", "back": f"/projects/{pid}/stages/2"})
        assert "Attachments for this stage" in r.text and "s2.md" in r.text

        db = SessionLocal()
        p = db.get(Project, pid)
        by_name = {a.filename: a for a in p.attachments}
        assert by_name["tool.exe"].kind == "other" and not by_name["tool.exe"].use_in_ai
        assert "# Client BRD" in attachments.extract_text(by_name["brd.docx"])
        assert "| Deposit | 20% |" in attachments.extract_text(by_name["brd.docx"])
        assert "## Sheet: Requirements" in attachments.extract_text(by_name["reqs.xlsx"])
        assert "| 1 | 2 |" in attachments.extract_text(by_name["notes.csv"])

        stage2 = attachments.for_stage(p, 2)
        assert {a.filename for a in stage2} == {"brd.docx", "reqs.xlsx", "screen.png", "notes.csv", "tool.exe", "s2.md"}
        assert {a.filename for a in attachments.for_stage(p, 6, include_project=False)} == set()
        blocks = attachments.content_blocks(stage2)
        types = [b["type"] for b in blocks]
        assert types.count("image") == 1 and "document" not in types
        assert not any("MZ" in b.get("text", "") for b in blocks)  # unreadable file never sent
        content = ai_orchestrator.user_content("PROMPT", blocks)
        assert content[-1]["text"].endswith("PROMPT") and content[-1]["text"].startswith(ai_orchestrator.ATTACHMENTS_NOTE)

        png_id, docx_id = by_name["screen.png"].id, by_name["brd.docx"].id
        db.close()
        assert c.get(f"/attachments/{png_id}/download").content == PNG
        c.post(f"/attachments/{docx_id}/toggle", data={"back": f"/projects/{pid}"})
        db = SessionLocal()
        assert not db.get(Project, pid).attachments[0].use_in_ai
        db.close()

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/projects/{pid}/export.zip").content))
        names = z.namelist()
        root = names[0].split("/")[0]
        assert f"{root}/README.md" in names and f"{root}/traceability.md" in names and f"{root}/issues.md" in names
        assert any(n.startswith(f"{root}/01-") and n.endswith("requirements.json") for n in names)
        assert any(n.startswith(f"{root}/02-") and n.endswith("brd.md") for n in names)
        assert any(n.endswith("-screen.png") and "/attachments/project/" in n for n in names)
        assert any("/attachments/stage-02/" in n for n in names)
        z2 = zipfile.ZipFile(io.BytesIO(c.get(f"/projects/{pid}/export.zip?attachments=0").content))
        assert not any("/attachments/" in n for n in z2.namelist())

        r = c.post(f"/attachments/{png_id}/delete", data={"back": f"/projects/{pid}"})
        assert "Removed screen.png" in r.text


def test_issue_triage_plan_and_apply(project_id, monkeypatch):
    pid = project_id
    live = SimpleNamespace(ai_is_live=True)
    seen = {}

    def fake_claude(prompt, files=None):
        seen["prompt"], seen["files"] = prompt, files
        return json.dumps({"kind": "cr", "title": "Deposits for large groups",
                           "reasoning": "No requirement mentions deposits; REQ-005 only asks the question.",
                           "related_refs": ["REQ-005"],
                           "plan": [{"stage_no": 2, "instruction": "Add a Deposits section."},
                                    {"stage_no": 1, "instruction": "Add FR: groups of 8+ pay a 20% deposit."},
                                    {"stage_no": 6, "instruction": "Stage without content - must be dropped."}]})

    revised = []

    def fake_revise(project, stage_no, feedback, extra_attachments=()):
        revised.append((stage_no, feedback, [a.filename for a in extra_attachments]))
        a = project.artifact(stage_no)
        if a.content_json is not None:
            return a.content_md, a.content_json, "ai", []
        return a.content_md + "\n\n## Deposits\n\nGroups of 8+ pay 20%.\n", None, "ai", []

    with TestClient(app) as c:
        # mock mode: the report is saved, triage explains what it needs
        r = c.post(f"/projects/{pid}/issues", data={"description": "Big groups should pay a deposit"})
        assert "triage failed" in r.text and "needs live Claude" in r.text

        monkeypatch.setattr(issues, "get_settings", lambda: live)
        monkeypatch.setattr(ai_orchestrator, "call_claude", fake_claude)
        monkeypatch.setattr(ai_orchestrator, "revise", fake_revise)
        r = c.post(f"/projects/{pid}/issues", data={"description": "Big groups should pay a deposit", "reporter": "Asha"},
                   files=[("files", ("photo.png", PNG))])
        assert "Triaged as change request CR-001" in r.text, r.text[:500]
        assert "<report>\nBig groups should pay a deposit" in seen["prompt"]
        assert any(b["type"] == "image" for b in seen["files"])
        iid = int(re.search(r"/issues/(\d+)", str(r.url)).group(1))

        db = SessionLocal()
        i = db.get(issues.Issue, iid)
        assert [s["stage_no"] for s in i.plan] == [1, 2]  # stage order, stage 6 dropped (no content)
        db.close()

        # override kind -> renumbered, edit an instruction, untick stage 2, apply
        r = c.post(f"/projects/{pid}/issues/{iid}/apply",
                   data={"kind": "bug", "stages": ["1"], "instruction_1": "Add FR: deposit of 20% for 8+ guests.",
                         "action": "apply"})
        assert "BUG-001 applied to 1 stage(s)" in r.text, r.text[:600]
        assert revised == [(1, "BUG-001 (bug): Add FR: deposit of 20% for 8+ guests.\n\nOriginal report: Big groups "
                               "should pay a deposit", ["photo.png"])]
        db = SessionLocal()
        i = db.get(issues.Issue, iid)
        assert i.status == "Applied" and i.plan[0]["version"] == 2 and not i.plan[1]["version"]
        rev = db.get(Project, pid).artifact(1).revisions
        assert any(r.feedback.startswith("BUG-001: Add FR") for r in rev)
        db.close()
        page = c.get(f"/projects/{pid}/issues").text
        assert "BUG-001" in page and "01→v2" in page
        assert "BUG-001" in zipfile.ZipFile(io.BytesIO(c.get(f"/projects/{pid}/export.zip").content)).read(
            [n for n in zipfile.ZipFile(io.BytesIO(c.get(f"/projects/{pid}/export.zip").content)).namelist()
             if n.endswith("issues.md")][0]).decode()


def test_stage_downloads_and_team_center(project_id):
    import docx

    pid = project_id
    with TestClient(app) as c:
        r = c.get(f"/projects/{pid}/stages/2/export.docx")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
        d = docx.Document(io.BytesIO(r.content))
        texts = [p.text for p in d.paragraphs]
        assert texts[0].startswith("02 · ") and any(t for t in texts[2:])
        assert c.get(f"/projects/{pid}/stages/1/export.json").json()["requirements"]
        assert c.get(f"/projects/{pid}/stages/2/export.json").status_code == 404
        assert c.get(f"/projects/{pid}/stages/9/export.docx").status_code == 404
        page = c.get(f"/projects/{pid}/stages/2").text
        assert "Word document (.docx)" in page and "export.json" not in page
        names = zipfile.ZipFile(io.BytesIO(c.get(f"/projects/{pid}/export.zip").content)).namelist()
        assert any(n.endswith("brd.docx") for n in names)


def test_markdown_to_docx_handles_tables_lists_code():
    import docx

    from app.services.docx_export import markdown_to_docx

    md = ("# Title\n\nSome **bold** and `code`.\n\n| A | B |\n|---|---|\n| 1 | 2 \\| 3 |\n\n- one\n  - nested\n1. first\n"
          "- [x] done item\n\n```mermaid\ngraph TD; A-->B\n```\n\n> quoted\n\n---\n")
    d = docx.Document(io.BytesIO(markdown_to_docx(md, title="T")))
    assert len(d.tables) == 1 and d.tables[0].cell(1, 1).text == "2 | 3"
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Some bold and code." in text and "graph TD; A-->B" in text and "☑ done item" in text and "quoted" in text
