"""The data model.

Three tables, one shape: a comparison, its stages, and its regions. There are no
runs, review queues, acknowledgements, artwork versions or discriminating regions
here — those all belong to a question this build does not ask.

All timestamps are UTC ISO-8601 **strings**, carried over deliberately: it keeps
the database inspectable with plain `sqlite3`, and history diffs cleanly.

SQLAlchemy 2.x with `create_all` and no migration tooling. At one pair at a time
Alembic buys nothing, and the schema is small enough to recreate — but the ORM
layer is kept so the patterns carry straight back over.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_path: Mapped[str] = mapped_column(Text)
    marketplace_path: Mapped[str] = mapped_column(Text)
    reference_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    marketplace_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The user's own note, e.g. "SKU001 front". Never parsed.
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    pipeline_version: Mapped[str] = mapped_column(String(20))
    # Frozen at run time. This is what makes a completed comparison reproducible:
    # recalibrating later cannot rewrite its verdict.
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)

    stages: Mapped[list["ComparisonStage"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan",
        order_by="ComparisonStage.ordinal")
    regions: Mapped[list["ComparisonRegion"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan",
        order_by="ComparisonRegion.id")


class ComparisonStage(Base):
    """One `StageTrace`, persisted.

    Every stage gets a row, including skipped and failed ones. A missing row would
    be indistinguishable from a stage that silently did nothing, and the whole
    point of this build is that the method is inspectable.
    """

    __tablename__ = "comparison_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    artifacts_json: Mapped[str] = mapped_column(Text, default="{}")
    notes_json: Mapped[str] = mapped_column(Text, default="[]")

    comparison: Mapped[Comparison] = relationship(back_populates="stages")


class ComparisonRegion(Base):
    """One candidate region, with its readings and its classification."""

    __tablename__ = "comparison_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    # Marketplace frame — the frame everything is displayed in.
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
    area_fraction: Mapped[float] = mapped_column(Float, default=0.0)

    reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketplace_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_reliable: Mapped[bool] = mapped_column(Boolean, default=True)
    difference_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    ref_crop_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mkt_crop_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal: Mapped[float] = mapped_column(Float, default=0.0)

    comparison: Mapped[Comparison] = relationship(back_populates="regions")


Index("ix_comparisons_created", Comparison.created_at.desc())
