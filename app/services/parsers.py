"""Strict JSON / Markdown output parsing and ID normalisation."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.schemas import STAGE_SCHEMAS

PREFIX_BY_STAGE = {1: "REQ", 4: "FEAT", 5: "US", 6: "DEV", 7: "QA"}
LIST_KEY_BY_STAGE = {1: "requirements", 4: "features", 5: "stories", 6: "tasks", 7: "plans"}

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


class OutputParseError(ValueError):
    """Raised when AI output (or a manual edit) does not satisfy the stage contract."""


def fmt_ref(prefix: str, n: int) -> str:
    return f"{prefix}-{n:03d}"


def extract_json(text: str) -> Any:
    if isinstance(text, (dict, list)):
        return text
    raw = (text or "").strip()
    m = _FENCE_RE.match(raw)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise OutputParseError("No JSON object found in output.")
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise OutputParseError(f"Invalid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}") from exc


def clean_markdown(text: str) -> str:
    raw = (text or "").strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", raw, re.DOTALL)
    return (m.group(1) if m else raw).strip() + "\n"


def _renumber(items: list[dict], prefix: str, start: int = 1) -> dict[str, str]:
    """Ensure refs are unique and well-formed. Returns old->new mapping (only when renumbering happened)."""
    pattern = re.compile(rf"^{prefix}-\d{{3,}}$")
    refs = [str(i.get("ref") or "").strip().upper() for i in items]
    if all(pattern.match(r) for r in refs) and len(set(refs)) == len(refs):
        for item, r in zip(items, refs):
            item["ref"] = r
        return {}
    mapping: dict[str, str] = {}
    for idx, item in enumerate(items):
        new = fmt_ref(prefix, start + idx)
        if item.get("ref"):
            mapping[str(item["ref"]).strip().upper()] = new
        item["ref"] = new
    return mapping


def validate_stage_json(stage_no: int, data: Any, *, known_feature_refs: set[str] | None = None) -> dict:
    """Validate against the stage schema and normalise IDs. Returns a plain dict."""
    schema = STAGE_SCHEMAS[stage_no]
    if isinstance(data, list):  # tolerate a bare list
        data = {LIST_KEY_BY_STAGE[stage_no]: data}
    try:
        doc = schema.model_validate(data).model_dump()
    except ValidationError as exc:
        errs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])
        raise OutputParseError(f"Schema validation failed: {errs}") from exc

    items = doc[LIST_KEY_BY_STAGE[stage_no]]
    mapping = _renumber(items, PREFIX_BY_STAGE[stage_no])

    if stage_no == 4:
        for f in items:
            f["depends_on"] = [mapping.get(d.upper(), d.upper()) for d in f["depends_on"]]
            f["requirement_refs"] = sorted({r.strip().upper() for r in f["requirement_refs"]})
        refs = {f["ref"] for f in items}
        for f in items:
            f["depends_on"] = [d for d in f["depends_on"] if d in refs and d != f["ref"]]

    if stage_no in (5, 6, 7):
        for it in items:
            it["feature_ref"] = it["feature_ref"].strip().upper()
        if known_feature_refs is not None:
            unknown = sorted({it["feature_ref"] for it in items} - known_feature_refs)
            if unknown:
                raise OutputParseError(f"Unknown feature refs: {', '.join(unknown)}")
    return doc


def parse_stage_output(stage_no: int, text: str, output: str, **kw) -> tuple[str, dict | None]:
    """Return (markdown, json_or_None). For JSON stages the caller renders markdown."""
    if output == "json":
        return "", validate_stage_json(stage_no, extract_json(text), **kw)
    md = clean_markdown(text)
    if len(md.strip()) < 20:
        raise OutputParseError("Markdown output is empty.")
    return md, None
