"""Unit tests for the blast_run Celery task."""
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.db import Job
from app.tasks.blast import blast_run


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def env(session_factory, tmp_path):
    """Patch the task's DB session and result dir; yield a helper to create jobs."""
    from app.config import get_settings
    settings = get_settings()
    original_dir = settings.RESULT_DIR
    settings.RESULT_DIR = tmp_path
    with patch("app.tasks.blast.SessionLocal", session_factory), \
         patch("app.tasks.blast._guard_memory", return_value=None):

        def make_job(status="PENDING", max_hits=50) -> str:
            s = session_factory()
            job = Job(
                program="blastn", database="testdb", query_length=20, num_sequences=1,
                evalue=1e-5, max_hits=max_hits, submitter_ip="127.0.0.1",
                submitted_at=datetime.now(timezone.utc), status=status,
            )
            s.add(job)
            s.commit()
            job_id = job.id
            s.close()
            (tmp_path / job_id).mkdir()
            (tmp_path / job_id / "query.fasta").write_text(">q1\nACGT\n")
            return job_id

        yield make_job, session_factory, tmp_path
    settings.RESULT_DIR = original_dir


def _status(session_factory, job_id) -> Job:
    s = session_factory()
    job = s.get(Job, job_id)
    s.close()
    return job


@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"])
def test_finished_job_is_skipped(env, status):
    make_job, session_factory, _ = env
    job_id = make_job(status=status)
    with patch("app.tasks.blast.blast_runner.run_blast") as run:
        result = blast_run.apply(args=[job_id]).get()
    run.assert_not_called()
    assert result["skipped"] is True
    assert _status(session_factory, job_id).status == status


def test_redelivered_running_job_runs_again(env):
    make_job, session_factory, tmp_path = env
    job_id = make_job(status="RUNNING")

    def fake_run(cmd, timeout_s=None):
        (tmp_path / job_id / "result.tsv").write_text("")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch("app.tasks.blast.blast_runner.build_blast_command", return_value=["mmseqs"]), \
         patch("app.tasks.blast.blast_runner.run_blast", side_effect=fake_run):
        blast_run.apply(args=[job_id]).get()
    assert _status(session_factory, job_id).status == "SUCCESS"


def test_success_caps_hits_and_removes_tmp(env):
    make_job, session_factory, tmp_path = env
    job_id = make_job(max_hits=1)
    tmp_dir = tmp_path / job_id / "tmp"

    def fake_run(cmd, timeout_s=None):
        tmp_dir.mkdir()
        (tmp_dir / "scratch").write_text("x")
        (tmp_path / job_id / "result.tsv").write_text(
            "q1\tA\t100.0\t4\t0\t0\t1\t4\t1\t4\t1E-5\t8\n"
            "q1\tB\t90.0\t4\t0\t0\t1\t4\t1\t4\t1E-4\t7\n"
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch("app.tasks.blast.blast_runner.build_blast_command",
               return_value=["mmseqs"]) as build, \
         patch("app.tasks.blast.blast_runner.run_blast", side_effect=fake_run):
        blast_run.apply(args=[job_id], kwargs={"use_gpu": True}).get()

    assert build.call_args.args[3] == tmp_dir
    assert build.call_args.kwargs == {"use_gpu": True}
    assert _status(session_factory, job_id).status == "SUCCESS"
    assert (tmp_path / job_id / "result.tsv").read_text().count("\n") == 1
    assert not tmp_dir.exists()


def test_nonzero_exit_marks_failure(env):
    make_job, session_factory, _ = env
    job_id = make_job()
    failed = subprocess.CompletedProcess(["mmseqs"], 1, "", "Error: database not found")
    with patch("app.tasks.blast.blast_runner.build_blast_command", return_value=["mmseqs"]), \
         patch("app.tasks.blast.blast_runner.run_blast", return_value=failed):
        blast_run.apply(args=[job_id]).get()
    job = _status(session_factory, job_id)
    assert job.status == "FAILURE"
    assert "database not found" in job.error_message
