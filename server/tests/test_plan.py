from datetime import date

import pytest
from plans import TODAY, create_item, plan_dict, to_plan, update_item

from wiki_mcp.service.masking import Masker
from wiki_mcp.service.plan import PlanError, RelatedRef, is_unobserved, parse_plan


def parse(data, names=()):
    return parse_plan(data, existing_ids={"sample-pattern"}, masker=Masker(names), today=TODAY)


def bad(**overrides):
    return plan_dict(create_item(**overrides))


def test_parses_create():
    plan = to_plan(create_item(
        resources=["master", "query"],
        symptoms={"query": "`q 증상`", "master": "`m 증상`", "data": "미관측(수집 실패) — 노드 접속 실패"},
    ))
    p = plan.patterns[0]
    assert (p.action, p.id, p.title, p.summary) == ("create", "new-pattern", "새 패턴", "새 증상과 원인 요약")
    assert p.resources == ("query", "master")
    assert list(p.symptoms) == ["query", "master", "data"]
    assert (p.first_seen, p.last_seen) == (date(2026, 10, 10), date(2026, 10, 11))
    assert (plan.infra_candidates, plan.unclassified, plan.notes) == ((), (), ())


def test_parses_update_with_defaults():
    p = to_plan(update_item(first_seen="", last_seen=None)).patterns[0]
    assert (p.action, p.title, p.cause, p.solution) == ("update", "", "", "")
    assert p.first_seen == p.last_seen == TODAY
    assert p.resources == ("query", "data")


def test_related_default_note_and_create_target():
    plan = to_plan(
        create_item(id="first-new", related=[{"id": "second-new"}]),
        create_item(id="second-new", related=[{"id": "sample-pattern", "note": "같은 사전 문제"}]),
    )
    assert plan.patterns[0].related == (RelatedRef("second-new", "동시 관측, 연관 미확인"),)
    assert plan.patterns[1].related == (RelatedRef("sample-pattern", "같은 사전 문제"),)


def test_top_level_lists():
    plan = parse(plan_dict(
        infra_candidates=[{"item": "데이터 노드 수", "report_value": "98", "note": "인프라 페이지는 100"}],
        unclassified=["클라이언트 노드 로그", "  "],
        notes=["원인 복합"],
    ))
    assert plan.infra_candidates == ({"item": "데이터 노드 수", "report_value": "98", "note": "인프라 페이지는 100"},)
    assert plan.unclassified == ("클라이언트 노드 로그",)
    assert plan.notes == ("원인 복합",)


@pytest.mark.parametrize("text, expected", [
    ("미관측(입력 없음)", True),
    ("미관측(수집 실패) — 이유", True),
    ("`<TS> WARN`", False),
])
def test_is_unobserved(text, expected):
    assert is_unobserved(text) is expected


@pytest.mark.parametrize("data, match", [
    ([], "JSON 객체"),
    (plan_dict(extra=1), "알 수 없는 최상위 키"),
    (plan_dict(patterns=[]), "1~5"),
    (plan_dict(*[create_item(id=f"p{i}") for i in range(6)]), "1~5"),
    (bad(action="delete"), "action"),
    (bad(id="Bad_ID"), "id 형식"),
    (bad(unknown_key=1), "알 수 없는 키"),
    (plan_dict({"action": "create", "id": "x"}), "필수 키"),
    (plan_dict(create_item(id="sample-pattern")), "이미 색인에 있는"),
    (plan_dict(update_item(id="unknown-pattern")), "색인에 없는 id"),
    (plan_dict(create_item(), create_item()), "두 번"),
    (bad(summary="첫 줄\n둘째 줄"), "한 줄"),
    (bad(summary="가" * 201), "200자"),
    (bad(title=""), "비어 있습니다"),
    (bad(cause=""), "비어 있습니다"),
    (bad(cause="가" * 3000), "너무 깁니다"),
    (bad(resources=["disk"]), "알 수 없는 값"),
    (bad(resources=[]), "비어 있지 않은"),
    (bad(resources=["master", "master"]), "중복"),
    (bad(resources=["master", "slowlog"]), "slowlog 증상이 없습니다"),
    (bad(resources=["master", "query"]), "관측 내용이 있어야"),
    (bad(symptoms={"master": "`m`", "data": "`d 관측`"}), "resources에도 넣어야"),
    (bad(symptoms={"master": "`m`", "data": "미관측(모름)"}), "미관측 표기"),
    (bad(symptoms={"master": "`m`", "disk": "x"}), "알 수 없는 리소스"),
    (bad(last_seen="2026-10-16"), "미래"),
    (bad(first_seen="2026/10/01"), "YYYY-MM-DD"),
    (bad(first_seen="2026-02-30"), "올바른 날짜"),
    (bad(first_seen="2026-10-12", last_seen="2026-10-11"), "늦습니다"),
    (bad(cause="담당 kim@example.com 확인"), "개인정보"),
    (bad(signature="master: host 10.0.0.1"), "개인정보"),
    (bad(solution="raw/2026-10-14/105317.txt 참고"), "raw 경로"),
    (bad(related=[{"id": "no-such"}]), "색인에 없습니다"),
    (bad(related=[{"id": "new-pattern"}]), "자기 자신"),
    (bad(related=[{"note": "id 없음"}]), "related"),
    (plan_dict(notes="문자열"), "문자열 목록"),
    (plan_dict(infra_candidates=[{"item": "노드", "value": 3}]), "infra_candidates"),
])
def test_rejects_invalid_plan(data, match):
    with pytest.raises(PlanError, match=match):
        parse(data)


def test_rejects_listed_company_name():
    with pytest.raises(PlanError, match="개인정보"):
        parse(bad(summary="뉴엔 고객사 쿼리 지연"), names=["뉴엔"])
