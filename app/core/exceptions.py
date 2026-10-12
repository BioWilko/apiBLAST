from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
        headers={"Retry-After": "60"},
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 response with just the type, location and message of each error.

    FastAPI's default also echoes each failing value back ("input"), which for
    an oversized query means returning the whole query to the client.
    """
    errors = [{k: err[k] for k in ("type", "loc", "msg") if k in err} for err in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
