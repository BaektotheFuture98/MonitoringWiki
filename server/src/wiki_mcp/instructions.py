"""AGENTS.md에서 절을 추출한다. 외부 에이전트용 Query 가이드 절은 서버 instructions로 쓴다."""
from __future__ import annotations

from wiki_mcp.store.wiki_store import WikiStore

AGENTS_MD_PATH = "AGENTS.md"
GUIDE_SECTION = "외부 에이전트용 Query 가이드"


class InstructionsError(Exception):
    """AGENTS.md나 필요한 절을 찾지 못했거나 비어 있음."""


def extract_section(markdown: str, heading: str) -> str:
    """`## <heading>` 절의 본문(다음 `## ` 전까지)을 돌려준다."""
    lines = markdown.split("\n")
    target = f"## {heading}"
    start = next((i for i, line in enumerate(lines) if line.strip() == target), None)
    if start is None:
        raise InstructionsError(f"AGENTS.md에 '{target}' 절이 없습니다.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start + 1:end]).strip()
    if not body:
        raise InstructionsError(f"'{target}' 절이 비어 있습니다.")
    return body


def extract_guide(agents_md: str) -> str:
    return extract_section(agents_md, GUIDE_SECTION)


def read_agents_md(store: WikiStore) -> str:
    try:
        return store.read(AGENTS_MD_PATH)
    except FileNotFoundError as exc:
        raise InstructionsError(f"{AGENTS_MD_PATH}가 없습니다.") from exc


def load_instructions(store: WikiStore) -> str:
    return extract_guide(read_agents_md(store))
