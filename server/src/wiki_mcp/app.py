"""MCP 서버 조립: 도구 등록, 인증 미들웨어, 상태 확인, 실행.

도구 처리기(git 호출, 파일 락 대기)는 이벤트 루프를 막지 않도록 스레드에서 실행한다.
"""
from __future__ import annotations

import json

import uvicorn
from anyio import to_thread
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import wiki_reader
from .access_log import AccessLog
from .auth import AuthError, TokenStore
from .config import Settings, load_settings
from .handlers import (
    Services,
    handle_get_index,
    handle_get_infra,
    handle_get_pattern,
    handle_submit_report,
)
from .instructions import load_instructions
from .ratelimit import RateLimiter
from .raw_store import RawStore

SUBMIT_LIMIT_PER_MINUTE = 10

GET_INDEX_DESCRIPTION = "장애 패턴 위키의 색인 전체를 반환합니다. 요약과 대표 시그니처 열을 보고 입력과 의미가 같은 패턴을 고르세요."
GET_PATTERN_DESCRIPTION = "패턴 페이지를 반환합니다. sections로 원인, 증상, 해결방법, 관련 패턴 중 일부만 요청할 수 있습니다."
GET_INFRA_DESCRIPTION = "현재 클러스터 구성(티어, 역할별 노드 수, 버전)을 반환합니다. 패턴 일치 판단의 근거로는 쓰지 마세요."
SUBMIT_DESCRIPTION = (
    "사람이 승인한 장애 보고서 전체(원인 판단·결론·권장 조치 포함)를 원문 그대로 제출합니다. "
    "질문에는 절대 사용하지 마세요. 제출된 보고서는 담당자가 수동으로 컴파일한 뒤 위키에 반영됩니다."
)


def build_services(settings: Settings) -> Services:
    return Services(
        settings=settings,
        tokens=TokenStore.load(settings.tokens_file),
        store=RawStore(settings.wiki_root, settings.tz, settings.max_report_bytes),
        limiter=RateLimiter(SUBMIT_LIMIT_PER_MINUTE, 60.0),
        log=AccessLog(settings.access_log),
    )


def _authorization(ctx: Context) -> str | None:
    request = ctx.request_context.request
    if request is None:
        return None
    return request.headers.get("authorization")


def create_mcp(svc: Services, instructions: str) -> FastMCP:
    mcp = FastMCP("monitoring-wiki", instructions=instructions)

    # ctx는 이벤트 루프 스레드에서 읽고, 처리기만 작업 스레드로 넘긴다.
    @mcp.tool(description=GET_INDEX_DESCRIPTION)
    async def get_index(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_index(svc, authorization))

    @mcp.tool(description=GET_PATTERN_DESCRIPTION)
    async def get_pattern(id: str, ctx: Context, sections: list[str] | None = None) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_pattern(svc, authorization, id, sections))

    @mcp.tool(description=GET_INFRA_DESCRIPTION)
    async def get_infra(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_infra(svc, authorization))

    @mcp.tool(description=SUBMIT_DESCRIPTION)
    async def submit_report(text: str, ctx: Context) -> str:
        authorization = _authorization(ctx)
        result = await to_thread.run_sync(lambda: handle_submit_report(svc, authorization, text))
        return json.dumps(result, ensure_ascii=False)

    return mcp


class BearerAuthMiddleware:
    """`/healthz`를 제외한 HTTP 요청에 유효한 Bearer 토큰을 요구한다(인증). 스코프(인가)는 도구 처리기가 확인한다."""

    def __init__(self, app, tokens: TokenStore, open_paths: tuple[str, ...] = ("/healthz",)) -> None:
        self.app = app
        self.tokens = tokens
        self.open_paths = set(open_paths)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] not in self.open_paths:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            try:
                self.tokens.authenticate(headers.get("authorization"))
            except AuthError as exc:
                response = JSONResponse({"error": str(exc)}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings):
    wiki_reader.check_ref(settings.wiki_root, settings.wiki_ref)
    svc = build_services(settings)
    instructions = load_instructions(settings.wiki_root, settings.wiki_ref)
    app = create_mcp(svc, instructions).streamable_http_app()

    async def healthz(request: Request) -> JSONResponse:
        try:
            wiki_reader.check_ref(settings.wiki_root, settings.wiki_ref)
        except wiki_reader.WikiReadError as exc:
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
        return JSONResponse({"status": "ok", "ref": settings.wiki_ref})

    app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    return BearerAuthMiddleware(app, svc.tokens)


def main() -> None:
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
