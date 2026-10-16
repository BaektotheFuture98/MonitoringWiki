import json

import pytest

from wiki_mcp.service.auth import AuthError, ScopeError, TokenStore, hash_token, main, require_scope


def write_tokens(path, items):
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    path = write_tokens(tmp_path / "tokens.json", [
        {"name": "query-agent", "sha256": hash_token("read-secret"), "scopes": ["read"]},
        {"name": "approver", "sha256": hash_token("submit-secret"), "scopes": ["submit"]},
    ])
    return TokenStore.load(path)


def test_authenticate_ok(store):
    assert store.authenticate("Bearer read-secret").name == "query-agent"
    assert store.authenticate("bearer submit-secret").name == "approver"


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer wrong"])
def test_authenticate_rejects(store, header):
    with pytest.raises(AuthError):
        store.authenticate(header)


def test_require_scope(store):
    entry = store.authenticate("Bearer read-secret")
    require_scope(entry, "read")
    with pytest.raises(ScopeError, match="submit"):
        require_scope(entry, "submit")


def test_load_rejects_unknown_scope(tmp_path):
    path = write_tokens(tmp_path / "t.json", [{"name": "x", "sha256": hash_token("t"), "scopes": ["admin"]}])
    with pytest.raises(ValueError, match="admin"):
        TokenStore.load(path)


def test_load_rejects_bad_hash(tmp_path):
    path = write_tokens(tmp_path / "t.json", [{"name": "x", "sha256": "abc", "scopes": ["read"]}])
    with pytest.raises(ValueError, match="sha256"):
        TokenStore.load(path)


def test_load_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        TokenStore.load(write_tokens(tmp_path / "t.json", []))


def test_hash_cli(capsys):
    assert main(["read-secret"]) == 0
    assert capsys.readouterr().out.strip() == hash_token("read-secret")
