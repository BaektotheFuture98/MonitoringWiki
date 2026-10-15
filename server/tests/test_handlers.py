import json

import pytest
from conftest import make_settings, write_tokens

from wiki_mcp.access_log import AccessLog
from wiki_mcp.auth import AuthError, ScopeError, TokenStore
from wiki_mcp.handlers import (
    Services,
    handle_get_index,
    handle_get_infra,
    handle_get_pattern,
    handle_submit_report,
)
from wiki_mcp.ratelimit import RateLimited, RateLimiter
from wiki_mcp.raw_store import PENDING_MESSAGE, RawStore
from wiki_mcp.wiki_store import FileWikiStore

READ = "Bearer read-secret"
SUBMIT = "Bearer submit-secret"


@pytest.fixture
def svc(wiki_root, tmp_path):
    settings = make_settings(wiki_root, tmp_path)
    write_tokens(settings.tokens_file,
                 ("query-agent", "read-secret", ["read"]),
                 ("approver", "submit-secret", ["submit"]))
    return Services(
        settings=settings,
        tokens=TokenStore.load(settings.tokens_file),
        wiki=FileWikiStore(wiki_root),
        store=RawStore(wiki_root, "Asia/Seoul", 10_000),
        limiter=RateLimiter(2, 60.0),
        log=AccessLog(settings.access_log),
    )


def last_record(svc):
    lines = svc.settings.access_log.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_get_index_with_read_token(svc):
    assert "[sample-pattern](patterns/sample-pattern.md)" in handle_get_index(svc, READ)
    record = last_record(svc)
    assert (record["token"], record["tool"], record["status"]) == ("query-agent", "get_index", "ok")


def test_get_pattern_and_infra(svc):
    assert "\nsources:" not in handle_get_pattern(svc, READ, "sample-pattern", ["원인"])
    assert last_record(svc)["args"] == {"id": "sample-pattern", "sections": ["원인"]}
    assert "# 클러스터 구성" in handle_get_infra(svc, READ)


def test_missing_token_is_logged(svc):
    with pytest.raises(AuthError):
        handle_get_index(svc, None)
    record = last_record(svc)
    assert (record["token"], record["status"]) == ("-", "unauthenticated")


def test_read_token_cannot_submit(svc):
    with pytest.raises(ScopeError):
        handle_submit_report(svc, READ, "승인된 보고서")
    assert not list((svc.settings.wiki_root / "raw").rglob("*.txt"))
    assert last_record(svc)["status"] == "error:ScopeError"


def test_submit_token_cannot_read(svc):
    with pytest.raises(ScopeError):
        handle_get_index(svc, SUBMIT)


def test_submit_saves_and_logs_without_body(svc):
    result = handle_submit_report(svc, SUBMIT, "비밀 원문 보고서")
    assert result["status"] == "saved"
    assert result["message"] == PENDING_MESSAGE
    assert (svc.settings.wiki_root / result["path"]).read_text(encoding="utf-8") == "비밀 원문 보고서"
    assert "비밀 원문 보고서" not in svc.settings.access_log.read_text(encoding="utf-8")
    assert last_record(svc)["args"]["length"] == len("비밀 원문 보고서")


def test_submit_rate_limited(svc):
    handle_submit_report(svc, SUBMIT, "보고서 1")
    handle_submit_report(svc, SUBMIT, "보고서 2")
    with pytest.raises(RateLimited):
        handle_submit_report(svc, SUBMIT, "보고서 3")
    assert last_record(svc)["status"] == "error:RateLimited"
