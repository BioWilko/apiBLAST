"""Manage per-job working directories and result files on the local filesystem."""
from pathlib import Path

from app.config import get_settings


def _job_dir(job_id: str, result_dir: Path | None = None) -> Path:
    root = result_dir or get_settings().BLAST_RESULT_DIR
    return root / job_id


def allocate_job_dir(job_id: str, result_dir: Path | None = None) -> Path:
    """Create and return the working directory for a job."""
    d = _job_dir(job_id, result_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def query_path(job_id: str, result_dir: Path | None = None) -> Path:
    return _job_dir(job_id, result_dir) / "query.fasta"


def result_path(job_id: str, result_dir: Path | None = None) -> Path:
    return _job_dir(job_id, result_dir) / "result.tsv"


def write_query(job_id: str, fasta_text: str, result_dir: Path | None = None) -> Path:
    """Write FASTA query to disk and return its path."""
    allocate_job_dir(job_id, result_dir)
    p = query_path(job_id, result_dir)
    p.write_text(fasta_text, encoding="utf-8")
    return p


def read_result(job_id: str, result_dir: Path | None = None) -> str | None:
    """Return the raw result file contents, or None if it no longer exists."""
    p = result_path(job_id, result_dir)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def parse_outfmt6(raw: str) -> list[dict]:
    """Parse BLAST tabular (outfmt 6) output into a list of dicts."""
    fields = [
        "query_id", "subject_id", "pct_identity", "alignment_length",
        "mismatches", "gap_opens", "q_start", "q_end",
        "s_start", "s_end", "evalue", "bitscore",
    ]
    hits = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 12:
            continue
        hits.append({
            "query_id":        parts[0],
            "subject_id":      parts[1],
            "pct_identity":    float(parts[2]),
            "alignment_length": int(parts[3]),
            "mismatches":      int(parts[4]),
            "gap_opens":       int(parts[5]),
            "q_start":         int(parts[6]),
            "q_end":           int(parts[7]),
            "s_start":         int(parts[8]),
            "s_end":           int(parts[9]),
            "evalue":          parts[10],
            "bitscore":        float(parts[11]),
        })
    return hits


def delete_job_dir(job_id: str, result_dir: Path | None = None) -> bool:
    """Remove the job's working directory. Returns True if it existed."""
    import shutil
    d = _job_dir(job_id, result_dir)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False
