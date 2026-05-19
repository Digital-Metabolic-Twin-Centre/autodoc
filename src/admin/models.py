import json
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from admin.database import Base


class RepositoryConfig(Base):
    __tablename__ = "repository_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    repo_url: Mapped[str] = mapped_column(String(500))
    repo_path: Mapped[str] = mapped_column(String(255), index=True)
    default_branch: Mapped[str] = mapped_column(String(255))
    target_folders_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reuse_doc: Mapped[bool] = mapped_column(Boolean, default=False)
    docstring_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    low_content_min_lines: Mapped[int] = mapped_column(Integer, default=4)
    encrypted_token: Mapped[str] = mapped_column(Text)
    token_last4: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    runs: Mapped[list["RunRecord"]] = relationship(back_populates="repository")

    @property
    def target_folders(self) -> list[str]:
        return json.loads(self.target_folders_json or "[]")

    @target_folders.setter
    def target_folders(self, value: list[str]) -> None:
        self.target_folders_json = json.dumps(value)


class RunRecord(Base):
    __tablename__ = "run_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("repository_configs.id"), nullable=True, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metrics_files_analyzed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_docstrings_generated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_skipped_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repository: Mapped[RepositoryConfig | None] = relationship(back_populates="runs")
