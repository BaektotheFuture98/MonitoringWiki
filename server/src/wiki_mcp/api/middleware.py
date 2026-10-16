"""HTTP 요청에 Bearer 토큰을 요구하는 ASGI 미들웨어(인증만). 스코프(인가)는 처리기가 확인한다."""
from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse

from wiki_mcp.service.auth import AuthError, TokenStore


class BearerAuthMiddleware:
    def __init__(self, app: Any, tokens: TokenStore, open_paths: tuple[str, ...] = ("/healthz",)) -> None:
        self.app = app
        self.tokens = tokens
        self.open_paths = set(open_paths)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] not in self.open_paths:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            try:
                self.tokens.authenticate(headers.get("authorization"))
            except AuthError as exc:
                response = JSONResponse(
                    {"error": str(exc), "code": "unauthenticated"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
