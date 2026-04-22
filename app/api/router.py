from fastapi import APIRouter

from app.api.endpoints import databases, health, jobs, results

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(jobs.router)
api_router.include_router(results.router)
api_router.include_router(databases.router)

# Health routes at root (no /api/v1 prefix) for Docker/k8s probes
health_router = APIRouter()
health_router.include_router(health.router)
