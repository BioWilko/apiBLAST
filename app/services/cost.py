"""Estimate the relative CPU cost of a search, used to deprioritise heavy jobs."""
from app.config import get_settings

# Work per query residue relative to blastp: blastn searches both strands,
# blastx searches six frames of L/3 residues.
_PROGRAM_FACTOR = {"blastn": 2.0, "blastp": 1.0, "blastx": 2.0}
_DEFAULT_SENSITIVITY = 5.7
# MMseqs2 prefilter width; the runner passes --max-seqs max(max_hits, 300)
_MIN_MAX_SEQS = 300
# Floor so tiny databases (or ones whose size could not be read) still cost something
_MIN_DB_GB = 0.1


def estimate_cost(
    program: str,
    query_length: int,
    db_size_bytes: int,
    max_hits: int,
    extra_args: dict,
) -> float:
    """Return a unitless cost score for a CPU search.

    Roughly query kilo-residues × target database gigabytes, scaled by the
    program, sensitivity and prefilter width. Only meaningful relative to
    ``COST_HEAVY_THRESHOLD``.

    Args:
        program: blastn, blastp or blastx.
        query_length: Total residues across all query sequences.
        db_size_bytes: On-disk size of the target database.
        max_hits: Requested maximum hits per query.
        extra_args: Validated MMseqs2 options; only ``s`` is used.

    Returns:
        The estimated cost.
    """
    sensitivity = float(extra_args.get("s", _DEFAULT_SENSITIVITY))
    return (
        _PROGRAM_FACTOR[program]
        * (query_length / 1000)
        * max(db_size_bytes / 1e9, _MIN_DB_GB)
        * (sensitivity / _DEFAULT_SENSITIVITY) ** 2
        * max(max_hits, _MIN_MAX_SEQS) / _MIN_MAX_SEQS
    )


def is_heavy(cost: float) -> bool:
    """Return True if a job of this cost should be deprioritised."""
    return cost >= get_settings().COST_HEAVY_THRESHOLD
