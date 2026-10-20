# MonitoringWiki

사람이 승인한 Elasticsearch 장애 보고서를 장애 패턴(원인 → 증상 → 해결방법)으로 컴파일해 쌓는 LLM Wiki입니다. 운영 규칙은 [AGENTS.md](AGENTS.md)에 있습니다.

## 빠른 시작

```bash
git clone https://github.com/BaektotheFuture98/MonitoringWiki.git
cd MonitoringWiki/server

# Python 3.11 이상 필요
python -m venv .venv

# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows Git Bash
source .venv/Scripts/activate

pip install -e ".[dev]"

cp .env.example .env   # 값 채우기 (아래 설정 참고)
wiki-mcp               # 서버 실행 (기본 http://127.0.0.1:8000)
```

설정과 토큰 발급 등 상세 안내는 [server/README.md](server/README.md)를 참고합니다.

## 폴더 구조

| 경로 | 내용 | git |
|---|---|---|
| `raw/` | 승인된 보고서 원본(추가만, 개인정보 포함) | 제외 (`raw/.gitkeep`만 추적) |
| `wiki/index.md` | 통합 색인 | 추적 (빈 템플릿으로 시작) |
| `wiki/log.md` | 시간순 작업 기록 | 추적 (빈 템플릿으로 시작) |
| `wiki/patterns/` | 장애 패턴 페이지 | 제외 (`.gitkeep`만 추적) |
| `wiki/infra/` | 현재 클러스터 구성 | 제외 (`*.example.md`만 추적) |
| `wiki/_template.md` | 패턴 페이지 형식 템플릿 | 추적 |
| `server/` | MCP + REST 서버 소스, 테스트, 스크립트 | 추적 |
| `docs/` | 운영 명세(`wiki-spec.md`), 외부 에이전트 가이드(`mcp-agent-guide.md`) | 추적 |
| `.state/` | 작업 기록, 위키 스냅샷 | 제외 |

## 서버 패키지 구조 (`server/src/wiki_mcp/`)

의존 방향은 `routers → services → repositories`이고, 셋 모두 `core`를 가져다 씁니다. `core`는 다른 패키지를 가져오지 않습니다.

| 패키지 | 역할 |
|---|---|
| `routers/` | 전송 계층. REST(`rest.py`), MCP(`mcp_adapter.py`) |
| `services/` | 처리 로직. 컴파일 서비스(`compile_service.py`), LLM 호출(`llm.py`), 위키 조회·쓰기(`wiki_service.py`) |
| `repositories/` | 저장소 계층. `WikiStore`(`store.py`), `RawStore`(`raw_store.py`), `JobStore`(`job_store.py`) |
| `core/` | 공용 기반. 설정(`config.py`), 예외(`errors.py`), 인증(`auth.py`), 속도 제한(`ratelimit.py`), 인증 미들웨어(`middleware.py`), 마스킹(`masking.py`), 컴파일 계획(`plan.py`), 마크다운 유틸(`markdown.py`) |
| (루트) | `app.py` — 컴포지션 루트·실행 진입점 |

`server/scripts/`에는 담당자용 도구가 있습니다: `pending.py`(미반영 raw 목록), `smoke.py`(서버 점검).
