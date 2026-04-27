"""convert datetime columns to timestamptz

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_TZ_COLS = ["submitted_at", "started_at", "finished_at", "result_expires_at"]


def upgrade() -> None:
    for col in _TZ_COLS:
        op.alter_column(
            "jobs",
            col,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for col in _TZ_COLS:
        op.alter_column(
            "jobs",
            col,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{col} AT TIME ZONE 'UTC'",
        )
