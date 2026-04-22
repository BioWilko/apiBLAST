"""Build and validate BLAST+ CLI commands.

num_threads is intentionally hardcoded to 1. BLAST's threading only covers
the word-matching phase and provides minimal benefit for short queries. Celery
manages parallelism at the process level across multiple workers instead.
"""
import json
import subprocess
from pathlib import Path

from app.config import get_settings
from app.models.db import Job

_BLAST_PROGRAMS = {"blastn", "blastp", "blastx", "tblastn", "tblastx"}


def build_blast_command(job: Job, query_file: Path, result_file: Path) -> list[str]:
    """Return a safe, shell=False command list for running BLAST+.

    Raises ValueError if the program is unrecognised or the binary is not found.
    """
    settings = get_settings()

    if job.program not in _BLAST_PROGRAMS:
        raise ValueError(f"Unknown BLAST program: {job.program!r}")

    binary = settings.BLAST_BIN_DIR / job.program
    if not binary.exists():
        raise FileNotFoundError(
            f"BLAST binary not found: {binary}. Check BLAST_BIN_DIR setting."
        )

    cmd: list[str] = [
        str(binary),
        "-db",              str(settings.BLAST_DB_DIR / job.database),
        "-query",           str(query_file),
        "-out",             str(result_file),
        "-evalue",          str(job.evalue),
        "-max_target_seqs", str(job.max_hits),
        "-num_threads",     "1",   # hardcoded — see module docstring
        "-outfmt",          str(job.outfmt),
    ]

    if job.word_size is not None:
        cmd += ["-word_size", str(job.word_size)]

    extra = json.loads(job.extra_args_json) if job.extra_args_json else {}
    for key, val in extra.items():
        cmd += [f"-{key.lstrip('-')}", str(val)]

    return cmd


def run_blast(
    cmd: list[str],
    timeout_s: int | None = None,
) -> subprocess.CompletedProcess:
    """Execute a BLAST command and return the CompletedProcess result.

    Raises subprocess.TimeoutExpired if timeout_s is exceeded.
    Raises FileNotFoundError if the binary path is wrong.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
