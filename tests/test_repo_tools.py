"""Read-only repository tools and the revise tool loop."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import ai_orchestrator
from app.services.repo_tools import RepoReader, RepoToolError


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "app" / "routes").mkdir(parents=True)
    (tmp_path / "app" / "routes" / "bills.py").write_text(
        "def view(bill_id):\n    fully_received = qty_outstanding <= 1e-6\n    return fully_received\n")
    (tmp_path / "app" / "page.html").write_text("<button>Create Goods Receipt</button>\n")
    (tmp_path / ".env").write_text("DB_PASSWORD=secret\n")
    (tmp_path / "data.csv").write_text("client,amount\n")
    (tmp_path / "server.key").write_text("-----BEGIN KEY-----\n")
    return tmp_path


def test_list_search_read(repo):
    r = RepoReader(repo)
    assert r.list_dir("") == "app/"
    assert r.list_dir("app") == "routes/\npage.html"
    hits = r.search_code(r"fully_received", glob="*.py")
    assert hits.startswith("app/routes/bills.py:2:")
    text = r.read_file("app/routes/bills.py", start_line=2, max_lines=1)
    assert text.startswith("2\t    fully_received") and "[lines 2-2 of 3]" in text
    assert r.files_read == ["app/routes/bills.py"]


def test_secrets_data_and_escapes_are_refused(repo):
    r = RepoReader(repo)
    assert ".env" not in r.files() and "data.csv" not in r.files() and "server.key" not in r.files()
    for bad in (".env", "data.csv", "server.key", "../outside.py"):
        with pytest.raises(RepoToolError):
            r.read_file(bad)
    assert "DB_PASSWORD" not in r.search_code("PASSWORD")


def test_run_validates_input(repo):
    r = RepoReader(repo)
    with pytest.raises(RepoToolError):
        r.run("read_file", {})
    with pytest.raises(RepoToolError):
        r.run("read_file", {"path": "app/page.html", "start_line": "2"})
    with pytest.raises(RepoToolError):
        r.run("delete_file", {"path": "x"})
    assert "Create Goods Receipt" in r.run("read_file", {"path": "app/page.html"})


def test_tool_loop_runs_tools_then_returns_document(repo, monkeypatch):
    calls = []

    def block(**kw):
        return SimpleNamespace(**kw)

    replies = [
        SimpleNamespace(stop_reason="tool_use", content=[
            block(type="tool_use", id="t1", name="search_code", input={"pattern": "fully_received"}),
            block(type="tool_use", id="t2", name="read_file", input={"path": ".env"})]),
        SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text='{"tasks": []}')]),
    ]

    def fake_stream(**kw):
        calls.append(kw)
        return replies[len(calls) - 1]

    monkeypatch.setattr(ai_orchestrator, "_stream_message", fake_stream)
    reader = RepoReader(repo)
    out = ai_orchestrator.call_claude_with_repo("revise this", reader)
    assert out == '{"tasks": []}'
    assert calls[0]["tools"] and calls[0]["cache_control"] == {"type": "ephemeral"}
    results = calls[1]["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "t1" and "bills.py:2" in results[0]["content"] and not results[0]["is_error"]
    assert results[1]["is_error"] and "Not a readable source file" in results[1]["content"]
