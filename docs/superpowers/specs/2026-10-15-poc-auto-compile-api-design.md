# PoC: 자동 컴파일 REST API 설계

작성일: 2026-10-15
관련 문서: `2026-10-13-monitoring-wiki-design.md`(위키 설계), `2026-10-14-mcp-server-design.md`(MCP 서버 설계)

## 1. 목적과 범위
외부 웹 페이지가 승인된 장애 보고서를 한 번 호출로 제출하면, 서버가 그 즉시 마스킹, 컴파일(LLM 포함), 위키 등록까지 끝내는 REST API를 기존 MCP 서버에 추가한다. 조회 API와 인프라 갱신 API를 함께 제공한다. PoC이므로 git을 쓰지 않는다.

| 포함 | 제외(PoC 이후) |
|---|---|
| FastAPI REST + 기존 MCP 유지(한 프로세스) | git(이력, 커밋, 원격) |
| 조회, 보고서 제출 원큐 컴파일, 인프라 갱신 API | 패턴 수정 API, 수동 컴파일 트리거 |
| 마스킹, 컴파일 파이프라인, 스냅샷 롤백 | 제출자 개인 단위 승인 기록, 웹 UI |
| 파일 기반 위키 읽기·쓰기, 토큰 인증 | 대량 처리 최적화, 영속 작업 큐 |

## 2. 이전 설계에서 바뀌는 결정
| 기존 | 변경 |
|---|---|
| 컴파일은 담당자가 Claude Code로 수동 실행 | 제출 즉시 서버가 자동 컴파일 |
| 서버에 LLM 없음 | 서버가 의미 판단 단계에서만 LLM 호출(질문 답변은 여전히 외부 에이전트의 몫) |
| 위키는 git `main`의 커밋된 상태를 읽음 | 파일을 직접 읽고 쓴다. git은 PoC 이후 `GitWikiStore`로 추가 |
| `submit_report`는 raw 저장으로 끝 | MCP `submit_report`도 같은 컴파일 서비스를 사용 |
| 컴파일 롤백은 git | 컴파일 직전 `wiki/` 스냅샷 |

`CLAUDE.md`의 Ingest 절(수동 컴파일, "`main`에 커밋")과 `2026-10-14-mcp-server-design.md`의 git 관련 부분은 구현 시 이 문서에 맞춰 고친다.

## 3. 전제와 승인 모델
- **승인은 웹에서 이미 끝난 상태**로 보고서가 들어온다. 서버는 승인 여부를 확인하지 않고 제출을 승인된 것으로 취급한다.
- 보고서를 넣을 수 있는 사람의 통제(로그인, 권한)는 웹의 책임이다. `submit` 토큰은 웹 **백엔드**만 보관한다. 브라우저에 두지 않는다.
- 접근 로그에는 호출자가 웹 서비스(토큰 이름)로만 남고 실제 제출자는 기록되지 않는다.
- 웹이 마스킹을 했더라도 서버는 항상 마스킹을 한 번 더 한다.

## 4. 구조
```
FastAPI 앱 (한 프로세스, 서버 프로세스는 1개)
 ├─ /api/...  REST ┐
 ├─ /mcp      MCP  ├─ 같은 TokenStore·스코프·접근 로그·속도 제한
 └─ CompileService ─ 단일 워커 큐 ─ 컴파일 파이프라인
WikiStore(인터페이스) ← FileWikiStore(PoC) / GitWikiStore(이후)
```
- `WikiStore`: `read(path)`, `list(dir)`, `write_atomic(path, text)`, `snapshot(dest)`, `write_lock()`. 위키 읽기를 쓰는 모듈(`wiki_reader`, `instructions`, `pending`)은 이 인터페이스를 통해서만 접근한다.
- MCP 앱의 라우트를 FastAPI 앱에 옮겨 붙이고(`/mcp` 유지), 부모 앱 lifespan에서 MCP 세션 관리자와 컴파일 워커를 함께 실행한다(`server/SPIKE.md` "FastAPI 결합 확인", SDK 1.30.0).

## 5. REST API
| 엔드포인트 | 스코프 | 동작 |
|---|---|---|
| `GET /api/index` | read | `wiki/index.md` 전체 |
| `GET /api/patterns/{id}` (`?sections=원인,증상`) | read | 패턴 페이지(`sources` 제외) |
| `GET /api/infra` | read | `wiki/infra/cluster.md` |
| `GET /api/guide` | read | CLAUDE.md "외부 에이전트용 Query 가이드" 절(에이전트와 웹이 같은 질문 규칙을 쓰도록) |
| `POST /api/reports` | submit | 원큐 컴파일(6절). 본문 `{"text": "..."}` |
| `GET /api/reports/{작업ID}` | submit | 작업 상태와 결과 |
| `POST /api/reports/{작업ID}/retry` | submit | 실패한 작업 재시도 |
| `PUT /api/infra` | infra | 인프라 구성 갱신(8절) |
| `GET /healthz` | 없음 | 상태 확인 |

- 스코프는 `read`, `submit`, `infra` 세 가지다(기존 `read`, `submit`에 `infra` 추가).
- `/docs`, `/redoc`, `/openapi.json`은 기본으로 끈다(설정으로 켤 수 있음).
- 오류 응답은 `{"error": "...", "code": "..."}` 형식이다. 인증 실패 401, 스코프 부족 403, 입력 오류 422, 크기 초과 413, 속도 제한 429.

## 6. `POST /api/reports` 원큐 컴파일
### 6.1 응답
| 상태 | 의미 | 본문 |
|---|---|---|
| 200 `compiled` | 완료 | `job_id`, `raw_path`, 만든·갱신한 패턴, `infra_candidates`, `unclassified`, `notes`, `snapshot` |
| 202 `queued`/`running` | 대기 시간 안에 끝나지 않음 | `job_id` (이후 `GET`으로 확인, 서버는 백그라운드에서 계속 처리) |
| 200 `duplicate` | 같은 내용(정규화 해시)이 이미 있음 | 기존 `raw_path`. 컴파일하지 않음 |
| 502 `compile_failed` | 컴파일 실패 | `job_id`, `raw_path`, `error`. raw는 **이미 저장된 상태** |

- 서버는 기본 90초(`WIKI_COMPILE_WAIT_SECONDS`)까지 기다리고, 그때까지 끝나지 않으면 202를 반환한다.
- MCP `submit_report`는 같은 서비스를 쓰되, MCP 클라이언트의 도구 호출 제한 시간이 더 짧을 수 있어 대기 시간을 따로 둔다(`WIKI_MCP_COMPILE_WAIT_SECONDS`, 기본 30초). 초과하면 작업 ID를 반환한다.
- 한 번에 한 건씩 처리한다. 동시에 여러 건이 오면 줄을 서므로 뒤쪽 요청은 202가 될 수 있다.
- 작업 하나의 전체 제한 시간은 `WIKI_COMPILE_TIMEOUT`(기본 300초). 넘기면 `compile_failed`로 처리한다.
- 웹의 HTTP 클라이언트 타임아웃과 프록시 읽기 타임아웃은 대기 시간보다 길게 설정해야 한다.

### 6.2 파이프라인
1. **검증**: UTF-8 텍스트, 비어 있지 않음, NUL 거부, 크기 상한(기본 1MB).
2. **중복 검사 → raw 저장**: 기존 `RawStore`를 재사용한다(KST 파일명, 배타적 생성, 정규화 해시, 파일 락).
3. **마스킹**(7절) 후 텍스트만 LLM에 전달한다.
4. **LLM이 컴파일 계획(JSON) 작성**(9절). 입력은 마스킹된 보고서, 현재 `wiki/index.md`, 컴파일 규칙이다.
5. **계획 검증**(9.2). 실패하면 한 번 재시도하고, 그래도 실패하면 `compile_failed`.
6. **서버 코드가 계산**: `occurrences`, `first_seen`/`last_seen`, `sources`, `confidence`(CLAUDE.md 기준), 색인 행.
7. **스냅샷**: `wiki/` 전체를 `<상태 폴더>/snapshots/<시각>-<작업ID>/`에 복사하고 최근 20개만 보관한다.
8. **원자적 쓰기**(쓰기 락 아래): 패턴 페이지 → `wiki/index.md` → `wiki/log.md` 순. 각 파일은 임시 파일에 쓴 뒤 교체한다.
9. 작업 기록을 저장하고 결과를 반환한다.

LLM은 파일을 쓰지 않는다. 쓰기는 모두 서버 코드가 한다.

### 6.3 작업 큐와 기록
- 단일 워커 스레드가 큐를 순서대로 처리한다. 작업 상태는 `queued`, `running`, `compiled`, `failed`이다.
- 작업 기록은 `<상태 폴더>/jobs/<작업ID>.json`에 파일로 남긴다(PoC에서 영속 큐는 제외하므로, 서버가 재시작되면 `running`이던 작업은 `failed`로 표시하고 retry로 다시 처리한다).
- `retry`는 저장된 raw를 다시 컴파일한다(raw를 새로 저장하지 않음).

## 7. 마스킹
LLM으로 보내기 전에 서버가 항상 수행한다. 위키 개인정보 규칙과 같은 자리표시자를 쓴다.

| 대상 | 방법 | 치환 |
|---|---|---|
| 이메일 | 정규식 | `<USER>` |
| IPv4 | 정규식 | `<IP>` |
| `user=<값>`, `company=<값>`, `keyword=[...]`(쿼리 로그 키-값) | 키 기준 | `<USER>`, `<COMPANY>`, `<KEYWORD>` |
| 회사·고객명 | `WIKI_MASK_NAMES_FILE`의 이름 목록과 일치 | `<COMPANY>` |

- 마스킹된 텍스트는 저장하지 않는다. raw에는 원문이 남는다(기존 규칙).
- **한계**: 목록에 없는 회사명, 본문에 풀어 쓴 사람 이름은 가려지지 않고 전송된다. 이름 목록은 담당자가 관리한다.
- 계획 검증(9.2)에서 이메일·IPv4가 남았는지 한 번 더 확인한다.

## 8. `PUT /api/infra` (스코프 `infra`)
### 8.1 입력(JSON)
```json
{
  "version": "8.12.2",
  "nodes": {"master": 3, "client": 5, "data": 100},
  "tiers": [
    {"name": "HOT", "data_nodes": 20, "racks": ["RC12"]},
    {"name": "WARM", "data_nodes": 40, "racks": ["RC10", "RC17"]},
    {"name": "WARM-03", "data_nodes": 40, "racks": ["RC18"]}
  ],
  "notes": ["오래된 데이터를 삭제하는 정책은 없음"],
  "unconfirmed": ["역할별 하드웨어 사양(CPU, 메모리, JVM heap, 디스크)"]
}
```
### 8.2 검증과 처리
- `nodes.data`가 `tiers`의 `data_nodes` 합과 같아야 한다(`tiers`가 있을 때). 다르면 422.
- 어떤 문자열 필드에도 IPv4, 노드명 형태(`RC\d+-\d+`), 날짜 범위가 있으면 422(노드명·IP·매일 바뀌는 값 금지 규칙).
- 서버가 `wiki/infra/cluster.md`를 기존 형식(frontmatter `id`, `summary`, `as_of`, `source` + 버전, 노드 구성 표, 데이터 티어 표, 미확인 항목)으로 만들어 쓴다. `as_of`는 서버의 오늘 날짜(KST), `source`는 `API(<토큰 이름>)`.
- 쓰기 전에 스냅샷을 만들고 쓰기 락을 잡는다. 컴파일 작업과 동시에 실행되지 않는다.
- **가정**: 입력은 구조화된 JSON이다. 마크다운 본문을 그대로 받는 방식이 필요하면 이 절을 고친다.

## 9. 컴파일 계획(JSON)
### 9.1 형식
```json
{
  "patterns": [
    {
      "action": "create | update",
      "id": "kebab-case-id",
      "title": "새 패턴 페이지 제목",
      "summary": "증상과 원인을 담은 한 줄 요약",
      "signature": "색인의 대표 시그니처",
      "resources": ["query", "master"],
      "cause": "원인 본문",
      "symptoms": {"query": "...", "master": "...", "data": "미관측(수집 실패)", "slowlog": "미관측(입력 없음)"},
      "solution": "해결방법 본문",
      "related": [{"id": "other-id", "note": "동시 관측, 연관 미확인"}],
      "first_seen": "YYYY-MM-DD",
      "last_seen": "YYYY-MM-DD"
    }
  ],
  "infra_candidates": [{"item": "...", "report_value": "...", "note": "..."}],
  "unclassified": ["리소스를 판별하지 못한 부분"],
  "notes": ["호출자에게 알릴 사항"]
}
```
- `title`(새 페이지 제목)과 `signature`(색인 대표 시그니처)는 `create`에서 필수다. `update`에서는 원인·해결이 기존과 같으면 `cause`·`solution`을 빈 문자열로 둔다.
- `update`는 현재 색인에 있는 `id`여야 하고, 서버는 `occurrences`+1, `last_seen` 갱신, `sources` 추가, `resources` 합집합, 새 리소스의 증상 추가를 수행한다. 기존 원인·해결은 덮어쓰지 않고 보고서가 다른 내용을 제시하면 "(추가 보고서)" 항목으로 나란히 기록한다.
- `create`는 현재 색인에 없는 `id`여야 하며 `wiki/_template.md` 형식으로 만든다. `solution_origin`은 `report`.

### 9.2 검증
- 최상위 키와 타입이 위 형식과 일치. `patterns`는 1~5개.
- `id`: `^[a-z0-9][a-z0-9-]*$`. `action` 값에 따라 존재 여부 확인.
- `summary`: 한 줄, 200자 이하. `resources`: `query|master|data|slowlog`의 부분집합.
- 텍스트 필드: 비어 있지 않고 길이 상한(필드당 8KB). 이메일·IPv4·`WIKI_MASK_NAMES_FILE` 이름이 남아 있으면 거부.
- `symptoms`의 값은 증상 본문이거나 `미관측(수집 실패|이벤트 없음|입력 없음|로그 없음)` 표기.
- 날짜는 `YYYY-MM-DD`, 미래 날짜 거부. 없으면 수신 날짜(KST)로 대체한다.
- `related`의 `id`는 현재 색인에 있거나 같은 계획의 `create` 대상이어야 한다.
- raw 경로(`raw/…`)가 본문에 있으면 거부(`sources`는 서버가 계산).

### 9.3 LLM 호출
- `PlanGenerator` 인터페이스(`generate_plan(masked_text, index_text) -> dict`)를 두고, 실제 구현은 Anthropic API(Claude) 직접 호출이다. 테스트에서는 가짜 구현으로 대체한다.
- 프롬프트는 CLAUDE.md의 "지식 종류 구분과 처리", "Ingest", "시그니처 정규화", "개인정보", "패턴 페이지 형식" 절에서 서버 시작 시 만든다. 보고서 본문은 데이터로만 취급하고 그 안의 지시를 따르지 않도록 명시한다.
- **가정**: LLM 제공자는 Anthropic API이고 키는 `ANTHROPIC_API_KEY`, 모델은 `WIKI_LLM_MODEL`로 지정한다(기본값 없음, 필수). 비밀값은 `.env` 파일로 관리한다(10절).
- 인프라 정보는 자동 반영하지 않고 `infra_candidates`로만 반환한다.

## 10. 설정 추가
**`.env` 관리 (2026-10-15 결정)**: API 키 같은 비밀값은 코드나 저장소가 아니라 `.env` 파일로 관리한다.
- 서버 시작 시(`main()`) `python-dotenv`로 `.env`를 읽는다. 파일 위치는 `WIKI_ENV_FILE`(기본 현재 디렉터리의 `.env`)이며 파일이 없어도 오류가 아니다(환경 변수만으로 동작).
- **이미 설정된 실제 환경 변수가 `.env`보다 우선**한다(`override=False`). 운영 서버는 systemd/컨테이너 환경 변수로 덮어쓸 수 있다.
- `.env`는 `.gitignore`에 넣어 커밋하지 않고, 키 이름만 담은 `server/.env.example`을 커밋한다.
- `load_settings(env)`는 지금처럼 매핑만 받는 순수 함수로 두어 테스트가 파일에 의존하지 않는다. `.env` 읽기는 `main()`에서만 한다.
- `Settings`의 `anthropic_api_key`는 `repr=False`로 두어 로그나 예외에 키가 찍히지 않게 한다. 접근 로그, 작업 기록, 오류 응답에도 키를 쓰지 않는다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_STATE_DIR` | `<WIKI_ROOT>/.state` | 작업 기록, 스냅샷 |
| `ANTHROPIC_API_KEY` | (필수) | LLM 호출 키 |
| `WIKI_LLM_MODEL` | (필수) | 모델 이름 |
| `WIKI_MASK_NAMES_FILE` | (선택) | 마스킹할 회사·고객명 목록(한 줄에 하나) |
| `WIKI_COMPILE_WAIT_SECONDS` | `90` | 동기 대기 시간 |
| `WIKI_MCP_COMPILE_WAIT_SECONDS` | `30` | MCP `submit_report`의 동기 대기 시간 |
| `WIKI_COMPILE_TIMEOUT` | `300` | 작업 전체 제한 시간 |
| `WIKI_SNAPSHOT_KEEP` | `20` | 스냅샷 보관 개수 |
| `WIKI_ENABLE_DOCS` | `false` | `/docs` 노출 |

## 11. 인증과 감사
- 기존 `TokenStore`를 재사용하고 스코프에 `infra`를 추가한다. 스코프는 MCP와 같은 공용 처리기(`handlers._run`)에서 확인한다. REST 라우트는 `Authorization` 헤더만 받아 넘긴다.
- 접근 로그 형식은 그대로이며, 컴파일 작업과 인프라 갱신 이벤트(작업 ID, 결과 상태)를 추가로 기록한다. 보고서 본문은 기록하지 않는다.
- `infra` 토큰은 인프라 갱신 권한이므로 승인 주체에게만 발급한다.

## 12. 테스트 방침
- LLM은 가짜 `PlanGenerator`로 대체한다.
- 마스킹(각 대상, 목록, 남은 개인정보 거부), 계획 검증(9.2의 각 규칙), `create`/`update` 적용 결과(`occurrences`, `sources`, `confidence`, 색인 행), 원자적 쓰기 순서, 스냅샷 생성·보관 개수, 큐 직렬화, 90초 후 202 전환, 재시작 후 `running` 작업 처리, retry, 중복 제출을 검증한다.
- 인프라: 정상 입력의 렌더링, 합계 불일치·IP·노드명 거부, `as_of` 자동 갱신.
- 권한: `read`/`submit`/`infra` 각각의 허용·거부, `/docs` 기본 비활성.
- `WikiStore`: `FileWikiStore` 단위 테스트와, 기존 `wiki_reader`·`pending`·`instructions`가 인터페이스 기준으로 같은 결과를 내는지 확인한다(기존 테스트를 임시 폴더 기준으로 이관).
- **평가 사례**: 기존 raw 4개 파일(사건 3건)을 마스킹해 입력으로 넣고, 기대하는 `resources`와 `summary` 핵심어를 비교하는 선택 실행 테스트(`tests/test_llm_eval.py`, `WIKI_LLM_EVAL=1`)를 둔다.

## 13. 위험과 감수
- 사람 검토 없이 바로 반영하므로 잘못된 컴파일의 복구 수단은 스냅샷뿐이다(git 이력 없음).
- 마스킹은 정규식과 목록 기반이라 목록에 없는 회사명·본문 속 이름은 전송된다.
- 서버가 위키의 유일한 쓰기 주체다. 담당자가 `wiki/`를 직접 고치려면 서버를 멈춘 뒤에 한다.
- LLM 출력 품질에 따라 컴파일 결과가 달라진다. 계획 검증과 평가 사례로 완화한다.

## 14. PoC 이후
- `GitWikiStore`로 git 이력·커밋·롤백 추가, 원격 저장소 연동.
- 패턴 수정 API, 제출자 단위 기록, 영속 작업 큐, 검토 대기 모드.
