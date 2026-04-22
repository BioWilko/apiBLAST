"""Periodic Celery beat task to expire old BLAST results."""
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.db import Job
from app.services import result_store
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.cleanup.expire_results")
def expire_results() -> dict:
    """Delete result files for jobs whose TTL has passed."""
    db = SessionLocal()
    deleted = 0
    errors = 0
    try:
        expired = (
            db.query(Job)
            .filter(
                Job.result_expires_at <= datetime.now(timezone.utc),
                Job.result_path.isnot(None),
            )
            .all()
        )
        for job in expired:
            try:
                result_store.delete_job_dir(job.id)
                job.result_path = None
                deleted += 1
            except Exception:
                errors += 1
        db.commit()
    finally:
        db.close()

    return {"deleted": deleted, "errors": errors}
