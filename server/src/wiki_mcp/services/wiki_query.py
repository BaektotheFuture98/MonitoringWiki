"""WikiStore에서 위키 파일을 읽는다. 패턴 페이지는 sources를 빼고 돌려준다."""
from __future__ import annotations

from typing import Sequence

from wiki_mcp.core.errors import InvalidRequest, PatternNotFound, WikiReadError
from wiki_mcp.core.markdown import drop_field, split_frontmatter, split_sections
from wiki_mcp.core.plan import PATTERN_ID_RE
from wiki_mcp.repositories.store import INDEX_PATH, INFRA_PATH, WikiStore, pattern_path

SECTION_NAMES = ("원인", "증상", "해결방법", "관련 패턴")


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
    head, sections_found = split_sections(body)
    found = dict(sections_found)
    parts = ["---", *drop_field(frontmatter, "sources"), "---", *head]
    for name in SECTION_NAMES:
        if name in wanted and name in found:
            parts.extend(found[name])
    return "\n".join(parts).rstrip("\n") + "\n"
