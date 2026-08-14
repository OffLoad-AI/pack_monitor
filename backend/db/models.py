"""SQLAlchemy 2.x models for the packaging compliance monitor.

All timestamps are UTC ISO-8601 strings (TEXT) so the DB stays inspectable with
plain `sqlite3` and so run history diffs cleanly.
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


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Reference side: what the brand approved
# --------------------------------------------------------------------------


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # SKU
    name: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    versions: Mapped[list["ArtworkVersion"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ArtworkVersion(Base):
    __tablename__ = "artwork_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    version_label: Mapped[str] = mapped_column(String)
    file_path: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, index=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Exactly one true per product.
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    product: Mapped[Product] = relationship(back_populates="versions")

    __table_args__ = (Index("ix_version_product_label", "product_id", "version_label"),)


class DiscriminatingRegion(Base):
    """A box that visually distinguishes one artwork version from the next.

    Coordinates are in `from_version` pixel space, which for our corpus is the
    same for every version of a product.
    """

    __tablename__ = "discriminating_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    from_version_id: Mapped[int] = mapped_column(ForeignKey("artwork_versions.id"), index=True)
    to_version_id: Mapped[int] = mapped_column(ForeignKey("artwork_versions.id"), index=True)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
    area_fraction: Mapped[float] = mapped_column(Float)
    field_key: Mapped[str | None] = mapped_column(String, nullable=True)
    old_value: Mapped[str | None] = mapped_column(String, nullable=True)
    new_value: Mapped[str | None] = mapped_column(String, nullable=True)
    edit_type: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String)  # MATERIAL | COSMETIC | UNKNOWN


# --------------------------------------------------------------------------
# Run side: what the marketplace is actually serving
# --------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[str] = mapped_column(String, default=utcnow)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="RUNNING")  # RUNNING|COMPLETE|FAILED
    pipeline_version: Mapped[str] = mapped_column(String)
    input_dir: Mapped[str] = mapped_column(String, default="")
    images_total: Mapped[int] = mapped_column(Integer, default=0)
    images_processed: Mapped[int] = mapped_column(Integer, default=0)
    images_cached: Mapped[int] = mapped_column(Integer, default=0)
    # Thresholds frozen at run start, so a later recalibration cannot rewrite history.
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScrapedImage(Base):
    __tablename__ = "scraped_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    source_path: Mapped[str] = mapped_column(String, index=True)
    sha256: Mapped[str] = mapped_column(String, index=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    scraped_image_id: Mapped[int] = mapped_column(ForeignKey("scraped_images.id"))
    verdict: Mapped[str] = mapped_column(String, index=True)  # PASS|STALE_VERSION|UNKNOWN_IMAGE|ERROR
    matched_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artwork_versions.id"), nullable=True
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artwork_versions.id"), nullable=True
    )
    match_method: Mapped[str] = mapped_column(String)  # HASH_EXACT|PIXEL_DIFF|REGION_CHECK|CACHED|NONE
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    diff_map_path: Mapped[str | None] = mapped_column(String, nullable=True)
    regions_json: Mapped[str] = mapped_column(Text, default="[]")
    severity: Mapped[str] = mapped_column(String, index=True)  # MATERIAL|COSMETIC|UNCERTAIN|NONE
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What each stage measured and why it decided as it did. Written for findings
    # that are not a clean pass, because those are the ones anyone investigates:
    # without it, answering "why was this refused?" meant re-running the image
    # under a one-off script with the run's original thresholds.
    stage_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class Acknowledgement(Base):
    """A reviewer's sign-off on one changed region, scoped to a reference version.

    When the brand approves new artwork the reference version changes, these stop
    matching, and the findings correctly resurface for re-review.
    """

    __tablename__ = "acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    region_signature: Mapped[str] = mapped_column(String, index=True)
    reference_version_id: Mapped[int] = mapped_column(
        ForeignKey("artwork_versions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String)  # ACKNOWLEDGED | ESCALATED
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String, default="reviewer")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    __table_args__ = (
        Index("ix_ack_lookup", "region_signature", "reference_version_id"),
    )
