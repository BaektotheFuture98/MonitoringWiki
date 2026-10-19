"""담당자용: 아직 위키에 반영되지 않은 raw 파일 목록을 출력한다(자동 컴파일이 실패한 보고서 확인용).

사용법: WIKI_ROOT=<저장소> python scripts/pending.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from wiki_mcp.core.errors import WikiReadError
from wiki_mcp.core.markdown import split_frontmatter
from wiki_mcp.services import wiki_query
from wiki_mcp.repositories.raw_store import IGNORED_NAMES
from wiki_mcp.repositories.store import LOG_PATH, PATTERNS_DIR, FileWikiStore, WikiStore

RAW_PATH_RE = re.compile(r"raw/\d{4}-\d{2}-\d{2}/[^\s`'\"\],)]+")
INGEST_HEADING_RE = re.compile(r"^## \[[^\]]*\] ingest\b")


def _sources_text(frontmatter: list[str]) -> str:
    collected: list[str] = []
    inside = False
    for line in frontmatter:
        if line.startswith("sources:"):
            inside = True
            collected.append(line)
        elif inside and line.startswith((" ", "\t", "-")):
            collected.append(line)
        else:
            inside = False
    return "\n".join(collected)


def _ingest_entries(log_text: str) -> str:
    collected: list[str] = []
    inside = False
    for line in log_text.split("\n"):
        if line.startswith("## "):
            inside = bool(INGEST_HEADING_RE.match(line))
        if inside:
            collected.append(line)
    return "\n".join(collected)


def referenced_raw_paths(store: WikiStore) -> set[str]:
    referenced: set[str] = set()
    for path in store.list(PATTERNS_DIR):
        if not path.endswith(".md"):
            continue
        frontmatter, _ = split_frontmatter(store.read(path))
        referenced.update(RAW_PATH_RE.findall(_sources_text(frontmatter)))
    try:
        log_text = store.read(LOG_PATH)
    except FileNotFoundError:
        log_text = ""
    referenced.update(RAW_PATH_RE.findall(_ingest_entries(log_text)))
    return referenced


def pending_raw_files(root: Path, store: WikiStore) -> list[str]:
    raw_dir = root / "raw"
    if not raw_dir.exists():
        return []
    referenced = referenced_raw_paths(store)
    files = [
        path.relative_to(root).as_posix()
        for path in sorted(raw_dir.rglob("*"))
        if path.is_file() and path.name not in IGNORED_NAMES
    ]
    return [path for path in files if path not in referenced]


def main() -> int:
    root_value = os.environ.get("WIKI_ROOT", "").strip()
    if not root_value:
        print("WIKI_ROOT 환경 변수가 필요합니다.", file=sys.stderr)
        return 2
    root = Path(root_value)
    store = FileWikiStore(root)
    try:
        wiki_query.check_wiki(store)
    except WikiReadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    pending = pending_raw_files(root, store)
    if not pending:
        print("컴파일 대기 중인 raw가 없습니다.")
        return 0
    print(f"컴파일 대기 {len(pending)}건:")
    for path in pending:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
