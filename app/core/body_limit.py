"""Reject oversized request bodies before they are buffered and parsed.

Parsing a JSON body holds several copies of it in memory, so without a cap a
single huge submission can exhaust the API's memory. The cap is derived from
the query length limits, so raising those raises it too.
"""
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.config import get_settings

# Room for FASTA headers, line breaks and the rest of the JSON body
_OVERHEAD_BYTES = 1_000_000


def max_request_bytes() -> int:
    """Return the largest request body the API accepts, in bytes."""
    settings = get_settings()
    longest = max(settings.MAX_QUERY_LENGTH_NT, settings.MAX_QUERY_LENGTH_AA)
    return 2 * longest + _OVERHEAD_BYTES


def _too_large_detail(limit: int) -> str:
    return (
        f"Request body exceeds {limit:,} bytes. Queries are limited to "
        f"{get_settings().MAX_QUERY_LENGTH_NT:,} nucleotides or "
        f"{get_settings().MAX_QUERY_LENGTH_AA:,} amino acids per job."
    )


class BodySizeLimitMiddleware:
    """Return 413 for bodies over ``max_request_bytes()``.

    A declared Content-Length over the limit is rejected without reading the
    body. A body without one (a chunked upload) is read here, up to the limit,
    and replayed to the app; reading stops as soon as it passes the limit.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        limit = max_request_bytes()
        too_large = JSONResponse({"detail": _too_large_detail(limit)}, status_code=413)
        length = Headers(scope=scope).get("content-length")
        if length is not None:
            # The server rejects bodies that don't match a declared length
            if length.isdigit() and int(length) > limit:
                return await too_large(scope, receive, send)
            return await self.app(scope, receive, send)

        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break  # client disconnected
            chunks.append(message.get("body", b""))
            received += len(chunks[-1])
            if received > limit:
                return await too_large(scope, receive, send)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
