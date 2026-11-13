"""Compare two versions of a stage document and highlight what changed.

JSON stages are compared item by item (matched on ref), then field by field, with word-level highlights inside
changed text. Markdown stages are compared line by line, with unchanged stretches collapsed.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from markupsafe import Markup, escape

from app.services.parsers import LIST_KEY_BY_STAGE

CONTEXT_LINES = 2
_TOKEN = re.compile(r"\s+|[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def _ins(text: str) -> str:
    return f'<ins class="diff-ins">{escape(text)}</ins>' if text else ""


def _del(text: str) -> str:
    return f'<del class="diff-del">{escape(text)}</del>' if text else ""


def word_diff(old: str, new: str) -> Markup:
    """Inline diff of two strings: removed words struck through in red, added words in green."""
    a, b = _TOKEN.findall(old or ""), _TOKEN.findall(new or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(str(escape("".join(a[i1:i2]))))
        else:
            out.append(_del("".join(a[i1:i2])) + _ins("".join(b[j1:j2])))
    return Markup("".join(out))


# --------------------------------------------------------------------------- JSON stages

def _as_lines(value: Any) -> list[str]:
    """Flatten a field value into comparable display lines."""
    if value is None or value == "" or value == [] or value == {}:
        return []
    if isinstance(value, list):
        return [_one_line(v) for v in value]
    if isinstance(value, dict):
        return [f"{k}: {_one_line(v)}" for k, v in value.items()]
    return [str(value)]


def _one_line(v: Any) -> str:
    if isinstance(v, dict):
        return " · ".join(_one_line(x) for x in v.values() if x not in (None, "", [], {}))
    if isinstance(v, list):
        return ", ".join(_one_line(x) for x in v)
    return str(v)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) or value is None


def _field_diff(old: Any, new: Any) -> dict | None:
    if old == new:
        return None
    if _is_text(old) and _is_text(new):
        return {"kind": "text", "html": word_diff(old or "", new or "")}
    a, b = _as_lines(old), _as_lines(new)
    rows = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            rows += [{"state": "same", "html": escape(x)} for x in a[i1:i2]]
        elif op == "replace" and (i2 - i1) == (j2 - j1):
            rows += [{"state": "changed", "html": word_diff(x, y)} for x, y in zip(a[i1:i2], b[j1:j2])]
        else:
            rows += [{"state": "removed", "html": escape(x)} for x in a[i1:i2]]
            rows += [{"state": "added", "html": escape(x)} for x in b[j1:j2]]
    return {"kind": "list", "rows": rows}


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _title(item: dict) -> str:
    return str(item.get("title") or item.get("goal") or item.get("i_want") or item.get("description") or "")[:140]


def _key(item: dict, idx: int) -> str:
    return str(item.get("ref") or f"#{idx + 1}").upper()


def diff_json(stage_no: int, old: dict | None, new: dict | None) -> dict:
    list_key = LIST_KEY_BY_STAGE.get(stage_no)
    old, new = old or {}, new or {}
    old_items = {_key(i, n): i for n, i in enumerate(old.get(list_key, []))}
    new_items = {_key(i, n): i for n, i in enumerate(new.get(list_key, []))}
    items, counts = [], {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}

    order = list(new_items) + [k for k in old_items if k not in new_items]
    for ref in order:
        o, n = old_items.get(ref), new_items.get(ref)
        if o == n:
            counts["unchanged"] += 1
            continue
        state = "added" if o is None else "removed" if n is None else "changed"
        counts[state] += 1
        o, n = o or {}, n or {}
        fields = []
        for key in list(n) + [k for k in o if k not in n]:
            if key == "ref":
                continue
            fd = _field_diff(o.get(key), n.get(key))
            if fd:
                fields.append({"name": _label(key), **fd})
        items.append({"ref": ref, "title": _title(n or o), "state": state, "fields": fields})

    # Top-level fields outside the item list (e.g. the stage 1 summary).
    extra = []
    for key in sorted(set(old) | set(new)):
        if key == list_key:
            continue
        fd = _field_diff(old.get(key), new.get(key))
        if fd:
            extra.append({"name": _label(key), **fd})
    return {"kind": "json", "counts": counts, "entries": items, "extra": extra}


# --------------------------------------------------------------------------- Markdown stages

def diff_markdown(old: str, new: str) -> dict:
    a, b = (old or "").splitlines(), (new or "").splitlines()
    rows, counts = [], {"added": 0, "removed": 0, "changed": 0}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            same = a[i1:i2]
            if len(same) > 2 * CONTEXT_LINES + 1:
                head = same[:CONTEXT_LINES] if rows else []
                tail = same[-CONTEXT_LINES:] if i2 < len(a) else []
                rows += [{"state": "same", "html": escape(x)} for x in head]
                rows.append({"state": "gap", "html": f"{len(same) - len(head) - len(tail)} unchanged lines"})
                rows += [{"state": "same", "html": escape(x)} for x in tail]
            else:
                rows += [{"state": "same", "html": escape(x)} for x in same]
        elif op == "replace" and (i2 - i1) == (j2 - j1):
            counts["changed"] += i2 - i1
            rows += [{"state": "changed", "html": word_diff(x, y)} for x, y in zip(a[i1:i2], b[j1:j2])]
        else:
            counts["removed"] += i2 - i1
            counts["added"] += j2 - j1
            rows += [{"state": "removed", "html": escape(x)} for x in a[i1:i2]]
            rows += [{"state": "added", "html": escape(x)} for x in b[j1:j2]]
    if rows and rows[-1]["state"] == "gap" and not any(r["state"] not in ("same", "gap") for r in rows):
        rows = []
    return {"kind": "markdown", "counts": counts, "rows": rows}


def diff_revisions(stage_no: int, output: str, old_rev, new_rev) -> dict:
    if output == "json":
        d = diff_json(stage_no, old_rev.content_json, new_rev.content_json)
    else:
        d = diff_markdown(old_rev.content_md, new_rev.content_md)
    d.update(old_version=old_rev.version, new_version=new_rev.version, feedback=new_rev.feedback,
             source=new_rev.source, empty=not any(v for k, v in d["counts"].items() if k != "unchanged")
             and not d.get("extra"))
    return d
