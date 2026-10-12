import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import priority_token
from app.core.limiter import limiter
from app.deps import get_db
from app.models.db import Job
from app.models.schemas import (
    CPU_ONLY_ARGS,
    GPU_PROGRAMS,
    CancelResponse,
    JobCreate,
    JobStatus,
    JobSubmitted,
)
from app.services import result_store
from app.services.cost import estimate_cost, is_heavy
from app.services.db_scanner import get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

# Celery message priorities. On the Redis broker lower values are consumed
# first; these sit on kombu's default priority_steps (0, 3, 6, 9).
_PRIORITY_TOKEN = 0
_PRIORITY_NORMAL = 3
_PRIORITY_HEAVY = 9


def _queue_pos(db: Session) -> int:
    return db.query(func.count(Job.id)).filter(Job.status == "PENDING").scalar() or 0


def _job_or_404(job_id: str, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _elapsed(job: Job) -> float | None:
    if job.started_at is None:
        return None
    end = _as_utc(job.finished_at) if job.finished_at else datetime.now(timezone.utc)
    return (end - _as_utc(job.started_at)).total_seconds()


@router.post("/jobs", response_model=JobSubmitted, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_SUBMIT_PER_MINUTE}/minute")
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_SUBMIT_PER_HOUR}/hour")
def submit_job(
    request: Request,
    job_in: JobCreate,
    db: Session = Depends(get_db),
) -> JobSubmitted:
    settings = get_settings()
    token = priority_token(request)

    # Global queue-depth guard (priority tokens bypass it)
    active = (
        db.query(func.count(Job.id))
        .filter(Job.status.in_(["PENDING", "RUNNING"]))
        .scalar()
        or 0
    )
    if token is None and active >= settings.MAX_QUEUE_DEPTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Server at capacity ({active} active jobs). Retry later.",
            headers={"Retry-After": "60"},
        )

    # Validate that the requested database exists and suits the program
    database = get_database(job_in.database)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Database {job_in.database!r} not found on this server. "
                   f"Use GET /api/v1/databases to list available databases.",
        )
    if job_in.program not in database.program_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Program {job_in.program!r} cannot search database {job_in.database!r}; "
                   f"supported programs: {', '.join(database.program_types)}",
        )

    use_gpu = settings.MMSEQS_GPU_ENABLED and job_in.program in GPU_PROGRAMS
    cpu_only = sorted(CPU_ONLY_ARGS & job_in.extra_args.keys())
    if use_gpu and cpu_only:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"extra_args {cpu_only} do not apply to GPU searches, "
                   f"which always run at maximum sensitivity",
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
        extra_args_json=json.dumps(job_in.extra_args) if job_in.extra_args else None,
        submitter_ip=request.client.host if request.client else "unknown",
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()  # get the generated ID before committing

    # Write query FASTA to disk so the Celery worker can read it
    result_store.write_query(job.id, job_in.query)

    db.commit()

    # Heavy CPU searches queue behind everything else. GPU searches are fast
    # enough that they are never deprioritised.
    cost = None
    if token is not None:
        priority = _PRIORITY_TOKEN
    elif use_gpu:
        priority = _PRIORITY_NORMAL
    else:
        cost = estimate_cost(
            job_in.program, total_length, database.size_bytes, job_in.max_hits, job_in.extra_args
        )
        priority = _PRIORITY_HEAVY if is_heavy(cost) else _PRIORITY_NORMAL
    logger.info(
        "Submitted job %s: program=%s database=%s query_length=%d use_gpu=%s "
        "cost=%s priority=%d token=%s",
        job.id, job.program, job.database, total_length, use_gpu,
        f"{cost:.1f}" if cost is not None else "-", priority, token.label if token else "-",
    )

    # Dispatch Celery task
    from app.tasks.blast import blast_run
    blast_run.apply_async(
        args=[job.id],
        kwargs={"use_gpu": use_gpu},
        task_id=None,
        queue="blast_gpu" if use_gpu else "blast",
        priority=priority,
    )

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
