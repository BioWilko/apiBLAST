"""Unit tests for db_scanner (config-file based)."""
import textwrap
from pathlib import Path

import pytest

from app.services.db_scanner import load_databases, database_exists


def _write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "databases.yml"
    cfg.write_text(textwrap.dedent(content))
    return cfg


def test_missing_config_returns_empty(tmp_path):
    assert load_databases(tmp_path / "nonexistent.yml") == []


def test_empty_databases_list_returns_empty(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases: []
    """)
    assert load_databases(cfg) == []


def test_no_databases_key_returns_empty(tmp_path):
    cfg = _write_config(tmp_path, "other_key: value\n")
    assert load_databases(cfg) == []


def test_nucleotide_db_program_types(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /data/blast/db/mydb
            type: nucleotide
            description: "Test nucleotide DB"
    """)
    dbs = load_databases(cfg)
    assert len(dbs) == 1
    assert dbs[0].name == "mydb"
    assert "blastn" in dbs[0].program_types
    assert "tblastn" in dbs[0].program_types
    assert "tblastx" in dbs[0].program_types
    assert "blastp" not in dbs[0].program_types
    assert "blastx" not in dbs[0].program_types


def test_protein_db_program_types(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nr
            path: /data/blast/db/nr
            type: protein
            description: "Non-redundant protein"
    """)
    dbs = load_databases(cfg)
    assert len(dbs) == 1
    assert "blastp" in dbs[0].program_types
    assert "blastx" in dbs[0].program_types
    assert "blastn" not in dbs[0].program_types


def test_description_populated(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt_small
            path: /data/blast/db/nt_small
            type: nucleotide
            description: "A small test database"
    """)
    dbs = load_databases(cfg)
    assert dbs[0].description == "A small test database"


def test_description_defaults_to_empty(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt_small
            path: /data/blast/db/nt_small
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].description == ""


def test_multiple_databases_returned(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt
            path: /data/blast/db/nt
            type: nucleotide
          - name: nr
            path: /data/blast/db/nr
            type: protein
    """)
    dbs = load_databases(cfg)
    names = {d.name for d in dbs}
    assert names == {"nt", "nr"}


def test_path_set_from_config(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /custom/location/mydb
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].path == "/custom/location/mydb"


def test_disk_stats_populated_when_files_exist(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "mydb.nhr").write_bytes(b"x" * 500)
    (db_dir / "mydb.nin").write_bytes(b"x" * 200)
    (db_dir / "mydb.nsq").write_bytes(b"x" * 1000)

    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: mydb
            path: {db_dir / "mydb"}
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].size_bytes == 1700
    assert dbs[0].last_updated is not None


def test_disk_stats_zero_when_files_absent(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: missing
            path: /data/blast/db/missing
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].size_bytes == 0
    assert dbs[0].last_updated is None


def test_database_exists_true(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /data/blast/db/mydb
            type: nucleotide
    """)
    assert database_exists("mydb", cfg) is True


def test_database_exists_false(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /data/blast/db/mydb
            type: nucleotide
    """)
    assert database_exists("other", cfg) is False


def test_database_exists_missing_config(tmp_path):
    assert database_exists("anything", tmp_path / "missing.yml") is False
