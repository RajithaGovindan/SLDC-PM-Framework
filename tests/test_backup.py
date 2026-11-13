"""Project backup: export a project with everything in it and import it again as a new project."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Project
from app.services import backup
from app.services.attachments import read_bytes
from app.services.traceability import build_matrix


def test_backup_round_trip():
    with TestClient(app) as c:
        r = c.post("/projects", data={"name": "Backup Source", "raw_notes": "- Users book appointments\n- Staff confirm"},
                   follow_redirects=False)
        pid = int(r.headers["location"].split("/")[2])
        for stage in (1, 2, 3, 4, 5):
            assert c.post(f"/projects/{pid}/stages/{stage}/generate", data={}).status_code == 200
            assert c.post(f"/projects/{pid}/stages/{stage}/approve", data={"approver": "lead"}).status_code == 200
        c.post(f"/projects/{pid}/attachments", data={"stage_no": "1"},
               files={"files": ("notes.txt", b"hello file", "text/plain")})
        c.post(f"/projects/{pid}/issues", data={"description": "The booking page crashes on submit"})

        z = c.get(f"/projects/{pid}/backup.zip")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"

        assert "already exists" in c.post("/projects/import", files={"file": ("b.zip", z.content)}).text
        assert "not a project backup" in c.post("/projects/import", files={"file": ("b.zip", b"junk")}).text

        r = c.post("/projects/import", data={"code": "BAK-02", "repo": "https://github.com/o/r"},
                   files={"file": ("b.zip", z.content)}, follow_redirects=False)
        assert r.status_code == 303 and "Imported+BAK-02" in r.headers["location"]

    with SessionLocal() as db:
        src = db.get(Project, pid)
        dst = db.scalar(select(Project).where(Project.code == "BAK-02"))
        assert dst.id != src.id and dst.target_repo_path == "https://github.com/o/r"
        assert backup.summary(dst) == backup.summary(src)
        for a, b in zip(src.artifacts, dst.artifacts):
            assert (a.stage_no, a.status, a.version, a.content_md, a.content_json) == \
                   (b.stage_no, b.status, b.version, b.content_md, b.content_json)
            assert [r.content_md for r in a.revisions] == [r.content_md for r in b.revisions]
        assert build_matrix(dst).stats == build_matrix(src).stats  # requirement-feature links survived
        assert read_bytes(dst.attachments[0]) == b"hello file"
        assert [i.ref for i in dst.issues] == [i.ref for i in src.issues]
