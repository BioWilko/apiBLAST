"""Unit tests for client-side query file reading and error formatting."""
import gzip

import pytest

from apiblast.client import _format_detail, read_query_file
from apiblast.exceptions import QueryFileError

FASTA = ">s1\nACGT\n>s2\nGGCC\n"


def test_reads_plain_text(tmp_path):
    f = tmp_path / "q.fa"
    f.write_text(FASTA)
    assert read_query_file(f) == FASTA


def test_reads_gzip_regardless_of_extension(tmp_path):
    f = tmp_path / "q.fa"  # no .gz suffix: detected from the magic bytes
    f.write_bytes(gzip.compress(FASTA.encode()))
    assert read_query_file(f) == FASTA


def test_too_large_plain_file(tmp_path):
    f = tmp_path / "q.fa"
    f.write_text(">s\n" + "A" * 200)
    with pytest.raises(QueryFileError, match="larger than"):
        read_query_file(f, max_bytes=100)


def test_too_large_after_decompression(tmp_path):
    f = tmp_path / "q.fa.gz"
    f.write_bytes(gzip.compress((">s\n" + "A" * 10_000).encode()))
    assert f.stat().st_size < 100
    with pytest.raises(QueryFileError, match="uncompressed"):
        read_query_file(f, max_bytes=1000)


def test_binary_file(tmp_path):
    f = tmp_path / "q.bin"
    f.write_bytes(bytes(range(256)))
    with pytest.raises(QueryFileError, match="not a text FASTA file"):
        read_query_file(f)


def test_corrupt_gzip(tmp_path):
    f = tmp_path / "q.fa.gz"
    f.write_bytes(gzip.compress(FASTA.encode())[:10])
    with pytest.raises(QueryFileError, match="gzipped"):
        read_query_file(f)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_query_file(tmp_path / "missing.fa")


def test_format_detail_validation_errors():
    detail = [
        {"type": "value_error", "loc": ["body"], "msg": "Value error, query too long"},
        {"type": "greater_than_equal", "loc": ["body", "max_hits"], "msg": "Input should be >= 1"},
    ]
    assert _format_detail(detail) == "query too long; max_hits: Input should be >= 1"


def test_format_detail_string_passthrough():
    assert _format_detail("Job not found") == "Job not found"
