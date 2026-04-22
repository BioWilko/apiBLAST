from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models.db import Job
from app.models.schemas import BlastHit, BlastResultResponse
from app.services import result_store

router = APIRouter(tags=["results"])

_TERMINAL = {"SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"}


def _job_or_404(job_id: str, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job


@router.get("/jobs/{job_id}/results")
def get_results(job_id: str, request: Request, db: Session = Depends(get_db)):
    job = _job_or_404(job_id, db)

    if job.status not in _TERMINAL:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not complete yet (status: {job.status}). Poll GET /api/v1/jobs/{job_id}.",
        )

    if job.status != "SUCCESS":
        raise HTTPException(
            status_code=404,
            detail=f"Job ended with status {job.status!r}. No results available.",
        )

    raw = result_store.read_result(job_id)
    if raw is None:
        raise HTTPException(
            status_code=410,
            detail="Result file has been deleted (TTL expired).",
        )

    accept = request.headers.get("accept", "application/json")

    if "text/tab-separated-values" in accept or "text/plain" in accept:
        return PlainTextResponse(content=raw)

    # Default: parse outfmt 6 and return JSON
    hits = result_store.parse_outfmt6(raw)
    return BlastResultResponse(
        job_id=job_id,
        num_hits=len(hits),
        hits=[BlastHit(**h) for h in hits],
    )
