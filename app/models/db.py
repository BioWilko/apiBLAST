import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    celery_task_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)

    # Status: PENDING | RUNNING | SUCCESS | FAILURE | REVOKED | TIMEOUT
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", index=True)

    # Search parameters
    program: Mapped[str] = mapped_column(String(16), nullable=False)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    query_length: Mapped[int] = mapped_column(Integer, nullable=False)
    num_sequences: Mapped[int] = mapped_column(Integer, nullable=False)
    evalue: Mapped[float] = mapped_column(Float, nullable=False, default=1e-5)
    max_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    extra_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stored separately so we don't expose the raw FASTA in the metadata DB.
    # The query file lives at RESULT_DIR/{id}/query.fasta
    submitter_ip: Mapped[str] = mapped_column(String(45), nullable=False)

    # Timestamps — stored as TIMESTAMPTZ (timezone=True) so Postgres preserves UTC offset
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Outcome
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_jobs_result_expires_at", "result_expires_at"),
    )

    def extra_args(self) -> dict:
        return json.loads(self.extra_args_json) if self.extra_args_json else {}


class PriorityToken(Base):
    """A token that exempts its holder from rate limits and deprioritisation.

    Only the SHA-256 hash of the token is stored; see app.services.tokens.
    """

    __tablename__ = "priority_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # Leading characters of the raw token, to identify it in listings
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
