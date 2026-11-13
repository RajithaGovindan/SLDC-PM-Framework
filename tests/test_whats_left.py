"""What's left: open work grouped in plain language, summaries kept until their source changes."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Project
from app.services import whats_left


def _project_with_dev_packs(c) -> int:
    r = c.post("/projects", data={"name": "Left Demo", "raw_notes": "- Users book appointments\n- Staff confirm"},
               follow_redirects=False)
    pid = int(r.headers["location"].split("/")[2])
    for stage in (1, 2, 3, 4, 5, 6):
        c.post(f"/projects/{pid}/stages/{stage}/generate", data={})
        c.post(f"/projects/{pid}/stages/{stage}/approve", data={"approver": "lead"})
    return pid


def test_whats_left_page_and_summaries():
    with TestClient(app) as c:
        pid = _project_with_dev_packs(c)
        with SessionLocal() as db:
            p = db.get(Project, pid)
            f0, f1 = p.features[0], p.features[1]
            f0.status = "Done"                       # its open dev pack becomes a "fix"
            for t in f1.dev_tasks:
                t.status = "Done"                    # feature still open, no open pack -> feature item
            db.commit()
            wl = whats_left.collect(p)
            groups = {k: items for k, _, _, items in wl.groups}
            assert [i.kind for i in groups["bug"]] == ["dev"] * len(f0.dev_tasks)
            assert any(i.kind == "feature" and i.ref == f1.ref for i in groups["feature"])
            assert len(wl.finished) == 1
            assert wl.missing == wl.count > 0

        page = c.get(f"/projects/{pid}/left").text
        assert "Bugs" in page and "Finished features" in page and "Write in plain words" in page

        # A type picked by hand moves the item and survives a rewrite of the summaries.
        c.post(f"/projects/{pid}/left/type", data={"ref": f1.ref, "type": "cr"})
        with SessionLocal() as db:
            groups = {k: items for k, _, _, items in whats_left.collect(db.get(Project, pid)).groups}
            assert [i.ref for i in groups["cr"]] == [f1.ref]

        r = c.post(f"/projects/{pid}/left/explain", follow_redirects=False)
        assert r.status_code == 303 and "Wrote" in r.headers["location"]
        with SessionLocal() as db:
            p = db.get(Project, pid)
            wl = whats_left.collect(p)
            assert wl.missing == 0
            assert [i.ref for k, _, _, items in wl.groups if k == "cr" for i in items] == [f1.ref]
            dev = next(t for f in p.features for t in f.dev_tasks if t.status != "Done")
            dev.implementation_steps_md += "\n- one more step"   # source changed -> summary flagged stale
            db.commit()
            item = next(i for *_, items in whats_left.collect(p).groups for i in items if i.ref == dev.ref)
            assert item.plain and item.stale

        # Marking work Done removes it from the list.
        c.post(f"/projects/{pid}/items/dev/{dev.id}/status", data={"status": "Done", "back": f"/projects/{pid}/left"})
        with SessionLocal() as db:
            refs = [i.ref for *_, items in whats_left.collect(db.get(Project, pid)).groups for i in items]
            assert dev.ref not in refs
