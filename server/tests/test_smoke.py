import subprocess

import wiki_mcp


def test_package_imports():
    assert wiki_mcp.__version__ == "0.1.0"


def test_fixture_repo_is_on_main(wiki_repo):
    branch = subprocess.run(
        ["git", "-C", str(wiki_repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == "main"
    assert (wiki_repo / "raw").is_dir()
