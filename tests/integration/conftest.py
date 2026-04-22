"""Integration test configuration.

SlowAPI rate limiting has two code paths that try to reach Redis:
  1. The @limiter.limit() decorator wraps endpoints in a sync_wrapper that calls
     self._check_request_limit() AND then reads request.state.view_rate_limit.
  2. SlowAPIMiddleware.dispatch() also checks limits and reads view_rate_limit.

We stub both so integration tests run without a live Redis instance.
"""
import pytest
from unittest.mock import patch
from fastapi import Request
from starlette.responses import Response


async def _passthrough_dispatch(self, request: Request, call_next) -> Response:
    return await call_next(request)


def _stub_check_request_limit(request, endpoint, is_middleware, *args, **kwargs):
    # Set the attribute that sync_wrapper reads after the check returns.
    request.state.view_rate_limit = None


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    from app.core.limiter import limiter as _limiter
    with (
        patch.object(
            _limiter,
            "_check_request_limit",
            side_effect=_stub_check_request_limit,
        ),
        patch("slowapi.middleware.SlowAPIMiddleware.dispatch", new=_passthrough_dispatch),
    ):
        yield
