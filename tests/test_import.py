"""import_artifacts.py: a folder of stage files becomes an approved project with item statuses."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_import_folder(tmp_path):
    db = tmp_path / "import.db"
    (tmp_path / "project.json").write_text(json.dumps({
        "name": "Legacy App", "code": "LEG-01", "client": "Acme", "description": "as built",
        "raw_notes": "reverse engineered", "approve_through": 4}))
    (tmp_path / "01-requirements.json").write_text(json.dumps({"summary": "s", "requirements": [
        {"ref": "REQ-001", "type": "FR", "title": "Login", "description": "Users sign in"}]}))
    (tmp_path / "02-brd.md").write_text("# BRD\n\nBusiness requirements for the legacy app.\n")
    (tmp_path / "03-tsd.md").write_text("# TSD\n\nTechnical specification for the legacy app.\n")
    (tmp_path / "04-features.json").write_text(json.dumps({"features": [
        {"ref": "FEAT-001", "title": "Auth", "requirement_refs": ["REQ-001"], "build_status": "Done"}]}))

    env = {"DATABASE_URL": f"sqlite:///{db.as_posix()}", "MOCK_AI": "true", "SYSTEMROOT": "C:\\Windows"}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "import_artifacts.py"), str(tmp_path), *a],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "stage 04 Features" in r.stdout and "1 item statuses set" in r.stdout
    assert run().returncode == 1          # refuses to overwrite without --replace
    assert run("--replace").returncode == 0

    import sqlite3
    con = sqlite3.connect(db)
    assert con.execute("select status from features where ref='FEAT-001'").fetchone()[0] == "Done"
    statuses = dict(con.execute("select stage_no, status from stage_artifacts"))
    assert statuses[4] == "Approved" and statuses[5] == "Not Started" and statuses[6] == "Locked"
