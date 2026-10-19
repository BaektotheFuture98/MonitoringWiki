"""MCP 도구와 REST가 함께 쓰는 처리. 인증·인가·속도 제한을 여기서 처리하고 SDK·웹 프레임워크와 독립적으로 테스트한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from wiki_mcp.services import wiki_query
from wiki_mcp.core.auth import TokenEntry, TokenStore, require_scope
from wiki_mcp.services.compile_service import CompileService
from wiki_mcp.core.config import Settings
from wiki_mcp.core.ratelimit import RateLimiter
from wiki_mcp.repositories.store import WikiStore

T = TypeVar("T")


@dataclass
class Services:
    settings: Settings
    tokens: TokenStore
    wiki: WikiStore
    compiler: CompileService
    limiter: RateLimiter


def _run(svc: Services, authorization: str | None, scope: str, action: Callable[[TokenEntry], T]) -> T:
    entry = svc.tokens.authenticate(authorization)
    require_scope(entry, scope)
    return action(entry)


def handle_get_index(svc: Services, authorization: str | None) -> str:
    return _run(svc, authorization, "read", lambda entry: wiki_query.read_index(svc.wiki))


def handle_get_pattern(
    svc: Services,
    authorization: str | None,
    pattern_id: str,
    sections: list[str] | None = None,
) -> str:
    return _run(svc, authorization, "read",
                lambda entry: wiki_query.read_pattern(svc.wiki, pattern_id, sections))


def handle_get_infra(svc: Services, authorization: str | None) -> str:
    return _run(svc, authorization, "read", lambda entry: wiki_query.read_infra(svc.wiki))


def handle_submit_report(svc: Services, authorization: str | None, text: str, *, wait: float) -> dict[str, Any]:
    def action(entry: TokenEntry) -> dict[str, Any]:
        svc.limiter.check(entry.name)
        return svc.compiler.submit(text, token=entry.name, wait=wait)

    return _run(svc, authorization, "submit", action)


def handle_get_job(svc: Services, authorization: str | None, job_id: str) -> dict[str, Any]:
    return _run(svc, authorization, "submit", lambda entry: svc.compiler.get(job_id))


def handle_retry_job(svc: Services, authorization: str | None, job_id: str, *, wait: float) -> dict[str, Any]:
    def action(entry: TokenEntry) -> dict[str, Any]:
        svc.limiter.check(entry.name)
        return svc.compiler.retry(job_id, token=entry.name, wait=wait)

    return _run(svc, authorization, "submit", action)

