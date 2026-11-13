"""Stage 3 - Technical Specification Document."""
from app.prompts.base import MARKDOWN_CONTRACT, feedback_block, project_header, section

OUTPUT = "markdown"

SECTIONS = """1. Overview & Technical Goals
2. System Architecture (components, responsibilities, ```mermaid flowchart or C4-style diagram)
3. Technology Stack (table with justification)
4. Data Model - ERD as ```mermaid erDiagram, then a table per entity (field, type, constraints)
5. API Specification - for each endpoint: METHOD /path, auth, request JSON, response JSON, error codes
6. Security & Authentication (authn, authz/roles, data protection, audit, OWASP considerations)
7. Integration Points (external systems, protocols, retries, idempotency)
8. Non-Functional Design (performance budgets, caching, scaling, observability)
9. Edge Cases & Failure Modes (table: scenario, handling)
10. Requirement Coverage (table: REQ ID -> component / endpoint / entity)"""


def build(ctx: dict) -> str:
    return (
        "Stage 3 - Technical Specification Document (TSD). Audience: solution architects and developers.\n\n"
        + project_header(ctx)
        + section("approved_requirements", ctx.get("requirements_md"))
        + section("approved_brd", ctx.get("brd_md"))
        + feedback_block(ctx)
        + "Task: translate the approved BRD into an implementable technical specification. Keep the design as "
        "simple as the requirements allow; name concrete tables, columns, endpoints and payload fields.\n\n"
        + MARKDOWN_CONTRACT + "\n\nRequired sections:\n" + SECTIONS
    )
