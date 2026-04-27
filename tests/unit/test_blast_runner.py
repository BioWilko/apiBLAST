"""Unit tests for blast_runner.build_blast_command."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.models.db import Job
from app.services.blast_runner import build_blast_command

_FAKE_DB_PATH = Path("/custom/location/testdb")


def _make_job(**kwargs) -> Job:
    defaults = dict(
        id="test-job-id",
        program="blastn",
        database="testdb",
        evalue=1e-5,
        max_hits=50,
        word_size=None,
        outfmt=6,
        extra_args_json=None,
    )
    defaults.update(kwargs)
    job = MagicMock(spec=Job)
    for k, v in defaults.items():
        setattr(job, k, v)
    return job


@pytest.fixture
def fake_binary(tmp_path):
    """Create a fake blastn binary so existence checks pass."""
    binary = tmp_path / "blastn"
    binary.touch(mode=0o755)
    return tmp_path


def _patch_deps(fake_binary, db_path=_FAKE_DB_PATH):
    """Return a context manager that patches settings and get_database_path."""
    settings_patch = patch("app.services.blast_runner.get_settings")
    db_path_patch = patch(
        "app.services.blast_runner.get_database_path", return_value=db_path
    )
    return settings_patch, db_path_patch


def test_num_threads_always_one(fake_binary, tmp_path):
    job = _make_job()
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert "-num_threads" in cmd
    assert cmd[cmd.index("-num_threads") + 1] == "1"


def test_db_path_comes_from_config(fake_binary, tmp_path):
    job = _make_job(database="mydb")
    configured_path = Path("/custom/location/mydb")
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=configured_path) as mock_get_path:
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert "-db" in cmd
    assert cmd[cmd.index("-db") + 1] == "/custom/location/mydb"
    mock_get_path.assert_called_once_with("mydb")


def test_word_size_none_not_in_command(fake_binary, tmp_path):
    job = _make_job(word_size=None)
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert "-word_size" not in cmd


def test_word_size_set_when_provided(fake_binary, tmp_path):
    job = _make_job(word_size=11)
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert "-word_size" in cmd
    assert cmd[cmd.index("-word_size") + 1] == "11"


def test_extra_args_appended(fake_binary, tmp_path):
    job = _make_job(extra_args_json=json.dumps({"dust": "no", "perc_identity": 90}))
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert "-dust" in cmd
    assert cmd[cmd.index("-dust") + 1] == "no"
    assert "-perc_identity" in cmd
    assert cmd[cmd.index("-perc_identity") + 1] == "90"


def test_unknown_program_raises(fake_binary, tmp_path):
    job = _make_job(program="megablast")
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        with pytest.raises(ValueError, match="Unknown BLAST program"):
            build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")


def test_missing_binary_raises(tmp_path):
    job = _make_job()
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = tmp_path  # no blastn here
        with pytest.raises(FileNotFoundError, match="BLAST binary not found"):
            build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")


def test_evalue_and_max_hits_in_command(fake_binary, tmp_path):
    job = _make_job(evalue=0.001, max_hits=100)
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=_FAKE_DB_PATH):
        mock_settings.return_value.BLAST_BIN_DIR = fake_binary
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv")
    assert cmd[cmd.index("-evalue") + 1] == "0.001"
    assert cmd[cmd.index("-max_target_seqs") + 1] == "100"
