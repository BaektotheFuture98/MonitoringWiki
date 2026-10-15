import asyncio
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from plans import FakePlanGenerator, plan_dict
from starlette.testclient import TestClient

from wiki_mcp.app import build_services, create_app
from wiki_mcp.config import ConfigError
from wiki_mcp.mcp_adapter import _authorization, create_mcp
from wiki_mcp.wiki_reader import WikiReadError

READ = {"Authorization": "Bearer read-secret"}
REPO_CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}


def make_app(settings, **overrides):
    return create_app(replace(settings, **overrides), generator=FakePlanGenerator(plan_dict()))


def test_healthz_without_token(server_settings):
    with TestClient(make_app(server_settings)) as client:
        response = client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_healthz_reports_missing_index(server_settings):
    with TestClient(make_app(server_settings)) as client:
        (server_settings.wiki_root / "wiki" / "index.md").unlink()
        assert client.get("/healthz").status_code == 503


def test_create_app_fails_without_index(server_settings):
    (server_settings.wiki_root / "wiki" / "index.md").unlink()
    with pytest.raises(WikiReadError):
        make_app(server_settings)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_disabled_by_default(server_settings, path):
    with TestClient(make_app(server_settings)) as client:
        assert client.get(path, headers=READ).status_code == 404


def test_docs_enabled_without_token(server_settings):
    with TestClient(make_app(server_settings, enable_docs=True)) as client:
        assert client.get("/docs").status_code == 200
        assert "/api/reports" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_mcp_requires_valid_token(server_settings, headers):
    with TestClient(make_app(server_settings)) as client:
        response = client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_mcp_initialize_with_token(server_settings):
    # FastMCP의 DNS 리바인딩 보호 때문에 Host가 127.0.0.1이어야 한다(SPIKE.md "Host 헤더 검사").
    # 부모 lifespan에서 세션 관리자를 시작하지 않으면 이 요청이 500이 된다.
    headers = {**READ, "Accept": "application/json, text/event-stream"}
    with TestClient(make_app(server_settings), base_url="http://127.0.0.1:8000") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 200
    assert "monitoring-wiki" in response.text


def test_tools_registered(server_settings):
    mcp = create_mcp(build_services(server_settings, generator=FakePlanGenerator(plan_dict())), "가이드")
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {"get_index", "get_pattern", "get_infra", "submit_report"}


def test_build_services_requires_llm_settings(server_settings):
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_services(server_settings)


def test_build_services_with_llm_settings(server_settings):
    shutil.copy(REPO_CLAUDE_MD, server_settings.wiki_root / "CLAUDE.md")
    svc = build_services(replace(server_settings, anthropic_api_key="sk-test", llm_model="claude-test"))
    assert svc.compiler.generator is not None


def test_authorization_header_from_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"authorization": "Bearer x"})))
    assert _authorization(ctx) == "Bearer x"


def test_authorization_without_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
    assert _authorization(ctx) is None
