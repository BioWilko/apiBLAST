from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import api_router, health_router
from app.config import get_settings
from app.core.exceptions import rate_limit_handler
from app.core.limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure result directory exists at startup
    settings = get_settings()
    settings.BLAST_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="apiBLAST",
        description="On-premises BLAST API server with async job queuing",
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )

    # Rate limiting middleware + exception handler
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # Routers
    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
