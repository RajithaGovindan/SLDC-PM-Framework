"""Stage 4 - Feature List Preparation."""
from app.prompts.base import JSON_CONTRACT, feedback_block, project_header, section

OUTPUT = "json"

SHAPE = """{
  "features": [
    {
      "ref": "FEAT-001",
      "title": "short feature name",
      "description": "what the feature delivers and its boundaries",
      "module": "module tag, e.g. auth | booking | billing | admin | notifications | platform",
      "priority": "P0 | P1 | P2 | P3",
      "depends_on": ["FEAT-000"],
      "requirement_refs": ["REQ-001", "REQ-004"],
      "effort_hours": {"solution_architect": 4, "developer": 24, "qa": 10, "docs": 3}
    }
  ]
}"""


def build(ctx: dict) -> str:
    return (
        "Stage 4 - Feature List Preparation.\n\n"
        + project_header(ctx)
        + section("approved_requirements", ctx.get("requirements_md"))
        + section("approved_tsd", ctx.get("tsd_md"))
        + feedback_block(ctx)
        + "Task: decompose the TSD into a prioritised, dependency-ordered feature list.\n"
        "- Each feature is an independently deliverable vertical slice (roughly 1-5 developer days).\n"
        "- Order the array so every feature appears after the features it depends on; number refs in that order.\n"
        "- Every FR and NFR must be covered by at least one feature via requirement_refs.\n"
        "- P0 = foundation/blocking, P1 = core value, P2 = important, P3 = nice to have.\n"
        "- Effort placeholders are hour estimates per role.\n\n"
        + JSON_CONTRACT.format(shape=SHAPE)
    )
