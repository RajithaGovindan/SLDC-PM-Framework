"""Stage 9 - Implementation & Deployment Runbook."""
from app.prompts.base import MARKDOWN_CONTRACT, feedback_block, project_header, section

OUTPUT = "markdown"

SECTIONS = """1. Release Overview (scope, window, go/no-go owner, communication channel)
2. Roles & Responsibilities (table: role, person placeholder, responsibilities)
3. Pre-Deployment Checklist (task list `- [ ]`, each item tagged with an owner role)
4. Backup Procedure (exact commands)
5. Database Migration Sequence (ordered, with verification query after each step)
6. Backend Rollout (order, commands, health checks)
7. Frontend Rollout (order, cache invalidation)
8. Smoke Test Verification (table: check, owner, expected result; reference QA IDs)
9. Rollback Procedure (trigger criteria, ordered steps, data restore)
10. Post-Deployment Monitoring & Sign-off"""


def build(ctx: dict) -> str:
    return (
        "Stage 9 - Implementation & Deployment Runbook. Audience: DevOps, developers, QA and the release manager "
        "executing the release.\n\n"
        + project_header(ctx)
        + section("approved_release_notes", ctx.get("release_md"))
        + section("tsd_excerpt", ctx.get("tsd_md"))
        + section("developer_packs", ctx.get("dev_md"))
        + feedback_block(ctx)
        + "Task: write a step-by-step release execution runbook. Every action is a checklist item with an explicit "
        "owner role in bold, e.g. `- [ ] **DevOps** - ...`. Commands go in fenced code blocks.\n\n"
        + MARKDOWN_CONTRACT + "\n\nRequired sections:\n" + SECTIONS
    )
