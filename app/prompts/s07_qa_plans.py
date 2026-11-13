"""Stage 7 - QA Test Plan & Execution Pack (generated once per feature)."""
from app.prompts.base import JSON_CONTRACT, feedback_block, project_header, section

OUTPUT = "json"

SHAPE = """{
  "plans": [
    {
      "ref": "QA-001",
      "feature_ref": "FEAT-001",
      "story_refs": ["US-001", "US-002"],
      "positive_tests": [
        {"id": "TC-001", "story_ref": "US-001", "title": "...", "steps": ["..."], "expected": "..."}
      ],
      "negative_tests": [
        {"id": "TC-010", "story_ref": "US-001", "title": "boundary / invalid input ...", "steps": ["..."], "expected": "..."}
      ],
      "regression_checks": ["existing behaviour to re-verify"],
      "automation_scaffold": "runnable test file skeleton (e.g. pytest or Playwright) covering the cases above",
      "claude_prompt": "a self-contained prompt a QA engineer pastes into Claude Code to automate and run this plan"
    }
  ]
}"""


def build(ctx: dict) -> str:
    return (
        "Stage 7 - QA Instructions. Audience: the QA engineer verifying ONE feature.\n\n"
        + project_header(ctx)
        + section("feature", ctx.get("feature_json"))
        + section("feature_user_stories", ctx.get("stories_json"))
        + section("developer_pack", ctx.get("dev_json"))
        + feedback_block(ctx)
        + f"Task: produce exactly one QA plan for {ctx.get('feature_ref')} with ref {ctx.get('qa_ref')}.\n"
        "- Map every Gherkin scenario of every story to at least one test case (story_ref set).\n"
        "- negative_tests cover invalid input, boundaries, permissions/authorisation and failure of dependencies.\n"
        "- regression_checks list adjacent behaviour that could break.\n"
        "- automation_scaffold is a code skeleton matching the TSD tech stack.\n"
        "- claude_prompt tells Claude Code to read `.sdlc/07-qa-plans/` for this plan, implement the automated "
        "tests, run them and report a pass/fail table per test case ID.\n\n"
        + JSON_CONTRACT.format(shape=SHAPE)
    )
