"""create tracks table

Revision ID: 090c18ae2a40
Revises:
Create Date: 2026-09-12 19:24:38.753134

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "090c18ae2a40"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

analysis_status = sa.Enum("PENDING", "PROCESSING", "COMPLETE", "FAILED", name="analysis_status")
metadata_source = sa.Enum("tags", "filename", "mixed", name="metadata_source")


def upgrade() -> None:
    op.create_table(
        "tracks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "audio_path",
            sa.Text(),
            nullable=False,
            comment="Library-relative path. The identity of a track; one row per file.",
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
            comment=(
                "SHA-256 of the file bytes, used only to detect changed files across rescans. "
                "Not unique: duplicate audio at two paths is two tracks."
            ),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("artist", sa.Text(), nullable=True),
        sa.Column("metadata_source", metadata_source, nullable=False),
        sa.Column("duration_seconds", sa.Double(), nullable=True),
        sa.Column("native_sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.SmallInteger(), nullable=True),
        sa.Column("codec_name", sa.Text(), nullable=True),
        sa.Column("bit_rate", sa.Integer(), nullable=True),
        sa.Column("analysis_status", analysis_status, nullable=False),
        sa.Column("failure_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audio_path"),
    )
    op.create_index("ix_tracks_analysis_status", "tracks", ["analysis_status"], unique=False)
    op.create_index("ix_tracks_content_hash", "tracks", ["content_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tracks_content_hash", table_name="tracks")
    op.drop_index("ix_tracks_analysis_status", table_name="tracks")
    op.drop_table("tracks")
    # create_table creates these types, so the downgrade has to remove them or a later
    # upgrade fails with "type already exists".
    analysis_status.drop(op.get_bind(), checkfirst=True)
    metadata_source.drop(op.get_bind(), checkfirst=True)
