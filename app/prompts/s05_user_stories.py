"""Stage 5 - User Story Preparation."""
from app.prompts.base import JSON_CONTRACT, feedback_block, project_header, section

OUTPUT = "json"

SHAPE = """{
  "stories": [
    {
      "ref": "US-001",
      "feature_ref": "FEAT-001",
      "role": "persona name",
      "goal": "what they want to do",
      "benefit": "why it matters to them",
      "acceptance_criteria": "Scenario: ...\\n  Given ...\\n  When ...\\n  Then ...\\n\\nScenario: ...",
      "ui_notes": "screens, components, validation messages",
      "api_notes": "endpoints and payload fields used",
      "edge_cases": ["edge case 1", "edge case 2"]
    }
  ]
}"""


def build(ctx: dict) -> str:
    return (
        "Stage 5 - User Story Preparation.\n\n"
        + project_header(ctx)
        + section("approved_features", ctx.get("features_md"))
        + section("approved_tsd", ctx.get("tsd_md"))
        + feedback_block(ctx)
        + "Task: expand every approved feature into granular user stories (typically 2-4 per feature).\n"
        "- Each story follows 'As a <role>, I want <goal>, so that <benefit>'.\n"
        "- acceptance_criteria holds at least two Gherkin scenarios (one happy path, one failure/validation path) "
        "using Given/When/Then/And, with concrete data values.\n"
        "- Number refs US-001 upward in feature order.\n\n"
        + JSON_CONTRACT.format(shape=SHAPE)
    )
