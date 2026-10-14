import pytest

from wiki_mcp import wiki_reader as wr


def test_check_ref_ok(wiki_repo):
    wr.check_ref(wiki_repo, "main")


def test_check_ref_missing(wiki_repo):
    with pytest.raises(wr.WikiReadError):
        wr.check_ref(wiki_repo, "no-such-branch")


def test_read_index_ignores_uncommitted_changes(wiki_repo):
    (wiki_repo / "wiki/index.md").write_text("작업 중인 변경\n", encoding="utf-8")
    text = wr.read_index(wiki_repo, "main")
    assert "작업 중인 변경" not in text
    assert "| [p1](patterns/p1.md) | 요약 |" in text


def test_read_infra(wiki_repo):
    assert "# 클러스터 구성" in wr.read_infra(wiki_repo, "main")


def test_read_pattern_drops_sources(wiki_repo):
    text = wr.read_pattern(wiki_repo, "main", "sample-pattern")
    assert "\nsources:" not in text  # "resources:" 부분 문자열과 구분
    assert "raw/" not in text
    assert "summary: 샘플 요약" in text
    assert "# 샘플 패턴" in text
    for heading in ("## 원인", "## 증상", "## 해결방법", "## 관련 패턴"):
        assert heading in text


def test_read_pattern_selected_sections(wiki_repo):
    text = wr.read_pattern(wiki_repo, "main", "sample-pattern", ["해결방법"])
    assert "## 해결방법" in text and "해결 본문" in text
    assert "## 원인" not in text and "원인 본문" not in text
    assert "# 샘플 패턴" in text


def test_drop_field_multiline_list():
    frontmatter = ["id: x", "sources:", "  - raw/a.txt", "  - raw/b.txt", "summary: s"]
    assert wr.drop_field(frontmatter, "sources") == ["id: x", "summary: s"]


@pytest.mark.parametrize("bad", ["../CLAUDE", "-x", "Sample", "a/b", "", "abc\n"])
def test_read_pattern_rejects_bad_id(wiki_repo, bad):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_repo, "main", bad)


def test_read_pattern_rejects_unknown_section(wiki_repo):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_repo, "main", "sample-pattern", ["원인", "근거 한계"])


def test_read_pattern_missing(wiki_repo):
    with pytest.raises(wr.PatternNotFound, match="get_index"):
        wr.read_pattern(wiki_repo, "main", "no-such-pattern")


def test_list_files(wiki_repo):
    assert wr.list_files(wiki_repo, "main", "wiki/patterns") == ["wiki/patterns/sample-pattern.md"]
    assert wr.list_files(wiki_repo, "main", "wiki/missing") == []
