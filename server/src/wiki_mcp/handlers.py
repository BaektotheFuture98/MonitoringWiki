"""MCP 도구의 실제 처리. 인증·인가·속도 제한·접근 로그를 여기서 처리하고 SDK와 독립적으로 테스트한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from . import wiki_reader
from .access_log import AccessLog, summarize_report
from .auth import AuthError, TokenEntry, TokenStore, require_scope
from .config import Settings
from .ratelimit import RateLimiter
from .raw_store import RawStore

T = TypeVar("T")


@dataclass
class Services:
    settings: Settings
    tokens: TokenStore
    store: RawStore
    limiter: RateLimiter
    log: AccessLog


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
    s = svc.settings
    return _run(svc, authorization, "get_index", "read", {},
                lambda entry: wiki_reader.read_index(s.wiki_root, s.wiki_ref))


def handle_get_pattern(
    svc: Services,
    authorization: str | None,
    pattern_id: str,
    sections: list[str] | None = None,
) -> str:
    s = svc.settings
    args = {"id": pattern_id, "sections": list(sections) if sections else None}
    return _run(svc, authorization, "get_pattern", "read", args,
                lambda entry: wiki_reader.read_pattern(s.wiki_root, s.wiki_ref, pattern_id, sections))


def handle_get_infra(svc: Services, authorization: str | None) -> str:
    s = svc.settings
    return _run(svc, authorization, "get_infra", "read", {},
                lambda entry: wiki_reader.read_infra(s.wiki_root, s.wiki_ref))


def handle_submit_report(svc: Services, authorization: str | None, text: str) -> dict[str, str]:
    def action(entry: TokenEntry) -> dict[str, str]:
        svc.limiter.check(entry.name)
        result = svc.store.save(text)
        return {"status": result.status, "path": result.path, "message": result.message}

    return _run(svc, authorization, "submit_report", "submit", summarize_report(text), action)
