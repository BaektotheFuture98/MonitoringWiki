# MonitoringWiki 서버 (MCP + REST, PoC)

외부 에이전트는 MCP로 장애 패턴 위키를 조회하고, 외부 웹은 REST로 조회·보고서 제출·인프라 갱신을 합니다. 승인된 보고서가 들어오면 서버가 즉시 마스킹 → LLM 컴파일 계획 → 검증 → 위키 등록까지 처리합니다. PoC이므로 git 없이 파일을 직접 읽고 씁니다. 설계: `docs/superpowers/specs/2026-10-15-poc-auto-compile-api-design.md`

## 설치
```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -e .
```

## 설정
비밀값(API 키)은 `.env`로 관리합니다. `server/.env.example`을 `server/.env`로 복사해 값을 채우세요. `.env`는 커밋하지 않습니다(`.gitignore`). 서버는 시작할 때 `WIKI_ENV_FILE`(기본: 현재 디렉터리의 `.env`)을 읽으며, 이미 설정된 환경 변수가 `.env`보다 우선합니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_ROOT` | (필수) | 위키 저장소 경로 |
| `WIKI_TOKENS_FILE` | (필수) | 토큰 파일 경로 |
| `WIKI_ACCESS_LOG` | (필수) | 접근 로그 경로(저장소 밖) |
| `ANTHROPIC_API_KEY` | (필수) | LLM 호출 키. `.env`에 둡니다 |
| `WIKI_LLM_MODEL` | (필수) | 컴파일에 쓸 모델 이름 |
| `WIKI_ENV_FILE` | `.env` | 읽을 `.env` 경로 |
| `WIKI_STATE_DIR` | `<WIKI_ROOT>/.state` | 작업 기록(`jobs/`)과 스냅샷(`snapshots/`) |
| `WIKI_MASK_NAMES_FILE` | (선택) | 마스킹할 회사·고객명 목록(한 줄에 하나, `#` 주석) |
| `WIKI_COMPILE_WAIT_SECONDS` | `90` | REST 제출의 동기 대기 시간 |
| `WIKI_MCP_COMPILE_WAIT_SECONDS` | `30` | MCP `submit_report`의 동기 대기 시간 |
| `WIKI_COMPILE_TIMEOUT` | `300` | 작업 하나의 제한 시간 |
| `WIKI_SNAPSHOT_KEEP` | `20` | 스냅샷 보관 개수 |
| `WIKI_ENABLE_DOCS` | `false` | `/docs`, `/redoc`, `/openapi.json` 노출(켜면 토큰 없이 열림) |
| `WIKI_TZ` | `Asia/Seoul` | raw 파일명·기준일 시간대 |
| `WIKI_MAX_REPORT_BYTES` | `1048576` | 제출 크기 상한 |
| `WIKI_HOST`, `WIKI_PORT` | `127.0.0.1`, `8000` | 바인드 주소 |

## 토큰 발급
1. 토큰 문자열을 만들고 해시를 구합니다: `python -m wiki_mcp.auth <토큰>`
2. 토큰 파일(JSON 배열)에 해시만 저장합니다:
   ```json
   [
     {"name": "query-agent", "sha256": "<해시>", "scopes": ["read"]},
     {"name": "web-backend", "sha256": "<해시>", "scopes": ["read", "submit"]},
     {"name": "infra-admin", "sha256": "<해시>", "scopes": ["infra"]}
   ]
   ```
3. 서버를 재시작합니다.

| 스코프 | 누구에게 | 할 수 있는 일 |
|---|---|---|
| `read` | 질문용 외부 에이전트, 웹(조회) | 색인·패턴·인프라·가이드 조회 |
| `submit` | 웹 **백엔드**(승인 후 제출) | 보고서 제출, 작업 조회·재시도 |
| `infra` | 인프라 담당 승인 주체 | 인프라 구성 갱신 |

**발급 정책:** 제출 자체가 승인이므로 `submit`은 승인을 마친 웹 백엔드에만 주고 브라우저에 두지 않습니다. 질문용 외부 에이전트에는 `read`만 줍니다. `infra`는 인프라 구성을 덮어쓰는 권한이므로 승인 주체에게만 줍니다.

## 실행
```bash
cd server
cp .env.example .env     # 값 채우기
wiki-mcp
```
- REST: `/api/*`, MCP: `/mcp`(streamable HTTP), 상태 확인: `GET /healthz`(토큰 불필요)
- 서버 프로세스는 1개로 운영합니다(컴파일 큐, 쓰기 락, 속도 제한이 프로세스 안에 있음).

## REST API
| 메서드와 경로 | 스코프 | 설명 |
|---|---|---|
| `GET /api/index` | read | 색인 `{"text": "..."}` |
| `GET /api/patterns/{id}?sections=원인,증상` | read | 패턴 페이지(`sources` 제외) |
| `GET /api/infra` | read | 클러스터 구성 페이지 |
| `GET /api/guide` | read | 외부 에이전트용 Query 가이드 |
| `POST /api/reports` | submit | 본문 `{"text": "<승인된 보고서 원문>"}`. 저장 → 마스킹 → 컴파일 → 위키 등록 |
| `GET /api/reports/{job_id}` | submit | 작업 상태와 결과 |
| `POST /api/reports/{job_id}/retry` | submit | 실패한 작업 재시도(raw는 다시 저장하지 않음) |
| `PUT /api/infra` | infra | 인프라 구성 덮어쓰기(아래 예시) |

제출·재시도 응답
| HTTP | `status` | 의미 |
|---|---|---|
| 200 | `compiled` | 완료. `created`, `updated`, `infra_candidates`, `unclassified`, `notes`, `snapshot` 포함 |
| 200 | `duplicate` | 같은 내용이 이미 있음. 컴파일하지 않음 |
| 202 | `queued`/`running` | 대기 시간 안에 끝나지 않음. `job_id`로 나중에 조회 |
| 502 | `failed` | 컴파일 실패(`code: compile_failed`). raw는 저장된 상태이며 retry 가능 |

오류 응답은 `{"error": "...", "code": "..."}`이며 401(토큰), 403(스코프), 404, 409(재시도 불가), 413(크기), 422(입력), 429(속도 제한)를 씁니다.

인프라 갱신 예시(노드명·IP·날짜 범위는 거부, 데이터 노드 수는 티어 합계와 같아야 함):
```bash
curl -X PUT localhost:8000/api/infra -H "Authorization: Bearer <infra 토큰>" -H "Content-Type: application/json" -d '{
  "version": "8.12.2",
  "nodes": {"master": 3, "client": 5, "data": 100},
  "tiers": [
    {"name": "HOT", "data_nodes": 20, "racks": ["RC12"]},
    {"name": "WARM", "data_nodes": 40, "racks": ["RC10", "RC17"]},
    {"name": "WARM-03", "data_nodes": 40, "racks": ["RC18"]}
  ],
  "notes": ["오래된 데이터를 삭제하는 정책은 없음"],
  "unconfirmed": ["역할별 하드웨어 사양(CPU, 메모리, JVM heap, 디스크)"]
}'
```

## 프록시
HTTPS는 사내 리버스 프록시에서 처리합니다. MCP 응답이 스트리밍(SSE)이므로 버퍼링을 끄고, 제출은 최대 `WIKI_COMPILE_WAIT_SECONDS`(90초)까지 응답을 기다리므로 읽기 타임아웃을 그보다 길게 둡니다. 서버가 Host 헤더를 검사하므로(`SPIKE.md`) 업스트림 Host를 `127.0.0.1:<WIKI_PORT>`로 넘깁니다. nginx 예:
```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host 127.0.0.1:8000;
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 2m;
}
```
웹의 HTTP 클라이언트 타임아웃도 `WIKI_COMPILE_WAIT_SECONDS`보다 길게(예: 120초) 설정합니다.

## 질문 명령 (위키로만 답하기)
서버는 `ask` 프롬프트를 제공하며, Claude Code에서는 슬래시 명령으로 보입니다(`/` 입력 후 `monitoring-wiki` 검색, 보통 `/mcp__monitoring-wiki__ask`).
```
/mcp__monitoring-wiki__ask 질문내용
/mcp__monitoring-wiki__ask 질문내용 true      # 두 번째 값(allow_inference)이 true면 일치가 없을 때만 '위키 외 추론(미검증)'을 덧붙임
```
- 명령을 쓰면 항상 `get_index`로 시작해 후보 패턴을 확인하고, 위키에 없으면 "알려진 패턴 없음"으로 답하게 지시합니다. 모델이 지시를 어길 가능성이 0은 아니므로 답변에 표시된 호출 도구와 일치 근거를 확인하세요.
- 프롬프트 목록은 연결할 때 받아 가므로, 서버를 갱신한 뒤에는 Claude Code에서 다시 연결해야 합니다.

## 담당자 작업
- 서버가 위키의 유일한 쓰기 주체입니다. `wiki/`를 직접 고치려면 서버를 멈춘 뒤에 하세요.
- 컴파일 실패 확인: 제출 응답의 `error`, `GET /api/reports/{job_id}`, `<WIKI_STATE_DIR>/jobs/*.json`. 다시 처리: `POST /api/reports/{job_id}/retry`. 서버가 재시작되면 처리 중이던 작업은 `failed`로 바뀌므로 retry합니다.
- 위키에 반영되지 않은 raw 목록: `WIKI_ROOT=<저장소> python -m wiki_mcp.pending`
- 되돌리기: 서버를 멈추고 `<WIKI_STATE_DIR>/snapshots/<시각>-<작업ID>/`를 `wiki/`로 복사합니다(최근 `WIKI_SNAPSHOT_KEEP`개 보관).
- 컴파일 품질 점검(실제 LLM 호출, 선택): `WIKI_LLM_EVAL=1 python -m pytest tests/test_llm_eval.py -v`

## 주의
- `raw/`는 git에 넣지 않습니다. 개인정보가 포함된 원문이므로 **서버 디스크 백업을 반드시 따로 구성**하세요.
- 마스킹은 정규식과 이름 목록 기반입니다. 목록에 없는 회사명이나 본문에 풀어 쓴 사람 이름은 LLM으로 전송됩니다. `WIKI_MASK_NAMES_FILE`을 관리하세요.
- 외부 instructions와 컴파일 규칙은 서버 시작 시 `AGENTS.md`에서 읽습니다. 바꾸면 서버를 재시작하세요.
