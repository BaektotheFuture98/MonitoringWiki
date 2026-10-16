import os
from pathlib import Path

import pytest

from wiki_mcp.core.config import ConfigError, load_env_file, load_settings

BASE = {
    "WIKI_ROOT": "/repo",
    "WIKI_TOKENS_FILE": "/etc/wiki/tokens.json",
    "WIKI_ACCESS_LOG": "/var/log/wiki/access.jsonl",
    "ANTHROPIC_API_KEY": "sk-test-secret",
    "WIKI_LLM_MODEL": "claude-test",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.wiki_root == Path("/repo")
    assert s.tokens_file == Path("/etc/wiki/tokens.json")
    assert s.access_log == Path("/var/log/wiki/access.jsonl")
    assert s.tz == "Asia/Seoul"
    assert s.max_report_bytes == 1_048_576
    assert (s.host, s.port) == ("127.0.0.1", 8000)
    assert s.state_root == Path("/repo") / ".state"
    assert (s.anthropic_api_key, s.llm_model) == ("sk-test-secret", "claude-test")
    assert s.mask_names_file is None
    assert (s.compile_wait_seconds, s.mcp_compile_wait_seconds, s.compile_timeout) == (90, 30, 300)
    assert s.snapshot_keep == 20
    assert s.enable_docs is False


def test_overrides():
    s = load_settings({
        **BASE,
        "WIKI_TZ": "UTC",
        "WIKI_MAX_REPORT_BYTES": "2048",
        "WIKI_HOST": "0.0.0.0",
        "WIKI_PORT": "9000",
        "WIKI_STATE_DIR": "/var/lib/wiki",
        "WIKI_MASK_NAMES_FILE": "/etc/wiki/names.txt",
        "WIKI_COMPILE_WAIT_SECONDS": "60",
        "WIKI_MCP_COMPILE_WAIT_SECONDS": "20",
        "WIKI_COMPILE_TIMEOUT": "120",
        "WIKI_SNAPSHOT_KEEP": "5",
        "WIKI_ENABLE_DOCS": "true",
    })
    assert (s.tz, s.max_report_bytes, s.host, s.port) == ("UTC", 2048, "0.0.0.0", 9000)
    assert s.state_root == Path("/var/lib/wiki")
    assert s.mask_names_file == Path("/etc/wiki/names.txt")
    assert (s.compile_wait_seconds, s.mcp_compile_wait_seconds, s.compile_timeout, s.snapshot_keep) == (60, 20, 120, 5)
    assert s.enable_docs is True


@pytest.mark.parametrize(
    "missing", ["WIKI_ROOT", "WIKI_TOKENS_FILE", "WIKI_ACCESS_LOG", "ANTHROPIC_API_KEY", "WIKI_LLM_MODEL"]
)
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_port(value):
    with pytest.raises(ConfigError, match="WIKI_PORT"):
        load_settings({**BASE, "WIKI_PORT": value})


def test_invalid_bool():
    with pytest.raises(ConfigError, match="WIKI_ENABLE_DOCS"):
        load_settings({**BASE, "WIKI_ENABLE_DOCS": "maybe"})


def test_api_key_hidden_from_repr():
    assert "sk-test-secret" not in repr(load_settings(BASE))


def test_load_env_file_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("WIKI_TEST_FROM_FILE=file\nWIKI_TEST_EXISTING=file\n", encoding="utf-8")
    monkeypatch.setenv("WIKI_ENV_FILE", str(env_file))
    monkeypatch.setenv("WIKI_TEST_EXISTING", "env")
    monkeypatch.delenv("WIKI_TEST_FROM_FILE", raising=False)
    try:
        assert load_env_file() is True
        assert os.environ["WIKI_TEST_FROM_FILE"] == "file"
        assert os.environ["WIKI_TEST_EXISTING"] == "env"
    finally:
        # .env가 채운 값은 monkeypatch가 기록하지 않으므로 직접 지운다.
        os.environ.pop("WIKI_TEST_FROM_FILE", None)


def test_load_env_file_missing_is_not_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_ENV_FILE", str(tmp_path / "none.env"))
    assert load_env_file() is False
