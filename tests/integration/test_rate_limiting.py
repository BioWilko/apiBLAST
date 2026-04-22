"""Integration tests for rate limiting behaviour.

Tests the exception handler directly rather than needing live Redis.
"""
import pytest
from unittest.mock import MagicMock
from fastapi import Request
from slowapi.errors import RateLimitExceeded

from app.core.exceptions import rate_limit_handler


def _make_request(path: str = "/api/v1/jobs") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def _make_rate_limit_exceeded() -> RateLimitExceeded:
    """Construct a RateLimitExceeded with a properly-shaped limit mock."""
    limit_mock = MagicMock()
    limit_mock.error_message = None
    limit_mock.limit = MagicMock()
    limit_mock.limit.__str__ = lambda self: "10 per 1 minute"
    exc = RateLimitExceeded(limit_mock)
    return exc


@pytest.mark.asyncio
async def test_rate_limit_handler_returns_429():
    request = _make_request()
    exc = _make_rate_limit_exceeded()
    response = await rate_limit_handler(request, exc)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_handler_includes_retry_after():
    request = _make_request()
    exc = _make_rate_limit_exceeded()
    response = await rate_limit_handler(request, exc)
    assert "Retry-After" in response.headers
    assert response.headers["Retry-After"] == "60"
