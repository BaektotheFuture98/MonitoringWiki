"""테스트용 컴파일 계획 빌더."""
from __future__ import annotations

import copy
from datetime import date
from typing import Any, Iterable

from wiki_mcp.masking import Masker
from wiki_mcp.plan import CompilePlan, parse_plan

TODAY = date(2026, 10, 15)
EXISTING_IDS = frozenset({"sample-pattern"})


def create_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action": "create",
        "id": "new-pattern",
        "title": "새 패턴",
        "summary": "새 증상과 원인 요약",
        "signature": "master: `<TS> WARN 새 시그니처`",
        "resources": ["master"],
        "cause": "(보고서 판단) 새 원인",
        "symptoms": {"master": "`<TS> WARN 새 시그니처`", "query": "미관측(입력 없음)"},
        "solution": "(보고서 권장 조치) 새 해결",
        "related": [],
        "first_seen": "2026-10-10",
        "last_seen": "2026-10-11",
    }
    item.update(overrides)
    return item


def update_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action": "update",
        "id": "sample-pattern",
        "resources": ["query", "data"],
        "symptoms": {"query": "새 보고서의 query 증상", "data": "`<TS> data 증상`"},
        "cause": "",
        "solution": "",
        "related": [],
        "first_seen": "2026-10-12",
        "last_seen": "2026-10-12",
    }
    item.update(overrides)
    return item


def plan_dict(*items: dict[str, Any], **top: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "patterns": list(items) if items else [create_item()],
        "infra_candidates": [],
        "unclassified": [],
        "notes": [],
    }
    data.update(top)
    return data


def to_plan(
    *items: dict[str, Any],
    existing_ids: Iterable[str] = EXISTING_IDS,
    names: Iterable[str] = (),
    **top: Any,
) -> CompilePlan:
    return parse_plan(plan_dict(*items, **top), existing_ids=set(existing_ids), masker=Masker(names), today=TODAY)


class FakePlanGenerator:
    """정해 둔 응답을 차례로 돌려준다. 마지막 응답은 계속 반복하고, 예외 객체는 던진다."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_plan(self, masked_text: str, index_text: str, feedback: str | None = None) -> dict[str, Any]:
        self.calls.append({"masked_text": masked_text, "index_text": index_text, "feedback": feedback})
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)
