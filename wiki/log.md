# 작업 로그

형식: `## [YYYY-MM-DD HH:MM] <ingest|query|promote|reject|lint> | <대상>` 아래에 한 줄 요약. 최신 항목이 아래에 추가됩니다.

## [2026-10-13 00:00] init | 위키 골격 생성
- 디렉터리와 인덱스 파일을 초기화했습니다.

## [2026-10-14 00:00] lint | 샘플 패턴 삭제
- 샘플 패턴 2개와 관련 색인 행을 삭제하고 빈 위키로 초기화했습니다.

## [2026-10-14 00:00] ingest | raw/2025-03-24 (master 로그 + 작업자 노트)
- 신규 draft 패턴 `es-nori-dictionary-mismatch-undesired-allocations` 생성 (confidence low, 증거 리소스 master 1개). 작업자가 수행한 조치는 solution_origin: human, 나머지 해결안은 미검증으로 표시했습니다.

## [2026-10-14 00:00] promote | es-nori-dictionary-mismatch-undesired-allocations
- 사람 승인으로 drafts에서 patterns로 승격했습니다. status: verified, solution_origin: human 유지. 해결방법 2~4번은 사람이 검증하지 않아 항목별 (미검증) 표시를 남겼습니다.

## [2026-10-14 08:40] ingest | raw/2026-10-14/083836.txt (분석 보고서 텍스트)
- 신규 draft 2건 생성: `es-wide-index-agg-query-slow`(query), `es-master-stats-response-timeout`(master). 두 증상은 연관 증거가 없어 분리하고 서로 "동시 관측, 연관 미확인"으로 링크했습니다. 둘 다 confidence low, 원인 미상.
- 보고서의 결론·원인 판단·권장 조치는 입력에서 제외됨. 개인정보는 raw에 원문 보관(사용자 허용), 위키 페이지에는 치환.
- CLAUDE.md 보강: 미관측 세분화, 파생 분석 취급, 개인정보 치환, 패턴 분리 기준.

## [2026-10-14 09:00] lint | draft를 wiki 밖으로 분리
- `wiki/drafts/`를 최상위 `drafts/`로 이동하고, wiki 색인(index, symptoms-index, by-resource)에서 draft를 제외했습니다. draft 목록은 `drafts/index.md`로 관리합니다. Query는 `wiki/patterns/`만 근거로 씁니다.

## [2026-10-14 10:00] lint | 색인에 한 줄 요약 추가, 검색 규칙 정리
- 패턴 frontmatter에 `summary` 필드를 추가하고 index, symptoms-index, drafts/index에 요약 열을 넣었습니다. Query는 색인을 읽고 의미로 후보를 판단하도록 규칙을 정리했습니다(후보 선택은 Claude, MCP는 읽기만 제공).

## [2026-10-14 10:30] infra | 클러스터 구성 페이지 추가
- `wiki/infra/cluster.md`를 사용자 설명 기준으로 작성했습니다(노드명·IP·랙 위치 제외). 미확인 항목은 페이지에 목록으로 남겼습니다.

## [2026-10-14 10:45] infra | 티어별 데이터 노드 수 반영
- `wiki/infra/cluster.md`에 HOT 20 / WARM 40 / WARM-03 40 데이터 노드를 추가하고 미확인 항목에서 제거했습니다(합계 100, 마스터 3, 클라이언트 5 확인).

## [2026-10-14 10:50] infra | 파생 열 제거
- 오해 소지가 있는 "노드당 평균 보유 개월 수" 열을 `wiki/infra/cluster.md`에서 삭제했습니다.

## [2026-10-14 11:10] infra | 티어별 랙 추가
- 랙은 노드명이 아니라 티어의 위치 정보이므로 `wiki/infra/cluster.md` 티어 표에 랙 열(HOT RC12, WARM RC10·RC17, WARM-03 RC18)을 추가하고 규칙을 정정했습니다.

## [2026-10-14 11:20] infra | 보유 기간 제거
- 매일 바뀌는 값이라 `wiki/infra/cluster.md`에서 티어별 보유 기간(날짜 범위, 개월 수)을 삭제했습니다. 티어 간 이동 방식을 미확인 항목에 추가했습니다.

## [2026-10-14 11:30] lint | 승인된 보고서 직접 컴파일 방식으로 전환
- draft/승격 단계와 `drafts/`를 폐기하고, 승인된 전체 보고서를 위키에 직접 컴파일하는 방식으로 바꿨습니다(`approved_by` 없음, 제출 자체가 승인). 색인은 `wiki/index.md` 하나로 통합하고 `symptoms-index.md`, `by-resource/*`를 삭제했습니다.

## [2026-10-14 11:30] ingest | raw/2026-10-14/105317.txt (승인된 전체 보고서)
- draft 2건(`es-wide-index-agg-query-slow`, `es-master-stats-response-timeout`)을 전체 보고서로 재컴파일해 `es-agg-query-slow-with-master-stats-wait`로 통합 등록했습니다(confidence medium, 근거 한계 기록).
- 결론 없는 질문용 텍스트였던 `raw/2026-10-14/083836.txt`는 새 규칙(질문 입력은 raw에 저장하지 않음)에 따라 삭제했습니다.

## [2026-10-14 11:45] lint | 근거 한계 섹션 제거, 옛 계획서 삭제
- 패턴 페이지, 템플릿, CLAUDE.md, 설계 문서에서 `근거 한계` 섹션과 관련 규칙(Ingest 근거 점검)을 제거했습니다. 옛 구조 기준 구현 계획서(docs/superpowers/plans/)를 삭제했습니다.

## [2026-10-14 11:19] ingest | raw/2026-10-14/111932.txt (승인된 보고서: quetta 템플릿 충돌 + 한글 단어 분석 이슈)
- 신규 패턴 `es-index-template-conflict-and-korean-term-tokenization` 생성(confidence low, 원인 복합·확정 불가). 클라이언트 노드 로그는 4개 리소스에 배정하지 않고 미분류로 기록했습니다.

## [2026-10-14 11:27] lint | 인프라와 로그 불일치 처리 규칙 추가
- 과거 로그의 노드 티어·랙이 현재 인프라 페이지와 달라도 오류로 단정하지 않고 "과거 구성과 다를 수 있음"으로 표기하는 규칙을 CLAUDE.md에 추가했습니다.

## [2026-10-14 11:29] lint | 인프라와 로그 불일치 처리 규칙 되돌림
- 직전에 추가한 "로그와 구성이 다를 때" 규칙을 사용자 요청으로 CLAUDE.md에서 제거했습니다(규칙 없이 이전 상태로 복귀).

## [2026-10-14 11:41] lint | MCP 서버 설계 반영
- MCP 서버 설계 문서(docs/superpowers/specs/2026-10-14-mcp-server-design.md)를 작성했습니다.
- `raw/`를 git에서 제외(.gitignore)하고, CLAUDE.md에 Ingest 시작점(서버가 저장한 raw)·커밋 단계·raw 경로 기록, "외부 에이전트용 Query 가이드" 절을 추가했습니다.

## [2026-10-15 14:55] lint | 지식 종류 구분과 처리 규칙 정립
- CLAUDE.md에 "지식 종류 구분과 처리" 절을 신설하고(원본/패턴/인프라 구분 기준, 섞였을 때의 처리), Ingest에 "인프라 갱신 후보" 단계(6단계)를 추가했습니다. 보고서 속 구성 정보는 인프라를 자동 갱신하지 않습니다.

## [2026-10-16 10:54] ingest | raw/2026-10-16/105449.txt
- 자동 컴파일(작업 f0ebd96fb355). 생성: es-search-circuit-breaking-excessive-agg-size / 갱신: 없음
- 인프라 갱신 후보 1건은 위키에 반영하지 않고 작업 결과로만 보고했습니다.
