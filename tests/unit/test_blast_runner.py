"""Unit tests for blast_runner (MMseqs2 command building and execution)."""
import json
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.db import Job
from app.services.blast_runner import FORMAT_OUTPUT, build_blast_command, run_blast

_FAKE_DB_PATH = Path("/custom/location/testdb")


def _make_job(**kwargs) -> Job:
    defaults = dict(
        id="test-job-id",
        program="blastn",
        database="testdb",
        evalue=1e-5,
        max_hits=50,
        extra_args_json=None,
    )
    defaults.update(kwargs)
    job = MagicMock(spec=Job)
    for k, v in defaults.items():
        setattr(job, k, v)
    return job


@pytest.fixture
def fake_binary(tmp_path):
    """Create a fake mmseqs binary so existence checks pass."""
    binary = tmp_path / "mmseqs"
    binary.touch(mode=0o755)
    return binary


def _build(fake_binary, tmp_path, job=None, use_gpu=False, threads=1, db_path=_FAKE_DB_PATH):
    job = job or _make_job()
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path", return_value=db_path):
        mock_settings.return_value.MMSEQS_BIN = fake_binary
        mock_settings.return_value.MMSEQS_THREADS = threads
        return build_blast_command(
            job, tmp_path / "q.fasta", tmp_path / "out.tsv", tmp_path / "tmp", use_gpu=use_gpu
        )


def _value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_easy_search_positional_order(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path)
    assert cmd[:6] == [
        str(fake_binary), "easy-search",
        str(tmp_path / "q.fasta"), str(_FAKE_DB_PATH),
        str(tmp_path / "out.tsv"), str(tmp_path / "tmp"),
    ]


def test_db_path_comes_from_config(fake_binary, tmp_path):
    configured_path = Path("/custom/location/mydb")
    job = _make_job(database="mydb")
    with patch("app.services.blast_runner.get_settings") as mock_settings, \
         patch("app.services.blast_runner.get_database_path",
               return_value=configured_path) as mock_get_path:
        mock_settings.return_value.MMSEQS_BIN = fake_binary
        mock_settings.return_value.MMSEQS_THREADS = 1
        cmd = build_blast_command(job, tmp_path / "q.fasta", tmp_path / "out.tsv", tmp_path / "tmp")
    assert cmd[3] == "/custom/location/mydb"
    mock_get_path.assert_called_once_with("mydb")


def test_twelve_blast_columns_with_pident(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path)
    assert _value(cmd, "--format-mode") == "0"
    columns = _value(cmd, "--format-output").split(",")
    assert len(columns) == 12
    assert columns[2] == "pident"
    assert _value(cmd, "--format-output") == FORMAT_OUTPUT


def test_blastn_searches_both_strands(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path, job=_make_job(program="blastn"))
    assert _value(cmd, "--search-type") == "3"
    assert _value(cmd, "--strand") == "2"


def test_blastp_search_type(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path, job=_make_job(program="blastp"))
    assert _value(cmd, "--search-type") == "1"
    assert "--strand" not in cmd
    assert "--translation-mode" not in cmd


def test_blastx_defaults_to_frame_mode(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path, job=_make_job(program="blastx"))
    assert _value(cmd, "--search-type") == "2"
    assert _value(cmd, "--translation-mode") == "1"


def test_blastx_translation_mode_override(fake_binary, tmp_path):
    job = _make_job(program="blastx", extra_args_json=json.dumps({"translation-mode": 0}))
    cmd = _build(fake_binary, tmp_path, job=job)
    assert cmd.count("--translation-mode") == 1
    assert _value(cmd, "--translation-mode") == "0"


def test_blastx_translation_table(fake_binary, tmp_path):
    job = _make_job(program="blastx", extra_args_json=json.dumps({"translation-table": 11}))
    cmd = _build(fake_binary, tmp_path, job=job)
    assert _value(cmd, "--translation-table") == "11"


def test_gpu_flag_only_when_requested(fake_binary, tmp_path):
    job = _make_job(program="blastp")
    assert "--gpu" not in _build(fake_binary, tmp_path, job=job)
    assert _value(_build(fake_binary, tmp_path, job=job, use_gpu=True), "--gpu") == "1"


def test_blastn_cannot_run_on_gpu(fake_binary, tmp_path):
    with pytest.raises(ValueError, match="cannot run on the GPU"):
        _build(fake_binary, tmp_path, job=_make_job(program="blastn"), use_gpu=True)


def test_max_seqs_never_below_prefilter_default(fake_binary, tmp_path):
    for max_hits, expected in [(50, "300"), (1000, "1000")]:
        cmd = _build(fake_binary, tmp_path, job=_make_job(max_hits=max_hits))
        assert _value(cmd, "--max-seqs") == expected


def test_threads_from_settings(fake_binary, tmp_path):
    assert _value(_build(fake_binary, tmp_path, threads=8), "--threads") == "8"


def test_evalue_in_command(fake_binary, tmp_path):
    cmd = _build(fake_binary, tmp_path, job=_make_job(evalue=0.001))
    assert _value(cmd, "-e") == "0.001"


def test_extra_args_rendering(fake_binary, tmp_path):
    job = _make_job(extra_args_json=json.dumps({"s": 7.5, "min-seq-id": 0.9}))
    cmd = _build(fake_binary, tmp_path, job=job)
    assert _value(cmd, "-s") == "7.5"
    assert _value(cmd, "--min-seq-id") == "0.9"


@pytest.mark.parametrize("program", ["megablast", "tblastn", "tblastx"])
def test_unknown_program_raises(fake_binary, tmp_path, program):
    with pytest.raises(ValueError, match="Unknown program"):
        _build(fake_binary, tmp_path, job=_make_job(program=program))


def test_missing_binary_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="mmseqs binary not found"):
        _build(tmp_path / "missing" / "mmseqs", tmp_path)


# ── run_blast ──────────────────────────────────────────────────────────────────

def test_run_returns_completed_process():
    proc = run_blast(["sh", "-c", "echo out; echo err >&2; exit 3"])
    assert proc.returncode == 3
    assert proc.stdout == "out\n"
    assert proc.stderr == "err\n"


def test_run_kills_process_group_on_timeout():
    with patch("app.services.blast_runner.os.killpg", wraps=__import__("os").killpg) as killpg:
        with pytest.raises(subprocess.TimeoutExpired):
            run_blast(["sh", "-c", "sleep 30 & wait"], timeout_s=0.5)
    killpg.assert_called_once()
    assert killpg.call_args.args[1] == signal.SIGKILL
