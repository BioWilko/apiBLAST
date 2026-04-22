"""Unit tests for Pydantic request/response schemas."""
import pytest
from pydantic import ValidationError
from unittest.mock import patch

from app.models.schemas import JobCreate

VALID_NT_QUERY = ">seq1\nATGCATGCATGCATGC\n"
VALID_AA_QUERY = ">prot1\nMKTLLLTLVVVTIVSA\n"


def _make_job(**kwargs) -> JobCreate:
    defaults = dict(program="blastn", database="testdb", query=VALID_NT_QUERY)
    defaults.update(kwargs)
    return JobCreate(**defaults)


# ── Program validation ─────────────────────────────────────────────────────────

def test_valid_programs_accepted():
    for prog in ("blastn", "blastp", "blastx", "tblastn", "tblastx"):
        query = VALID_AA_QUERY if prog in ("blastp", "tblastn") else VALID_NT_QUERY
        job = _make_job(program=prog, query=query)
        assert job.program == prog


def test_invalid_program_rejected():
    with pytest.raises(ValidationError, match="program"):
        _make_job(program="megablast")


# ── Query FASTA validation ─────────────────────────────────────────────────────

def test_empty_query_rejected():
    with pytest.raises(ValidationError):
        _make_job(query="")


def test_query_without_header_rejected():
    with pytest.raises(ValidationError, match="FASTA"):
        _make_job(query="ATGCATGC")


def test_query_with_header_accepted():
    job = _make_job(query=">seq1\nATGCATGC")
    assert job.query.startswith(">")


def test_too_many_sequences_rejected():
    many = "".join(f">seq{i}\nATGC\n" for i in range(200))
    with pytest.raises(ValidationError, match="sequences"):
        _make_job(query=many)


def test_oversized_nt_query_rejected():
    big_seq = "A" * 600_000
    query = f">big\n{big_seq}"
    with pytest.raises(ValidationError, match="nucleotides"):
        _make_job(program="blastn", query=query)


def test_oversized_aa_query_rejected():
    big_seq = "M" * 200_000
    query = f">big\n{big_seq}"
    with pytest.raises(ValidationError, match="amino acids"):
        _make_job(program="blastp", query=query)


# ── extra_args validation ──────────────────────────────────────────────────────

def test_blocked_out_arg_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        _make_job(extra_args={"out": "/etc/passwd"})


def test_blocked_num_threads_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        _make_job(extra_args={"num_threads": 8})


def test_blocked_db_arg_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        _make_job(extra_args={"db": "/other/db"})


def test_safe_extra_args_accepted():
    job = _make_job(extra_args={"dust": "no", "perc_identity": 90})
    assert job.extra_args["dust"] == "no"


# ── outfmt / evalue / max_hits ─────────────────────────────────────────────────

def test_outfmt_range():
    _make_job(outfmt=0)
    _make_job(outfmt=18)
    with pytest.raises(ValidationError):
        _make_job(outfmt=19)
    with pytest.raises(ValidationError):
        _make_job(outfmt=-1)


def test_evalue_range():
    _make_job(evalue=0)
    _make_job(evalue=10)
    with pytest.raises(ValidationError):
        _make_job(evalue=-0.1)
    with pytest.raises(ValidationError):
        _make_job(evalue=10.1)


def test_max_hits_range():
    _make_job(max_hits=1)
    _make_job(max_hits=5000)
    with pytest.raises(ValidationError):
        _make_job(max_hits=0)
    with pytest.raises(ValidationError):
        _make_job(max_hits=5001)
