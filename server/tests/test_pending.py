from conftest import write

from wiki_mcp.services.pending import main, pending_raw_files, referenced_raw_paths


def add_raw(root, rel, text="보고서"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_referenced_from_sources_and_ingest_log(wiki_root, wiki_store):
    write(wiki_root, "wiki/log.md",
          "# 작업 로그\n\n"
          "## [2026-10-01 10:20] ingest | raw/2026-10-01/101010.txt\n- 처리\n\n"
          "## [2026-10-02 09:10] ingest | 보고서\n- 원본: `raw/2026-10-02/080000.txt` 처리\n\n"
          "## [2026-10-02 10:00] lint | raw/2026-10-02/090000.txt 언급만\n")
    assert referenced_raw_paths(wiki_store) == {
        "raw/2026-10-01/101010.txt",
        "raw/2026-10-02/080000.txt",
    }


def test_pending_lists_uncompiled_raw(wiki_root, wiki_store):
    add_raw(wiki_root, "raw/2026-10-01/101010.txt")
    add_raw(wiki_root, "raw/2026-10-02/120000.txt")
    (wiki_root / "raw" / ".submit.lock").write_text("", encoding="utf-8")
    assert pending_raw_files(wiki_root, wiki_store) == ["raw/2026-10-02/120000.txt"]


def test_pattern_sources_in_working_tree_count(wiki_root, wiki_store):
    add_raw(wiki_root, "raw/2026-10-02/120000.txt")
    write(wiki_root, "wiki/patterns/new-pattern.md",
          "---\nid: new-pattern\nsources: [raw/2026-10-02/120000.txt]\n---\n# 새 패턴\n")
    assert pending_raw_files(wiki_root, wiki_store) == []


def test_cli_output(wiki_root, monkeypatch, capsys):
    add_raw(wiki_root, "raw/2026-10-02/120000.txt")
    monkeypatch.setenv("WIKI_ROOT", str(wiki_root))
    assert main() == 0
    out = capsys.readouterr().out
    assert "컴파일 대기 1건" in out
    assert "raw/2026-10-02/120000.txt" in out


def test_cli_nothing_pending(wiki_root, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(wiki_root))
    assert main() == 0
    assert "컴파일 대기 중인 raw가 없습니다." in capsys.readouterr().out


def test_cli_requires_root(monkeypatch, capsys):
    monkeypatch.delenv("WIKI_ROOT", raising=False)
    assert main() == 2


def test_cli_missing_wiki(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path))
    assert main() == 1
    assert "wiki/index.md" in capsys.readouterr().err
