---
id: es-nori-dictionary-mismatch-undesired-allocations
summary: 노드별 Nori 사용자 사전 불일치로 샤드 생성이 실패하고 undesired_allocations가 증가하는 장애
confidence: low
resources: [master]
first_seen: 2025-03-24
last_seen: 2025-03-25
occurrences: 1
sources: [raw/2025-03-24/133734_master.log, raw/2025-03-24/incident-note.md]
solution_origin: human
---
# Nori 사용자 사전 불일치로 인한 샤드 생성 실패와 undesired_allocations 증가

## 원인
노드별로 설정된 Nori 사용자 사전(`user_dictionary`)과 일부 인덱스가 참조하는 사전이 일치하지 않았습니다. 그 인덱스의 샤드를 다른 노드로 재배치(peer recovery)하거나 리인덱스하는 과정에서 사전을 읽지 못해 `failed to create index`가 반복됐고, 특정 노드에 부하가 몰려 GC 증가와 CircuitBreaker 발생까지 이어졌습니다. (작업자 결론. 마스터 로그에는 사전 읽기 IOException만 있고, 사전 내용 불일치 자체를 보여주는 증거는 없습니다.)

## 증상
- **query**: 미관측(로그 없음) (작업자 결론에 CircuitBreaker 발생이 언급되나 로그 미첨부)
- **master**: `<TS> WARN AllocationService [<NODE>] failing shard [FailedShard[routingEntry=[<INDEX>][<N>], ..., recovery_source[peer recovery], s[INITIALIZING], ..., message=failed to create index, failure=java.lang.IllegalArgumentException: IOException while reading user_dictionary: <PATH>/nori_dictionary.txt, markAsStale=true]]`
- **data**: 미관측(로그 없음) (로그 미첨부). 작업자 노트: hot 노드에서 서버별로 돌아가며 GC가 크게 늘고 CPU 사용률이 증가
- **slowlog**: 미관측(입력 없음)
- **API**: `GET _internal/desired_balance`의 `undesired_allocations`가 2에서 시작해 점진적으로 최대 약 1000까지 증가

## 해결방법
> 1번은 작업자가 실제로 수행해 회복을 확인한 조치입니다. 2~4번은 Claude 추론이며 사람이 검증하지 않았으므로 항목별 `(미검증)` 표시를 유지합니다. 공식 문서 링크는 확인하지 못했습니다.

1. (작업자 수행) 사전과 연관 있을 법한 리인덱스 완료 인덱스(`lucy_main_v3_20240101`~`20240811`)를 전부 삭제하자 undesired_allocations가 줄기 시작했고, 1000에서 0까지 약 6시간 걸림.
   - 주의: 샤드 생성 실패의 직접 대상은 `sample_lucy3_fleet_log_shlee_20240412`였는데, 이 인덱스를 삭제한 직후에는 오히려 undesired_allocations가 증가했습니다. 회복의 직접 원인이 어느 인덱스 삭제였는지는 노트만으로는 분리되지 않습니다.
2. (미검증) 모든 노드의 `config/nori_dictionary/nori_dictionary.txt`가 동일한 파일(내용·권한·소유자)인지 확인하고 일치시킵니다.
3. (미검증) 인덱스 설정이 파일 경로 대신 `user_dictionary_rules`를 직접 포함하도록 바꾸면 노드별 파일 불일치 문제를 피할 수 있는지 검토합니다.
4. (미검증) 사전 변경 후에는 영향받는 인덱스에 한해 리인덱스를 하기 전에 각 노드에서 사전 로드가 되는지 먼저 확인합니다.

## 관련 패턴
없음
