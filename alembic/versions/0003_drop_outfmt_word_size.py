"""drop outfmt and word_size columns (removed in 2.0)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode recreates the table on SQLite, which cannot drop columns in place.
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("outfmt")
        batch.drop_column("word_size")


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("word_size", sa.Integer, nullable=True))
        batch.add_column(sa.Column("outfmt", sa.Integer, nullable=False, server_default="6"))
