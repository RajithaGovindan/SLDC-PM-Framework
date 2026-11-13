"""Pydantic v2 schemas: strict AI output contracts per JSON stage + form/API payloads."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ----------------------------------------------------------------- Stage 1


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = ""
    type: Literal["FR", "NFR", "CONSTRAINT", "ASSUMPTION", "OPEN_QUESTION"]
    title: str
    description: str = ""
    priority: Literal["Must", "Should", "Could", "Won't"] = "Should"
    source: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v: str) -> str:
        v = str(v).strip().upper().replace(" ", "_").replace("-", "_")
        aliases = {"FUNCTIONAL": "FR", "NON_FUNCTIONAL": "NFR", "NONFUNCTIONAL": "NFR", "QUESTION": "OPEN_QUESTION",
                   "OPEN_QUESTIONS": "OPEN_QUESTION", "CONSTRAINTS": "CONSTRAINT", "ASSUMPTIONS": "ASSUMPTION"}
        return aliases.get(v, v)

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v: str) -> str:
        v = str(v or "Should").strip().capitalize()
        return {"High": "Must", "Medium": "Should", "Low": "Could", "Wont": "Won't"}.get(v, v)


class RequirementsDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str = ""
    requirements: list[RequirementItem] = Field(min_length=1)


# ----------------------------------------------------------------- Stage 4


class Effort(BaseModel):
    model_config = ConfigDict(extra="ignore")
    solution_architect: float = 0
    developer: float = 0
    qa: float = 0
    docs: float = 0


class FeatureItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = ""
    title: str
    description: str = ""
    module: str = "core"
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    depends_on: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)
    effort_hours: Effort = Field(default_factory=Effort)

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v: str) -> str:
        v = str(v or "P2").strip().upper()
        return {"CRITICAL": "P0", "HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}.get(v, v)


class FeaturesDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    features: list[FeatureItem] = Field(min_length=1)


# ----------------------------------------------------------------- Stage 5


class StoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = ""
    feature_ref: str
    role: str
    goal: str
    benefit: str
    acceptance_criteria: str = Field(description="Gherkin scenarios: Scenario/Given/When/Then")
    ui_notes: str = ""
    api_notes: str = ""
    edge_cases: list[str] = Field(default_factory=list)


class StoriesDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    stories: list[StoryItem] = Field(min_length=1)


# ----------------------------------------------------------------- Stage 6


class TargetFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    action: Literal["create", "modify", "delete"] = "create"
    purpose: str = ""

    @field_validator("action", mode="before")
    @classmethod
    def _norm_action(cls, v: str) -> str:
        return str(v or "create").strip().lower()


class DevTaskItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = ""
    feature_ref: str
    title: str
    target_files: list[TargetFile] = Field(default_factory=list)
    migration_notes: str = ""
    implementation_steps: list[str] = Field(default_factory=list)
    unit_tests: list[str] = Field(default_factory=list)
    claude_prompt: str = ""


class DevTasksDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tasks: list[DevTaskItem] = Field(min_length=1)


# ----------------------------------------------------------------- Stage 7


class TestCase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    story_ref: str = ""
    title: str
    steps: list[str] = Field(default_factory=list)
    expected: str = ""


class QAPlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = ""
    feature_ref: str
    story_refs: list[str] = Field(default_factory=list)
    positive_tests: list[TestCase] = Field(default_factory=list)
    negative_tests: list[TestCase] = Field(default_factory=list)
    regression_checks: list[str] = Field(default_factory=list)
    automation_scaffold: str = ""
    claude_prompt: str = ""


class QAPlansDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    plans: list[QAPlanItem] = Field(min_length=1)


STAGE_SCHEMAS: dict[int, type[BaseModel]] = {
    1: RequirementsDoc,
    4: FeaturesDoc,
    5: StoriesDoc,
    6: DevTasksDoc,
    7: QAPlansDoc,
}


# ----------------------------------------------------------------- API payloads


class RenderRequest(BaseModel):
    content: str


class RenderResponse(BaseModel):
    markdown: str
    error: str = ""
