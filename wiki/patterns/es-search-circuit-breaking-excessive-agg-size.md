---
id: es-search-circuit-breaking-excessive-agg-size
summary: terms 집계의 size를 너무 크게 설정한 쿼리 반복 호출로 reduce 단계에서 힙 메모리 임계치를 초과하여 검색 실패(429/503) 발생
confidence: medium
resources: [query, data]
first_seen: 2026-10-16
last_seen: 2026-10-16
occurrences: 1
sources: [raw/2026-10-16/105449.txt]
solution_origin: report
---
# 집계 쿼리 terms size 과다로 인한 parent circuit breaker 발생

## 원인
날짜 필터 없이 terms 집계 size를 10000으로 설정한 쿼리가 반복 실행되어 집계 reduce 단계에서 힙 메모리 할당량이 임계치를 초과함. JVM 힙 사이즈(7GB) 대비 할당 공간이 부족함.

## 증상
- **query**: Search request from <IP> failed: CircuitBreakingException [parent] Data too large
- **master**: 미관측(이벤트 없음)
- **data**: [<TS>][WARN ][o.e.i.b.HierarchyCircuitBreakerService] [data-hot-07] attempting to trigger G1GC due to high heap usage; [ERROR][o.e.a.s.TransportSearchAction] [data-hot-07] CircuitBreakingException: [parent] Data too large; [WARN ][o.e.m.j.JvmGcMonitorService] [gc][young] duration [2.1s]
- **slowlog**: 미관측(이벤트 없음)

## 해결방법
1. 집계 쿼리의 terms size 축소 및 필수 날짜 범위 필터 적용. 2. search.max_buckets 설정 조정. 3. 데이터 노드의 JVM 힙 상향 검토.

## 관련 패턴
없음
