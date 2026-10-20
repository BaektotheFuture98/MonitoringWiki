"""위키 마크다운 페이지를 frontmatter와 `## ` 절 단위로 나누는 순수 함수."""
from __future__ import annotations

from typing import Sequence

Sections = list[tuple[str, list[str]]]


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


def extract_section(markdown: str, heading: str) -> str:
    """`## <heading>` 절의 본문(다음 `## ` 전까지)을 돌려준다. 절이 없거나 비어 있으면 ValueError."""
    lines = markdown.split("\n")
    target = f"## {heading}"
    start = next((i for i, line in enumerate(lines) if line.strip() == target), None)
    if start is None:
        raise ValueError(f"'{target}' 절이 없습니다.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start + 1:end]).strip()
    if not body:
        raise ValueError(f"'{target}' 절이 비어 있습니다.")
    return body


def split_sections(body: Sequence[str]) -> tuple[list[str], Sections]:
    head: list[str] = []
    sections: Sections = []
    for line in body:
        if line.startswith("## "):
            sections.append((line[3:].strip(), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            head.append(line)
    return head, sections
