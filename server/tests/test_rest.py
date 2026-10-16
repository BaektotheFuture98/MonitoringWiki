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
INFRA_BODY = {
    "version": "8.12.2",
    "nodes": {"master": 3, "client": 5, "data": 60},
    "tiers": [
        {"name": "HOT", "data_nodes": 20, "racks": ["RC12"]},
        {"name": "WARM", "data_nodes": 40, "racks": ["RC10", "RC17"]},
    ],
    "notes": [],
    "unconfirmed": ["하드웨어 사양"],
}


@pytest.fixture
def generator():
    return FakePlanGenerator(plan_dict(create_item()))


@pytest.fixture
def client(server_settings, generator):
    with TestClient(create_app(server_settings, generator=generator, now=lambda: NOW)) as test_client:
        yield test_client


def test_read_endpoints(client):
    assert "[sample-pattern]" in client.get("/api/index", headers=READ).json()["text"]
    body = client.get("/api/patterns/sample-pattern", params={"sections": "원인,해결방법"}, headers=READ).json()
    assert "## 원인" in body["text"] and "## 해결방법" in body["text"] and "## 증상" not in body["text"]
    assert "# 클러스터 구성" in client.get("/api/infra", headers=READ).json()["text"]
    assert "외부 가이드 본문입니다." in client.get("/api/guide", headers=READ).json()["text"]


@pytest.mark.parametrize("path, status, code", [
    ("/api/patterns/no-such", 404, "not_found"),
    ("/api/patterns/Bad_ID", 422, "invalid_request"),
    ("/api/patterns/sample-pattern?sections=근거", 422, "invalid_request"),
])
def test_pattern_errors(client, path, status, code):
    response = client.get(path, headers=READ)
    assert (response.status_code, response.json()["code"]) == (status, code)


def test_auth_errors(client):
    response = client.get("/api/index")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "Bearer 토큰이 필요합니다.", "code": "unauthenticated"}
    response = client.get("/api/index", headers=SUBMIT)
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


def test_update_infra(client, server_settings):
    response = client.put("/api/infra", json=INFRA_BODY, headers=INFRA)
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["as_of"]) == ("updated", "2026-10-15")
    page = (server_settings.wiki_root / "wiki" / "infra" / "cluster.md").read_text(encoding="utf-8")
    assert "| HOT | 20 | RC12 |" in page and "source: API(infra-admin)" in page


@pytest.mark.parametrize("change, code", [
    ({"nodes": {"master": 3, "client": 5, "data": 61}}, "invalid_infra"),
    ({"notes": ["노드 10.0.0.1 교체"]}, "invalid_infra"),
    ({"nodes": {"master": -1, "client": 5, "data": 60}}, "invalid_request"),
    ({"unknown": 1}, "invalid_request"),
])
def test_update_infra_rejects(client, change, code):
    response = client.put("/api/infra", json={**INFRA_BODY, **change}, headers=INFRA)
    assert (response.status_code, response.json()["code"]) == (422, code)


def test_update_infra_requires_infra_scope(client):
    assert client.put("/api/infra", json=INFRA_BODY, headers=SUBMIT).status_code == 403
