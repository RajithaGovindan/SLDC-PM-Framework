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


def _stream_message(**extra):
    """One streamed Claude request with the project's model settings. Returns the final message."""
    import anthropic

    s = get_settings()
    client = _client()
    kwargs = dict(
        model=s.claude_model,
        max_tokens=s.claude_max_tokens,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": s.claude_effort},
        **extra,
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
    return msg


def _final_text(msg) -> str:
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if not text.strip():
        raise AIError("Claude returned an empty response.")
    return text


def call_claude(prompt: str) -> str:
    """Single streamed Claude call. Returns the concatenated text output."""
    return _final_text(_stream_message(messages=[{"role": "user", "content": prompt}]))


MAX_TOOL_ROUNDS = 24
TOOL_BUDGET_MSG = ("Tool budget used up. Stop exploring and write the final document now, "
                   "based on what you have already read.")


def call_claude_with_repo(prompt: str, reader) -> str:
    """Streamed Claude call that may read the project's repository through read-only tools first."""
    from app.services.repo_tools import TOOL_DEFS, RepoToolError

    messages: list[dict] = [{"role": "user", "content": prompt}]
    rounds = 0
    while True:
        # Automatic prompt caching: each round re-sends the growing conversation, so cache its prefix.
        msg = _stream_message(messages=messages, tools=TOOL_DEFS, cache_control={"type": "ephemeral"})
        if msg.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": msg.content})
            continue
        if msg.stop_reason != "tool_use":
            return _final_text(msg)
        rounds += 1
        if rounds > MAX_TOOL_ROUNDS + 3:
            raise AIError("Claude kept reading code without writing the document - try narrower feedback.")
        messages.append({"role": "assistant", "content": msg.content})
        results = []
        for block in msg.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            if rounds > MAX_TOOL_ROUNDS:
                content, is_error = TOOL_BUDGET_MSG, True
            else:
                try:
                    content, is_error = reader.run(block.name, block.input), False
                except RepoToolError as exc:
                    content, is_error = f"Error: {exc}", True
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                            "is_error": is_error})
        messages.append({"role": "user", "content": results})


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
        packs = [dev_to_dict(d) for d in f.dev_tasks]
        c["dev_json"] = json.dumps(packs[0] if len(packs) == 1 else packs, indent=2, ensure_ascii=False)
    prev = prev_items.get(f.ref)
    c["previous_output"] = json.dumps(prev, indent=2, ensure_ascii=False) if prev else ""
    if not prev:
        c["feedback"] = ctx.get("feedback", "")
    return c


MOCK_REVISE_MSG = ("Plain-language feedback needs live Claude: mock mode cannot read instructions. Set MOCK_AI=false and "
                   "ANTHROPIC_API_KEY in .env and restart, or make the change in the editor and click Save.")


def revise(project: Project, stage_no: int, feedback: str) -> tuple[str, dict | None, str, list[str]]:
    """Apply plain-language feedback to the stage's current document, keeping everything it doesn't mention.

    Returns (markdown, json, source, files_read). On technical stages with a target repository, Claude reads the
    relevant source files first; files_read lists them.
    """
    from app.prompts import revise as revise_prompt

    if not get_settings().ai_is_live:
        raise AIError(MOCK_REVISE_MSG)
    stage = get_stage(stage_no)
    feature_refs = {f.ref for f in project.features} if stage_no in (5, 6, 7) else None
    reader = repo_reader(project, stage_no)
    prompt = revise_prompt.build(stage_no, base_context(project), _previous_output(project, stage_no), feedback,
                                 repo=reader is not None)
    raw = call_claude_with_repo(prompt, reader) if reader else call_claude(prompt)
    try:
        md, doc = parse_stage_output(stage_no, raw, stage.output, known_feature_refs=feature_refs)
    except OutputParseError as first:
        log.warning("Stage %s revision failed validation (%s); retrying with repair prompt", stage_no, first)
        raw = call_claude(_repair_prompt(prompt, raw, str(first)))
        try:
            md, doc = parse_stage_output(stage_no, raw, stage.output, known_feature_refs=feature_refs)
        except OutputParseError as second:
            raise AIError(f"Model output failed validation twice: {second}") from second
    if doc is not None:
        md = render_stage_json(stage_no, doc)
    return md, doc, "ai", (reader.files_read if reader else [])


CODE_AWARE_STAGES = (3, 6, 7)


def repo_reader(project: Project, stage_no: int):
    """A read-only reader over the project's repository, for technical stages; None when unavailable."""
    from app.services.repo_tools import RepoReader, RepoToolError

    if stage_no not in CODE_AWARE_STAGES or not (project.target_repo_path or "").strip():
        return None
    try:
        return RepoReader(project.target_repo_path)
    except RepoToolError:
        return None


def default_feature_scope(project: Project, stage_no: int) -> list[Feature]:
    """Features that need a per-feature pack by default.

    Stage 6: features not yet Done. Stage 7: features that have a dev pack (a defect fix on a Done feature still
    needs testing), else features not yet Done. Already-built features are skipped, so generating for an as-built
    system costs one call per open piece of work rather than one per feature.
    """
    open_features = [f for f in project.features if f.status != "Done"]
    if stage_no == 7:
        with_packs = [f for f in project.features if f.dev_tasks]
        return with_packs or open_features
    return open_features


def generate(db: Session, project: Project, stage_no: int, feedback: str = "",
             feature_refs: list[str] | None = None) -> tuple[str, dict | None, str]:
    """Produce new content for a stage. Does not persist; the workflow layer stores it.

    For stages 6 and 7, `feature_refs` picks the features to generate for (one call each); None uses
    default_feature_scope.
    """
    ctx = base_context(project, feedback, _previous_output(project, stage_no) if feedback else "")
    all_refs = {f.ref for f in project.features}

    if stage_no in (6, 7):
        if not project.features:
            raise AIError("No approved features found - approve Stage 4 first.")
        list_key, prefix, ref_key = ("tasks", "DEV", "dev_ref") if stage_no == 6 else ("plans", "QA", "qa_ref")
        prev_doc = (project.artifact(stage_no).content_json or {}) if project.artifact(stage_no) else {}
        prev_items = {i["feature_ref"]: i for i in prev_doc.get(list_key, [])} if feedback else {}
        existing = {(d.feature.ref): d.ref for d in (all_dev_tasks(project) if stage_no == 6 else all_qa_plans(project))}
        if feature_refs is None:
            targets = default_feature_scope(project, stage_no)
        else:
            wanted = {r.upper() for r in feature_refs}
            targets = [f for f in project.features if f.ref in wanted]
        if not targets:
            raise AIError("No features selected - pick at least one feature to generate for.")
        items, sources = [], set()
        for idx, f in enumerate(targets, 1):
            ref = existing.get(f.ref) or fmt_ref(prefix, idx)
            fctx = _feature_ctx(ctx, f, prev_items, ref_key, ref)
            _, doc, src = run_stage_prompt(stage_no, fctx, known_feature_refs=all_refs)
            item = doc[list_key][0]
            item["ref"], item["feature_ref"] = ref, f.ref
            items.append(item)
            sources.add(src)
        merged = {list_key: items}
        return render_stage_json(stage_no, merged), merged, "ai" if "ai" in sources else "mock"

    md, doc, source = run_stage_prompt(stage_no, ctx, known_feature_refs=all_refs if stage_no == 5 else None)
    if doc is not None:
        md = render_stage_json(stage_no, doc)
    return md, doc, source
