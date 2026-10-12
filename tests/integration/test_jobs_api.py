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
from app.models.schemas import DatabaseInfo

VALID_QUERY = ">seq1\nATGCATGCATGCATGCATGC\n"
VALID_AA_QUERY = ">prot1\nMKTLLLTLVVVTIVSA\n"

_DATABASES = {
    "testdb": DatabaseInfo(
        name="testdb", description="", molecule_type="nucleotide",
        path="/data/db/testdb", size_bytes=0, last_updated=None,
    ),
    "protdb": DatabaseInfo(
        name="protdb", description="", molecule_type="protein",
        path="/data/db/protdb", size_bytes=0, last_updated=None,
    ),
}


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
def dispatch():
    with patch("app.tasks.blast.blast_run.apply_async") as apply_async:
        yield apply_async


@pytest.fixture
def gpu_enabled():
    from app.config import get_settings
    settings = get_settings()
    original = settings.MMSEQS_GPU_ENABLED
    settings.MMSEQS_GPU_ENABLED = True
    yield
    settings.MMSEQS_GPU_ENABLED = original


@pytest.fixture
def api(session, tmp_path, dispatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session

    with patch("app.api.endpoints.jobs.get_database", side_effect=_DATABASES.get), \
         patch("app.services.result_store.write_query"):
        with TestClient(app) as c:
            yield c


def test_submit_valid_job_returns_201(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "testdb",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "PENDING"
    assert body["poll_url"].startswith("/api/v1/jobs/")


def test_submit_invalid_query_type_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "blastn",
        "database": "testdb",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 422


def test_submit_oversized_query_returns_422(api):
    big = ">seq1\n" + "A" * 600_000
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "testdb",
        "query": big,
    })
    assert resp.status_code == 422


def test_submit_blocked_extra_arg_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "testdb",
        "query": VALID_QUERY,
        "extra_args": {"mpi-runner": 1},
    })
    assert resp.status_code == 422


def test_submit_protein_query_against_nucleotide_db_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "protein",
        "database": "testdb",
        "query": VALID_AA_QUERY,
    })
    assert resp.status_code == 422
    assert "translating the database" in resp.text


@pytest.mark.parametrize("query_type,database,query", [
    ("nucleotide", "testdb", VALID_QUERY),
    ("protein", "protdb", VALID_AA_QUERY),
])
def test_translation_args_rejected_for_untranslated_searches(api, query_type, database, query):
    resp = api.post("/api/v1/jobs", json={
        "query_type": query_type,
        "database": database,
        "query": query,
        "extra_args": {"translation-table": 11},
    })
    assert resp.status_code == 422
    assert "only valid for nucleotide queries against protein databases" in resp.text


def test_translation_args_accepted_for_translated_search(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "protdb",
        "query": VALID_QUERY,
        "extra_args": {"translation-table": 11},
    })
    assert resp.status_code == 201


def test_submit_unknown_database_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "missing",
        "query": VALID_QUERY,
    })
    assert resp.status_code == 422


def test_submit_legacy_default_fields_accepted(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "testdb",
        "query": VALID_QUERY,
        "outfmt": 6,
        "word_size": None,
    })
    assert resp.status_code == 201


def test_submit_legacy_non_default_field_returns_422(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
        "database": "testdb",
        "query": VALID_QUERY,
        "word_size": 11,
    })
    assert resp.status_code == 422
    assert "removed in apiBLAST 2.0" in resp.text


# ── Queue routing ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query_type,database,query", [
    ("nucleotide", "testdb", VALID_QUERY),
    ("protein", "protdb", VALID_AA_QUERY),
    ("nucleotide", "protdb", VALID_QUERY),
])
def test_gpu_disabled_routes_everything_to_cpu(api, dispatch, query_type, database, query):
    resp = api.post(
        "/api/v1/jobs", json={"query_type": query_type, "database": database, "query": query}
    )
    assert resp.status_code == 201
    kwargs = dispatch.call_args.kwargs
    assert kwargs["queue"] == "blast"
    assert kwargs["kwargs"] == {"use_gpu": False}


@pytest.mark.parametrize("query_type,query", [("protein", VALID_AA_QUERY), ("nucleotide", VALID_QUERY)])
def test_gpu_enabled_routes_protein_db_searches_to_gpu(api, dispatch, gpu_enabled, query_type, query):
    resp = api.post(
        "/api/v1/jobs", json={"query_type": query_type, "database": "protdb", "query": query}
    )
    assert resp.status_code == 201
    kwargs = dispatch.call_args.kwargs
    assert kwargs["queue"] == "blast_gpu"
    assert kwargs["kwargs"] == {"use_gpu": True}


def test_gpu_enabled_keeps_nucleotide_db_searches_on_cpu(api, dispatch, gpu_enabled):
    resp = api.post(
        "/api/v1/jobs", json={"query_type": "nucleotide", "database": "testdb", "query": VALID_QUERY}
    )
    assert resp.status_code == 201
    assert dispatch.call_args.kwargs["queue"] == "blast"


def test_sensitivity_rejected_for_gpu_jobs(api, gpu_enabled):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "protein",
        "database": "protdb",
        "query": VALID_AA_QUERY,
        "extra_args": {"s": 7.5},
    })
    assert resp.status_code == 422
    assert "GPU" in resp.text


def test_sensitivity_accepted_for_cpu_jobs(api):
    resp = api.post("/api/v1/jobs", json={
        "query_type": "protein",
        "database": "protdb",
        "query": VALID_AA_QUERY,
        "extra_args": {"s": 7.5},
    })
    assert resp.status_code == 201


def test_get_job_status(api):
    # Submit first
    resp = api.post("/api/v1/jobs", json={
        "query_type": "nucleotide",
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
    assert body["query_type"] == "nucleotide"
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
