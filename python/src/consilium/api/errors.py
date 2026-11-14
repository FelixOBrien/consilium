from __future__ import annotations

from typing import NoReturn

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from consilium.api.schemas.common import (  # pragma: allowlist secret
    ErrorBody,
    ErrorEnvelope,
    FieldError,
)
from consilium.api.store import StoreError  # pragma: allowlist secret

_STATUS_CODES = {
    400: "bad_request",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
}


def envelope(code: str, message: str, fields: list[FieldError] | None = None) -> dict[str, object]:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, fields=fields))
    return body.model_dump(mode="json", exclude_none=True)


def fail(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=envelope(code, message))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StoreError)
    async def store_error(_request: object, exc: StoreError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=envelope(exc.code, exc.message))

    @app.exception_handler(HTTPException)
    async def http_error(_request: object, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        message = detail if isinstance(detail, str) else "Request failed."
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(status_code=exc.status_code, content=envelope(code, message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: object, exc: RequestValidationError) -> JSONResponse:
        fields = [
            FieldError(loc=[str(part) for part in error["loc"]], message=error["msg"])
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=envelope("validation_error", "Request validation failed.", fields),
        )
