import pytest

from wiki_mcp.wiki import wiki_reader as wr


def test_check_wiki_ok(wiki_store):
    wr.check_wiki(wiki_store)


def test_check_wiki_missing_index(wiki_root, wiki_store):
    (wiki_root / "wiki" / "index.md").unlink()
    with pytest.raises(wr.WikiReadError, match="wiki/index.md"):
        wr.check_wiki(wiki_store)


def test_read_index_reads_working_tree(wiki_root, wiki_store):
    assert "[sample-pattern](patterns/sample-pattern.md)" in wr.read_index(wiki_store)
    (wiki_root / "wiki" / "index.md").write_text("바뀐 색인\n", encoding="utf-8")
    assert wr.read_index(wiki_store) == "바뀐 색인\n"


def test_read_infra(wiki_store):
    assert "# 클러스터 구성" in wr.read_infra(wiki_store)


def test_read_pattern_drops_sources(wiki_store):
    text = wr.read_pattern(wiki_store, "sample-pattern")
    assert "\nsources:" not in text  # "resources:" 부분 문자열과 구분
    assert "raw/" not in text
    assert "summary: 샘플 요약" in text
    assert "# 샘플 패턴" in text
    for heading in ("## 원인", "## 증상", "## 해결방법", "## 관련 패턴"):
        assert heading in text


def test_read_pattern_selected_sections(wiki_store):
    text = wr.read_pattern(wiki_store, "sample-pattern", ["해결방법"])
    assert "## 해결방법" in text and "해결 본문" in text
    assert "## 원인" not in text and "원인 본문" not in text
    assert "# 샘플 패턴" in text


def test_drop_field_multiline_list():
    frontmatter = ["id: x", "sources:", "  - raw/a.txt", "  - raw/b.txt", "summary: s"]
    assert wr.drop_field(frontmatter, "sources") == ["id: x", "summary: s"]


@pytest.mark.parametrize("bad", ["../CLAUDE", "-x", "Sample", "a/b", "", "abc\n"])
def test_read_pattern_rejects_bad_id(wiki_store, bad):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_store, bad)


def test_read_pattern_rejects_unknown_section(wiki_store):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_store, "sample-pattern", ["원인", "근거 한계"])


def test_read_pattern_missing(wiki_store):
    with pytest.raises(wr.PatternNotFound, match="get_index"):
        wr.read_pattern(wiki_store, "no-such-pattern")


def test_pattern_path():
    assert wr.pattern_path("a-b") == "wiki/patterns/a-b.md"
