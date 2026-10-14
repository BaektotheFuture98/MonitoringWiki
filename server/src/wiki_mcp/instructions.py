"""CLAUDE.md에서 외부 에이전트용 Query 가이드 절을 추출해 서버 instructions로 쓴다."""
from __future__ import annotations

from pathlib import Path

from .wiki_reader import git_show

GUIDE_HEADING = "## 외부 에이전트용 Query 가이드"


class InstructionsError(Exception):
    """외부 가이드 절을 찾지 못했거나 비어 있음."""


def extract_guide(claude_md: str) -> str:
    lines = claude_md.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == GUIDE_HEADING), None)
    if start is None:
        raise InstructionsError(f"CLAUDE.md에 '{GUIDE_HEADING}' 절이 없습니다.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start + 1:end]).strip()
    if not body:
        raise InstructionsError("외부 가이드 절이 비어 있습니다.")
    return body


def load_instructions(root: Path, ref: str) -> str:
    try:
        text = git_show(root, ref, "CLAUDE.md")
    except FileNotFoundError as exc:
        raise InstructionsError(f"{ref}에 CLAUDE.md가 없습니다.") from exc
    return extract_guide(text)
