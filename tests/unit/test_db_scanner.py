"""Unit tests for db_scanner (config-file based)."""
import logging
import textwrap
from pathlib import Path

from app.services import db_scanner
from app.services.db_scanner import database_exists, get_database, load_databases


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
            path: /data/db/mydb
            type: nucleotide
            description: "Test nucleotide DB"
    """)
    dbs = load_databases(cfg)
    assert len(dbs) == 1
    assert dbs[0].name == "mydb"
    assert dbs[0].program_types == ["blastn"]


def test_protein_db_program_types(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nr
            path: /data/db/nr
            type: protein
            description: "Non-redundant protein"
    """)
    dbs = load_databases(cfg)
    assert len(dbs) == 1
    assert dbs[0].program_types == ["blastp", "blastx"]


def test_description_populated(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt_small
            path: /data/db/nt_small
            type: nucleotide
            description: "A small test database"
    """)
    dbs = load_databases(cfg)
    assert dbs[0].description == "A small test database"


def test_description_defaults_to_empty(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt_small
            path: /data/db/nt_small
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].description == ""


def test_multiple_databases_returned(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nt
            path: /data/db/nt
            type: nucleotide
          - name: nr
            path: /data/db/nr
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
    (db_dir / "mydb").write_bytes(b"x" * 1000)
    (db_dir / "mydb.index").write_bytes(b"x" * 200)
    (db_dir / "mydb.dbtype").write_bytes(b"x" * 4)
    (db_dir / "mydb_h").write_bytes(b"x" * 500)
    (db_dir / "mydb_h.index").write_bytes(b"x" * 50)
    (db_dir / "mydb.idx").write_bytes(b"x" * 3000)
    # Another database sharing the name prefix is not counted
    (db_dir / "mydb_human").write_bytes(b"x" * 9999)
    (db_dir / "mydb2.index").write_bytes(b"x" * 9999)

    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: mydb
            path: {db_dir}
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].size_bytes == 4754
    assert dbs[0].last_updated is not None


def test_unindexed_nucleotide_db_warns_once(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(db_scanner, "_reported", set())
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "nt").write_bytes(b"x" * 100)
    (db_dir / "nt.dbtype").write_bytes(b"x" * 4)
    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: nt
            path: {db_dir}
            type: nucleotide
    """)
    with caplog.at_level(logging.WARNING, logger="app.services.db_scanner"):
        load_databases(cfg)
        load_databases(cfg)
    warnings = [r for r in caplog.records if "no precomputed index" in r.message]
    assert len(warnings) == 1


def test_indexed_nucleotide_db_does_not_warn(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(db_scanner, "_reported", set())
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "nt").write_bytes(b"x" * 100)
    (db_dir / "nt.dbtype").write_bytes(b"x" * 4)
    (db_dir / "nt.idx").write_bytes(b"x" * 100)
    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: nt
            path: {db_dir}
            type: nucleotide
    """)
    with caplog.at_level(logging.WARNING, logger="app.services.db_scanner"):
        load_databases(cfg)
    assert not [r for r in caplog.records if "no precomputed index" in r.message]


def test_disk_stats_zero_when_files_absent(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: missing
            path: /data/db/missing
            type: nucleotide
    """)
    dbs = load_databases(cfg)
    assert dbs[0].size_bytes == 0
    assert dbs[0].last_updated is None


def test_database_exists_true(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /data/db/mydb
            type: nucleotide
    """)
    assert database_exists("mydb", cfg) is True


def test_database_exists_false(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: mydb
            path: /data/db/mydb
            type: nucleotide
    """)
    assert database_exists("other", cfg) is False


def test_database_exists_missing_config(tmp_path):
    assert database_exists("anything", tmp_path / "missing.yml") is False


def test_blast_database_reported(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(db_scanner, "_reported", set())
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    for ext in ("00.nsq", "00.nin", "00.nhr", "nal"):
        (db_dir / f"nt.{ext}").write_bytes(b"x")
    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: nt
            path: {db_dir}
            type: nucleotide
    """)
    with caplog.at_level(logging.ERROR, logger="app.services.db_scanner"):
        load_databases(cfg)
    assert any("is a BLAST database" in r.message for r in caplog.records)


def test_missing_mmseqs_database_reported(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(db_scanner, "_reported", set())
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    cfg = _write_config(tmp_path, f"""\
        databases:
          - name: swissprot
            path: {db_dir}
            type: protein
    """)
    with caplog.at_level(logging.ERROR, logger="app.services.db_scanner"):
        load_databases(cfg)
    assert any("no MMseqs2 database found" in r.message for r in caplog.records)

def test_get_database_returns_definition(tmp_path):
    cfg = _write_config(tmp_path, """\
        databases:
          - name: nr
            path: /data/db/nr
            type: protein
    """)
    db = get_database("nr", cfg)
    assert db is not None
    assert db.program_types == ["blastp", "blastx"]
    assert get_database("other", cfg) is None
