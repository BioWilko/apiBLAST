"""Integration tests for priority tokens and cost-based job prioritisation."""
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
from app.models.schemas import DatabaseInfo
from app.services import tokens

VALID_QUERY = ">seq1\nATGCATGCATGCATGCATGC\n"
VALID_AA_QUERY = ">prot1\nMKTLLLTLVVVTIVSA\n"
# 2 × 100 kb × 10 GB = 2000, above the default threshold of 1000
HEAVY_QUERY = ">big\n" + "ACGT" * 25_000 + "\n"

_DATABASES = {
    "smalldb": DatabaseInfo(
        name="smalldb", description="", program_types=["blastn"],
        path="/data/db/smalldb", size_bytes=0, last_updated=None,
    ),
    "bigdb": DatabaseInfo(
        name="bigdb", description="", program_types=["blastn"],
        path="/data/db/bigdb", size_bytes=10 * 10**9, last_updated=None,
    ),
    "bigprot": DatabaseInfo(
        name="bigprot", description="", program_types=["blastp", "blastx"],
        path="/data/db/bigprot", size_bytes=10 * 10**9, last_updated=None,
    ),
}


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
def dispatch():
    with patch("app.tasks.blast.blast_run.apply_async") as apply_async:
        yield apply_async


@pytest.fixture
def api(session, session_factory, dispatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with patch("app.api.endpoints.jobs.get_database", side_effect=_DATABASES.get), \
         patch("app.services.result_store.write_query"), \
         patch("app.core.database.SessionLocal", session_factory):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def token(session):
    _, raw = tokens.create(session, "test user")
    return raw


def _submit(api, database="smalldb", query=VALID_QUERY, program="blastn", headers=None):
    return api.post(
        "/api/v1/jobs",
        json={"program": program, "database": database, "query": query},
        headers=headers or {},
    )


def _bearer(raw):
    return {"Authorization": f"Bearer {raw}"}


def _fill_queue(session):
    from app.config import get_settings
    for _ in range(get_settings().MAX_QUEUE_DEPTH):
        session.add(Job(
            program="blastn", database="smalldb", query_length=20, num_sequences=1,
            submitter_ip="127.0.0.1",
        ))
    session.commit()


def test_no_token_light_job_normal_priority(api, dispatch):
    assert _submit(api).status_code == 201
    assert dispatch.call_args.kwargs["priority"] == 3


def test_no_token_heavy_job_deprioritised(api, dispatch):
    assert _submit(api, database="bigdb", query=HEAVY_QUERY).status_code == 201
    assert dispatch.call_args.kwargs["priority"] == 9


def test_gpu_jobs_never_deprioritised(api, dispatch):
    from app.config import get_settings
    settings = get_settings()
    original = settings.MMSEQS_GPU_ENABLED
    settings.MMSEQS_GPU_ENABLED = True
    try:
        resp = _submit(api, database="bigprot", query=HEAVY_QUERY, program="blastx")
    finally:
        settings.MMSEQS_GPU_ENABLED = original
    assert resp.status_code == 201
    assert dispatch.call_args.kwargs["queue"] == "blast_gpu"
    assert dispatch.call_args.kwargs["priority"] == 3


def test_token_heavy_job_top_priority(api, dispatch, token):
    resp = _submit(api, database="bigdb", query=HEAVY_QUERY, headers=_bearer(token))
    assert resp.status_code == 201
    assert dispatch.call_args.kwargs["priority"] == 0


def test_full_queue_rejects_without_token(api, session):
    _fill_queue(session)
    assert _submit(api).status_code == 503


def test_full_queue_accepts_token(api, session, token):
    _fill_queue(session)
    assert _submit(api, headers=_bearer(token)).status_code == 201


def test_invalid_token_returns_401(api):
    resp = _submit(api, headers=_bearer("apb_not-a-real-token"))
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_revoked_token_returns_401(api, session, token):
    tokens.revoke(session, token[:12])
    assert _submit(api, headers=_bearer(token)).status_code == 401


def test_token_accepted_on_other_endpoints(api, token):
    assert api.get("/health", headers=_bearer(token)).status_code == 200


def test_non_bearer_authorization_ignored(api, dispatch):
    resp = _submit(api, headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 201
    assert dispatch.call_args.kwargs["priority"] == 3
