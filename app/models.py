"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.stages import Status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    client: Mapped[str] = mapped_column(String(200), default="")
    raw_notes: Mapped[str] = mapped_column(Text, default="")
    target_repo_path: Mapped[str] = mapped_column(String(1000), default="")
    # Plain-language summaries for the "What's left" page: {ref: {title, what, why, src}}
    plain_summaries: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    artifacts: Mapped[list[StageArtifact]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="StageArtifact.stage_no")
    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Requirement.ref")
    features: Mapped[list[Feature]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Feature.order_index")
    sync_logs: Mapped[list[SyncLog]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SyncLog.created_at.desc()")
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Attachment.id")
    issues: Mapped[list[Issue]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Issue.id.desc()")

    def artifact(self, stage_no: int) -> StageArtifact | None:
        return next((a for a in self.artifacts if a.stage_no == stage_no), None)


class StageArtifact(Base):
    __tablename__ = "stage_artifacts"
    __table_args__ = (UniqueConstraint("project_id", "stage_no", name="uq_artifact_project_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage_no: Mapped[int] = mapped_column(Integer)
    stage_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=Status.LOCKED)
    content_md: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[str] = mapped_column(String(120), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocker_note: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="artifacts")
    revisions: Mapped[list[ArtifactRevision]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan", order_by="ArtifactRevision.version.desc()")

    @property
    def has_content(self) -> bool:
        return bool((self.content_md or "").strip()) or self.content_json is not None


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("stage_artifacts.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_md: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")  # ai | mock | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    artifact: Mapped[StageArtifact] = relationship(back_populates="revisions")


feature_requirements = Table(
    "feature_requirements",
    Base.metadata,
    Column("feature_id", ForeignKey("features.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_req_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="Should")
    status: Mapped[str] = mapped_column(String(20), default="Approved")

    project: Mapped[Project] = relationship(back_populates="requirements")
    features: Mapped[list[Feature]] = relationship(secondary=feature_requirements, back_populates="requirements")


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_feat_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    module: Mapped[str] = mapped_column(String(100), default="")
    priority: Mapped[str] = mapped_column(String(10), default="P2")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    depends_on: Mapped[Any] = mapped_column(JSON, default=list)
    effort_sa: Mapped[float] = mapped_column(Float, default=0)
    effort_dev: Mapped[float] = mapped_column(Float, default=0)
    effort_qa: Mapped[float] = mapped_column(Float, default=0)
    effort_docs: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="To Do")

    project: Mapped[Project] = relationship(back_populates="features")
    requirements: Mapped[list[Requirement]] = relationship(secondary=feature_requirements, back_populates="features")
    stories: Mapped[list[UserStory]] = relationship(
        back_populates="feature", cascade="all, delete-orphan", order_by="UserStory.ref")
    dev_tasks: Mapped[list[DevTask]] = relationship(
        back_populates="feature", cascade="all, delete-orphan", order_by="DevTask.ref")
    qa_plans: Mapped[list[QAPlan]] = relationship(
        back_populates="feature", cascade="all, delete-orphan", order_by="QAPlan.ref")

    @property
    def total_effort(self) -> float:
        return (self.effort_sa or 0) + (self.effort_dev or 0) + (self.effort_qa or 0) + (self.effort_docs or 0)


class UserStory(Base):
    __tablename__ = "user_stories"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_us_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feature_id: Mapped[int] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(200), default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    benefit: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    ui_notes: Mapped[str] = mapped_column(Text, default="")
    api_notes: Mapped[str] = mapped_column(Text, default="")
    edge_cases: Mapped[Any] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="To Do")

    feature: Mapped[Feature] = relationship(back_populates="stories")


class DevTask(Base):
    __tablename__ = "dev_tasks"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_dev_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feature_id: Mapped[int] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    target_files: Mapped[Any] = mapped_column(JSON, default=list)
    migration_notes: Mapped[str] = mapped_column(Text, default="")
    implementation_steps_md: Mapped[str] = mapped_column(Text, default="")
    unit_test_reqs_md: Mapped[str] = mapped_column(Text, default="")
    claude_prompt: Mapped[str] = mapped_column(Text, default="")
    assignee_role: Mapped[str] = mapped_column(String(40), default="Developer")
    status: Mapped[str] = mapped_column(String(20), default="To Do")

    feature: Mapped[Feature] = relationship(back_populates="dev_tasks")


class QAPlan(Base):
    __tablename__ = "qa_plans"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_qa_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feature_id: Mapped[int] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    story_refs: Mapped[Any] = mapped_column(JSON, default=list)
    positive_md: Mapped[str] = mapped_column(Text, default="")
    negative_md: Mapped[str] = mapped_column(Text, default="")
    regression_md: Mapped[str] = mapped_column(Text, default="")
    automation_scaffold: Mapped[str] = mapped_column(Text, default="")
    claude_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="To Do")

    feature: Mapped[Feature] = relationship(back_populates="qa_plans")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    target_path: Mapped[str] = mapped_column(String(1000))
    files_written: Mapped[Any] = mapped_column(JSON, default=list)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sync_logs")


class Attachment(Base):
    """A file the team attached to a project, a stage or an issue. Stored on disk under ATTACHMENTS_DIR."""
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = project-level
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    filename: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(20), default="other")  # image | pdf | docx | xlsx | text | other
    size: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    use_in_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="attachments")
    issue: Mapped[Issue | None] = relationship(back_populates="attachments")


class Issue(Base):
    """A bug, change request or question reported in plain words, triaged by Claude into an impact plan."""
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_issue_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))  # BUG-001 | CR-001 | Q-001
    kind: Mapped[str] = mapped_column(String(20), default="")  # bug | cr | question
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    reporter: Mapped[str] = mapped_column(String(120), default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[Any] = mapped_column(JSON, default=list)  # [{stage_no, instruction, selected, result, version}]
    status: Mapped[str] = mapped_column(String(20), default="New")  # New | Planned | Applied | Rejected
    files_read: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="issues")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="issue", cascade="all, delete-orphan",
                                                         order_by="Attachment.id")
