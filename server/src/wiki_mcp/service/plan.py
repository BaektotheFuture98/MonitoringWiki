"""LLM이 만든 컴파일 계획(JSON)을 검증해 값 객체로 바꾼다. 검증을 통과하지 못한 계획은 위키에 쓰지 않는다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from wiki_mcp.service.masking import Masker

RESOURCES = ("query", "master", "data", "slowlog")
UNOBSERVED_RE = re.compile(r"미관측\((?:수집 실패|이벤트 없음|입력 없음|로그 없음)\)")
PATTERN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
RAW_PATH_RE = re.compile(r"\braw/\d{4}-\d{2}-\d{2}/")
MAX_PATTERNS = 5
MAX_TITLE = 120
MAX_SUMMARY = 200
MAX_SIGNATURE = 300
MAX_NOTE = 200
MAX_TEXT_BYTES = 8 * 1024
DEFAULT_RELATED_NOTE = "동시 관측, 연관 미확인"
TOP_KEYS = frozenset({"patterns", "infra_candidates", "unclassified", "notes"})
PATTERN_KEYS = frozenset({
    "action", "id", "title", "summary", "signature", "resources",
    "cause", "symptoms", "solution", "related", "first_seen", "last_seen",
})
CREATE_REQUIRED = ("id", "title", "summary", "signature", "resources", "cause", "symptoms", "solution")
UPDATE_REQUIRED = ("id", "resources", "symptoms")
CREATE_NONEMPTY = ("title", "summary", "signature", "cause", "solution")
CANDIDATE_KEYS = frozenset({"item", "report_value", "note"})


class PlanError(ValueError):
    """컴파일 계획이 형식이나 위키 규칙에 맞지 않음."""


@dataclass(frozen=True)
class RelatedRef:
    id: str
    note: str


@dataclass(frozen=True)
class PatternPlan:
    action: str
    id: str
    title: str
    summary: str
    signature: str
    resources: tuple[str, ...]
    cause: str
    symptoms: Mapping[str, str]
    solution: str
    related: tuple[RelatedRef, ...]
    first_seen: date
    last_seen: date


@dataclass(frozen=True)
class CompilePlan:
    patterns: tuple[PatternPlan, ...]
    infra_candidates: tuple[Mapping[str, str], ...]
    unclassified: tuple[str, ...]
    notes: tuple[str, ...]


def is_unobserved(text: str) -> bool:
    return text.strip().startswith("미관측")


def parse_plan(data: Any, *, existing_ids: set[str], masker: Masker, today: date) -> CompilePlan:
    if not isinstance(data, dict):
        raise PlanError("계획은 JSON 객체여야 합니다.")
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise PlanError(f"알 수 없는 최상위 키: {unknown}")
    items = data.get("patterns")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PATTERNS:
        raise PlanError(f"patterns는 1~{MAX_PATTERNS}개의 목록이어야 합니다.")
    patterns = tuple(_parse_pattern(item, i, masker, today) for i, item in enumerate(items))
    _check_ids(patterns, existing_ids)
    return CompilePlan(
        patterns=patterns,
        infra_candidates=_candidates(data.get("infra_candidates", [])),
        unclassified=_strings(data.get("unclassified", []), "unclassified"),
        notes=_strings(data.get("notes", []), "notes"),
    )


def _parse_pattern(item: Any, index: int, masker: Masker, today: date) -> PatternPlan:
    where = f"patterns[{index}]"
    if not isinstance(item, dict):
        raise PlanError(f"{where}는 객체여야 합니다.")
    unknown = sorted(set(item) - PATTERN_KEYS)
    if unknown:
        raise PlanError(f"{where}에 알 수 없는 키: {unknown}")
    action = item.get("action")
    if action not in ("create", "update"):
        raise PlanError(f"{where}.action은 create 또는 update여야 합니다.")
    required = CREATE_REQUIRED if action == "create" else UPDATE_REQUIRED
    missing = [key for key in required if key not in item]
    if missing:
        raise PlanError(f"{where}에 필수 키가 없습니다: {missing}")
    pattern_id = item["id"]
    if not isinstance(pattern_id, str) or not PATTERN_ID_RE.fullmatch(pattern_id):
        raise PlanError(f"{where}.id 형식이 올바르지 않습니다: {pattern_id!r}")
    resources = _resources(item["resources"], where)
    pattern = PatternPlan(
        action=action,
        id=pattern_id,
        title=_line(item, "title", where, MAX_TITLE),
        summary=_line(item, "summary", where, MAX_SUMMARY),
        signature=_line(item, "signature", where, MAX_SIGNATURE),
        resources=resources,
        cause=_body(item, "cause", where),
        symptoms=_symptoms(item["symptoms"], resources, where),
        solution=_body(item, "solution", where),
        related=_related(item.get("related", []), where),
        first_seen=_date(item.get("first_seen"), today, f"{where}.first_seen"),
        last_seen=_date(item.get("last_seen"), today, f"{where}.last_seen"),
    )
    if action == "create":
        empty = [key for key in CREATE_NONEMPTY if not getattr(pattern, key)]
        if empty:
            raise PlanError(f"{where}의 값이 비어 있습니다: {empty}")
    if pattern.first_seen > pattern.last_seen:
        raise PlanError(f"{where}.first_seen이 last_seen보다 늦습니다.")
    _check_written_text(pattern, masker, where)
    return pattern


def _line(item: Mapping[str, Any], key: str, where: str, limit: int) -> str:
    value = item.get(key, "")
    if not isinstance(value, str):
        raise PlanError(f"{where}.{key}는 문자열이어야 합니다.")
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise PlanError(f"{where}.{key}는 한 줄이어야 합니다.")
    if len(value) > limit:
        raise PlanError(f"{where}.{key}는 {limit}자 이하여야 합니다({len(value)}자).")
    return value


def _body(item: Mapping[str, Any], key: str, where: str) -> str:
    value = item.get(key, "")
    if not isinstance(value, str):
        raise PlanError(f"{where}.{key}는 문자열이어야 합니다.")
    return _check_size(value.strip(), f"{where}.{key}")


def _check_size(text: str, label: str) -> str:
    size = len(text.encode("utf-8"))
    if size > MAX_TEXT_BYTES:
        raise PlanError(f"{label}가 너무 깁니다({size} bytes, 상한 {MAX_TEXT_BYTES}).")
    return text


def _resources(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise PlanError(f"{where}.resources는 비어 있지 않은 문자열 목록이어야 합니다.")
    unknown = sorted(set(value) - set(RESOURCES))
    if unknown:
        raise PlanError(f"{where}.resources에 알 수 없는 값: {unknown}")
    if len(set(value)) != len(value):
        raise PlanError(f"{where}.resources에 중복이 있습니다.")
    return tuple(resource for resource in RESOURCES if resource in value)


def _symptoms(value: Any, resources: tuple[str, ...], where: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PlanError(f"{where}.symptoms는 객체여야 합니다.")
    unknown = sorted(set(value) - set(RESOURCES))
    if unknown:
        raise PlanError(f"{where}.symptoms에 알 수 없는 리소스: {unknown}")
    symptoms: dict[str, str] = {}
    for resource in RESOURCES:
        label = f"{where}.symptoms.{resource}"
        if resource not in value:
            if resource in resources:
                raise PlanError(f"{where}.symptoms에 {resource} 증상이 없습니다.")
            continue
        text = value[resource]
        if not isinstance(text, str) or not text.strip():
            raise PlanError(f"{label}가 비어 있습니다.")
        text = _check_size(text.strip(), label)
        unobserved = is_unobserved(text)
        if unobserved and not UNOBSERVED_RE.match(text):
            raise PlanError(f"{label}의 미관측 표기는 미관측(수집 실패|이벤트 없음|입력 없음|로그 없음) 중 하나여야 합니다.")
        if resource in resources and unobserved:
            raise PlanError(f"{label}: resources에 넣은 리소스는 관측 내용이 있어야 합니다.")
        if resource not in resources and not unobserved:
            raise PlanError(f"{label}: 관측 내용이 있으면 resources에도 넣어야 합니다.")
        symptoms[resource] = text
    return symptoms


def _related(value: Any, where: str) -> tuple[RelatedRef, ...]:
    if not isinstance(value, list):
        raise PlanError(f"{where}.related는 목록이어야 합니다.")
    refs: list[RelatedRef] = []
    for i, ref in enumerate(value):
        label = f"{where}.related[{i}]"
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            raise PlanError(f"{label}는 id를 가진 객체여야 합니다.")
        if not PATTERN_ID_RE.fullmatch(ref["id"]):
            raise PlanError(f"{label}.id 형식이 올바르지 않습니다: {ref['id']!r}")
        refs.append(RelatedRef(ref["id"], _line(ref, "note", label, MAX_NOTE) or DEFAULT_RELATED_NOTE))
    return tuple(refs)


def _date(value: Any, today: date, label: str) -> date:
    if value is None or value == "":
        return today
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise PlanError(f"{label}는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PlanError(f"{label}가 올바른 날짜가 아닙니다: {value}") from exc
    if parsed > today:
        raise PlanError(f"{label}가 미래 날짜입니다: {value}")
    return parsed


def _check_written_text(pattern: PatternPlan, masker: Masker, where: str) -> None:
    texts = [
        pattern.title, pattern.summary, pattern.signature, pattern.cause, pattern.solution,
        *pattern.symptoms.values(), *(ref.note for ref in pattern.related),
    ]
    for text in texts:
        leaks = masker.find_leaks(text)
        if leaks:
            raise PlanError(f"{where}에 개인정보가 남아 있습니다: {', '.join(leaks)}")
        if RAW_PATH_RE.search(text):
            raise PlanError(f"{where}에 raw 경로를 쓸 수 없습니다(sources는 서버가 계산).")


def _check_ids(patterns: tuple[PatternPlan, ...], existing_ids: set[str]) -> None:
    seen: set[str] = set()
    for pattern in patterns:
        if pattern.id in seen:
            raise PlanError(f"같은 id가 계획에 두 번 있습니다: {pattern.id}")
        seen.add(pattern.id)
        if pattern.action == "create" and pattern.id in existing_ids:
            raise PlanError(f"이미 색인에 있는 id로 create할 수 없습니다: {pattern.id}")
        if pattern.action == "update" and pattern.id not in existing_ids:
            raise PlanError(f"색인에 없는 id는 update할 수 없습니다: {pattern.id}")
    created = {pattern.id for pattern in patterns if pattern.action == "create"}
    for pattern in patterns:
        for ref in pattern.related:
            if ref.id == pattern.id:
                raise PlanError(f"{pattern.id}가 자기 자신을 관련 패턴으로 가리킵니다.")
            if ref.id not in existing_ids and ref.id not in created:
                raise PlanError(f"관련 패턴 id가 색인에 없습니다: {ref.id}")


def _candidates(value: Any) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, list):
        raise PlanError("infra_candidates는 목록이어야 합니다.")
    result: list[Mapping[str, str]] = []
    for i, candidate in enumerate(value):
        if (
            not isinstance(candidate, dict)
            or set(candidate) - CANDIDATE_KEYS
            or not all(isinstance(v, str) for v in candidate.values())
        ):
            raise PlanError(f"infra_candidates[{i}]는 item, report_value, note 문자열만 가진 객체여야 합니다.")
        result.append(dict(candidate))
    return tuple(result)


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PlanError(f"{name}는 문자열 목록이어야 합니다.")
    return tuple(v.strip() for v in value if v.strip())
