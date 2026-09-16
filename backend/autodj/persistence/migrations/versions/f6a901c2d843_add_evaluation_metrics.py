"""Add nullable M6 metrics; old mixes have not been measured."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a901c2d843"
down_revision: str | None = "e7b2c91d4a08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METRICS = (
    "bpm_delta",
    "stretch_percent_a",
    "stretch_percent_b",
    "alignment_error_ms",
    "alignment_correlation",
    "energy_discontinuity_db",
    "region_stability_a",
    "region_stability_b",
    "planning_seconds",
    "render_seconds",
    "measurement_seconds",
)


def upgrade() -> None:
    op.add_column("transitions", sa.Column("strategy", sa.Text(), nullable=True))
    op.add_column("transitions", sa.Column("evaluation", postgresql.JSONB(), nullable=True))
    for name in METRICS:
        op.add_column("transitions", sa.Column(name, sa.Double(), nullable=True))


def downgrade() -> None:
    for name in reversed((*METRICS, "evaluation", "strategy")):
        op.drop_column("transitions", name)
