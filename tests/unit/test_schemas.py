"""Unit tests for Pydantic request/response schemas."""
import pytest
from pydantic import ValidationError
from unittest.mock import patch

from app.models.schemas import JobCreate, query_type_of, resolve_program

VALID_NT_QUERY = ">seq1\nATGCATGCATGCATGC\n"
VALID_AA_QUERY = ">prot1\nMKTLLLTLVVVTIVSA\n"


def _make_job(**kwargs) -> JobCreate:
    defaults = dict(query_type="nucleotide", database="testdb", query=VALID_NT_QUERY)
    defaults.update(kwargs)
    return JobCreate(**defaults)


# ── Query type validation ──────────────────────────────────────────────────────

def test_valid_query_types_accepted():
    for query_type, query in (("nucleotide", VALID_NT_QUERY), ("protein", VALID_AA_QUERY)):
        job = _make_job(query_type=query_type, query=query)
        assert job.query_type == query_type


@pytest.mark.parametrize("query_type", ["blastn", "dna", ""])
def test_invalid_query_type_rejected(query_type):
    with pytest.raises(ValidationError, match="query_type"):
        _make_job(query_type=query_type)


@pytest.mark.parametrize("query_type,db_type,program", [
    ("nucleotide", "nucleotide", "blastn"),
    ("protein", "protein", "blastp"),
    ("nucleotide", "protein", "blastx"),
    ("protein", "nucleotide", None),
])
def test_resolve_program(query_type, db_type, program):
    assert resolve_program(query_type, db_type) == program


@pytest.mark.parametrize("program,query_type", [
    ("blastn", "nucleotide"), ("blastp", "protein"), ("blastx", "nucleotide"),
])
def test_query_type_of(program, query_type):
    assert query_type_of(program) == query_type


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
        _make_job(query_type="nucleotide", query=query)


def test_nucleotide_query_uses_nucleotide_length_limit():
    query = f">big\n{'A' * 200_000}"
    job = _make_job(query_type="nucleotide", query=query)
    assert job.query_type == "nucleotide"


def test_oversized_aa_query_rejected():
    big_seq = "M" * 200_000
    query = f">big\n{big_seq}"
    with pytest.raises(ValidationError, match="amino acids"):
        _make_job(query_type="protein", query=query)


# ── extra_args validation ──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["mpi-runner", "threads", "gpu", "alt-ali", "format-output", "out"])
def test_unlisted_args_rejected(key):
    with pytest.raises(ValidationError, match="not permitted"):
        _make_job(extra_args={key: 1})


def test_allowed_args_accepted_and_normalised():
    job = _make_job(extra_args={"--min-seq-id": 0.9, "c": 0.8, "cov-mode": 1, "s": 7.5})
    assert job.extra_args == {"min-seq-id": 0.9, "c": 0.8, "cov-mode": 1, "s": 7.5}


def test_non_numeric_arg_value_rejected():
    with pytest.raises(ValidationError, match="must be a number"):
        _make_job(extra_args={"s": "7.5 --mpi-runner sh"})


def test_translation_args_accepted():
    job = _make_job(extra_args={"translation-mode": 0, "translation-table": 11})
    assert job.extra_args["translation-table"] == 11


def test_invalid_translation_mode_rejected():
    with pytest.raises(ValidationError, match="translation-mode"):
        _make_job(extra_args={"translation-mode": 2})


@pytest.mark.parametrize("table", [7, 8, 17, 32])
def test_invalid_translation_table_rejected(table):
    with pytest.raises(ValidationError, match="genetic code"):
        _make_job(extra_args={"translation-table": table})


# ── Fields removed in 2.0 ──────────────────────────────────────────────────────

def test_legacy_defaults_dropped():
    job = _make_job(outfmt=6, word_size=None)
    assert "outfmt" not in job.model_dump()
    assert "word_size" not in job.model_dump()


@pytest.mark.parametrize("field,value", [("outfmt", 5), ("word_size", 11)])
def test_legacy_non_default_values_rejected(field, value):
    with pytest.raises(ValidationError, match="removed in apiBLAST 2.0"):
        _make_job(**{field: value})


def test_unknown_field_rejected():
    with pytest.raises(ValidationError, match="max_hit"):
        _make_job(max_hit=10)


# ── evalue / max_hits ──────────────────────────────────────────────────────────

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
