import threading

import pytest

from wiki_mcp.store.wiki_store import FileWikiStore, WikiPathError


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "root"
    (root / "wiki" / "patterns").mkdir(parents=True)
    (root / "wiki" / "index.md").write_text("색인\n", encoding="utf-8")
    (root / "wiki" / "patterns" / "b.md").write_text("b\n", encoding="utf-8")
    (root / "wiki" / "patterns" / "a.md").write_text("a\n", encoding="utf-8")
    (root / "wiki" / "patterns" / ".a.md.123.tmp").write_text("임시\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("규칙\n", encoding="utf-8")
    return FileWikiStore(root)


def test_read_and_exists(store):
    assert store.read("wiki/index.md") == "색인\n"
    assert store.read("AGENTS.md") == "규칙\n"
    assert store.exists("wiki/index.md")
    assert not store.exists("wiki/missing.md")
    with pytest.raises(FileNotFoundError):
        store.read("wiki/missing.md")


def test_list_returns_sorted_files_without_hidden(store):
    assert store.list("wiki/patterns") == ["wiki/patterns/a.md", "wiki/patterns/b.md"]
    assert store.list("wiki/missing") == []


def test_write_atomic_creates_parents_and_uses_lf(store):
    store.write_atomic("wiki/infra/cluster.md", "첫 줄\n둘째 줄\n")
    path = store.root / "wiki" / "infra" / "cluster.md"
    assert path.read_bytes() == "첫 줄\n둘째 줄\n".encode("utf-8")
    store.write_atomic("wiki/infra/cluster.md", "바뀜\n")
    assert path.read_text(encoding="utf-8") == "바뀜\n"
    assert [p.name for p in path.parent.iterdir()] == ["cluster.md"]


@pytest.mark.parametrize("bad", ["../x.md", "/etc/passwd", "wiki/../../x.md", "wiki\\index.md", ""])
def test_rejects_paths_outside_root(store, bad):
    with pytest.raises(WikiPathError):
        store.read(bad)


@pytest.mark.parametrize("path", ["AGENTS.md", "raw/2026-10-15/100000.txt"])
def test_write_only_under_wiki(store, path):
    with pytest.raises(WikiPathError):
        store.write_atomic(path, "x")


def test_snapshot_copies_wiki_tree(store, tmp_path):
    dest = tmp_path / "state" / "snapshots" / "s1"
    store.snapshot(dest)
    store.write_atomic("wiki/index.md", "바뀐 색인\n")
    assert (dest / "index.md").read_text(encoding="utf-8") == "색인\n"
    assert (dest / "patterns" / "a.md").exists()


def test_write_lock_is_exclusive(store):
    entered = threading.Event()
    with store.write_lock():
        thread = threading.Thread(target=lambda: (store.write_lock().__enter__(), entered.set()))
        thread.start()
        assert not entered.wait(0.1)
    assert entered.wait(1)
    thread.join()
