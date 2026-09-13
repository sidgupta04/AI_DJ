"""add track analysis

Revision ID: b3e91c07f2a1
Revises: 090c18ae2a40
Create Date: 2026-09-12 23:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3e91c07f2a1"
down_revision: str | None = "090c18ae2a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column(
            "native_bpm",
            sa.Double(),
            nullable=True,
            comment="Median-IBI tempo of the chosen beat grid. Null until analysis completes.",
        ),
    )
    op.add_column(
        "tracks",
        sa.Column(
            "analysis_confidence",
            sa.Double(),
            nullable=True,
            comment=(
                "Heuristic beat-grid quality in [0, 1] "
                "(tempo_regularity * onset_contrast). Not a probability of correctness."
            ),
        ),
    )
    op.add_column(
        "tracks",
        sa.Column(
            "analysis_version",
            sa.Integer(),
            nullable=True,
            comment="Feature-format version that produced native_bpm and the beat grid.",
        ),
    )
    op.create_table(
        "track_analysis",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "beat_times",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Refined beat timestamps in seconds from the start of the file.",
        ),
        sa.Column("beat_count", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("hop_length", sa.Integer(), nullable=False),
        sa.Column("refine_hop_length", sa.Integer(), nullable=False),
        sa.Column("median_ibi_seconds", sa.Double(), nullable=False),
        sa.Column("ibi_cv", sa.Double(), nullable=False),
        sa.Column("onset_contrast", sa.Double(), nullable=False),
        sa.Column(
            "tempo_octave_factor",
            sa.Double(),
            nullable=False,
            comment="0.5, 1.0 or 2.0: which octave of the raw librosa grid was kept.",
        ),
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
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id"),
    )


def downgrade() -> None:
    op.drop_table("track_analysis")
    op.drop_column("tracks", "analysis_version")
    op.drop_column("tracks", "analysis_confidence")
    op.drop_column("tracks", "native_bpm")
