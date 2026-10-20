from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from plans import FakePlanGenerator, create_item, plan_dict

from wiki_mcp.app import build_services
from wiki_mcp.core.auth import AuthError, ScopeError
from wiki_mcp.core.errors import JobNotRetryable
from wiki_mcp.services.compile_service import (
    handle_get_index,
    handle_get_infra,
    handle_get_job,
    handle_get_pattern,
    handle_retry_job,
    handle_submit_report,
)
from wiki_mcp.core.ratelimit import RateLimited

READ = "Bearer read-secret"
SUBMIT = "Bearer submit-secret"
INFRA = "Bearer infra-secret"
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def generator():
    return FakePlanGenerator(plan_dict(create_item()))


@pytest.fixture
def svc(server_settings, generator):
    services = build_services(server_settings, generator=generator, now=lambda: NOW)
    services.compiler.start()
    yield services
    services.compiler.stop()


def test_read_handlers(svc):
    assert "[sample-pattern](patterns/sample-pattern.md)" in handle_get_index(svc, READ)
    assert "\nsources:" not in handle_get_pattern(svc, READ, "sample-pattern", ["원인"])
    assert "# 클러스터 구성" in handle_get_infra(svc, READ)


def test_missing_token_rejected(svc):
    with pytest.raises(AuthError):
        handle_get_index(svc, None)


@pytest.mark.parametrize("token, call", [
    (SUBMIT, lambda svc, t: handle_get_index(svc, t)),
    (INFRA, lambda svc, t: handle_get_infra(svc, t)),
    (READ, lambda svc, t: handle_submit_report(svc, t, "보고서", wait=1)),
    (INFRA, lambda svc, t: handle_submit_report(svc, t, "보고서", wait=1)),
    (READ, lambda svc, t: handle_get_job(svc, t, "0123456789ab")),
    (READ, lambda svc, t: handle_retry_job(svc, t, "0123456789ab", wait=1)),
])
def test_scope_enforced(svc, token, call):
    with pytest.raises(ScopeError):
        call(svc, token)
    assert not list((svc.settings.wiki_root / "raw").rglob("*.txt"))


def test_submit_compiles(svc):
    view = handle_submit_report(svc, SUBMIT, "비밀 원문 보고서", wait=5)
    assert (view["status"], view["created"]) == ("compiled", ["new-pattern"])
    assert handle_get_job(svc, SUBMIT, view["job_id"])["status"] == "compiled"


def test_retry_only_failed(svc):
    view = handle_submit_report(svc, SUBMIT, "보고서", wait=5)
    with pytest.raises(JobNotRetryable):
        handle_retry_job(svc, SUBMIT, view["job_id"], wait=5)


def test_retry_failed_job(svc, generator):
    generator.responses = [RuntimeError("일시 오류")]
    failed = handle_submit_report(svc, SUBMIT, "보고서", wait=5)
    assert failed["status"] == "failed"
    generator.responses = [plan_dict(create_item())]
    assert handle_retry_job(svc, SUBMIT, failed["job_id"], wait=5)["status"] == "compiled"


def test_submit_rate_limited(svc):
    for i in range(10):
        handle_submit_report(svc, SUBMIT, f"보고서 {i}", wait=0)
    with pytest.raises(RateLimited):
        handle_submit_report(svc, SUBMIT, "보고서 10", wait=0)

