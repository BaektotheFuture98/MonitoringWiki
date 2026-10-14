---
id: es-index-template-conflict-and-korean-term-tokenization
summary: quetta_* 인덱스 템플릿 등록 시 기존 템플릿과 충돌하고 한글 단어('에그')가 한 글자로 분석되는 문제가 겹쳐 일부 노드가 이탈했다 복귀하고 클라이언트 노드 ES가 내려간 장애(원인 복합, 확정 불가)
confidence: low
resources: [query]
first_seen: 2025-09-15
last_seen: 2025-09-15
occurrences: 1
sources: [raw/2026-10-14/111932.txt]
solution_origin: report
---
# 인덱스 템플릿 충돌과 한글 단어 분석 이슈가 겹친 노드 이탈·클라이언트 노드 다운

## 원인
(보고서 판단) 복합 원인이며 하나로 확정하지 못했습니다. 보고서는 두 가지 이슈가 동시에 발생해 무엇이 결정적 문제인지 규정하기 어렵다고 합니다.
- 인덱스 템플릿(`quetta_v10`, 인덱스 패턴 `quetta_*`)을 등록하면서 기존에 등록돼 있던 템플릿과 충돌했습니다.
- 쿼리의 한글 키워드가 한 글자로 분리되어 분석되는 문제가 있었습니다. 보고서는 이를 "지난번과 같은 이슈"라고 하며, 해당 단어의 사전 등록을 요청했습니다.

## 증상
- **query**: 해당 시간대에 들어온 `query_string` 쿼리(`default_operator: AND`, `default_field: an_*`): `(in_date:[<N> TO <N>]) AND (("<KEYWORD>")) AND (kw_sourcetype:(<코드 12개 OR>)) AND (inl_spam:(0))`. 키워드가 한 글자 단위로 분석되는 문제가 있었습니다(보고서).
- **미분류**(보고서가 "클라이언트 노드 로그"로 제공, 4개 리소스에 배정하지 않음): `<TS> INFO o.e.c.m.MetadataIndexTemplateService [<NODE>] adding index template [<NAME>] for index patterns [quetta_*]`
- **master**: 미관측(입력 없음)
- **data**: 미관측(로그 없음) — 일부 노드가 클러스터에서 떨어졌다가 다시 붙었고, 클라이언트 노드 1대의 ES가 내려갔다는 보고서 서술만 있고 로그는 없습니다.
- **slowlog**: 미관측(입력 없음)

## 해결방법
(보고서 조치)
1. 내려간 클라이언트 노드의 ES를 재기동합니다.
2. 인덱스 템플릿을 `quetta_*` 전체가 아니라 실시간용 `quetta_realtime_*`로 범위를 줄여 등록합니다.
3. 분석이 한 글자로 쪼개지는 단어('에그')의 사전 등록을 요청합니다.

## 관련 패턴
- [es-nori-dictionary-mismatch-undesired-allocations](es-nori-dictionary-mismatch-undesired-allocations.md) — 사전(Nori) 관련이나 같은 이슈인지는 미확인
