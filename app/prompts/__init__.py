"""Stage-specific prompt templates."""
from types import ModuleType

from app.prompts import (s01_requirements, s02_brd, s03_tsd, s04_features, s05_user_stories, s06_dev_tasks,
                         s07_qa_plans, s08_release_notes, s09_runbook, s10_user_manual)
from app.prompts.base import SYSTEM_PROMPT

PROMPTS: dict[int, ModuleType] = {
    1: s01_requirements,
    2: s02_brd,
    3: s03_tsd,
    4: s04_features,
    5: s05_user_stories,
    6: s06_dev_tasks,
    7: s07_qa_plans,
    8: s08_release_notes,
    9: s09_runbook,
    10: s10_user_manual,
}

__all__ = ["PROMPTS", "SYSTEM_PROMPT"]
