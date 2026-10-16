from dataclasses import replace
from datetime import date

import pytest
from conftest import write_tokens

from wiki_mcp.service.auth import TokenStore, require_scope
from wiki_mcp.service.infra import InfraError, InfraSpec, Tier, infra_summary, render_infra, validate_infra

SPEC = InfraSpec(
    version="8.12.2",
    master=3,
    client=5,
    data=100,
    tiers=(Tier("HOT", 20, ("RC12",)), Tier("WARM", 40, ("RC10", "RC17")), Tier("WARM-03", 40, ("RC18",))),
    notes=("오래된 데이터를 삭제하는 정책은 없음",),
    unconfirmed=("역할별 하드웨어 사양(CPU, 메모리, JVM heap, 디스크)",),
)

EXPECTED = """---
id: infra-cluster
summary: Elasticsearch 8.12.2, 108노드(마스터 3, 클라이언트 5, 데이터 100 = HOT 20 / WARM 40 / WARM-03 40), 티어별 랙 RC12 / RC10·RC17 / RC18
as_of: 2026-10-15
source: API(web-backend)
---
# 클러스터 구성

> 기준일 2026-10-15의 현재 상태입니다. 구성이 바뀌면 덮어쓰고 `as_of`를 갱신합니다. 노드명과 IP는 적지 않습니다. 랙은 티어가 위치한 곳을 나타내는 정보로만 적습니다. 매일 바뀌는 값(티어별 데이터 보유 기간 등)은 적지 않습니다.

## 버전
- Elasticsearch 8.12.2

## 노드 구성 (총 108대)
| 역할 | 수 |
|---|---|
| 마스터 | 3 |
| 클라이언트(코디네이팅) | 5 |
| 데이터 | 100 |

## 데이터 티어
| 티어 | 데이터 노드 수 | 랙 |
|---|---|---|
| HOT | 20 | RC12 |
| WARM | 40 | RC10, RC17 |
| WARM-03 | 40 | RC18 |
| 합계 | 100 | |

## 참고
- 오래된 데이터를 삭제하는 정책은 없음

## 미확인 항목 (설명 받으면 채움)
- 역할별 하드웨어 사양(CPU, 메모리, JVM heap, 디스크)
"""


def test_render_matches_existing_page_format():
    validate_infra(SPEC)
    assert render_infra(SPEC, as_of=date(2026, 10, 15), source="API(web-backend)") == EXPECTED


def test_minimal_spec_without_tiers():
    spec = InfraSpec(version="9.0.0", master=3, client=0, data=10)
    validate_infra(spec)
    text = render_infra(spec, as_of=date(2026, 10, 15), source="API(t)")
    assert "## 데이터 티어" not in text and "## 참고" not in text
    assert text.endswith("## 미확인 항목 (설명 받으면 채움)\n- 없음\n")
    assert infra_summary(spec) == "Elasticsearch 9.0.0, 13노드(마스터 3, 클라이언트 0, 데이터 10)"


def test_single_date_is_allowed():
    validate_infra(replace(SPEC, notes=("2026-10-01 증설 완료",)))


@pytest.mark.parametrize("change, match", [
    ({"data": 98}, "합계"),
    ({"version": " "}, "version"),
    ({"master": -1}, "0 이상"),
    ({"notes": ("노드 10.0.0.1 교체",)}, "IP"),
    ({"notes": ("RC12-07 노드 교체",)}, "노드명"),
    ({"notes": ("HOT 보유 2025-03 ~ 2025-10",)}, "날짜 범위"),
    ({"notes": ("2025.03.01-2025.04.01 데이터",)}, "날짜 범위"),
    ({"unconfirmed": ("2025년 3월 ~ 데이터 이동",)}, "날짜 범위"),
    ({"notes": ("첫 줄\n둘째 줄",)}, "한 줄"),
    ({"tiers": (Tier("HOT", 50), Tier("HOT", 50))}, "중복"),
    ({"tiers": (Tier("A|B", 100),)}, "표"),
    ({"tiers": (Tier("HOT", -1), Tier("WARM", 101))}, "0 이상"),
])
def test_rejects_invalid(change, match):
    with pytest.raises(InfraError, match=match):
        validate_infra(replace(SPEC, **change))


def test_infra_scope_is_valid(tmp_path):
    path = write_tokens(tmp_path / "tokens.json", ("infra-admin", "secret", ["infra"]))
    entry = TokenStore.load(path).authenticate("Bearer secret")
    require_scope(entry, "infra")
