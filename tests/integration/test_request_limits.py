"""Integration tests for request body limits and validation error responses."""
import pytest
from fastapi.testclient import TestClient

from app.core.body_limit import max_request_bytes
from app.main import create_app


# Every request here is rejected before the endpoint runs, so no database or
# queue is needed.
@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def _job(query: str) -> dict:
    return {"query_type": "nucleotide", "database": "testdb", "query": query}


def test_oversized_body_rejected_with_413(api):
    resp = api.post("/api/v1/jobs", json=_job(">s\n" + "A" * max_request_bytes()))
    assert resp.status_code == 413
    assert "nucleotides" in resp.json()["detail"]
    assert len(resp.content) < 1000


def test_oversized_chunked_body_rejected_with_413(api):
    def chunks():
        yield b'{"query_type": "nucleotide", "database": "testdb", "query": ">s\\n'
        for _ in range(max_request_bytes() // 65_536 + 2):
            yield b"A" * 65_536
        yield b'"}'

    resp = api.post(
        "/api/v1/jobs", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413


def test_chunked_body_under_limit_reaches_app(api):
    def chunks():
        yield b'{"query_type": "nucleotide", "database": "testdb", '
        yield b'"query": ">s\\nACGT", "max_hits": 0}'

    resp = api.post(
        "/api/v1/jobs", content=chunks(), headers={"Content-Type": "application/json"}
    )
    # Reaches validation (max_hits must be >= 1), so the body was replayed intact
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "max_hits"]


def test_validation_error_does_not_echo_query(api):
    query = ">s\n" + "ACGT" * 150_000  # 600,000 nt: under the body limit, over the length limit
    resp = api.post("/api/v1/jobs", json=_job(query))
    assert resp.status_code == 422
    assert "ACGTACGT" not in resp.text
    assert len(resp.content) < 1000
    [err] = resp.json()["detail"]
    assert set(err) == {"type", "loc", "msg"}
    assert "exceeds maximum" in err["msg"]
