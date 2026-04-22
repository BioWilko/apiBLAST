"""Celery task that executes a BLAST job end-to-end."""
import subprocess
from datetime import datetime, timezone, timedelta

import psutil
from celery.exceptions import SoftTimeLimitExceeded

from app.config import get_settings
from app.core.database import SessionLocal
from app.models.db import Job
from app.services import blast_runner, result_store
from app.tasks.celery_app import celery_app


def _guard_memory(settings) -> str | None:
    """Return an error string if free memory is below the configured floor."""
    available_mb = psutil.virtual_memory().available / 1_048_576
    if available_mb < settings.MEMORY_FLOOR_MB:
        return f"Insufficient free memory ({available_mb:.0f} MB available, need {settings.MEMORY_FLOOR_MB} MB)"
    return None


@celery_app.task(
    bind=True,
    name="app.tasks.blast.blast_run",
    max_retries=0,  # BLAST jobs are not safely idempotent by default
    throws=(SoftTimeLimitExceeded,),
)
def blast_run(self, job_id: str) -> dict:
    settings = get_settings()
    db = SessionLocal()
    try:
        job: Job | None = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found in database")

        # ── Memory guard ──────────────────────────────────────────────────────
        mem_error = _guard_memory(settings)
        if mem_error:
            job.status = "FAILURE"
            job.error_message = mem_error
            db.commit()
            return {"status": "FAILURE", "job_id": job_id}

        # ── Transition to RUNNING ─────────────────────────────────────────────
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.celery_task_id = self.request.id
        db.commit()

        # ── Resolve file paths ────────────────────────────────────────────────
        q_path = result_store.query_path(job_id)
        r_path = result_store.result_path(job_id)
        # The query FASTA was written to disk by the API at submission time.
        if not q_path.exists():
            raise FileNotFoundError(f"Query file missing for job {job_id}: {q_path}")

        # ── Build and run BLAST command ───────────────────────────────────────
        cmd = blast_runner.build_blast_command(job, q_path, r_path)

        try:
            proc = blast_runner.run_blast(cmd, timeout_s=settings.BLAST_HARD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            job.status = "TIMEOUT"
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = "Process exceeded hard time limit"
            db.commit()
            return {"status": "TIMEOUT", "job_id": job_id}

        if proc.returncode != 0:
            job.status = "FAILURE"
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = proc.stderr[:4096]
            db.commit()
            return {"status": "FAILURE", "job_id": job_id}

        # ── Success ───────────────────────────────────────────────────────────
        job.status = "SUCCESS"
        job.finished_at = datetime.now(timezone.utc)
        job.result_path = str(r_path)
        job.result_expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.RESULT_TTL_S)
        db.commit()
        return {"status": "SUCCESS", "job_id": job_id}

    except SoftTimeLimitExceeded:
        job.status = "TIMEOUT"
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = "Soft time limit exceeded (SIGTERM received)"
        db.commit()
        raise  # Celery escalates to SIGKILL after hard_time_limit

    except Exception as exc:
        if job is not None:
            job.status = "FAILURE"
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = str(exc)[:4096]
            db.commit()
        raise

    finally:
        db.close()
