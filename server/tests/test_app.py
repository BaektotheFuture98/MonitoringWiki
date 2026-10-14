import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from wiki_mcp.app import _authorization, build_services, create_app, create_mcp
from wiki_mcp.auth import hash_token
from wiki_mcp.config import Settings
from wiki_mcp.wiki_reader import WikiReadError


@pytest.fixture
def settings(wiki_repo, tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps([
        {"name": "query-agent", "sha256": hash_token("read-secret"), "scopes": ["read"]},
    ]), encoding="utf-8")
    return Settings(
        wiki_root=wiki_repo, wiki_ref="main", tz="Asia/Seoul", tokens_file=tokens,
        access_log=tmp_path / "access.jsonl", max_report_bytes=10_000, host="127.0.0.1", port=8000,
    )


def test_healthz_without_token(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ref": "main"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_mcp_requires_valid_token(settings, headers):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json={}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_create_app_fails_without_ref(settings):
    with pytest.raises(WikiReadError):
        create_app(replace(settings, wiki_ref="no-such-branch"))


def test_tools_registered(settings):
    mcp = create_mcp(build_services(settings), "가이드")
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {"get_index", "get_pattern", "get_infra", "submit_report"}


def test_authorization_header_from_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"authorization": "Bearer x"})))
    assert _authorization(ctx) == "Bearer x"


def test_authorization_without_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
    assert _authorization(ctx) is None
