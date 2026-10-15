import asyncio
from types import SimpleNamespace

import pytest
from conftest import make_settings, write_tokens
from starlette.testclient import TestClient

from wiki_mcp.app import _authorization, build_services, create_app, create_mcp
from wiki_mcp.wiki_reader import WikiReadError


@pytest.fixture
def settings(wiki_root, tmp_path):
    s = make_settings(wiki_root, tmp_path)
    write_tokens(s.tokens_file, ("query-agent", "read-secret", ["read"]))
    return s


def test_healthz_without_token(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_mcp_requires_valid_token(settings, headers):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json={}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_create_app_fails_without_index(settings):
    (settings.wiki_root / "wiki" / "index.md").unlink()
    with pytest.raises(WikiReadError):
        create_app(settings)


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
