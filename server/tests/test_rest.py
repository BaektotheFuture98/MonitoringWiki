import threading
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from plans import FakePlanGenerator, create_item, plan_dict
from starlette.testclient import TestClient

from wiki_mcp.app import create_app

READ = {"Authorization": "Bearer read-secret"}
SUBMIT = {"Authorization": "Bearer submit-secret"}
INFRA = {"Authorization": "Bearer infra-secret"}
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def generator():
    return FakePlanGenerator(plan_dict(create_item()))


@pytest.fixture
def client(server_settings, generator):
    with TestClient(create_app(server_settings, generator=generator, now=lambda: NOW)) as test_client:
        yield test_client


def test_read_infra(client):
    assert "# 클러스터 구성" in client.get("/api/infra", headers=READ).json()["text"]


def test_auth_errors(client):
    response = client.get("/api/infra")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "Bearer 토큰이 필요합니다.", "code": "unauthenticated"}
    response = client.get("/api/infra", headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")


def test_submit_compiled_then_job_and_retry_conflict(client):
    response = client.post("/api/reports", json={"text": "승인된 보고서"}, headers=SUBMIT)
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["created"]) == ("compiled", ["new-pattern"])
    job = client.get(f"/api/reports/{body['job_id']}", headers=SUBMIT)
    assert (job.status_code, job.json()["status"]) == (200, "compiled")
    retry = client.post(f"/api/reports/{body['job_id']}/retry", headers=SUBMIT)
    assert (retry.status_code, retry.json()["code"]) == (409, "not_retryable")


def test_submit_duplicate(client):
    first = client.post("/api/reports", json={"text": "같은 보고서"}, headers=SUBMIT).json()
    response = client.post("/api/reports", json={"text": "같은 보고서"}, headers=SUBMIT)
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["raw_path"]) == ("duplicate", first["raw_path"])


def test_submit_failed_returns_502_and_retry(client, generator):
    generator.responses = [RuntimeError("LLM 장애")]
    response = client.post("/api/reports", json={"text": "보고서"}, headers=SUBMIT)
    assert response.status_code == 502
    body = response.json()
    assert (body["status"], body["code"]) == ("failed", "compile_failed")
    assert body["raw_path"].startswith("raw/")
    generator.responses = [plan_dict(create_item())]
    retry = client.post(f"/api/reports/{body['job_id']}/retry", headers=SUBMIT)
    assert (retry.status_code, retry.json()["status"]) == (200, "compiled")


def test_submit_returns_202_when_not_finished(server_settings):
    release = threading.Event()

    class BlockingGenerator:
        def generate_plan(self, masked_text, index_text, feedback=None):
            release.wait(5)
            return plan_dict(create_item())

    app = create_app(replace(server_settings, compile_wait_seconds=1), generator=BlockingGenerator(),
                     now=lambda: NOW)
    with TestClient(app) as test_client:
        response = test_client.post("/api/reports", json={"text": "보고서"}, headers=SUBMIT)
        release.set()
    assert response.status_code == 202
    assert response.json()["status"] in ("queued", "running")


@pytest.mark.parametrize("payload", [{}, {"text": 1}, {"text": "x", "extra": 1}])
def test_submit_invalid_body(client, payload):
    response = client.post("/api/reports", json=payload, headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_request")


def test_submit_empty_and_too_large(client):
    response = client.post("/api/reports", json={"text": "   "}, headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_report")
    response = client.post("/api/reports", json={"text": "가" * 5000}, headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (413, "too_large")


def test_unknown_job(client):
    response = client.get("/api/reports/0123456789ab", headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_submit_rate_limited(client):
    for i in range(10):
        client.post("/api/reports", json={"text": f"보고서 {i}"}, headers=SUBMIT)
    response = client.post("/api/reports", json={"text": "보고서 10"}, headers=SUBMIT)
    assert (response.status_code, response.json()["code"]) == (429, "rate_limited")


def test_infra_missing_page_is_503(client, server_settings):
    (server_settings.wiki_root / "wiki" / "infra" / "cluster.md").unlink()
    response = client.get("/api/infra", headers=READ)
    assert (response.status_code, response.json()["code"]) == (503, "wiki_unavailable")
