"""WikiStore에서 위키 파일을 읽는다. 패턴 페이지는 sources를 빼고 돌려준다."""
from __future__ import annotations

import re
from typing import Sequence

from wiki_mcp.store.wiki_store import WikiStore

PATTERN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
SECTION_NAMES = ("원인", "증상", "해결방법", "관련 패턴")
INDEX_PATH = "wiki/index.md"
INFRA_PATH = "wiki/infra/cluster.md"
LOG_PATH = "wiki/log.md"
PATTERNS_DIR = "wiki/patterns"


class WikiReadError(Exception):
    """위키 파일을 읽지 못함."""


class PatternNotFound(WikiReadError):
    """요청한 패턴 페이지가 없음."""


class InvalidRequest(ValueError):
    """도구 입력값이 규칙에 맞지 않음."""


def pattern_path(pattern_id: str) -> str:
    return f"{PATTERNS_DIR}/{pattern_id}.md"


def _read(store: WikiStore, path: str) -> str:
    try:
        return store.read(path)
    except FileNotFoundError as exc:
        raise WikiReadError(f"{path}를 찾을 수 없습니다.") from exc


def check_wiki(store: WikiStore) -> None:
    if not store.exists(INDEX_PATH):
        raise WikiReadError(f"{INDEX_PATH}가 없습니다. WIKI_ROOT를 확인하세요.")


def read_index(store: WikiStore) -> str:
    return _read(store, INDEX_PATH)


def read_infra(store: WikiStore) -> str:
    return _read(store, INFRA_PATH)


def split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    return [], lines


def drop_field(frontmatter: list[str], field: str) -> list[str]:
    kept: list[str] = []
    skipping = False
    for line in frontmatter:
        if skipping and line.startswith((" ", "\t", "-")):
            continue
        skipping = False
        if line.startswith(f"{field}:"):
            skipping = True
            continue
        kept.append(line)
    return kept


def _split_sections(body: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif current is None:
            head.append(line)
        else:
            sections[current].append(line)
    return head, sections


def read_pattern(store: WikiStore, pattern_id: str, sections: Sequence[str] | None = None) -> str:
    if not PATTERN_ID_RE.fullmatch(pattern_id):
        raise InvalidRequest(f"패턴 id 형식이 올바르지 않습니다: {pattern_id!r}")
    wanted = set(sections) if sections else set(SECTION_NAMES)
    unknown = sorted(wanted - set(SECTION_NAMES))
    if unknown:
        raise InvalidRequest(f"알 수 없는 섹션: {unknown}. 가능한 값: {list(SECTION_NAMES)}")
    try:
        text = store.read(pattern_path(pattern_id))
    except FileNotFoundError as exc:
        raise PatternNotFound(f"패턴 {pattern_id}가 없습니다. get_index로 id를 확인하세요.") from exc

    frontmatter, body = split_frontmatter(text)
    head, found = _split_sections(body)
    parts = ["---", *drop_field(frontmatter, "sources"), "---", *head]
    for name in SECTION_NAMES:
        if name in wanted and name in found:
            parts.extend(found[name])
    return "\n".join(parts).rstrip("\n") + "\n"
