"""위키 페이지·색인·로그 텍스트를 계산하는 순수 함수. 파일을 읽거나 쓰지 않는다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping, Sequence

from .plan import RESOURCES, PatternPlan, is_unobserved
from .wiki_reader import split_frontmatter

INDEX_HEADER_PREFIX = "| 패턴 |"
INDEX_ID_RE = re.compile(r"^\| \[([a-z0-9][a-z0-9-]*)\]\(patterns/")
STATS_RE = re.compile(r"^- 패턴: \d+$", re.MULTILINE)
INFRA_LINK = "- [클러스터 구성](infra/cluster.md)"
CONFIDENCE_LEVELS = ("low", "medium", "high")
NO_RELATED = "없음"
DEFAULT_UNOBSERVED = "미관측(입력 없음)"

Sections = list[tuple[str, list[str]]]


class PageFormatError(ValueError):
    """기존 위키 페이지나 색인이 서버가 기대하는 형식이 아님."""


@dataclass(frozen=True)
class UpdatedPage:
    text: str
    resources: tuple[str, ...]
    resources_changed: bool
    confidence: str
    last_seen: date


# 색인 ---------------------------------------------------------------

def index_pattern_ids(index_text: str) -> set[str]:
    return {match.group(1) for line in index_text.split("\n") if (match := INDEX_ID_RE.match(line))}


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]


def _join_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def upsert_index_row(
    index_text: str,
    pattern_id: str,
    *,
    confidence: str,
    last_seen: date,
    resources: Sequence[str] | None = None,
    summary: str | None = None,
    signature: str | None = None,
) -> str:
    lines = index_text.split("\n")
    header = next((i for i, line in enumerate(lines) if line.startswith(INDEX_HEADER_PREFIX)), None)
    if header is None:
        raise PageFormatError("색인에 패턴 표가 없습니다.")
    end = header + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    row = next(
        (i for i in range(header + 2, end) if (m := INDEX_ID_RE.match(lines[i])) and m.group(1) == pattern_id),
        None,
    )
    if row is None:
        if summary is None or signature is None or resources is None:
            raise PageFormatError(f"새 색인 행에는 요약, 시그니처, 리소스가 필요합니다: {pattern_id}")
        cells = [
            f"[{pattern_id}](patterns/{pattern_id}.md)", _escape_cell(summary), ", ".join(resources),
            _escape_cell(signature), confidence, last_seen.isoformat(),
        ]
        lines.insert(end, _join_row(cells))
    else:
        cells = _split_row(lines[row])
        if len(cells) != 6:
            raise PageFormatError(f"색인 행의 열 수가 6이 아닙니다: {pattern_id}")
        if resources is not None:
            cells[2] = ", ".join(resources)
        cells[4] = confidence
        cells[5] = last_seen.isoformat()
        lines[row] = _join_row(cells)
    text = "\n".join(lines)
    return STATS_RE.sub(f"- 패턴: {len(index_pattern_ids(text))}", text, count=1)


def update_index_infra_line(index_text: str, summary: str, as_of: date) -> str:
    lines = [
        f"{INFRA_LINK} — {summary} (기준일 {as_of.isoformat()})" if line.startswith(INFRA_LINK) else line
        for line in index_text.split("\n")
    ]
    return "\n".join(lines)


# confidence --------------------------------------------------------

def confidence_for(resource_count: int, occurrences: int) -> str:
    """AGENTS.md 기준: 리소스 2개 이상이고 3회 이상이면 high, 둘 중 하나면 medium, 나머지 low."""
    many_resources = resource_count >= 2
    many_occurrences = occurrences >= 3
    if many_resources and many_occurrences:
        return "high"
    if many_resources or many_occurrences:
        return "medium"
    return "low"


def stronger_confidence(a: str, b: str) -> str:
    rank = {level: i for i, level in enumerate(CONFIDENCE_LEVELS)}
    return max(a, b, key=lambda level: rank.get(level, 0))


# frontmatter와 본문 -------------------------------------------------

def parse_list(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [item.strip() for item in inner.split(",") if item.strip()]


def format_list(items: Iterable[str]) -> str:
    return "[" + ", ".join(items) + "]"


def parse_frontmatter(lines: Sequence[str]) -> dict[str, str]:
    """`key: value` 줄을 순서대로 읽는다. 블록 목록(`- x`)은 인라인 목록 문자열로 바꾼다."""
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if current is not None and stripped.startswith("- "):
            fields[current] = format_list([*parse_list(fields[current]), stripped[2:].strip()])
            continue
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t")):
            raise PageFormatError(f"frontmatter 줄을 해석할 수 없습니다: {line!r}")
        current = key.strip()
        fields[current] = value.strip() or "[]"
    return fields


def _render_frontmatter(fields: Mapping[str, str]) -> list[str]:
    return ["---", *(f"{key}: {value}" for key, value in fields.items()), "---"]


def _split_body(body: Sequence[str]) -> tuple[list[str], Sections]:
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


def _join_body(head: list[str], sections: Sections) -> list[str]:
    lines = list(head)
    for _, section in sections:
        lines.extend(section)
    return lines


def _section(sections: Sections, name: str) -> list[str]:
    for section_name, lines in sections:
        if section_name == name:
            return lines
    lines = [f"## {name}"]
    sections.append((name, lines))
    return lines


def _append_lines(section: list[str], new_lines: Sequence[str]) -> None:
    """절 끝의 빈 줄을 걷어 내고 새 줄을 붙인 뒤, 다음 절과 구분할 빈 줄을 하나 둔다."""
    while len(section) > 1 and not section[-1].strip():
        section.pop()
    section.extend(new_lines)
    section.append("")


def _bullet(resource: str, text: str) -> list[str]:
    first, *rest = text.strip().split("\n")
    return [f"- **{resource}**: {first}", *(f"  {line}" if line.strip() else "" for line in rest)]


def _related_line(pattern_id: str, note: str) -> str:
    return f"- [{pattern_id}]({pattern_id}.md) — {note}"


def _finish(lines: Sequence[str]) -> str:
    return "\n".join(lines).rstrip("\n") + "\n"


# 패턴 페이지 ---------------------------------------------------------

def render_new_pattern(pattern: PatternPlan, raw_path: str) -> str:
    fields = {
        "id": pattern.id,
        "summary": pattern.summary,
        "confidence": confidence_for(len(pattern.resources), 1),
        "resources": format_list(pattern.resources),
        "first_seen": pattern.first_seen.isoformat(),
        "last_seen": pattern.last_seen.isoformat(),
        "occurrences": "1",
        "sources": format_list([raw_path]),
        "solution_origin": "report",
    }
    symptoms: list[str] = []
    for resource in RESOURCES:
        symptoms.extend(_bullet(resource, pattern.symptoms.get(resource, DEFAULT_UNOBSERVED)))
    related = [_related_line(ref.id, ref.note) for ref in pattern.related] or [NO_RELATED]
    body = [
        f"# {pattern.title}", "",
        "## 원인", pattern.cause, "",
        "## 증상", *symptoms, "",
        "## 해결방법", pattern.solution, "",
        "## 관련 패턴", *related,
    ]
    return _finish([*_render_frontmatter(fields), *body])


def _merge_resources(old: Sequence[str], new: Sequence[str]) -> tuple[str, ...]:
    known = [resource for resource in RESOURCES if resource in old or resource in new]
    extra = [resource for resource in old if resource not in RESOURCES]
    return tuple(known + extra)


def _merge_symptoms(section: list[str], symptoms: Mapping[str, str]) -> None:
    """새로 관측된 리소스만 반영한다. 미관측 줄은 교체하고, 이미 관측된 줄은 덮어쓰지 않는다."""
    for resource, text in symptoms.items():
        if is_unobserved(text):
            continue
        prefix = f"- **{resource}**:"
        at = next((i for i, line in enumerate(section) if line.startswith(prefix)), None)
        if at is None:
            _append_lines(section, _bullet(resource, text))
        elif is_unobserved(section[at][len(prefix):]):
            section[at:at + 1] = _bullet(resource, text)


def merge_pattern_update(page_text: str, pattern: PatternPlan, raw_path: str, received: date) -> UpdatedPage:
    frontmatter, body = split_frontmatter(page_text)
    if not frontmatter:
        raise PageFormatError(f"패턴 {pattern.id}에 frontmatter가 없습니다.")
    fields = parse_frontmatter(frontmatter)
    try:
        occurrences = int(fields.get("occurrences", "0")) + 1
        first_seen = min(date.fromisoformat(fields["first_seen"]), pattern.first_seen)
        last_seen = max(date.fromisoformat(fields["last_seen"]), pattern.last_seen)
    except (KeyError, ValueError) as exc:
        raise PageFormatError(f"패턴 {pattern.id}의 frontmatter 값을 해석할 수 없습니다: {exc}") from exc
    old_resources = parse_list(fields.get("resources", "[]"))
    resources = _merge_resources(old_resources, pattern.resources)
    sources = parse_list(fields.get("sources", "[]"))
    if raw_path not in sources:
        sources.append(raw_path)
    confidence = stronger_confidence(fields.get("confidence", "low"), confidence_for(len(resources), occurrences))
    fields.update(
        confidence=confidence,
        resources=format_list(resources),
        first_seen=first_seen.isoformat(),
        last_seen=last_seen.isoformat(),
        occurrences=str(occurrences),
        sources=format_list(sources),
    )

    head, sections = _split_body(body)
    _merge_symptoms(_section(sections, "증상"), pattern.symptoms)
    # 기존 원인·해결은 덮어쓰지 않고, 보고서가 다른 내용을 내면 날짜를 붙여 나란히 둔다.
    for name, text in (("원인", pattern.cause), ("해결방법", pattern.solution)):
        if text:
            _append_lines(_section(sections, name), ["", f"(추가 보고서 {received.isoformat()}) {text}"])
    merged = _finish([*_render_frontmatter(fields), *_join_body(head, sections)])
    for ref in pattern.related:
        merged = add_related_link(merged, ref.id, ref.note)
    return UpdatedPage(
        text=merged,
        resources=resources,
        resources_changed=set(resources) != set(old_resources),
        confidence=confidence,
        last_seen=last_seen,
    )


def add_related_link(page_text: str, target_id: str, note: str) -> str:
    frontmatter, body = split_frontmatter(page_text)
    head, sections = _split_body(body)
    section = _section(sections, "관련 패턴")
    if any(f"]({target_id}.md)" in line for line in section):
        return page_text
    if [line for line in section[1:] if line.strip()] == [NO_RELATED]:
        del section[1:]
    _append_lines(section, [_related_line(target_id, note)])
    prefix = ["---", *frontmatter, "---"] if frontmatter else []
    return _finish([*prefix, *_join_body(head, sections)])


# 로그 ----------------------------------------------------------------

def append_log(log_text: str, *, when: datetime, kind: str, target: str, lines: Sequence[str]) -> str:
    entry = [f"## [{when:%Y-%m-%d %H:%M}] {kind} | {target}", *(f"- {line}" for line in lines)]
    return log_text.rstrip("\n") + "\n\n" + "\n".join(entry) + "\n"
