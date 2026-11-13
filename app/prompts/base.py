"""Shared prompt scaffolding used by every stage."""
from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are the SDLC Orchestrator: a principal solution architect, business analyst, \
tech lead, QA lead and release manager working as one team. You produce precise, implementation-ready \
software delivery artifacts for a single project, one SDLC stage at a time.

Working rules:
- Ground every statement in the upstream artifacts you are given. Do not invent business facts; when \
information is missing, state the assumption explicitly or raise it as an open question.
- Preserve traceability. Reuse the exact IDs you are given (REQ-###, FEAT-###, US-###, DEV-###, QA-###) \
and reference them wherever an item derives from another.
- Be concrete: real file paths, real field names, real HTTP verbs and status codes, measurable numbers.
- Write for the named audience of the stage. Engineering artifacts are terse and exact; end-user \
documents are plain-language.
- Follow the output contract of the stage exactly. When JSON is requested, reply with a single JSON \
object and nothing else (no prose, no code fences)."""

JSON_CONTRACT = """Output contract: respond with ONE valid JSON object that matches this shape exactly. \
No markdown fences, no commentary before or after the JSON.

{shape}"""

MARKDOWN_CONTRACT = """Output contract: respond with a complete GitHub-flavoured Markdown document only. \
Start with a level-1 heading. Use the section headings listed below, in order. Use tables where they \
help scanning. Mermaid diagrams go in ```mermaid fenced blocks."""


def section(title: str, body: Any) -> str:
    if body is None or body == "" or body == []:
        return ""
    if not isinstance(body, str):
        body = json.dumps(body, indent=2, ensure_ascii=False)
    return f"<{title}>\n{body.strip()}\n</{title}>\n\n"


def project_header(ctx: dict) -> str:
    p = ctx["project"]
    return section("project", f"Name: {p['name']}\nCode: {p['code']}\nClient: {p.get('client') or 'n/a'}\n"
                              f"Description: {p.get('description') or 'n/a'}")


def feedback_block(ctx: dict) -> str:
    if not ctx.get("feedback"):
        return ""
    out = section("previous_version", ctx.get("previous_output") or "")
    out += section("reviewer_feedback", ctx["feedback"])
    out += ("Revise the previous version to address every point of the reviewer feedback. Keep the parts "
            "the feedback does not mention, and keep existing IDs stable.\n\n")
    return out
