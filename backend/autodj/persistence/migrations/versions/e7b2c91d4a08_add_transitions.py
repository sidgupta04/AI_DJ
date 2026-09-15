"""add transitions table

Revision ID: e7b2c91d4a08
Revises: 8f2c4a91d0b7
Create Date: 2026-09-14 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b2c91d4a08"
down_revision: str | None = "8f2c4a91d0b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

transition_status = sa.Enum("RENDERED", "FAILED", name="transition_status")


def upgrade() -> None:
    op.create_table(
        "transitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("track_a_id", sa.BigInteger(), nullable=False),
        sa.Column("track_b_id", sa.BigInteger(), nullable=False),
        sa.Column("session_bpm", sa.Double(), nullable=False),
        sa.Column(
            "stretch_ratio",
            sa.Double(),
            nullable=False,
            comment="session_bpm / track B native_bpm, the constant incoming stretch.",
        ),
        sa.Column("outgoing_start_beat", sa.Integer(), nullable=False),
        sa.Column("outgoing_end_beat", sa.Integer(), nullable=False),
        sa.Column("incoming_start_beat", sa.Integer(), nullable=False),
        sa.Column("incoming_end_beat", sa.Integer(), nullable=False),
        sa.Column("pair_cost", sa.Double(), nullable=False),
        sa.Column("stability_cost", sa.Double(), nullable=False),
        sa.Column("energy_cost", sa.Double(), nullable=False),
        sa.Column("stretch_cost", sa.Double(), nullable=False),
        sa.Column("position_cost", sa.Double(), nullable=False),
        sa.Column(
            "wav_path",
            sa.Text(),
            nullable=True,
            comment="Path relative to render_cache_dir when status is RENDERED.",
        ),
        sa.Column("peak_dbfs", sa.Double(), nullable=True),
        sa.Column("peak_exceeded", sa.Boolean(), nullable=False),
        sa.Column("clipped", sa.Boolean(), nullable=False),
        sa.Column("status", transition_status, nullable=False),
        sa.Column("failure_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(["track_a_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_b_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transitions_tracks", "transitions", ["track_a_id", "track_b_id"])


def downgrade() -> None:
    op.drop_index("ix_transitions_tracks", table_name="transitions")
    op.drop_table("transitions")
    transition_status.drop(op.get_bind(), checkfirst=True)
