import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from plans import FakePlanGenerator, create_item, plan_dict

from wiki_mcp.app import build_services
from wiki_mcp.auth import AuthError, ScopeError
from wiki_mcp.compile_service import JobNotRetryable
from wiki_mcp.handlers import (
    handle_get_guide,
    handle_get_index,
    handle_get_infra,
    handle_get_job,
    handle_get_pattern,
    handle_retry_job,
    handle_submit_report,
    handle_update_infra,
)
from wiki_mcp.infra import InfraError, InfraSpec, Tier
from wiki_mcp.ratelimit import RateLimited

READ = "Bearer read-secret"
SUBMIT = "Bearer submit-secret"
INFRA = "Bearer infra-secret"
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
SPEC = InfraSpec(version="8.12.2", master=3, client=5, data=60,
                 tiers=(Tier("HOT", 20, ("RC12",)), Tier("WARM", 40, ("RC10", "RC17"))))


@pytest.fixture
def generator():
    return FakePlanGenerator(plan_dict(create_item()))


@pytest.fixture
def svc(server_settings, generator):
    services = build_services(server_settings, generator=generator, now=lambda: NOW)
    services.compiler.start()
    yield services
    services.compiler.stop()


def records(svc, tool=None):
    lines = svc.settings.access_log.read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if tool is None or r["tool"] == tool]


def test_read_handlers(svc):
    assert "[sample-pattern](patterns/sample-pattern.md)" in handle_get_index(svc, READ)
    assert "\nsources:" not in handle_get_pattern(svc, READ, "sample-pattern", ["원인"])
    assert records(svc, "get_pattern")[-1]["args"] == {"id": "sample-pattern", "sections": ["원인"]}
    assert "# 클러스터 구성" in handle_get_infra(svc, READ)
    assert "외부 가이드 본문입니다." in handle_get_guide(svc, READ)
    last = records(svc)[-1]
    assert (last["token"], last["tool"], last["status"]) == ("query-agent", "get_guide", "ok")


def test_missing_token_is_logged(svc):
    with pytest.raises(AuthError):
        handle_get_index(svc, None)
    assert (records(svc)[-1]["token"], records(svc)[-1]["status"]) == ("-", "unauthenticated")


@pytest.mark.parametrize("token, call", [
    (SUBMIT, lambda svc, t: handle_get_index(svc, t)),
    (INFRA, lambda svc, t: handle_get_guide(svc, t)),
    (READ, lambda svc, t: handle_submit_report(svc, t, "보고서", wait=1)),
    (INFRA, lambda svc, t: handle_submit_report(svc, t, "보고서", wait=1)),
    (READ, lambda svc, t: handle_get_job(svc, t, "0123456789ab")),
    (READ, lambda svc, t: handle_retry_job(svc, t, "0123456789ab", wait=1)),
    (SUBMIT, lambda svc, t: handle_update_infra(svc, t, SPEC)),
    (READ, lambda svc, t: handle_update_infra(svc, t, SPEC)),
])
def test_scope_enforced(svc, token, call):
    with pytest.raises(ScopeError):
        call(svc, token)
    assert records(svc)[-1]["status"] == "error:ScopeError"
    assert not list((svc.settings.wiki_root / "raw").rglob("*.txt"))


def test_submit_compiles_and_logs_without_body(svc):
    view = handle_submit_report(svc, SUBMIT, "비밀 원문 보고서", wait=5)
    assert (view["status"], view["created"]) == ("compiled", ["new-pattern"])
    assert "비밀 원문 보고서" not in svc.settings.access_log.read_text(encoding="utf-8")
    submit = records(svc, "submit_report")[-1]
    assert (submit["token"], submit["status"]) == ("web-backend", "ok")
    assert submit["args"]["length"] == len("비밀 원문 보고서")
    assert records(svc, "compile")[-1]["status"] == "compiled"
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
    assert records(svc, "retry_job")[-1]["args"] == {"job_id": failed["job_id"]}


def test_submit_rate_limited(svc):
    for i in range(10):
        handle_submit_report(svc, SUBMIT, f"보고서 {i}", wait=0)
    with pytest.raises(RateLimited):
        handle_submit_report(svc, SUBMIT, "보고서 10", wait=0)
    assert records(svc, "submit_report")[-1]["status"] == "error:RateLimited"


def test_update_infra(svc):
    result = handle_update_infra(svc, INFRA, SPEC)
    assert (result["status"], result["as_of"]) == ("updated", "2026-10-15")
    page = (svc.settings.wiki_root / "wiki" / "infra" / "cluster.md").read_text(encoding="utf-8")
    assert "as_of: 2026-10-15" in page and "source: API(infra-admin)" in page
    assert (svc.settings.state_root / "snapshots" / result["snapshot"]).is_dir()
    assert records(svc, "update_infra")[-1]["args"] == {"version": "8.12.2", "tiers": 2}


def test_update_infra_rejects_invalid(svc):
    with pytest.raises(InfraError):
        handle_update_infra(svc, INFRA, replace(SPEC, data=61))
    assert records(svc, "update_infra")[-1]["status"] == "error:InfraError"
