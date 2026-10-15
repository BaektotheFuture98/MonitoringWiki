# MonitoringWiki 색인

승인된 보고서에서 컴파일한 Elasticsearch 장애 패턴 위키입니다. 운영 규칙은 `../AGENTS.md`를 따릅니다. LLM은 이 색인을 끝까지 읽고 입력과 의미가 같은 패턴을 골라 해당 페이지를 엽니다.

## 통계
- 패턴: 3

## 패턴
| 패턴 | 요약 | 리소스 | 대표 시그니처 | confidence | last_seen |
|---|---|---|---|---|---|
| [es-nori-dictionary-mismatch-undesired-allocations](patterns/es-nori-dictionary-mismatch-undesired-allocations.md) | 노드별 Nori 사용자 사전 불일치로 샤드 생성이 실패하고 undesired_allocations가 증가하는 장애 | master | master: `failing shard [...] message=failed to create index, failure=...IOException while reading user_dictionary: <PATH>/nori_dictionary.txt` | low | 2025-03-25 |
| [es-agg-query-slow-with-master-stats-wait](patterns/es-agg-query-slow-with-master-stats-wait.md) | 다수 월 인덱스를 조회하는 장기간 agg 쿼리가 10초 이상 지연되고, 같은 시간대 마스터의 indices:monitor/stats 요청이 데이터 노드 응답 대기로 타임아웃된 현상 | query, master | query: `run_time=<N> ... cmd=agg ... date_range=<N>` (run_time ≥ 10s) / master: `Received response for a request that has timed out, ... action [indices:monitor/stats[n]], node [{<NODE>}...` | medium | 2026-10-12 |
| [es-index-template-conflict-and-korean-term-tokenization](patterns/es-index-template-conflict-and-korean-term-tokenization.md) | quetta_* 인덱스 템플릿 등록 시 기존 템플릿과 충돌하고 한글 단어(에그)가 한 글자로 분석되는 문제가 겹쳐 일부 노드가 이탈했다 복귀하고 클라이언트 노드 ES가 내려간 장애(원인 복합, 확정 불가) | query (+ 클라이언트 노드 로그 미분류) | query: `query_string ... (in_date:[<N> TO <N>]) AND (("<KEYWORD>")) AND ...` / 미분류: `MetadataIndexTemplateService [<NODE>] adding index template [<NAME>] for index patterns [quetta_*]` | low | 2025-09-15 |

## 인프라
- [클러스터 구성](infra/cluster.md) — Elasticsearch 8.12.2, 108노드(마스터 3, 클라이언트 5, 데이터 100 = HOT 20 / WARM 40 / WARM-03 40), 티어별 랙 RC12 / RC10·RC17 / RC18 (기준일 2026-10-14)

## 기록
- [작업 로그](log.md)
