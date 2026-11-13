"""Parser and live-mode repair-loop tests (Claude calls are stubbed; no network)."""
from __future__ import annotations

import json

import pytest

from app.services import ai_orchestrator
from app.services.parsers import OutputParseError, extract_json, validate_stage_json


def test_extract_json_from_fenced_and_chatty_output():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go:\n{"a": {"b": 2}}\nThanks') == {"a": {"b": 2}}
    with pytest.raises(OutputParseError):
        extract_json("no json here")


def test_features_renumbered_and_dependencies_remapped():
    doc = validate_stage_json(4, {"features": [
        {"ref": "F1", "title": "Auth", "priority": "high"},
        {"ref": "F2", "title": "Booking", "depends_on": ["F1"], "requirement_refs": ["req-001"]},
    ]})
    assert [f["ref"] for f in doc["features"]] == ["FEAT-001", "FEAT-002"]
    assert doc["features"][1]["depends_on"] == ["FEAT-001"]
    assert doc["features"][0]["priority"] == "P1"
    assert doc["features"][1]["requirement_refs"] == ["REQ-001"]


def test_unknown_feature_ref_rejected():
    with pytest.raises(OutputParseError, match="Unknown feature refs"):
        validate_stage_json(5, {"stories": [{"feature_ref": "FEAT-999", "role": "r", "goal": "g", "benefit": "b",
                                             "acceptance_criteria": "Scenario: x"}]}, known_feature_refs={"FEAT-001"})


def test_live_mode_repairs_invalid_json_once(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "mock_ai", False)
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")
    good = {"summary": "s", "requirements": [{"type": "FR", "title": "Book", "description": "d"}]}
    replies = iter(["sorry, not json", json.dumps(good)])
    prompts = []
    monkeypatch.setattr(ai_orchestrator, "call_claude", lambda p: (prompts.append(p), next(replies))[1])
    ctx = {"project": {"name": "P", "code": "P-01", "client": "", "description": ""}, "raw_notes": "x"}
    md, doc, source = ai_orchestrator.run_stage_prompt(1, ctx)
    assert source == "ai" and doc["requirements"][0]["ref"] == "REQ-001"
    assert "failed validation" in prompts[1]
