"""서버 조립(컴포지션 루트): 서비스를 만들고 FastAPI 앱에 REST·MCP·인증 미들웨어를 올린 뒤 실행한다."""
from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from wiki_mcp.wiki import wiki_reader
from wiki_mcp.services.access_log import AccessLog
from wiki_mcp.api.rest import create_api_router, install_error_handlers
from wiki_mcp.core.auth import TokenStore
from wiki_mcp.services.compile_service import CompileService, JobStore
from wiki_mcp.core.config import ConfigError, Settings, load_env_file, load_settings
from wiki_mcp.services.handlers import Services
from wiki_mcp.instructions import load_instructions, read_agents_md
from wiki_mcp.services.llm import GeminiPlanGenerator, PlanGenerator, build_system_prompt
from wiki_mcp.core.masking import Masker, load_names
from wiki_mcp.api.mcp_adapter import create_mcp
from wiki_mcp.api.middleware import BearerAuthMiddleware
from wiki_mcp.core.ratelimit import RateLimiter
from wiki_mcp.wiki.raw_store import RawStore
from wiki_mcp.wiki.wiki_store import FileWikiStore, WikiStore
from wiki_mcp.wiki.wiki_writer import WikiWriter

SUBMIT_LIMIT_PER_MINUTE = 10
HEALTH_PATH = "/healthz"
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def _gemini_generator(settings: Settings, wiki: WikiStore) -> GeminiPlanGenerator:
    if not settings.gemini_api_key or not settings.llm_model:
        raise ConfigError("GEMINI_API_KEY와 WIKI_LLM_MODEL이 필요합니다(.env 또는 환경 변수).")
    return GeminiPlanGenerator(
        api_key=settings.gemini_api_key,
        model=settings.llm_model,
        system_prompt=build_system_prompt(read_agents_md(wiki)),
        timeout=float(settings.compile_timeout),
    )


def build_services(
    settings: Settings,
    *,
    generator: PlanGenerator | None = None,
    now: Callable[[], datetime] | None = None,
) -> Services:
    tz = ZoneInfo(settings.tz)
    now = now or (lambda: datetime.now(tz))
    wiki = FileWikiStore(settings.wiki_root)
    log = AccessLog(settings.access_log)
    writer = WikiWriter(wiki, settings.state_root / "snapshots", settings.snapshot_keep, now)
    compiler = CompileService(
        raw_store=RawStore(settings.wiki_root, settings.tz, settings.max_report_bytes, now=now),
        wiki=wiki,
        writer=writer,
        generator=generator or _gemini_generator(settings, wiki),
        masker=Masker(load_names(settings.mask_names_file)),
        jobs=JobStore(settings.state_root / "jobs"),
        log=log,
        timeout=float(settings.compile_timeout),
        now=now,
    )
    return Services(
        settings=settings,
        tokens=TokenStore.load(settings.tokens_file),
        wiki=wiki,
        compiler=compiler,
        writer=writer,
        limiter=RateLimiter(SUBMIT_LIMIT_PER_MINUTE, 60.0),
        log=log,
        now=now,
    )


def create_app(
    settings: Settings,
    *,
    generator: PlanGenerator | None = None,
    now: Callable[[], datetime] | None = None,
) -> FastAPI:
    svc = build_services(settings, generator=generator, now=now)
    wiki_reader.check_wiki(svc.wiki)
    mcp = create_mcp(svc, load_instructions(svc.wiki))
    mcp_app = mcp.streamable_http_app()  # session_manager는 이 호출 뒤에 생긴다

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # 하위 앱의 lifespan은 실행되지 않으므로 MCP 세션 관리자를 여기서 직접 실행한다(SPIKE.md 조건 1).
        svc.compiler.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            svc.compiler.stop()

    docs = settings.enable_docs
    app = FastAPI(
        title="monitoring-wiki",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    install_error_handlers(app)

    @app.get(HEALTH_PATH, include_in_schema=False)
    def healthz() -> JSONResponse:
        try:
            wiki_reader.check_wiki(svc.wiki)
        except wiki_reader.WikiReadError as exc:
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
        return JSONResponse({"status": "ok"})

    app.include_router(create_api_router(svc))
    app.router.routes.extend(mcp_app.routes)  # /mcp 경로를 그대로 유지한다
    open_paths = (HEALTH_PATH, *DOCS_PATHS) if docs else (HEALTH_PATH,)
    app.add_middleware(BearerAuthMiddleware, tokens=svc.tokens, open_paths=open_paths)
    return app


def main() -> None:
    load_env_file()
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
