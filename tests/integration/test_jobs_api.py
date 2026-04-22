"""Integration tests for job submission and status endpoints."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.deps import get_db
from app.main import create_app

VALID_QUERY = ">seq1\nATGCATGCATGCATGCATGC\n"


@pytest.fixture(scope="module")
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # single shared connection so in-memory DB is visible everywhere
    )
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture
def session(engine):
    S = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    s = S()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def api(session, tmp_path):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session

    with patch("app.api.endpoints.jobs.database_exists", return_value=True), \
         patch("app.services.result_store.write_query"), \
         patch("app.tasks.blast.blast_run.apply_async"):
        with TestClient(app) as c:
            yield c


def test_submit_valid_job_returns_201(api):
    resp = api.post("/api/v1/jobs", json={
        "program": "blastn",
        "database": "testdb",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "PENDING"
    assert body["poll_url"].startswith("/api/v1/jobs/")


def test_submit_invalid_program_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "program": "megablast",
        "database": "testdb",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 422


def test_submit_oversized_query_returns_422(api):
    big = ">seq1\n" + "A" * 600_000
    resp = api.post("/api/v1/jobs", json={
        "program": "blastn",
        "database": "testdb",
        "query": big,
    })
    assert resp.status_code == 422


def test_submit_blocked_extra_arg_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "program": "blastn",
        "database": "testdb",
        "query": VALID_QUERY,
        "extra_args": {"out": "/etc/passwd"},
    })
    assert resp.status_code == 422


def test_get_job_status(api):
    # Submit first
    resp = api.post("/api/v1/jobs", json={
        "program": "blastn",
        "database": "testdb",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]

    # Poll
    resp2 = api.get(f"/api/v1/jobs/{job_id}")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["job_id"] == job_id
    assert body["status"] == "PENDING"
    assert body["result_url"] is None


def test_get_nonexistent_job_returns_404(api):
    resp = api.get("/api/v1/jobs/does-not-exist")
    assert resp.status_code == 404


def test_health_endpoint(api):
    resp = api.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_databases_endpoint(api):
    resp = api.get("/api/v1/databases")
    assert resp.status_code == 200
    assert "databases" in resp.json()
