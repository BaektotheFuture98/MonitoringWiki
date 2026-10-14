from pathlib import Path

import pytest

from wiki_mcp.config import ConfigError, load_settings

BASE = {
    "WIKI_ROOT": "/repo",
    "WIKI_TOKENS_FILE": "/etc/wiki/tokens.json",
    "WIKI_ACCESS_LOG": "/var/log/wiki/access.jsonl",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.wiki_root == Path("/repo")
    assert s.tokens_file == Path("/etc/wiki/tokens.json")
    assert s.access_log == Path("/var/log/wiki/access.jsonl")
    assert s.wiki_ref == "main"
    assert s.tz == "Asia/Seoul"
    assert s.max_report_bytes == 1_048_576
    assert (s.host, s.port) == ("127.0.0.1", 8000)


def test_overrides():
    s = load_settings({
        **BASE,
        "WIKI_REF": "release",
        "WIKI_TZ": "UTC",
        "WIKI_MAX_REPORT_BYTES": "2048",
        "WIKI_HOST": "0.0.0.0",
        "WIKI_PORT": "9000",
    })
    assert (s.wiki_ref, s.tz, s.max_report_bytes, s.host, s.port) == ("release", "UTC", 2048, "0.0.0.0", 9000)


@pytest.mark.parametrize("missing", ["WIKI_ROOT", "WIKI_TOKENS_FILE", "WIKI_ACCESS_LOG"])
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_port(value):
    with pytest.raises(ConfigError, match="WIKI_PORT"):
        load_settings({**BASE, "WIKI_PORT": value})
