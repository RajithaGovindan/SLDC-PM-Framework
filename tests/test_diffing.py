"""Version diffs: item-level for JSON stages, line-level for Markdown, word highlights inside changed text."""
from app.services.diffing import diff_json, diff_markdown, word_diff


def test_word_diff_marks_only_changed_words():
    html = str(word_diff("Create GRN for the invoice", "Open draft GRN for the invoice"))
    assert '<del class="diff-del">Create</del>' in html
    assert '<ins class="diff-ins">Open draft</ins>' in html
    assert "GRN for the invoice" in html


def test_json_diff_added_changed_removed():
    old = {"tasks": [
        {"ref": "DEV-001", "feature_ref": "FEAT-001", "title": "A", "unit_tests": ["t1", "t2"]},
        {"ref": "DEV-002", "feature_ref": "FEAT-002", "title": "B"},
        {"ref": "DEV-003", "feature_ref": "FEAT-003", "title": "C"}]}
    new = {"tasks": [
        {"ref": "DEV-001", "feature_ref": "FEAT-001", "title": "A", "unit_tests": ["t1", "t3"]},
        {"ref": "DEV-003", "feature_ref": "FEAT-003", "title": "C"},
        {"ref": "DEV-004", "feature_ref": "FEAT-001", "title": "New <b>pack</b>"}]}
    d = diff_json(6, old, new)
    assert d["counts"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}
    by_ref = {e["ref"]: e for e in d["entries"]}
    assert by_ref["DEV-004"]["state"] == "added" and by_ref["DEV-002"]["state"] == "removed"
    tests = next(f for f in by_ref["DEV-001"]["fields"] if f["name"] == "Unit tests")
    assert [r["state"] for r in tests["rows"]] == ["same", "changed"]
    title = next(f for f in by_ref["DEV-004"]["fields"] if f["name"] == "Title")
    assert "&lt;b&gt;" in str(title["html"])  # content is escaped


def test_markdown_diff_collapses_unchanged_lines():
    old = "\n".join(f"line {i}" for i in range(20))
    new = old.replace("line 10", "line ten") + "\nnew last line"
    d = diff_markdown(old, new)
    assert d["counts"] == {"added": 1, "removed": 0, "changed": 1}
    states = [r["state"] for r in d["rows"]]
    assert "gap" in states and states.count("same") <= 8
