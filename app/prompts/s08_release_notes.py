"""Stage 8 - Release Documentation."""
from app.prompts.base import MARKDOWN_CONTRACT, feedback_block, project_header, section

OUTPUT = "markdown"

SECTIONS = """1. Release Summary (version, target date, highlights)
2. New Features (table: FEAT ID, title, user-facing description, stories)
3. Improvements
4. Bug Fixes (state "None in this release" if none are known)
5. Breaking Changes & Required Actions
6. Database Migrations (ordered list with reversibility notes)
7. Environment Variable / Configuration Updates (table: name, required, default, description)
8. Known Issues & Limitations
9. Traceability (table: FEAT -> REQ -> DEV -> QA)"""


def build(ctx: dict) -> str:
    return (
        "Stage 8 - Release Notes. Audience: stakeholders, support and the release team.\n\n"
        + project_header(ctx)
        + section("release_features", ctx.get("features_md"))
        + section("developer_packs", ctx.get("dev_md"))
        + section("qa_plans_summary", ctx.get("qa_md"))
        + section("tsd_excerpt", ctx.get("tsd_md"))
        + feedback_block(ctx)
        + "Task: aggregate all completed/approved features into release notes. Derive migrations and env vars "
        "from the developer packs and TSD.\n\n"
        + MARKDOWN_CONTRACT + "\n\nRequired sections:\n" + SECTIONS
    )
