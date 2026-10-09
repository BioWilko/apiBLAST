"""Integration tests for the results endpoint."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.deps import get_db
from app.main import create_app
from app.models.db import Job

SAMPLE_OUTFMT6 = (
    "seq1\tNM_001234.3\t98.700\t500\t6\t0\t1\t500\t120\t619\t1.2e-180\t912.0\n"
    "seq1\tNM_005678.1\t95.000\t400\t20\t1\t1\t400\t50\t449\t2.5e-120\t720.0\n"
)


@pytest.fixture(scope="module")
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
def api(session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c, session


def _make_job(session, status="SUCCESS", result_path="/tmp/result.tsv", expires_delta=None):
    job = Job(
        program="blastn",
        database="testdb",
        query_length=20,
        num_sequences=1,
        evalue=1e-5,
        max_hits=50,
        submitter_ip="127.0.0.1",
        submitted_at=datetime.now(timezone.utc),
        status=status,
        result_path=result_path,
        result_expires_at=(
            datetime.now(timezone.utc) + timedelta(hours=24)
            if expires_delta is None
            else datetime.now(timezone.utc) + expires_delta
        ),
    )
    session.add(job)
    session.flush()
    return job


def test_results_success_returns_hits(api):
    client, session = api
    job = _make_job(session, status="SUCCESS")
    session.commit()

    with patch("app.api.endpoints.results.result_store.read_result", return_value=SAMPLE_OUTFMT6):
        resp = client.get(f"/api/v1/jobs/{job.id}/results")

    assert resp.status_code == 200
    body = resp.json()
    assert body["num_hits"] == 2
    assert body["hits"][0]["pct_identity"] == 98.7


def test_results_running_job_returns_409(api):
    client, session = api
    job = _make_job(session, status="RUNNING", result_path=None)
    session.commit()

    resp = client.get(f"/api/v1/jobs/{job.id}/results")
    assert resp.status_code == 409


def test_results_failed_job_returns_404(api):
    client, session = api
    job = _make_job(session, status="FAILURE", result_path=None)
    session.commit()

    resp = client.get(f"/api/v1/jobs/{job.id}/results")
    assert resp.status_code == 404


def test_results_expired_returns_410(api):
    client, session = api
    job = _make_job(session, status="SUCCESS")
    session.commit()

    # Simulate deleted result file
    with patch("app.api.endpoints.results.result_store.read_result", return_value=None):
        resp = client.get(f"/api/v1/jobs/{job.id}/results")

    assert resp.status_code == 410


def test_results_tsv_accept_header(api):
    client, session = api
    job = _make_job(session, status="SUCCESS")
    session.commit()

    with patch("app.api.endpoints.results.result_store.read_result", return_value=SAMPLE_OUTFMT6):
        resp = client.get(
            f"/api/v1/jobs/{job.id}/results",
            headers={"Accept": "text/tab-separated-values"},
        )

    assert resp.status_code == 200
    assert "98.700" in resp.text
