"""Rate limiting with real SlowAPI checks (in-memory storage) and priority tokens.

Lives outside tests/integration, whose conftest stubs rate limiting out.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.core.database import Base
from app.core.limiter import limiter
from app.deps import get_db
from app.main import create_app
from app.models.schemas import DatabaseInfo
from app.services import tokens

QUERY = {"program": "blastn", "database": "testdb", "query": ">s\nACGTACGTACGT\n"}
_DB = DatabaseInfo(
    name="testdb", description="", program_types=["blastn"],
    path="/data/db/testdb", size_bytes=0, last_updated=None,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api(session_factory):
    session = session_factory()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    storage = MemoryStorage()
    settings = get_settings()
    original_depth = settings.MAX_QUEUE_DEPTH
    settings.MAX_QUEUE_DEPTH = 1000
    with patch.object(limiter, "_storage", storage), \
         patch.object(limiter, "_limiter", FixedWindowRateLimiter(storage)), \
         patch("app.api.endpoints.jobs.get_database", return_value=_DB), \
         patch("app.services.result_store.write_query"), \
         patch("app.tasks.blast.blast_run.apply_async"), \
         patch("app.core.database.SessionLocal", session_factory):
        with TestClient(app) as c:
            c.session = session
            yield c
    settings.MAX_QUEUE_DEPTH = original_depth
    session.close()


def test_submit_limit_enforced_without_token(api):
    per_minute = get_settings().RATE_LIMIT_SUBMIT_PER_MINUTE
    codes = [api.post("/api/v1/jobs", json=QUERY).status_code for _ in range(per_minute + 1)]
    assert codes[:-1] == [201] * per_minute
    assert codes[-1] == 429


def test_submit_limit_follows_settings(api):
    settings = get_settings()
    original = settings.RATE_LIMIT_SUBMIT_PER_MINUTE
    settings.RATE_LIMIT_SUBMIT_PER_MINUTE = 2
    try:
        codes = [api.post("/api/v1/jobs", json=QUERY).status_code for _ in range(3)]
    finally:
        settings.RATE_LIMIT_SUBMIT_PER_MINUTE = original
    assert codes == [201, 201, 429]


def test_token_bypasses_submit_limit(api):
    _, raw = tokens.create(api.session, "priority user")
    headers = {"Authorization": f"Bearer {raw}"}
    n = get_settings().RATE_LIMIT_SUBMIT_PER_MINUTE + 5
    codes = [api.post("/api/v1/jobs", json=QUERY, headers=headers).status_code for _ in range(n)]
    assert codes == [201] * n


def test_token_bypasses_default_limit(api):
    _, raw = tokens.create(api.session, "priority user")
    headers = {"Authorization": f"Bearer {raw}"}
    codes = {api.get("/api/v1/databases", headers=headers).status_code for _ in range(205)}
    assert codes == {200}


def test_default_limit_enforced_without_token(api):
    codes = [api.get("/api/v1/databases").status_code for _ in range(201)]
    assert codes[-1] == 429
