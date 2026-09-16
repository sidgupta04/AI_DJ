"""Persist M7 pre-rendered sessions without altering historical transitions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c401d90ef2"
down_revision = "f6a901c2d843"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dj_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("dj_sessions")
