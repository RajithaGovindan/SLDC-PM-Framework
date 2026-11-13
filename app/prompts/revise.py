"""Revise an existing stage document from plain-language reviewer feedback.

Unlike a stage prompt, this edits the current document in place: everything the feedback does not mention is
copied through unchanged, so hand-written or imported content survives a revision.
"""
from __future__ import annotations

from app.prompts import PROMPTS
from app.prompts.base import JSON_CONTRACT, MARKDOWN_CONTRACT, project_header, section
from app.stages import get_stage

# Upstream documents worth showing the model when revising each stage.
UPSTREAM: dict[int, tuple[str, ...]] = {
    1: ("raw_notes",),
    2: ("requirements_md",),
    3: ("requirements_md", "brd_md"),
    4: ("requirements_md", "tsd_md"),
    5: ("features_md",),
    6: ("tsd_md", "features_md", "stories_md"),
    7: ("features_md", "stories_md", "dev_md"),
    8: ("features_md", "dev_md", "qa_md"),
    9: ("tsd_md", "dev_md", "release_md"),
    10: ("requirements_md", "features_md", "stories_md"),
}
MAX_UPSTREAM_CHARS = 80_000

REPO_GUIDE = (
    "You can read this project's source repository with the tools search_code, read_file and list_dir "
    "(read-only). The reviewer is a project lead, not a developer, so the feedback will not name files, functions "
    "or columns. Before you write, look up the code the feedback concerns: find the routes, functions, templates "
    "and columns involved, read them, and work out the likely cause. Then write the change using the real names "
    "and paths you found. Prefer fixing the existing logic where it lives over adding a parallel copy of it. Where "
    "you could not confirm something in the code, say so in the item instead of guessing. Be economical: search "
    "first, then read only the parts you need, in at most about 15 tool calls. Your final message must contain "
    "only the document.\n\n")


def build(stage_no: int, ctx: dict, current: str, feedback: str, *, repo: bool = False) -> str:
    stage = get_stage(stage_no)
    upstream = "".join(section(key, (ctx.get(key) or "")[:MAX_UPSTREAM_CHARS]) for key in UPSTREAM.get(stage_no, ()))
    if stage.output == "json":
        contract = JSON_CONTRACT.format(shape=PROMPTS[stage_no].SHAPE)
        keep = ("Copy every item and field the feedback does not touch exactly as it is, character for character. "
                "Keep every existing ref. A new item gets the next unused ref number. Remove an item only if the "
                "feedback asks for it. Return the complete document, not only the changed items.")
    else:
        contract = MARKDOWN_CONTRACT + " Keep the current document's headings and order."
        keep = ("Copy every section and sentence the feedback does not touch exactly as it is. "
                "Return the complete document, not only the changed sections.")
    return (
        f"Stage {stage_no:02d} - {stage.title}. Task: apply a reviewer's change request to the current document.\n\n"
        + project_header(ctx)
        + upstream
        + section("current_document", current)
        + section("reviewer_feedback", feedback)
        + "Edit the current document so it fully addresses the reviewer feedback. The feedback is written in plain "
          "language by a project lead; interpret it as an edit request (add, change or remove), not as a request to "
          "rewrite the document. Ground new content in the current document and the upstream documents above; "
          "when the feedback states a fact that is not in them, take it as given. "
          "The reviewer need not name an item: when the feedback reports a bug or new work that no existing item "
          "covers, add a new item and link it to the best-matching parent (feature, story or requirement); when it "
          "refines something an existing item already covers, edit that item instead. "
        + keep + "\n\n"
        + (REPO_GUIDE if repo else "")
        + contract
    )
