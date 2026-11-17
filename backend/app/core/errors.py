"""Structured API errors: every error response has the shape {"error": {"code", "message"}}."""

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(exc.code, exc.message),
        headers=exc.headers,
    )


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(f"http_{exc.status_code}", str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


def _without_input(errors: list[Any]) -> list[Any]:
    """Drop the submitted value from each error: FastAPI echoes it back as `input`."""
    return [{key: value for key, value in error.items() if key != "input"} for error in errors]


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    if request.url.path.endswith("/credential"):
        # The body of this request is a secret. An error must never repeat it, not even a
        # rejected one (too long, wrong type, extra field).
        errors = _without_input(errors)
    return JSONResponse(
        status_code=422,
        content=_body("validation_error", "The request is invalid.", errors),
    )
