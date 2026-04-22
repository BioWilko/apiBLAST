from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=get_settings().APP_VERSION)


@router.get("/health/ready")
def readiness() -> JSONResponse:
    """Check Redis and database connectivity. Used as Docker/k8s readiness probe."""
    settings = get_settings()
    errors: list[str] = []

    # Redis check
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
    except Exception as exc:
        errors.append(f"redis: {exc}")

    # DB check
    try:
        from app.core.database import engine
        with engine.connect():
            pass
    except Exception as exc:
        errors.append(f"db: {exc}")

    if errors:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "errors": errors},
        )
    return JSONResponse(content={"status": "ok"})
