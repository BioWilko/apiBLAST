"""Manage per-job working directories and result files on the local filesystem."""
from pathlib import Path

from app.config import get_settings


def _job_dir(job_id: str, result_dir: Path | None = None) -> Path:
    root = result_dir or get_settings().RESULT_DIR
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


def tmp_path(job_id: str, result_dir: Path | None = None) -> Path:
    """MMseqs2 scratch directory for a job; removed when the job finishes."""
    return _job_dir(job_id, result_dir) / "tmp"


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


def cap_hits_per_query(path: Path, max_hits: int) -> None:
    """Keep only the first max_hits distinct subjects per query, in place.

    Relies on MMseqs2 output being grouped by query and sorted best-first.
    """
    subjects: dict[str, set[str]] = {}
    kept: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.split("\t", 2)
            if len(parts) < 2:
                kept.append(line)
                continue
            seen = subjects.setdefault(parts[0], set())
            if parts[1] in seen or len(seen) < max_hits:
                seen.add(parts[1])
                kept.append(line)
    tmp = path.with_suffix(".tsv.tmp")
    tmp.write_text("".join(kept), encoding="utf-8")
    tmp.replace(path)


def to_blast_strand_convention(path: Path) -> None:
    """Rewrite reverse-strand nucleotide hits to BLAST's coordinate convention, in place.

    For a minus-strand hit MMseqs2 reports the query reversed (qstart > qend)
    and the subject ascending; BLAST reports the query ascending and the subject
    reversed. Swapping both pairs describes the same alignment. Nucleotide vs
    nucleotide only: for blastx both tools report the reversed query.
    """
    out: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 12 and int(parts[6]) > int(parts[7]):
                parts[6], parts[7] = parts[7], parts[6]
                parts[8], parts[9] = parts[9], parts[8]
                line = "\t".join(parts) + "\n"
            out.append(line)
    tmp = path.with_suffix(".tsv.tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    tmp.replace(path)


def finalise_results(path: Path, program: str, max_hits: int) -> None:
    """Post-process a finished MMseqs2 result file into what the API serves."""
    cap_hits_per_query(path, max_hits)
    if program == "blastn":
        to_blast_strand_convention(path)


def parse_outfmt6(raw: str) -> list[dict]:
    """Parse 12-column tabular (BLAST outfmt 6 layout) output into a list of dicts."""
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
