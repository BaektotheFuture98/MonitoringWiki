"""환경 변수에서 서버 설정을 읽는다. `.env`는 main()에서 load_env_file()로 먼저 읽어 환경 변수로 채운다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

ENV_FILE_VAR = "WIKI_ENV_FILE"
DEFAULT_ENV_FILE = ".env"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """필수 설정이 없거나 값이 잘못됨."""


@dataclass(frozen=True)
class Settings:
    wiki_root: Path
    tz: str
    tokens_file: Path | None
    access_log: Path
    max_report_bytes: int
    host: str
    port: int
    state_dir: Path | None = None
    gemini_api_key: str = field(default="", repr=False)
    llm_model: str = ""
    mask_names_file: Path | None = None
    compile_wait_seconds: int = 90
    mcp_compile_wait_seconds: int = 30
    compile_timeout: int = 300
    snapshot_keep: int = 20
    enable_docs: bool = False
    auth_disabled: bool = False

    @property
    def state_root(self) -> Path:
        """작업 기록과 스냅샷을 두는 폴더. 지정하지 않으면 <WIKI_ROOT>/.state."""
        return self.state_dir if self.state_dir is not None else self.wiki_root / ".state"


def load_env_file(env: Mapping[str, str] | None = None) -> bool:
    """WIKI_ENV_FILE(기본 ./.env)을 읽어 os.environ에 채운다. 이미 설정된 환경 변수가 우선하고, 파일이 없으면 False."""
    env = os.environ if env is None else env
    path = env.get(ENV_FILE_VAR, "").strip() or DEFAULT_ENV_FILE
    return load_dotenv(path, override=False)


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} 환경 변수가 필요합니다.")
    return value


def _optional(env: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, "").strip() or default


def _optional_path(env: Mapping[str, str], key: str) -> Path | None:
    value = env.get(key, "").strip()
    return Path(value) if value else None


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


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ConfigError(f"{key}는 true 또는 false여야 합니다: {raw!r}")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    auth_disabled = _bool(env, "WIKI_AUTH_DISABLED", False)
    return Settings(
        wiki_root=Path(_required(env, "WIKI_ROOT")),
        tz=_optional(env, "WIKI_TZ", "Asia/Seoul"),
        tokens_file=_optional_path(env, "WIKI_TOKENS_FILE") if auth_disabled else Path(_required(env, "WIKI_TOKENS_FILE")),
        access_log=Path(_required(env, "WIKI_ACCESS_LOG")),
        max_report_bytes=_positive_int(env, "WIKI_MAX_REPORT_BYTES", 1_048_576),
        host=_optional(env, "WIKI_HOST", "127.0.0.1"),
        port=_positive_int(env, "WIKI_PORT", 8000),
        state_dir=_optional_path(env, "WIKI_STATE_DIR"),
        gemini_api_key=_required(env, "GEMINI_API_KEY"),
        llm_model=_required(env, "WIKI_LLM_MODEL"),
        mask_names_file=_optional_path(env, "WIKI_MASK_NAMES_FILE"),
        compile_wait_seconds=_positive_int(env, "WIKI_COMPILE_WAIT_SECONDS", 90),
        mcp_compile_wait_seconds=_positive_int(env, "WIKI_MCP_COMPILE_WAIT_SECONDS", 30),
        compile_timeout=_positive_int(env, "WIKI_COMPILE_TIMEOUT", 300),
        snapshot_keep=_positive_int(env, "WIKI_SNAPSHOT_KEEP", 20),
        enable_docs=_bool(env, "WIKI_ENABLE_DOCS", False),
        auth_disabled=auth_disabled,
    )
