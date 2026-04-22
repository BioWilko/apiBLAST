import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings

# IUPAC nucleotide + protein characters plus FASTA header/whitespace
_FASTA_HEADER_RE = re.compile(r"^>.*")
_NT_CHARS = re.compile(r"^[ACGTURYSWKMBDHVNacgturyswkmbdhvn\s]+$")
_AA_CHARS = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXacdefghiklmnpqrstvwyx*\s]+$")

_NT_PROGRAMS = {"blastn"}
_AA_QUERY_PROGRAMS = {"blastp", "blastx"}
_NT_QUERY_PROGRAMS = {"tblastn", "tblastx"}

# Keys that would override critical CLI flags – blocked in extra_args
_BLOCKED_ARGS = {"out", "query", "db", "num_threads", "subject", "remote"}


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    """Return list of (header, sequence) tuples from a FASTA string."""
    records: list[tuple[str, str]] = []
    header = None
    seq_parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(seq_parts)))
            header = line[1:]
            seq_parts = []
        else:
            seq_parts.append(line)
    if header is not None:
        records.append((header, "".join(seq_parts)))
    return records


# ── Request ───────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    program: Literal["blastn", "blastp", "blastx", "tblastn", "tblastx"]
    database: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    evalue: float = Field(default=1e-5, ge=0, le=10)
    max_hits: int = Field(default=50, ge=1, le=5000)
    word_size: int | None = Field(default=None, ge=2, le=28)
    outfmt: int = Field(default=6, ge=0, le=18)
    extra_args: dict[str, str | int | float] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def validate_query_fasta(cls, v: str) -> str:
        settings = get_settings()
        records = _parse_fasta(v)
        if not records:
            raise ValueError("query must contain at least one FASTA record (lines starting with '>')")
        if len(records) > settings.MAX_SEQUENCES_PER_JOB:
            raise ValueError(
                f"query contains {len(records)} sequences; maximum is {settings.MAX_SEQUENCES_PER_JOB}"
            )
        total_length = sum(len(seq) for _, seq in records)
        if total_length == 0:
            raise ValueError("query sequences are empty")
        return v

    @model_validator(mode="after")
    def validate_length_for_program(self) -> "JobCreate":
        settings = get_settings()
        records = _parse_fasta(self.query)
        total = sum(len(seq) for _, seq in records)
        if self.program in _NT_PROGRAMS or self.program in _NT_QUERY_PROGRAMS:
            # blastn queries nucleotides; tblastn/tblastx query proteins against NT db
            # For length checking: blastn = NT query, tblastn = AA query
            limit = (
                settings.MAX_QUERY_LENGTH_AA
                if self.program == "tblastn"
                else settings.MAX_QUERY_LENGTH_NT
            )
            label = "amino acids" if self.program == "tblastn" else "nucleotides"
        else:
            limit = settings.MAX_QUERY_LENGTH_AA
            label = "amino acids"
        if total > limit:
            raise ValueError(
                f"total query length {total:,} {label} exceeds maximum {limit:,}"
            )
        return self

    @field_validator("extra_args")
    @classmethod
    def block_dangerous_args(cls, v: dict) -> dict:
        for key in v:
            normalised = key.lstrip("-")
            if normalised in _BLOCKED_ARGS:
                raise ValueError(
                    f"extra_arg '{key}' is not permitted (would override a protected flag)"
                )
        return v


# ── Responses ─────────────────────────────────────────────────────────────────

class JobSubmitted(BaseModel):
    job_id: str
    status: str
    queue_pos: int
    submitted_at: datetime
    poll_url: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    program: str
    database: str
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_s: float | None
    error: str | None
    result_url: str | None


class BlastHit(BaseModel):
    query_id: str
    subject_id: str
    pct_identity: float
    alignment_length: int
    mismatches: int
    gap_opens: int
    q_start: int
    q_end: int
    s_start: int
    s_end: int
    evalue: str      # kept as string to preserve scientific notation exactly
    bitscore: float


class BlastResultResponse(BaseModel):
    job_id: str
    num_hits: int
    hits: list[BlastHit]


class DatabaseInfo(BaseModel):
    name: str
    description: str
    program_types: list[str]
    path: str
    size_bytes: int
    last_updated: datetime | None


class DatabaseListResponse(BaseModel):
    databases: list[DatabaseInfo]


class HealthResponse(BaseModel):
    status: str
    version: str


class CancelResponse(BaseModel):
    job_id: str
    cancelled: bool
