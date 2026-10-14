---
id: es-agg-query-slow-with-master-stats-wait
summary: 다수 월 인덱스를 조회하는 장기간 agg 쿼리가 10초 이상 지연되고, 같은 시간대 마스터의 indices:monitor/stats 요청이 데이터 노드 응답 대기로 타임아웃된 현상
confidence: medium
resources: [query, master]
first_seen: 2026-10-12
last_seen: 2026-10-12
occurrences: 1
sources: [raw/2026-10-14/105317.txt]
solution_origin: report
---
# 다수 인덱스 장기간 agg 쿼리 지연과 마스터 stats 응답 대기

## 원인
(보고서 판단) 많은 인덱스를 참조하는 특정 집계 쿼리의 구조와 마스터 노드의 일시적인 응답 대기가 결합되어 개별 쿼리 지연이 발생한 것으로 보입니다. 지연된 쿼리는 공통적으로 7개 이상의 인덱스를 참조하는 `agg` 형태였고, 같은 시간대에 마스터 노드에서 `indices:monitor/stats` 응답 대기가 15.01초간 발생했습니다.

## 증상
- **query**: `run_time=<N> success=Y host=<IP> service=web company=<COMPANY> user=<USER> cmd=agg keyword=[<KEYWORD>] s_date=<N> e_date=<N> date_range=<N> search_count=0` 중 `run_time`이 10초 이상. 10초 이상 9건(전체 2316건), 최대 25.24s. 분별 최대 실행시간은 25.24 → 16.66 → 12.06 → 4.14 → 0.76 → 7.32초.
- **master**: `<TS> WARN o.e.t.TransportService Received response for a request that has timed out, sent [<N>s/<N>ms] ago, timed out [<N>s/<N>ms] ago, action [indices:monitor/stats[n]], node [{<NODE>}{...}{<IP>}...{d}...tier=hot...], id [<N>]`
- **data**: 미관측(수집 실패) — 대기가 발생한 노드의 로그를 SSH로 수집하지 못했습니다.
- **slowlog**: 미관측(이벤트 없음) — 수집했으며 특이사항이 없었습니다.

## 해결방법
(보고서 권장 조치) 다수의 인덱스를 참조하는 집계 쿼리의 기간 범위를 축소하여 실행합니다.

## 관련 패턴
없음
