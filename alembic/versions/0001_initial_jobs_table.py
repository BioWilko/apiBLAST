"""initial jobs table

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("celery_task_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("program", sa.String(16), nullable=False),
        sa.Column("database", sa.String(128), nullable=False),
        sa.Column("query_length", sa.Integer, nullable=False),
        sa.Column("num_sequences", sa.Integer, nullable=False),
        sa.Column("evalue", sa.Float, nullable=False, server_default="1e-5"),
        sa.Column("max_hits", sa.Integer, nullable=False, server_default="50"),
        sa.Column("word_size", sa.Integer, nullable=True),
        sa.Column("outfmt", sa.Integer, nullable=False, server_default="6"),
        sa.Column("extra_args_json", sa.Text, nullable=True),
        sa.Column("submitter_ip", sa.String(45), nullable=False),
        sa.Column("submitted_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("result_path", sa.Text, nullable=True),
        sa.Column("result_expires_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_jobs_celery_task_id", "jobs", ["celery_task_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_result_expires_at", "jobs", ["result_expires_at"])


def downgrade() -> None:
    op.drop_table("jobs")
