"""환경 변수에서 서버 설정을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(Exception):
    """필수 설정이 없거나 값이 잘못됨."""


@dataclass(frozen=True)
class Settings:
    wiki_root: Path
    wiki_ref: str
    tz: str
    tokens_file: Path
    access_log: Path
    max_report_bytes: int
    host: str
    port: int


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} 환경 변수가 필요합니다.")
    return value


def _optional(env: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, "").strip() or default


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}는 정수여야 합니다: {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key}는 0보다 커야 합니다: {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        wiki_root=Path(_required(env, "WIKI_ROOT")),
        wiki_ref=_optional(env, "WIKI_REF", "main"),
        tz=_optional(env, "WIKI_TZ", "Asia/Seoul"),
        tokens_file=Path(_required(env, "WIKI_TOKENS_FILE")),
        access_log=Path(_required(env, "WIKI_ACCESS_LOG")),
        max_report_bytes=_positive_int(env, "WIKI_MAX_REPORT_BYTES", 1_048_576),
        host=_optional(env, "WIKI_HOST", "127.0.0.1"),
        port=_positive_int(env, "WIKI_PORT", 8000),
    )
