import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.limiter import limiter
from app.deps import get_db
from app.models.db import Job
from app.models.schemas import CancelResponse, JobCreate, JobStatus, JobSubmitted
from app.services import result_store
from app.services.db_scanner import database_exists

router = APIRouter(tags=["jobs"])


def _queue_pos(db: Session) -> int:
    return db.query(func.count(Job.id)).filter(Job.status == "PENDING").scalar() or 0


def _job_or_404(job_id: str, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job


def _elapsed(job: Job) -> float | None:
    if job.started_at is None:
        return None
    end = job.finished_at or datetime.now(timezone.utc)
    return (end - job.started_at).total_seconds()


@router.post("/jobs", response_model=JobSubmitted, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
@limiter.limit("100/hour")
def submit_job(
    request: Request,
    job_in: JobCreate,
    db: Session = Depends(get_db),
) -> JobSubmitted:
    settings = get_settings()

    # Global queue-depth guard
    active = (
        db.query(func.count(Job.id))
        .filter(Job.status.in_(["PENDING", "RUNNING"]))
        .scalar()
        or 0
    )
    if active >= settings.MAX_QUEUE_DEPTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Server at capacity ({active} active jobs). Retry later.",
            headers={"Retry-After": "60"},
        )

    # Validate that the requested database actually exists on disk
    if not database_exists(job_in.database):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"BLAST database {job_in.database!r} not found on this server. "
                   f"Use GET /api/v1/databases to list available databases.",
        )

    # Compute query metrics
    from app.models.schemas import _parse_fasta
    records = _parse_fasta(job_in.query)
    total_length = sum(len(seq) for _, seq in records)

    # Persist job metadata
    job = Job(
        program=job_in.program,
        database=job_in.database,
        query_length=total_length,
        num_sequences=len(records),
        evalue=job_in.evalue,
        max_hits=job_in.max_hits,
        word_size=job_in.word_size,
        outfmt=job_in.outfmt,
        extra_args_json=json.dumps(job_in.extra_args) if job_in.extra_args else None,
        submitter_ip=request.client.host if request.client else "unknown",
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()  # get the generated ID before committing

    # Write query FASTA to disk so the Celery worker can read it
    result_store.write_query(job.id, job_in.query)

    db.commit()

    # Dispatch Celery task
    from app.tasks.blast import blast_run
    blast_run.apply_async(args=[job.id], task_id=None, queue="blast")

    queue_pos = _queue_pos(db)
    return JobSubmitted(
        job_id=job.id,
        status=job.status,
        queue_pos=queue_pos,
        submitted_at=job.submitted_at,
        poll_url=f"/api/v1/jobs/{job.id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobStatus:
    job = _job_or_404(job_id, db)
    return JobStatus(
        job_id=job.id,
        status=job.status,
        program=job.program,
        database=job.database,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        elapsed_s=_elapsed(job),
        error=job.error_message,
        result_url=f"/api/v1/jobs/{job.id}/results" if job.status == "SUCCESS" else None,
    )


@router.delete("/jobs/{job_id}", response_model=CancelResponse)
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> CancelResponse:
    job = _job_or_404(job_id, db)

    if job.status in ("SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"):
        return CancelResponse(job_id=job_id, cancelled=False)

    # Revoke via Celery (terminate running process with SIGTERM)
    from app.tasks.celery_app import celery_app
    celery_app.control.revoke(job.celery_task_id or job_id, terminate=True, signal="SIGTERM")

    job.status = "REVOKED"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()

    return CancelResponse(job_id=job_id, cancelled=True)
