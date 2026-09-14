"""add energy curve and stable regions

Revision ID: 8f2c4a91d0b7
Revises: b3e91c07f2a1
Create Date: 2026-09-14 15:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8f2c4a91d0b7"
down_revision: str | None = "b3e91c07f2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column(
            "energy",
            sa.Double(),
            nullable=True,
            comment=(
                "Library-normalized aggregated energy in [0, 1] "
                "(5th/95th of per-track scalars). Null until analysis completes."
            ),
        ),
    )
    op.add_column(
        "track_analysis",
        sa.Column(
            "energy_curve",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Combined energy E(t) at energy_curve_hz, each sample in [0, 1].",
        ),
    )
    op.add_column(
        "track_analysis",
        sa.Column(
            "energy_curve_hz",
            sa.Double(),
            nullable=False,
            server_default="10.0",
        ),
    )
    op.add_column(
        "track_analysis",
        sa.Column(
            "energy_scalar",
            sa.Double(),
            nullable=False,
            server_default="0.0",
            comment="Per-track aggregation of energy_curve, before library-wide scaling.",
        ),
    )
    op.add_column(
        "track_analysis",
        sa.Column(
            "stable_regions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Non-overlapping mixable windows (beat indices, times, scores).",
        ),
    )
    op.alter_column("track_analysis", "energy_curve", server_default=None)
    op.alter_column("track_analysis", "energy_curve_hz", server_default=None)
    op.alter_column("track_analysis", "energy_scalar", server_default=None)
    op.alter_column("track_analysis", "stable_regions", server_default=None)


def downgrade() -> None:
    op.drop_column("track_analysis", "stable_regions")
    op.drop_column("track_analysis", "energy_scalar")
    op.drop_column("track_analysis", "energy_curve_hz")
    op.drop_column("track_analysis", "energy_curve")
    op.drop_column("tracks", "energy")
