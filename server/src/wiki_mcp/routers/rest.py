"""REST 어댑터: 요청 본문을 검증해 공용 처리기로 넘기고, 결과와 예외를 HTTP 응답으로 바꾼다."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from wiki_mcp.core.auth import AuthError, ScopeError
from wiki_mcp.core.errors import (
    JobNotFound,
    JobNotRetryable,
    ReportRejected,
    ReportTooLarge,
    WikiReadError,
)
from wiki_mcp.core.ratelimit import RateLimited
from wiki_mcp.services.handlers import (
    Services,
    handle_get_infra,
    handle_get_job,
    handle_retry_job,
    handle_submit_report,
)

SUBMIT_STATUS_CODES = {"compiled": 200, "duplicate": 200, "queued": 202, "running": 202, "failed": 502}
ERROR_RESPONSES: tuple[tuple[type[Exception], int, str], ...] = (
    (AuthError, 401, "unauthenticated"),
    (ScopeError, 403, "forbidden"),
    (JobNotFound, 404, "not_found"),
    (JobNotRetryable, 409, "not_retryable"),
    (ReportTooLarge, 413, "too_large"),
    (ReportRejected, 422, "invalid_report"),
    (RateLimited, 429, "rate_limited"),
    (WikiReadError, 503, "wiki_unavailable"),
)


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def _submit_response(view: dict[str, Any]) -> JSONResponse:
    body = {**view, "code": "compile_failed"} if view["status"] == "failed" else view
    return JSONResponse(body, status_code=SUBMIT_STATUS_CODES[view["status"]])


def create_api_router(svc: Services) -> APIRouter:
    # 처리기가 블로킹(파일 읽기, 컴파일 대기)이므로 라우트를 동기 함수로 두어 스레드 풀에서 실행되게 한다.
    router = APIRouter(prefix="/api")
    wait = float(svc.settings.compile_wait_seconds)

    @router.get("/infra")
    def get_infra(authorization: str | None = Header(default=None)) -> dict[str, str]:
        return {"text": handle_get_infra(svc, authorization)}

    @router.post("/reports")
    def submit_report(body: ReportIn, authorization: str | None = Header(default=None)) -> JSONResponse:
        return _submit_response(handle_submit_report(svc, authorization, body.text, wait=wait))

    @router.get("/reports/{job_id}")
    def get_job(job_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        return JSONResponse(handle_get_job(svc, authorization, job_id))

    @router.post("/reports/{job_id}/retry")
    def retry_job(job_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        return _submit_response(handle_retry_job(svc, authorization, job_id, wait=wait))

    return router


def _error_handler(status: int, code: str) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse({"error": str(exc), "code": code}, status_code=status, headers=headers)

    return handle


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    # 입력값을 되돌려주지 않도록 위치와 메시지만 남긴다(보고서 본문이 응답에 섞이지 않게).
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [".".join(str(part) for part in error["loc"]) + f": {error['msg']}" for error in errors]
    return JSONResponse(
        {"error": "요청 형식이 올바르지 않습니다.", "code": "invalid_request", "detail": detail},
        status_code=422,
    )


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status, code in ERROR_RESPONSES:
        app.add_exception_handler(exc_type, _error_handler(status, code))
    app.add_exception_handler(RequestValidationError, _validation_handler)
