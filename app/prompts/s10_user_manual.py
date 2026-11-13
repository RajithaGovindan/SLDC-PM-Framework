"""Stage 10 - User Manual."""
from app.prompts.base import MARKDOWN_CONTRACT, feedback_block, project_header, section

OUTPUT = "markdown"

SECTIONS = """1. Introduction (what the product does, who it is for)
2. Getting Started (access, sign-in, navigation overview)
3. One section per user persona, each with its workflows as numbered step-by-step instructions
4. Notifications & Account Settings
5. Troubleshooting & FAQs (question/answer pairs, at least 8)
6. Glossary
7. Getting Help"""


def build(ctx: dict) -> str:
    return (
        "Stage 10 - User Manual. Audience: end users with no technical background.\n\n"
        + project_header(ctx)
        + section("brd", ctx.get("brd_md"))
        + section("user_stories", ctx.get("stories_md"))
        + section("release_notes", ctx.get("release_md"))
        + feedback_block(ctx)
        + "Task: write a clean end-user manual organised by persona and workflow. Plain language, second person, "
        "no internal IDs, no implementation details. Describe screens and buttons by their visible labels.\n\n"
        + MARKDOWN_CONTRACT + "\n\nRequired sections:\n" + SECTIONS
    )
