"""add priority_tokens table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "priority_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("priority_tokens")
