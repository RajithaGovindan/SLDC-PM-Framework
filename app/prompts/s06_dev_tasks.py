"""Stage 6 - Developer Execution Pack (generated once per feature)."""
from app.prompts.base import JSON_CONTRACT, feedback_block, project_header, section

OUTPUT = "json"

SHAPE = """{
  "tasks": [
    {
      "ref": "DEV-001",
      "feature_ref": "FEAT-001",
      "title": "Implement <feature>",
      "target_files": [
        {"path": "app/api/bookings.py", "action": "create | modify | delete", "purpose": "why this file changes"}
      ],
      "migration_notes": "tables/columns/indexes to add, migration name, backfill, reversibility",
      "implementation_steps": ["ordered, concrete step", "..."],
      "unit_tests": ["test name - what it asserts", "..."],
      "claude_prompt": "a self-contained prompt a developer pastes into Claude Code to implement this feature"
    }
  ]
}"""


def build(ctx: dict) -> str:
    return (
        "Stage 6 - Developer Instructions. Audience: the developer implementing ONE feature.\n\n"
        + project_header(ctx)
        + section("approved_tsd", ctx.get("tsd_md"))
        + section("feature", ctx.get("feature_json"))
        + section("feature_user_stories", ctx.get("stories_json"))
        + feedback_block(ctx)
        + f"Task: produce exactly one Developer Execution Pack for {ctx.get('feature_ref')} with ref "
        f"{ctx.get('dev_ref')}.\n"
        "- target_files lists every file to create or modify, with paths consistent with the TSD architecture.\n"
        "- implementation_steps are ordered and specific (models, migrations, services, routes, UI, wiring).\n"
        "- unit_tests cover every Gherkin scenario of the feature's stories plus key edge cases.\n"
        "- claude_prompt must be self-contained: it names the feature and story IDs, tells Claude Code to read "
        "`.sdlc/03-tsd/tsd.md` and this pack under `.sdlc/06-dev-tasks/`, lists the files, the acceptance "
        "criteria, the tests to write, and the definition of done (tests pass, lint clean, no unrelated changes).\n\n"
        + JSON_CONTRACT.format(shape=SHAPE)
    )
