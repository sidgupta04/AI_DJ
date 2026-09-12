"""SQLAlchemy models.

Tables are introduced by the milestone that needs them, each with its own Alembic revision, so
the schema and the code that uses it always land together.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    Enum,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from autodj.audio.naming import MetadataSource


class Base(DeclarativeBase):
    pass


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class Track(Base):
    """A library file and what is known about it before analysis runs.

    ``audio_path`` is relative to the configured library directory so the root can move without
    invalidating rows. Audio itself never lives in the database.

    Identity is the path, not the audio. ``audio_path`` is unique; ``content_hash`` is
    deliberately not, so the same recording filed under two paths is two tracks. See
    ``docs/architecture.md`` for why.
    """

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    audio_path: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
        comment="Library-relative path. The identity of a track; one row per file.",
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "SHA-256 of the file bytes, used only to detect changed files across rescans. "
            "Not unique: duplicate audio at two paths is two tracks."
        ),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    artist: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_source: Mapped[MetadataSource] = mapped_column(
        Enum(
            MetadataSource, name="metadata_source", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
    )

    duration_seconds: Mapped[float | None] = mapped_column(Double, nullable=True)
    native_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    codec_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    bit_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    analysis_status: Mapped[AnalysisStatus] = mapped_column(
        Enum(
            AnalysisStatus,
            name="analysis_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )
    failure_reason: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_tracks_content_hash", "content_hash"),
        Index("ix_tracks_analysis_status", "analysis_status"),
    )

    def __repr__(self) -> str:
        return (
            f"Track(id={self.id!r}, audio_path={self.audio_path!r}, status={self.analysis_status})"
        )
