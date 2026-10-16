# MonitoringWiki

사람이 승인한 Elasticsearch 장애 보고서를 장애 패턴(원인 → 증상 → 해결방법)으로 컴파일해 쌓는 LLM Wiki입니다. 운영 규칙은 [AGENTS.md](AGENTS.md)에 있습니다.

## 폴더 구조

| 경로 | 내용 | git |
|---|---|---|
| `raw/YYYY-MM-DD/HHMMSS.txt` | 승인된 보고서 원본(추가만, 개인정보 포함) | 제외 |
| `wiki/index.md` | 통합 색인 | 추적 |
| `wiki/log.md` | 시간순 작업 기록 | 추적 |
| `wiki/patterns/` | 장애 패턴 페이지 | 추적 |
| `wiki/infra/` | 현재 클러스터 구성 | 추적 |
| `wiki/_template.md` | 패턴 템플릿 | 추적 |
| `server/` | MCP + REST 서버(`src/wiki_mcp/{api,core,services,wiki}`, `tests`, `scripts`) | 추적 |
| `docs/superpowers/` | 설계(specs)와 구현 계획(plans) | 추적 |
| `.state/` | 작업 기록, 위키 스냅샷 | 제외 |
| `.local-test/` | 로컬 실행 확인용 | 제외 |

서버 실행과 설정은 [server/README.md](server/README.md)를 참고합니다.

## 서버 패키지 구조 (`server/src/wiki_mcp/`)

의존 방향은 `api → services → wiki`이고, 셋 모두 `core`를 가져다 씁니다. `core`는 다른 패키지를 가져오지 않습니다.

| 패키지 | 역할 |
|---|---|
| `api/` | 전송 계층. REST(`rest.py`), MCP(`mcp_adapter.py`), 인증 미들웨어(`middleware.py`) |
| `core/` | 공용 기반. 설정(`config.py`), 컴파일 계획 모델·검증(`plan.py`), 개인정보 마스킹(`masking.py`), 토큰 인증(`auth.py`), 속도 제한(`ratelimit.py`) |
| `services/` | 처리 로직. 공용 처리기(`handlers.py`), 컴파일 서비스·LLM(`compile_service.py`, `llm.py`), 접근 로그, 인프라, 미반영 raw 점검 |
| `wiki/` | 저장소 계층. `WikiStore`(위키 파일), `RawStore`(raw), 위키 읽기·쓰기·페이지 렌더링 |
| (루트) | `app.py`(조립·실행), `instructions.py`(AGENTS.md 가이드 추출) |
