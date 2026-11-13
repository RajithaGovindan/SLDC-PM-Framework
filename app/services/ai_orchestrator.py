"""AI orchestration: context assembly from approved upstream artifacts, Claude calls, parsing and repair."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Feature, Project
from app.prompts import PROMPTS, SYSTEM_PROMPT
from app.services import mock_ai
from app.services.parsers import OutputParseError, fmt_ref, parse_stage_output
from app.services.renderers import render_stage_json
from app.services.traceability import (all_dev_tasks, all_qa_plans, all_stories, dev_to_dict, feature_to_dict,
                                       req_to_dict, story_to_dict)
from app.stages import get_stage

log = logging.getLogger("sdlc.ai")


class AIError(RuntimeError):
    """Raised when generation fails (API error, refusal, unparseable output)."""


# --------------------------------------------------------------------------- Claude client

def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def call_claude(prompt: str) -> str:
    """Single streamed Claude call. Returns the concatenated text output."""
    import anthropic

    s = get_settings()
    client = _client()
    kwargs = dict(
        model=s.claude_model,
        max_tokens=s.claude_max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": s.claude_effort},
    )
    try:
        if s.claude_enable_fallbacks:
            # Server-side refusal fallback: a declined request is re-run on a fallback model in the same call.
            with client.beta.messages.stream(**kwargs, betas=["server-side-fallback-2026-07-01"],
                                             fallbacks="default") as stream:
                msg = stream.get_final_message()
        else:
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AIError("Anthropic authentication failed - check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Anthropic rate limit reached - wait a moment and retry.") from exc
    except anthropic.BadRequestError as exc:
        raise AIError(f"Anthropic rejected the request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Could not reach the Anthropic API - check network connectivity.") from exc

    if msg.stop_reason == "refusal":
        detail = getattr(getattr(msg, "stop_details", None), "explanation", "") or ""
        raise AIError(f"Claude declined this request. {detail}".strip())
    if msg.stop_reason == "max_tokens":
        raise AIError("Output hit CLAUDE_MAX_TOKENS before completing - raise the limit or narrow the stage input.")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if not text.strip():
        raise AIError("Claude returned an empty response.")
    return text


def _repair_prompt(original_prompt: str, bad_output: str, error: str) -> str:
    return (f"{original_prompt}\n\n<previous_attempt>\n{bad_output[:60000]}\n</previous_attempt>\n\n"
            f"The previous attempt failed validation with this error:\n{error}\n\n"
            "Return the corrected output only, satisfying the output contract exactly.")


def run_stage_prompt(stage_no: int, ctx: dict, *, known_feature_refs: set[str] | None = None) -> tuple[str, dict | None, str]:
    """Generate one stage output. Returns (markdown, json, source)."""
    stage = get_stage(stage_no)
    s = get_settings()
    if not s.ai_is_live:
        raw = mock_ai.generate(stage_no, ctx)
        md, doc = parse_stage_output(stage_no, raw, stage.output, known_feature_refs=known_feature_refs)
        return md, doc, "mock"

    prompt = PROMPTS[stage_no].build(ctx)
    raw = call_claude(prompt)
    try:
        md, doc = parse_stage_output(stage_no, raw, stage.output, known_feature_refs=known_feature_refs)
    except OutputParseError as first:
        log.warning("Stage %s output failed validation (%s); retrying with repair prompt", stage_no, first)
        raw = call_claude(_repair_prompt(prompt, raw, str(first)))
        try:
            md, doc = parse_stage_output(stage_no, raw, stage.output, known_feature_refs=known_feature_refs)
        except OutputParseError as second:
            raise AIError(f"Model output failed validation twice: {second}") from second
    return md, doc, "ai"


# --------------------------------------------------------------------------- context assembly

def _md(project: Project, stage_no: int) -> str:
    a = project.artifact(stage_no)
    return a.content_md if a else ""


def base_context(project: Project, feedback: str = "", previous_output: str = "") -> dict:
    return {
        "project": {"name": project.name, "code": project.code, "client": project.client,
                    "description": project.description},
        "raw_notes": project.raw_notes,
        "feedback": feedback.strip(),
        "previous_output": previous_output,
        "requirements": [req_to_dict(r) for r in project.requirements],
        "requirements_md": _md(project, 1),
        "brd_md": _md(project, 2),
        "tsd_md": _md(project, 3),
        "features": [feature_to_dict(f) for f in project.features],
        "features_md": _md(project, 4),
        "stories": [story_to_dict(s) for s in all_stories(project)],
        "stories_md": _md(project, 5),
        "dev_tasks": [dev_to_dict(d) for d in all_dev_tasks(project)],
        "dev_md": _md(project, 6),
        "qa_md": _md(project, 7),
        "release_md": _md(project, 8),
    }


def _previous_output(project: Project, stage_no: int) -> str:
    a = project.artifact(stage_no)
    if not a or not a.has_content:
        return ""
    if a.content_json is not None:
        return json.dumps(a.content_json, indent=2, ensure_ascii=False)
    return a.content_md


def _feature_ctx(ctx: dict, f: Feature, prev_items: dict[str, dict], key: str, ref: str) -> dict:
    c = dict(ctx)
    c["feature"] = feature_to_dict(f)
    c["feature_ref"] = f.ref
    c["feature_json"] = json.dumps(c["feature"], indent=2, ensure_ascii=False)
    c["stories"] = [story_to_dict(s) for s in f.stories]
    c["stories_json"] = json.dumps(c["stories"], indent=2, ensure_ascii=False)
    c[key] = ref
    if f.dev_tasks:
        c["dev_json"] = json.dumps(dev_to_dict(f.dev_tasks[0]), indent=2, ensure_ascii=False)
    prev = prev_items.get(f.ref)
    c["previous_output"] = json.dumps(prev, indent=2, ensure_ascii=False) if prev else ""
    if not prev:
        c["feedback"] = ctx.get("feedback", "")
    return c


def generate(db: Session, project: Project, stage_no: int, feedback: str = "") -> tuple[str, dict | None, str]:
    """Produce new content for a stage. Does not persist; the workflow layer stores it."""
    ctx = base_context(project, feedback, _previous_output(project, stage_no) if feedback else "")
    feature_refs = {f.ref for f in project.features}

    if stage_no in (6, 7):
        if not project.features:
            raise AIError("No approved features found - approve Stage 4 first.")
        list_key, prefix, ref_key = ("tasks", "DEV", "dev_ref") if stage_no == 6 else ("plans", "QA", "qa_ref")
        prev_doc = (project.artifact(stage_no).content_json or {}) if project.artifact(stage_no) else {}
        prev_items = {i["feature_ref"]: i for i in prev_doc.get(list_key, [])} if feedback else {}
        existing = {(d.feature.ref): d.ref for d in (all_dev_tasks(project) if stage_no == 6 else all_qa_plans(project))}
        items, sources = [], set()
        for idx, f in enumerate(project.features, 1):
            ref = existing.get(f.ref) or fmt_ref(prefix, idx)
            fctx = _feature_ctx(ctx, f, prev_items, ref_key, ref)
            _, doc, src = run_stage_prompt(stage_no, fctx, known_feature_refs=feature_refs)
            item = doc[list_key][0]
            item["ref"], item["feature_ref"] = ref, f.ref
            items.append(item)
            sources.add(src)
        merged = {list_key: items}
        return render_stage_json(stage_no, merged), merged, "ai" if "ai" in sources else "mock"

    md, doc, source = run_stage_prompt(stage_no, ctx, known_feature_refs=feature_refs if stage_no == 5 else None)
    if doc is not None:
        md = render_stage_json(stage_no, doc)
    return md, doc, source
