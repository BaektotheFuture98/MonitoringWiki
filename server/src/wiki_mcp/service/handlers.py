"""MCP 도구와 REST가 함께 쓰는 처리. 인증·인가·속도 제한·접근 로그를 여기서 처리하고 SDK·웹 프레임워크와 독립적으로 테스트한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, TypeVar

from wiki_mcp.store import wiki_reader
from wiki_mcp.service.access_log import AccessLog, summarize_report
from wiki_mcp.service.auth import AuthError, TokenEntry, TokenStore, require_scope
from wiki_mcp.service.compile_service import CompileService
from wiki_mcp.config import Settings
from wiki_mcp.service.infra import InfraSpec, infra_summary, render_infra, validate_infra
from wiki_mcp.instructions import load_instructions
from wiki_mcp.service.ratelimit import RateLimiter
from wiki_mcp.store.wiki_store import WikiStore
from wiki_mcp.store.wiki_writer import WikiWriter

T = TypeVar("T")


@dataclass
class Services:
    settings: Settings
    tokens: TokenStore
    wiki: WikiStore
    compiler: CompileService
    writer: WikiWriter
    limiter: RateLimiter
    log: AccessLog
    now: Callable[[], datetime]


def _run(
    svc: Services,
    authorization: str | None,
    tool: str,
    scope: str,
    args: dict[str, Any],
    action: Callable[[TokenEntry], T],
) -> T:
    try:
        entry = svc.tokens.authenticate(authorization)
    except AuthError:
        svc.log.write(token="-", tool=tool, args=args, status="unauthenticated")
        raise
    try:
        require_scope(entry, scope)
        result = action(entry)
    except Exception as exc:
        svc.log.write(token=entry.name, tool=tool, args=args, status=f"error:{type(exc).__name__}")
        raise
    svc.log.write(token=entry.name, tool=tool, args=args, status="ok")
    return result


def handle_get_index(svc: Services, authorization: str | None) -> str:
    return _run(svc, authorization, "get_index", "read", {},
                lambda entry: wiki_reader.read_index(svc.wiki))


def handle_get_pattern(
    svc: Services,
    authorization: str | None,
    pattern_id: str,
    sections: list[str] | None = None,
) -> str:
    args = {"id": pattern_id, "sections": list(sections) if sections else None}
    return _run(svc, authorization, "get_pattern", "read", args,
                lambda entry: wiki_reader.read_pattern(svc.wiki, pattern_id, sections))


def handle_get_infra(svc: Services, authorization: str | None) -> str:
    return _run(svc, authorization, "get_infra", "read", {},
                lambda entry: wiki_reader.read_infra(svc.wiki))


def handle_get_guide(svc: Services, authorization: str | None) -> str:
    return _run(svc, authorization, "get_guide", "read", {},
                lambda entry: load_instructions(svc.wiki))


def handle_submit_report(svc: Services, authorization: str | None, text: str, *, wait: float) -> dict[str, Any]:
    def action(entry: TokenEntry) -> dict[str, Any]:
        svc.limiter.check(entry.name)
        return svc.compiler.submit(text, token=entry.name, wait=wait)

    return _run(svc, authorization, "submit_report", "submit", summarize_report(text), action)


def handle_get_job(svc: Services, authorization: str | None, job_id: str) -> dict[str, Any]:
    return _run(svc, authorization, "get_job", "submit", {"job_id": job_id},
                lambda entry: svc.compiler.get(job_id))


def handle_retry_job(svc: Services, authorization: str | None, job_id: str, *, wait: float) -> dict[str, Any]:
    def action(entry: TokenEntry) -> dict[str, Any]:
        svc.limiter.check(entry.name)
        return svc.compiler.retry(job_id, token=entry.name, wait=wait)

    return _run(svc, authorization, "retry_job", "submit", {"job_id": job_id}, action)


def handle_update_infra(svc: Services, authorization: str | None, spec: InfraSpec) -> dict[str, str]:
    def action(entry: TokenEntry) -> dict[str, str]:
        validate_infra(spec)
        as_of = svc.now().date()
        source = f"API({entry.name})"
        snapshot = svc.writer.write_infra(
            render_infra(spec, as_of=as_of, source=source),
            summary=infra_summary(spec), as_of=as_of, source=source,
        )
        return {"status": "updated", "as_of": as_of.isoformat(), "snapshot": snapshot}

    args = {"version": spec.version, "tiers": len(spec.tiers)}
    return _run(svc, authorization, "update_infra", "infra", args, action)
