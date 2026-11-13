"""Stage 2 - Business Requirements Document."""
from app.prompts.base import MARKDOWN_CONTRACT, feedback_block, project_header, section

OUTPUT = "markdown"

SECTIONS = """1. Document Control (version, date, status, owner)
2. Executive Summary
3. Business Objectives (numbered, each linked to REQ IDs)
4. Stakeholders & Personas (table)
5. Scope - In-Scope / Out-of-Scope (two lists)
6. Current vs Future Process Flows (at least one ```mermaid flowchart)
7. Business Rules (table: BR-ID, rule, source REQ)
8. Functional Requirements Summary (table: REQ ID, title, priority)
9. Non-Functional Requirements Summary
10. Constraints, Assumptions & Dependencies
11. Success Metrics / KPIs (measurable, with target values)
12. Risks & Open Questions"""


def build(ctx: dict) -> str:
    return (
        "Stage 2 - Business Requirements Document (BRD). Audience: client sponsor and business stakeholders.\n\n"
        + project_header(ctx)
        + section("approved_requirements", ctx.get("requirements_md"))
        + feedback_block(ctx)
        + "Task: synthesise the approved requirements into a formal BRD. Every business objective and business "
        "rule must cite the REQ IDs it comes from.\n\n"
        + MARKDOWN_CONTRACT + "\n\nRequired sections:\n" + SECTIONS
    )
