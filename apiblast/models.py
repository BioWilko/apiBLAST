"""Typed dataclasses returned by BLASTClient."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BlastHit:
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
    evalue: str       # preserved as string to keep scientific notation exactly
    bitscore: float

    @classmethod
    def _from_dict(cls, d: dict) -> "BlastHit":
        return cls(
            query_id=d["query_id"],
            subject_id=d["subject_id"],
            pct_identity=d["pct_identity"],
            alignment_length=d["alignment_length"],
            mismatches=d["mismatches"],
            gap_opens=d["gap_opens"],
            q_start=d["q_start"],
            q_end=d["q_end"],
            s_start=d["s_start"],
            s_end=d["s_end"],
            evalue=d["evalue"],
            bitscore=d["bitscore"],
        )


@dataclass
class BlastResult:
    job_id: str
    num_hits: int
    hits: list[BlastHit] = field(default_factory=list)

    @classmethod
    def _from_dict(cls, d: dict) -> "BlastResult":
        return cls(
            job_id=d["job_id"],
            num_hits=d["num_hits"],
            hits=[BlastHit._from_dict(h) for h in d.get("hits", [])],
        )


@dataclass
class Job:
    id: str
    status: str
    program: str
    database: str
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    elapsed_s: float | None
    error: str | None
    result_url: str | None

    @property
    def is_done(self) -> bool:
        return self.status in {"SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"}

    @classmethod
    def _from_dict(cls, d: dict) -> "Job":
        return cls(
            id=d["job_id"],
            status=d["status"],
            program=d["program"],
            database=d["database"],
            submitted_at=d.get("submitted_at", ""),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            elapsed_s=d.get("elapsed_s"),
            error=d.get("error"),
            result_url=d.get("result_url"),
        )


@dataclass
class Database:
    name: str
    description: str
    program_types: list[str]
    path: str
    size_bytes: int
    last_updated: str | None

    @property
    def type(self) -> str:
        return "nucleotide" if "blastn" in self.program_types else "protein"

    @classmethod
    def _from_dict(cls, d: dict) -> "Database":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            program_types=d.get("program_types", []),
            path=d.get("path", ""),
            size_bytes=d.get("size_bytes", 0),
            last_updated=d.get("last_updated"),
        )
