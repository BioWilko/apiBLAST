from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.core.auth import priority_token


class _Limiter(Limiter):
    """Limiter that exempts requests carrying a priority token."""

    def _check_request_limit(self, request, endpoint_func, in_middleware=True):
        if priority_token(request) is not None:
            # SlowAPI reads this after the check to set response headers
            request.state.view_rate_limit = None
            return
        super()._check_request_limit(request, endpoint_func, in_middleware)


limiter = _Limiter(
    key_func=get_remote_address,
    storage_uri=get_settings().REDIS_URL,
    default_limits=["200/minute"],
    in_memory_fallback_enabled=True,
)
