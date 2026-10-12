"""Optional priority tokens.

Requests without an ``Authorization`` header are unaffected. A request with
``Authorization: Bearer <token>`` must carry a valid, unrevoked token; its
holder bypasses rate limits, the queue-depth guard and deprioritisation.
"""
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core import database
from app.services import tokens


@dataclass(frozen=True)
class TokenInfo:
    id: str
    label: str


def priority_token(request: Request) -> TokenInfo | None:
    """Return the request's verified priority token, if it presented one."""
    return getattr(request.state, "priority_token", None)


def _lookup(raw: str) -> TokenInfo | None:
    with database.SessionLocal() as db:
        token = tokens.verify(db, raw)
        return TokenInfo(id=token.id, label=token.label) if token else None


class PriorityTokenMiddleware:
    """Verify bearer tokens and record the holder in ``request.state``.

    Must be the outermost middleware so the token is known before SlowAPI
    checks rate limits.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        scheme, _, raw = Request(scope).headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            return await self.app(scope, receive, send)

        info = await run_in_threadpool(_lookup, raw.strip())
        if info is None:
            response = JSONResponse(
                {"detail": "Invalid or revoked priority token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            return await response(scope, receive, send)

        scope.setdefault("state", {})["priority_token"] = info
        return await self.app(scope, receive, send)
