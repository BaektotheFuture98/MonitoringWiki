"""베어러 토큰 인증과 스코프 확인. 토큰은 sha256 해시로만 보관한다."""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from dataclasses import dataclass
from pathlib import Path

VALID_SCOPES = frozenset({"read", "submit", "infra"})


class AuthError(Exception):
    """토큰이 없거나 유효하지 않음(HTTP 401)."""


class ScopeError(Exception):
    """토큰에 필요한 스코프가 없음(HTTP 403)."""


@dataclass(frozen=True)
class TokenEntry:
    name: str
    sha256: str
    scopes: frozenset[str]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


ANONYMOUS = TokenEntry("anonymous", "", VALID_SCOPES)


class TokenStore:
    def __init__(self, entries: list[TokenEntry], *, open_access: bool = False) -> None:
        if not entries and not open_access:
            raise ValueError("토큰이 하나 이상 필요합니다.")
        self.entries = entries
        self.open_access = open_access

    @classmethod
    def open(cls) -> "TokenStore":
        """인증을 끈 저장소(내부망 테스트용). 모든 요청을 모든 스코프를 가진 anonymous로 취급한다."""
        return cls([], open_access=True)

    @classmethod
    def load(cls, path: Path) -> "TokenStore":
        data = json.loads(path.read_text(encoding="utf-8"))
        entries: list[TokenEntry] = []
        for item in data:
            scopes = frozenset(item["scopes"])
            unknown = scopes - VALID_SCOPES
            if unknown:
                raise ValueError(f"알 수 없는 스코프 {sorted(unknown)} (토큰 {item['name']})")
            digest = str(item["sha256"]).lower()
            if len(digest) != 64:
                raise ValueError(f"sha256 값이 올바르지 않습니다 (토큰 {item['name']})")
            entries.append(TokenEntry(item["name"], digest, scopes))
        return cls(entries)

    def authenticate(self, authorization: str | None) -> TokenEntry:
        if self.open_access:
            return ANONYMOUS
        if not authorization:
            raise AuthError("Bearer 토큰이 필요합니다.")
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthError("Bearer 토큰이 필요합니다.")
        digest = hash_token(token)
        match: TokenEntry | None = None
        for entry in self.entries:
            if hmac.compare_digest(entry.sha256, digest):
                match = entry
        if match is None:
            raise AuthError("유효하지 않은 토큰입니다.")
        return match


def require_scope(entry: TokenEntry, scope: str) -> None:
    if scope not in entry.scopes:
        raise ScopeError(f"토큰 {entry.name}에 '{scope}' 권한이 없습니다.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("사용법: python -m wiki_mcp.core.auth <토큰>", file=sys.stderr)
        return 2
    print(hash_token(args[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
