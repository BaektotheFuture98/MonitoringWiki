# MonitoringWiki MCP 서버

외부 에이전트가 장애 패턴 위키를 조회하고, 승인 주체가 승인된 장애 보고서를 제출하는 MCP 서버입니다. 서버에는 LLM이 없으며, 제출된 보고서의 컴파일은 담당자가 저장소에서 Claude Code로 수동 실행합니다. 설계: `docs/superpowers/specs/2026-10-14-mcp-server-design.md`

## 설치
```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -e .
```

## 설정(환경 변수)
| 변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_ROOT` | (필수) | 위키 저장소 경로 |
| `WIKI_REF` | `main` | 위키를 읽을 git ref |
| `WIKI_TZ` | `Asia/Seoul` | raw 파일명 시간대 |
| `WIKI_TOKENS_FILE` | (필수) | 토큰 파일 경로 |
| `WIKI_ACCESS_LOG` | (필수) | 접근 로그 경로(저장소 밖) |
| `WIKI_MAX_REPORT_BYTES` | `1048576` | 제출 크기 상한 |
| `WIKI_HOST`, `WIKI_PORT` | `127.0.0.1`, `8000` | 바인드 주소 |

## 토큰 발급
1. 토큰 문자열을 만들고 해시를 구합니다: `python -m wiki_mcp.auth <토큰>`
2. 토큰 파일(JSON 배열)에 해시만 저장합니다:
   ```json
   [
     {"name": "query-agent", "sha256": "<해시>", "scopes": ["read"]},
     {"name": "approver", "sha256": "<해시>", "scopes": ["submit"]}
   ]
   ```
3. 서버를 재시작합니다.

**발급 정책:** `submit` 토큰은 승인 주체(사람 또는 승인 시스템)에게만 발급합니다. 질문용 외부 에이전트에는 `read`만 줍니다. 제출 자체가 승인이므로, 질문 에이전트가 `submit`을 가지면 자기 분석을 스스로 승인하게 됩니다.

## 실행
```bash
WIKI_ROOT=/srv/MonitoringWiki WIKI_TOKENS_FILE=/etc/wiki-mcp/tokens.json WIKI_ACCESS_LOG=/var/log/wiki-mcp/access.jsonl wiki-mcp
```
- MCP 엔드포인트: `/mcp`(streamable HTTP), 상태 확인: `GET /healthz`
- HTTPS는 사내 리버스 프록시에서 처리합니다. 응답이 스트리밍(SSE)으로 나가므로 프록시 버퍼링을 꺼야 합니다.
- 서버가 Host 헤더를 검사하는 경우(`SPIKE.md`의 "Host 헤더 검사" 결과) 프록시가 업스트림 Host를 `127.0.0.1:<WIKI_PORT>`로 전달해야 합니다. nginx 예:
  ```nginx
  location /mcp {
      proxy_pass http://127.0.0.1:8000;
      proxy_set_header Host 127.0.0.1:8000;
      proxy_buffering off;
      proxy_read_timeout 300s;
  }
  ```
- 서버 프로세스는 1개로 운영합니다.

## 담당자 작업
- 컴파일 대기 목록: `WIKI_ROOT=<저장소> python -m wiki_mcp.pending`
- 컴파일 규칙은 저장소의 `CLAUDE.md` Ingest 절을 따르고, 끝나면 `main`에 커밋해야 조회에 반영됩니다.

## 주의
- `raw/`는 git에 넣지 않습니다. 개인정보가 포함된 원문이므로 **서버 디스크 백업을 반드시 따로 구성**하세요.
- 외부 instructions는 `main`의 `CLAUDE.md` "외부 에이전트용 Query 가이드" 절에서 서버 시작 시 읽습니다. 바꾸면 커밋 후 재시작하세요.
