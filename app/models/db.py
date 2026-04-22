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

    # BLAST parameters
    program: Mapped[str] = mapped_column(String(16), nullable=False)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    query_length: Mapped[int] = mapped_column(Integer, nullable=False)
    num_sequences: Mapped[int] = mapped_column(Integer, nullable=False)
    evalue: Mapped[float] = mapped_column(Float, nullable=False, default=1e-5)
    max_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    word_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outfmt: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    extra_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stored separately so we don't expose the raw FASTA in the metadata DB.
    # The query file lives at BLAST_RESULT_DIR/{id}/query.fasta
    submitter_ip: Mapped[str] = mapped_column(String(45), nullable=False)

    # Timestamps
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Outcome
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_jobs_result_expires_at", "result_expires_at"),
    )

    def extra_args(self) -> dict:
        return json.loads(self.extra_args_json) if self.extra_args_json else {}
