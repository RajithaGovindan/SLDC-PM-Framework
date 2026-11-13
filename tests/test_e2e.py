"""End-to-end workflow test in mock mode against a throwaway SQLite database.

Run: python -m pytest -q
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sdlc_test_"))
os.environ.update(MOCK_AI="true", DATABASE_URL=f"sqlite:///{(TMP / 'test.db').as_posix()}", ANTHROPIC_API_KEY="")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

NOTES = """- Customers must be able to book a table online
- Staff need to see tonight's reservations
- Pages must load in under 2 seconds
- Budget is limited to $50k
- Do we need deposits for large groups?"""


def _pid(resp) -> int:
    return int(re.search(r"/projects/(\d+)", str(resp.url)).group(1))


def test_full_pipeline():
    with TestClient(app) as c:
        assert c.get("/healthz").json()["ai"] == "mock"
        r = c.post("/projects", data={"name": "Table Booker", "client": "Bistro", "raw_notes": NOTES})
        assert r.status_code == 200
        pid = _pid(r)

        # stage 2 is locked until stage 1 is approved
        r = c.post(f"/projects/{pid}/stages/2/generate")
        assert "must be approved first" in r.text

        for n in range(1, 11):
            r = c.post(f"/projects/{pid}/stages/{n}/generate", data={"feedback": ""} if n > 1 else {"raw_notes": NOTES})
            assert "Generated v1" in r.text, (n, r.text[:500])
            r = c.post(f"/projects/{pid}/stages/{n}/approve", data={"approver": "Tester"})
            assert r.status_code == 200
            assert ("approved" in r.text.lower()), n

        # plain-language feedback needs live Claude; mock mode says so and leaves the document alone
        r = c.post(f"/projects/{pid}/stages/4/generate", data={"feedback": "Split auth into its own feature"})
        assert "needs live Claude" in r.text and "Last generation failed" not in r.text

        # an edit to an approved stage creates v2, flags downstream stages and shows highlighted changes
        doc = c.get(f"/projects/{pid}/stages/4").text
        import html, json as _json, re as _re
        feats = _json.loads(_json.loads(html.unescape(_re.search(
            r'id="editor-initial">(.*?)</script>', doc, _re.S).group(1))))
        feats["features"][0]["title"] = "Renamed feature"
        r = c.post(f"/projects/{pid}/stages/4/save", data={"content": _json.dumps(feats)})
        assert "Saved as v2" in r.text
        page = c.get(f"/projects/{pid}").text
        assert "changed after approval" in page
        r = c.get(f"/projects/{pid}/stages/4?view=changes")
        assert "v1 → v2" in r.text and "1 changed" in r.text and 'class="diff-ins">Renamed' in r.text

        # invalid JSON is rejected on manual save, valid edit is accepted
        r = c.post(f"/projects/{pid}/stages/1/save", data={"content": "{not json"})
        assert "Not saved" in r.text
        render = c.post(f"/api/projects/{pid}/stages/1/render", json={"content": "{}"}).json()
        assert render["error"]

        # every main page renders
        for path in ("/", f"/projects/{pid}", f"/projects/{pid}/traceability", f"/projects/{pid}/sync",
                     f"/projects/{pid}/traceability.md", f"/projects/{pid}/stages/3/export.md"):
            assert c.get(path).status_code == 200, path
        for role in ("All", "Solution Architect", "Developer", "QA", "DevOps/Release"):
            assert c.get(f"/projects/{pid}/team", params={"role": role}).status_code == 200

        # repo sync writes .sdlc and .claude/commands
        repo = TMP / "repo"
        repo.mkdir()
        r = c.post(f"/projects/{pid}/sync", data={"target_repo_path": str(repo)})
        assert "Wrote" in r.text
        assert (repo / ".claude/commands/implement-feature.md").read_text().count("$ARGUMENTS") > 2
        assert (repo / ".sdlc/03-tsd/tsd.md").exists()
        assert list((repo / ".sdlc/06-dev-tasks").glob("DEV-001-FEAT-001.md"))
        manifest = json.loads((repo / ".sdlc/manifest.json").read_text())
        assert manifest["generator"] == "sdlc-orchestrator"
        # second sync replaces the folder it owns
        assert "Wrote" in c.post(f"/projects/{pid}/sync", data={"target_repo_path": str(repo)}).text

        # refuses to overwrite a foreign .sdlc folder
        foreign = TMP / "foreign"
        (foreign / ".sdlc").mkdir(parents=True)
        r = c.post(f"/projects/{pid}/sync", data={"target_repo_path": str(foreign)})
        assert "refusing to overwrite" in r.text


def test_feedback_revises_current_document(monkeypatch):
    """Live mode: feedback edits the current version (kept items survive) and the change is highlighted."""
    from types import SimpleNamespace

    from app.services import ai_orchestrator

    with TestClient(app) as c:
        r = c.post("/projects", data={"name": "Revise Me", "client": "Bistro", "raw_notes": NOTES})
        pid = _pid(r)
        c.post(f"/projects/{pid}/stages/1/generate", data={"raw_notes": NOTES})
        c.post(f"/projects/{pid}/stages/1/approve", data={"approver": "Tester"})
        c.post(f"/projects/{pid}/stages/2/generate", data={"feedback": ""})

        seen = {}

        def fake_claude(prompt):
            seen["prompt"] = prompt
            return "# BRD\n\nKept intro.\n\n## Deposits\n\nGroups of 8 or more pay a deposit.\n"

        monkeypatch.setattr(ai_orchestrator, "get_settings", lambda: SimpleNamespace(ai_is_live=True))
        monkeypatch.setattr(ai_orchestrator, "call_claude", fake_claude)
        r = c.post(f"/projects/{pid}/stages/2/generate", data={"feedback": "Add a section on deposits for groups"})
        assert "Revised as v2" in r.text, r.text[:400]
        assert "<reviewer_feedback>\nAdd a section on deposits" in seen["prompt"]
        assert "<current_document>" in seen["prompt"]
        assert 'class="diff-row diff-added">Groups of 8 or more pay a deposit.' in r.text
