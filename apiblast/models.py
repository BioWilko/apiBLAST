"""Typed dataclasses returned by BLASTClient."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BlastHit:
    """A single alignment hit in BLAST tabular (outfmt 6) layout.

    Corresponds to one row in BLAST's tabular output. The ``evalue`` field is
    stored as a string to preserve scientific notation exactly as returned by
    the server (e.g. ``"1.2e-45"``).

    Attributes:
        query_id: Identifier of the query sequence.
        subject_id: Identifier of the database subject sequence.
        pct_identity: Percentage of identical positions in the alignment.
        alignment_length: Total length of the alignment, including gaps.
        mismatches: Number of mismatched positions.
        gap_opens: Number of gap openings.
        q_start: Start position in the query sequence (1-based).
        q_end: End position in the query sequence (1-based).
        s_start: Start position in the subject sequence (1-based).
        s_end: End position in the subject sequence (1-based).
        evalue: Expect value as a string (e.g. ``"1.2e-45"``).
        bitscore: Bit score of the alignment.

    Example:
        >>> from apiblast import BLASTClient
        >>> with BLASTClient("http://blast-server:8000") as client:
        ...     result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")
        ...     for hit in result.hits:
        ...         print(f"{hit.subject_id}: {hit.pct_identity:.1f}% identity, e={hit.evalue}")
    """

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
    """Parsed results for a completed BLAST job.

    Returned by :meth:`~apiblast.BLASTClient.results` and
    :meth:`~apiblast.BLASTClient.blast`. Contains all alignment hits parsed
    from the server's JSON response.

    Attributes:
        job_id: The unique identifier of the job that produced these results.
        num_hits: Total number of hits found (may be capped by ``max_hits``).
        hits: List of :class:`BlastHit` objects, one per alignment row.

    Example:
        >>> from apiblast import BLASTClient
        >>> with BLASTClient("http://blast-server:8000") as client:
        ...     result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")
        ...     print(f"Found {result.num_hits} hits for job {result.job_id}")
        ...     if result.hits:
        ...         best = min(result.hits, key=lambda h: float(h.evalue))
        ...         print(f"Best hit: {best.subject_id} (e={best.evalue})")
    """

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
    """Metadata and current status for a BLAST job.

    Returned by :meth:`~apiblast.BLASTClient.submit`,
    :meth:`~apiblast.BLASTClient.status`, and
    :meth:`~apiblast.BLASTClient.wait`. Reflects the server-side job record
    at the time the request was made.

    Attributes:
        id: Unique job identifier (UUID string).
        status: Current job status. One of ``PENDING``, ``STARTED``,
            ``SUCCESS``, ``FAILURE``, ``TIMEOUT``, or ``REVOKED``.
        program: BLAST program used (e.g. ``"blastn"``).
        database: Name of the target database.
        submitted_at: ISO 8601 timestamp when the job was queued.
        started_at: ISO 8601 timestamp when execution began, or ``None`` if
            the job has not yet started.
        finished_at: ISO 8601 timestamp when the job finished, or ``None`` if
            it is still running.
        elapsed_s: Wall-clock execution time in seconds, or ``None`` if the
            job has not finished.
        error: Error message from a failed job, or ``None``.
        result_url: Relative URL to retrieve results, or ``None`` if results
            are not yet available.

    Example:
        >>> from apiblast import BLASTClient
        >>> with BLASTClient("http://blast-server:8000") as client:
        ...     job = client.submit("blastn", "nt_small", ">seq1\\nATGCATGC")
        ...     print(f"Job {job.id} queued with status {job.status}")
        ...     job = client.wait(job.id)
        ...     if job.elapsed_s is not None:
        ...         print(f"Completed in {job.elapsed_s:.1f}s")
    """

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
        """Whether the job has reached a terminal state.

        Returns:
            True if status is ``SUCCESS``, ``FAILURE``, ``TIMEOUT``, or
            ``REVOKED``; False if the job is still ``PENDING`` or ``STARTED``.
        """
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
    """Metadata for a database available on the server.

    Returned as elements of the list from
    :meth:`~apiblast.BLASTClient.databases`.

    Attributes:
        name: Unique database identifier used when submitting jobs.
        description: Human-readable description of the database contents.
        program_types: Programs compatible with this database:
            ``["blastn"]`` for a nucleotide database, ``["blastp", "blastx"]``
            for a protein database.
        path: Absolute path to the database files on the server.
        size_bytes: Total size of the database files in bytes.
        last_updated: ISO 8601 timestamp of the last database update, or
            ``None`` if unknown.

    Example:
        >>> from apiblast import BLASTClient
        >>> with BLASTClient("http://blast-server:8000") as client:
        ...     for db in client.databases():
        ...         size_gb = db.size_bytes / 1e9
        ...         print(f"{db.name} ({db.type}, {size_gb:.1f} GB): {db.description}")
    """

    name: str
    description: str
    program_types: list[str]
    path: str
    size_bytes: int
    last_updated: str | None

    @property
    def type(self) -> str:
        """Molecule type inferred from compatible programs.

        Returns:
            ``"nucleotide"`` if ``"blastn"`` is in :attr:`program_types`,
            otherwise ``"protein"``.
        """
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
