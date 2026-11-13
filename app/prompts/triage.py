"""Triage a plain-language report into bug / change request / question, with a per-stage impact plan."""
from __future__ import annotations

from app.prompts.base import project_header, section
from app.stages import STAGES

SHAPE = """{
  "kind": "bug | cr | question",
  "title": "short title, max 12 words",
  "reasoning": "the evidence for the classification: quote the requirement, story or acceptance criterion that \
already covers the behaviour (bug) or show that none does / that an agreed rule changes (cr); for code-aware \
runs, what the code does today",
  "related_refs": ["FEAT-014", "US-043"],
  "plan": [
    {"stage_no": 6, "instruction": "precise edit instruction for that stage's document"}
  ]
}"""

UPSTREAM_KEYS = ("requirements_md", "features_md", "stories_md", "dev_md", "qa_md")
MAX_CHARS = 60_000


def build(ctx: dict, report: str, stages_with_content: list[int], repo: bool) -> str:
    stage_list = "\n".join(f"- {s.no}: {s.title}{'' if s.no in stages_with_content else ' (no content yet - do not plan edits here)'}"
                           for s in STAGES)
    return (
        "Task: triage a report from the project team. The reporter is not a developer and does not know whether "
        "it is a bug or a change; decide that for them, with evidence.\n\n"
        + project_header(ctx)
        + "".join(section(k, (ctx.get(k) or "")[:MAX_CHARS]) for k in UPSTREAM_KEYS)
        + section("stages", stage_list)
        + section("report", report)
        + "Classify the report:\n"
        "- bug: an existing requirement, user story or acceptance criterion already describes the expected "
        "behaviour and the system does not meet it.\n"
        "- cr (change request): no requirement or story asks for this behaviour, or it changes an agreed rule, "
        "screen or flow. A report that is partly a bug and partly new behaviour is a cr; say which part is which "
        "in the reasoning.\n"
        "- question: it cannot be acted on without an answer from the client or business.\n\n"
        "Then plan the documents to update, in stage order. Only plan stages that already have content. Each "
        "instruction must be self-contained and precise enough to apply to that stage alone: name the existing "
        "item IDs to change, or say to add a new item and under which parent. Typical plans:\n"
        "- bug: stage 6 (fix in a dev pack under the affected feature) and stage 7 (tests that would have caught "
        "it). Change stage 5 only if the acceptance criteria are ambiguous.\n"
        "- cr: stage 1 (new or changed requirement) -> 2 or 3 only if business rules or the technical design "
        "change -> 4 (new feature or changed scope) -> 5 (stories with Gherkin) -> 6 -> 7, and 8-10 only if "
        "they already describe the area.\n"
        "- question: stage 1 only, adding an OPEN_QUESTION requirement.\n"
        + ("You can read the source code with search_code, read_file and list_dir (read-only). Use them to check "
           "what the system does today before you classify, in at most about 12 tool calls.\n" if repo else "")
        + "\nOutput contract: respond with ONE JSON object of this shape and nothing else:\n" + SHAPE
    )
