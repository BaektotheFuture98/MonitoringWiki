from conftest import git, write

from wiki_mcp.pending import main, pending_raw_files, referenced_raw_paths


def add_raw(root, rel, text="보고서"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_referenced_from_sources_and_ingest_log(wiki_repo):
    write(wiki_repo, "wiki/log.md",
          "# 작업 로그\n\n"
          "## [2026-10-01 10:20] ingest | raw/2026-10-01/101010.txt\n- 처리\n\n"
          "## [2026-10-02 09:10] ingest | 보고서\n- 원본: `raw/2026-10-02/080000.txt` 처리\n\n"
          "## [2026-10-02 10:00] lint | raw/2026-10-02/090000.txt 언급만\n")
    git(wiki_repo, "commit", "-am", "log")
    assert referenced_raw_paths(wiki_repo, "main") == {
        "raw/2026-10-01/101010.txt",
        "raw/2026-10-02/080000.txt",
    }


def test_pending_lists_uncompiled_raw(wiki_repo):
    add_raw(wiki_repo, "raw/2026-10-01/101010.txt")
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    (wiki_repo / "raw" / ".submit.lock").write_text("", encoding="utf-8")
    assert pending_raw_files(wiki_repo, "main") == ["raw/2026-10-02/120000.txt"]


def test_uncommitted_compile_is_still_pending(wiki_repo):
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    write(wiki_repo, "wiki/patterns/new-pattern.md", "---\nid: new-pattern\nsources: [raw/2026-10-02/120000.txt]\n---\n# 새 패턴\n")
    assert pending_raw_files(wiki_repo, "main") == ["raw/2026-10-02/120000.txt"]


def test_cli_output(wiki_repo, monkeypatch, capsys):
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    assert main() == 0
    out = capsys.readouterr().out
    assert "컴파일 대기 1건" in out
    assert "raw/2026-10-02/120000.txt" in out


def test_cli_nothing_pending(wiki_repo, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    assert main() == 0
    assert "컴파일 대기 중인 raw가 없습니다." in capsys.readouterr().out


def test_cli_requires_root(monkeypatch, capsys):
    monkeypatch.delenv("WIKI_ROOT", raising=False)
    assert main() == 2


def test_cli_bad_ref(wiki_repo, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    monkeypatch.setenv("WIKI_REF", "no-such-branch")
    assert main() == 1
    assert "no-such-branch" in capsys.readouterr().err
