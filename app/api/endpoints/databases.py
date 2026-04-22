from fastapi import APIRouter

from app.models.schemas import DatabaseListResponse
from app.services.db_scanner import load_databases

router = APIRouter(tags=["databases"])


@router.get("/databases", response_model=DatabaseListResponse)
def list_databases() -> DatabaseListResponse:
    return DatabaseListResponse(databases=load_databases())
