import wiki_mcp


def test_package_imports():
    assert wiki_mcp.__version__ == "0.1.0"


def test_fixture_root_has_wiki_and_raw(wiki_root):
    assert (wiki_root / "wiki" / "index.md").is_file()
    assert (wiki_root / "raw").is_dir()
    assert not (wiki_root / ".git").exists()
