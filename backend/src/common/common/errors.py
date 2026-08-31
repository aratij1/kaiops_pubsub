from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.resilience import CircuitOpenError


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    code: str
    message: str
    retryable: bool = False
    category: str = "application"


def request_trace_id(request: Request) -> str:
    """Return the request correlation identifier without trusting empty headers."""
    existing = str(getattr(request.state, "trace_id", "") or "").strip()
    header = str(request.headers.get("x-trace-id") or "").strip()
    trace_id = existing or header or uuid4().hex
    request.state.trace_id = trace_id
    return trace_id


def error_response_payload(
    request: Request,
    descriptor: ErrorDescriptor,
    *,
    detail: Any | None = None,
    validation_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the versioned error contract while retaining FastAPI's detail key."""
    trace_id = request_trace_id(request)
    public_detail = descriptor.message if detail is None else detail
    payload: dict[str, Any] = {
        "detail": public_detail,
        "trace_id": trace_id,
        "error": {
            "contract_version": "kaiops.error.v1",
            "code": descriptor.code,
            "message": descriptor.message,
            "category": descriptor.category,
            "retryable": descriptor.retryable,
            "trace_id": trace_id,
        },
    }
    if validation_errors:
        payload["error"]["validation_errors"] = validation_errors
    return payload


def safe_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose actionable locations and messages but never rejected input values."""
    return [
        {
            "location": [str(part) for part in item.get("loc", ())],
            "message": str(item.get("msg") or "Invalid value"),
            "type": str(item.get("type") or "validation_error"),
        }
        for item in errors
    ]


def install_exception_handlers(app: FastAPI, logger: logging.Logger) -> None:
    """Install one error contract across every service created by common.service."""

    @app.exception_handler(RequestValidationError)
    async def request_validation_failed(request: Request, exc: RequestValidationError) -> JSONResponse:
        descriptor = ErrorDescriptor(
            code="request_validation_failed",
            message="The request did not satisfy the endpoint contract.",
            category="validation",
        )
        return JSONResponse(
            status_code=422,
            headers={"x-trace-id": request_trace_id(request)},
            content=error_response_payload(
                request,
                descriptor,
                detail="Request validation failed",
                validation_errors=safe_validation_errors(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handled_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        structured_detail = exc.detail if isinstance(exc.detail, dict) else {}
        retryable = exc.status_code in {408, 425, 429, 502, 503, 504} or structured_detail.get("retryable") is True
        message = (
            str(exc.detail)
            if isinstance(exc.detail, str)
            else str(structured_detail.get("message") or "The request could not be completed.")
        )
        descriptor = ErrorDescriptor(
            code=str(structured_detail.get("code") or f"http_{exc.status_code}"),
            message=message,
            retryable=retryable,
            category="downstream" if exc.status_code >= 500 else "request",
        )
        headers = dict(exc.headers or {})
        headers["x-trace-id"] = request_trace_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content=error_response_payload(request, descriptor, detail=exc.detail),
        )

    @app.exception_handler(CircuitOpenError)
    async def database_circuit_open(request: Request, _exc: CircuitOpenError) -> JSONResponse:
        descriptor = ErrorDescriptor(
            code="database_temporarily_unavailable",
            message="The database is recovering. Please retry in a few seconds.",
            retryable=True,
            category="dependency",
        )
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "5", "x-trace-id": request_trace_id(request)},
            content=error_response_payload(request, descriptor),
        )

    @app.exception_handler(Exception)
    async def unhandled_application_error(request: Request, exc: Exception) -> JSONResponse:
        trace_id = request_trace_id(request)
        logger.exception(
            "unhandled_application_error",
            extra={"method": request.method, "path": request.url.path, "trace_id": trace_id},
            exc_info=exc,
        )
        descriptor = ErrorDescriptor(
            code="internal_error",
            message="An unexpected service error occurred.",
            category="internal",
        )
        return JSONResponse(
            status_code=500,
            headers={"x-trace-id": trace_id},
            content=error_response_payload(request, descriptor),
        )
