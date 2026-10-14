import subprocess
from pathlib import Path

import pytest

CLAUDE_MD = """# 규칙

## Query
내부용 절입니다. `wiki/index.md`를 읽습니다.

## 외부 에이전트용 Query 가이드
외부 가이드 본문입니다.
1. `get_index`로 색인을 읽습니다.

## Lint
린트 절입니다.
"""

INDEX_MD = "# 색인\n\n| 패턴 | 요약 |\n|---|---|\n| [p1](patterns/p1.md) | 요약 |\n"

INFRA_MD = "---\nid: infra-cluster\nas_of: 2026-10-14\n---\n# 클러스터 구성\n"

PATTERN_MD = """---
id: sample-pattern
summary: 샘플 요약
confidence: low
resources: [query]
first_seen: 2026-10-01
last_seen: 2026-10-01
occurrences: 1
sources: [raw/2026-10-01/101010.txt]
solution_origin: report
---
# 샘플 패턴

## 원인
원인 본문

## 증상
- **query**: 증상 본문

## 해결방법
해결 본문

## 관련 패턴
없음
"""

LOG_MD = "# 작업 로그\n\n## [2026-10-01 10:20] ingest | raw/2026-10-01/101010.txt\n- 처리\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def wiki_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    git(root, "config", "core.autocrlf", "false")
    write(root, "CLAUDE.md", CLAUDE_MD)
    write(root, "wiki/index.md", INDEX_MD)
    write(root, "wiki/infra/cluster.md", INFRA_MD)
    write(root, "wiki/patterns/sample-pattern.md", PATTERN_MD)
    write(root, "wiki/log.md", LOG_MD)
    write(root, ".gitignore", "raw/\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "init")
    (root / "raw").mkdir()
    return root
