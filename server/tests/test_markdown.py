from wiki_mcp.core.markdown import drop_field, split_frontmatter, split_sections


def test_split_frontmatter():
    frontmatter, body = split_frontmatter("---\nid: x\nsummary: s\n---\n# 제목\n본문")
    assert frontmatter == ["id: x", "summary: s"]
    assert body == ["# 제목", "본문"]


def test_split_frontmatter_without_frontmatter():
    assert split_frontmatter("# 제목\n본문") == ([], ["# 제목", "본문"])


def test_split_frontmatter_unclosed():
    assert split_frontmatter("---\nid: x\n본문") == ([], ["---", "id: x", "본문"])


def test_drop_field_multiline_list():
    frontmatter = ["id: x", "sources:", "  - raw/a.txt", "  - raw/b.txt", "summary: s"]
    assert drop_field(frontmatter, "sources") == ["id: x", "summary: s"]


def test_split_sections_keeps_order_and_head():
    head, sections = split_sections(["# 제목", "", "## 원인", "a", "", "## 증상", "b"])
    assert head == ["# 제목", ""]
    assert sections == [("원인", ["## 원인", "a", ""]), ("증상", ["## 증상", "b"])]


def test_split_sections_without_sections():
    assert split_sections(["a", "b"]) == (["a", "b"], [])


def test_split_sections_keeps_duplicate_names():
    _, sections = split_sections(["## 원인", "a", "## 원인", "b"])
    assert [name for name, _ in sections] == ["원인", "원인"]
