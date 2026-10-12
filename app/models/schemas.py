import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings

# IUPAC nucleotide + protein characters plus FASTA header/whitespace
_FASTA_HEADER_RE = re.compile(r"^>.*")
_NT_CHARS = re.compile(r"^[ACGTURYSWKMBDHVNacgturyswkmbdhvn\s]+$")
_AA_CHARS = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXacdefghiklmnpqrstvwyx*\s]+$")

MoleculeType = Literal["nucleotide", "protein"]

# Internal search programs, chosen from the query and database molecule types.
PROGRAMS = ("blastn", "blastp", "blastx")
# Routed to the blast_gpu queue when MMSEQS_GPU_ENABLED is set. MMseqs2 has no
# GPU path for nucleotide searches.
GPU_PROGRAMS = {"blastp", "blastx"}
# (query, database) → program. Protein queries against a nucleotide database
# are missing: they would need the target DB translated.
_PROGRAM_FOR = {
    ("nucleotide", "nucleotide"): "blastn",
    ("protein", "protein"): "blastp",
    ("nucleotide", "protein"): "blastx",
}

# MMseqs2 options accepted in extra_args; anything else is rejected.
ALLOWED_ARGS = {"min-seq-id", "c", "cov-mode", "s", "translation-mode", "translation-table"}
# GPU searches always run at maximum sensitivity
CPU_ONLY_ARGS = {"s"}
BLASTX_ARGS = {"translation-mode", "translation-table"}
TRANSLATION_TABLES = {*range(1, 7), *range(9, 17), *range(21, 32)}

# Fields removed in 2.0 → the 1.x client default, which is dropped silently.
# Any other value is rejected.
_REMOVED_FIELDS = {"outfmt": 6, "word_size": None}


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
    model_config = ConfigDict(extra="forbid")

    query_type: MoleculeType
    database: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    evalue: float = Field(default=1e-5, ge=0, le=10)
    max_hits: int = Field(default=50, ge=1, le=5000)
    extra_args: dict[str, str | int | float] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def drop_removed_fields(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for field, legacy_default in _REMOVED_FIELDS.items():
            if field not in data:
                continue
            if data[field] != legacy_default:
                raise ValueError(f"'{field}' was removed in apiBLAST 2.0")
            del data[field]
        return data

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
    def validate_query_length(self) -> "JobCreate":
        settings = get_settings()
        records = _parse_fasta(self.query)
        total = sum(len(seq) for _, seq in records)
        if self.query_type == "nucleotide":
            limit = settings.MAX_QUERY_LENGTH_NT
            label = "nucleotides"
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
    def allow_listed_args(cls, v: dict) -> dict:
        normalised: dict[str, str | int | float] = {}
        for key, val in v.items():
            name = key.lstrip("-")
            if name not in ALLOWED_ARGS:
                allowed = ", ".join(sorted(ALLOWED_ARGS))
                raise ValueError(f"extra_arg '{key}' is not permitted; allowed: {allowed}")
            if isinstance(val, bool) or not _is_number(val):
                raise ValueError(f"extra_arg '{key}' must be a number")
            normalised[name] = val
        mode = normalised.get("translation-mode")
        if mode is not None and str(mode) not in ("0", "1"):
            raise ValueError("extra_arg 'translation-mode' must be 0 (ORFs) or 1 (full frames)")
        if "translation-table" in normalised and not _is_table(normalised["translation-table"]):
            raise ValueError("extra_arg 'translation-table' is not a valid genetic code table")
        return normalised


def resolve_program(query_type: str, db_type: str) -> str | None:
    """Return the search program for a query against a database, or None if unsupported."""
    return _PROGRAM_FOR.get((query_type, db_type))


def query_type_of(program: str) -> MoleculeType:
    """Return the query molecule type a program searches with."""
    return "protein" if program == "blastp" else "nucleotide"


def _is_number(val) -> bool:
    try:
        float(val)
    except (TypeError, ValueError):
        return False
    return True


def _is_table(val) -> bool:
    try:
        return int(str(val)) in TRANSLATION_TABLES
    except ValueError:
        return False


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
    query_type: MoleculeType
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
    molecule_type: MoleculeType
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
