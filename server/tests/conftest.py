"""공용 테스트 픽스처. 위키 루트는 git 없는 임시 폴더다(PoC는 파일을 직접 읽고 쓴다)."""
import json
from pathlib import Path

import pytest

from wiki_mcp.service.auth import hash_token
from wiki_mcp.config import Settings
from wiki_mcp.store.wiki_store import FileWikiStore

AGENTS_MD = """# 규칙

## Query
내부용 절입니다. `wiki/index.md`를 읽습니다.

## 외부 에이전트용 Query 가이드
외부 가이드 본문입니다.
1. `get_index`로 색인을 읽습니다.

## Lint
린트 절입니다.
"""

INDEX_MD = """# 색인

## 통계
- 패턴: 1

## 패턴
| 패턴 | 요약 | 리소스 | 대표 시그니처 | confidence | last_seen |
|---|---|---|---|---|---|
| [sample-pattern](patterns/sample-pattern.md) | 샘플 요약 | query | query: `샘플 시그니처` | low | 2026-10-01 |

## 인프라
- [클러스터 구성](infra/cluster.md) — 샘플 구성 (기준일 2026-10-14)

## 기록
- [작업 로그](log.md)
"""

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


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_tokens(path: Path, *entries: tuple[str, str, list[str]]) -> Path:
    """entries: (토큰 이름, 비밀값, 스코프 목록)."""
    data = [{"name": name, "sha256": hash_token(secret), "scopes": scopes} for name, secret, scopes in entries]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_settings(root: Path, tmp_path: Path, **overrides) -> Settings:
    values = {
        "wiki_root": root,
        "tz": "Asia/Seoul",
        "tokens_file": tmp_path / "tokens.json",
        "access_log": tmp_path / "access.jsonl",
        "max_report_bytes": 10_000,
        "host": "127.0.0.1",
        "port": 8000,
        "state_dir": tmp_path / "state",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki-root"
    write(root, "AGENTS.md", AGENTS_MD)
    write(root, "wiki/index.md", INDEX_MD)
    write(root, "wiki/infra/cluster.md", INFRA_MD)
    write(root, "wiki/patterns/sample-pattern.md", PATTERN_MD)
    write(root, "wiki/log.md", LOG_MD)
    (root / "raw").mkdir()
    return root


@pytest.fixture
def wiki_store(wiki_root: Path) -> FileWikiStore:
    return FileWikiStore(wiki_root)


@pytest.fixture
def server_settings(wiki_root: Path, tmp_path: Path) -> Settings:
    settings = make_settings(wiki_root, tmp_path)
    write_tokens(
        settings.tokens_file,
        ("query-agent", "read-secret", ["read"]),
        ("web-backend", "submit-secret", ["submit"]),
        ("infra-admin", "infra-secret", ["infra"]),
    )
    return settings
