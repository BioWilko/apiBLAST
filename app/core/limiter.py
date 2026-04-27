from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=get_settings().REDIS_URL,
    default_limits=["200/minute"],
    in_memory_fallback_enabled=True,
)
