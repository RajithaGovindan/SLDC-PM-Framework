"""Stage 1 - Requirement Gathering."""
from app.prompts.base import JSON_CONTRACT, feedback_block, project_header, section

OUTPUT = "json"

SHAPE = """{
  "summary": "2-4 sentence summary of what the client wants and why",
  "requirements": [
    {
      "ref": "REQ-001",
      "type": "FR | NFR | CONSTRAINT | ASSUMPTION | OPEN_QUESTION",
      "title": "short imperative title",
      "description": "one precise, testable statement (for OPEN_QUESTION: the question to ask the client)",
      "priority": "Must | Should | Could | Won't",
      "source": "quote or paraphrase of the note that produced this item"
    }
  ]
}"""


def build(ctx: dict) -> str:
    return (
        "Stage 1 - Requirement Gathering.\n\n"
        + project_header(ctx)
        + section("raw_client_input", ctx.get("raw_notes") or "(no notes supplied)")
        + feedback_block(ctx)
        + "Task: extract a complete, de-duplicated requirement set from the raw client input.\n"
        "- FR: behaviour the system must provide. NFR: performance, security, availability, compliance, "
        "accessibility, scalability with measurable targets where the notes allow.\n"
        "- CONSTRAINT: fixed budget, deadline, technology, regulatory or integration limits.\n"
        "- ASSUMPTION: what you must assume to proceed. OPEN_QUESTION: ambiguities the client must answer.\n"
        "- Split compound statements so each item is individually testable. Number refs REQ-001 upward in "
        "the order: FR, NFR, CONSTRAINT, ASSUMPTION, OPEN_QUESTION.\n\n"
        + JSON_CONTRACT.format(shape=SHAPE)
    )
