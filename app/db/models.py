from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BIGINT, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserVisitLog(Base):
    __tablename__ = "user_visit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class JobDefinition(Base):
    __tablename__ = "job_definitions"

    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("job_definitions.job_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduler")
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WidgetSnapshot(Base):
    __tablename__ = "widget_snapshots"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    widget_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False, default="global")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Legacy plain-text attribution (prefer payload.source + payload.period for UI)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Job fetch time (when we fetched & materialized this snapshot)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Source-declared or reasonably inferred timestamp of the *data point* itself.
    # This is NOT the job run time.
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    job_run_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PublicContext(Base):
    __tablename__ = "public_contexts"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WidgetInsightJobState(Base):
    __tablename__ = "widget_insight_job_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WidgetInsight(Base):
    __tablename__ = "widget_insights"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)

    # homepage card key, e.g. trade_flow / wealth / finance
    card_key: Mapped[str] = mapped_column(String(80), nullable=False)

    # tab key inside the card, e.g. corridors/exim/balance/wci/portwatch
    tab_key: Mapped[str] = mapped_column(String(80), nullable=False)

    scope: Mapped[str] = mapped_column(String(80), nullable=False, default="global")
    lang: Mapped[str] = mapped_column(String(16), nullable=False, default="en")

    content: Mapped[str] = mapped_column(Text, nullable=False)
    reference_list: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # Source data timestamp used in this insight (declared or inferred)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provenance / de-dup
    data_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_snapshot_keys: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    llm_provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    llm_model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    llm_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    llm_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    generated_by: Mapped[str] = mapped_column(String(80), nullable=False, default="job")
    job_run_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
