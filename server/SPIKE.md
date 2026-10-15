# SDK 확인 결과 (2026-10-14)

## spike_check.py 출력
```
Processing request of type CallToolRequest
mcp version: 1.30.0
tool error text: Error executing tool boom: 의도된 오류
OK       FastMCP(instructions=...)
OK       FastMCP.streamable_http_app
OK       FastMCP.tool(description=...)
OK       RequestContext.request
OK       도구 예외 → isError
ALL OK
exit 0
```
(첫 줄 `Processing request of type CallToolRequest`는 SDK 로그(stderr)이며 stdout/stderr 합쳐 캡처한 순서 차이임.)

## 배포 관련
1. streamable HTTP 기본 경로: `/mcp` 확인. `.venv/Lib/site-packages/mcp/server/fastmcp/server.py:176` (`streamable_http_path: str = "/mcp"`), 라우트 등록 1043/1051행. `FastMCP(streamable_http_path=...)`로 변경 가능.
2. Host 헤더 검사:
   - 기본 동작: `FastMCP(host=...)`의 기본값은 `127.0.0.1`(171행)이고, `transport_security`를 주지 않고 host가 `127.0.0.1`/`localhost`/`::1`이면 DNS rebinding 보호가 자동 활성화되며 allowed_hosts=`127.0.0.1:*`,`localhost:*`,`[::1]:*` (191-195행). 그 외 host로 만들면서 `transport_security`를 주지 않으면 `None` → 보호 비활성(`mcp/server/transport_security.py:50`, 기본 `enable_dns_rebinding_protection=False`).
   - 활성 시 Host가 허용 목록에 없으면 421 `Invalid Host header`, Origin 불일치는 403 (`transport_security.py:121-132`). Content-Type은 POST에서 항상 `application/json`으로 시작해야 함(114-118행).
   - 프록시 뒤 설정: `FastMCP(..., transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["wiki.example.com", "wiki.example.com:*"], allowed_origins=[...]))` (`transport_security.py:19-41`; 정확 일치 또는 `host:*` 포트 와일드카드, 59-69행). 프록시가 Host를 원본 그대로 전달하는지 확인 필요. `host="127.0.0.1"`로 바인드하며 `transport_security`를 생략하면 외부 도메인 Host는 421로 거부됨.
   - 적용 지점: `server.py:850`(SSE), `server.py:984`(streamable HTTP)에서 `self.settings.transport_security` 전달.
3. (참고) 요청 본문 상한 기본 4 MiB(`transport_security.py:15`, `server.py:179` `max_request_body_size`). 제출 상한 1 MiB와는 별개.
4. Host 헤더 검사 실측(Task 9, 실제 서버 `wiki-mcp`, 기본 host 127.0.0.1): `Host: wiki-mcp.internal`로 유효한 토큰과 함께 `POST /mcp initialize` 요청 시 **421**(`Invalid Host header: wiki-mcp.internal`). Host 검사가 켜져 있으므로 README의 프록시 설정(업스트림 Host를 `127.0.0.1:<WIKI_PORT>`로 전달)이 **필수**다. 토큰 없는 `POST /mcp`는 401.

## FastAPI 결합 확인 (2026-10-15, fastapi 0.143.1 / starlette 1.8.0 / mcp 1.30.0)
`FastAPI` 앱 하나에 기존 MCP 앱과 인증 미들웨어, REST 라우트를 함께 올릴 수 있는지 실제 uvicorn 서버로 확인했다. FastAPI 설치로 기존 패키지(starlette 등)는 바뀌지 않았고 기존 테스트 97개도 그대로 통과했다.

| 확인 항목 | 라우트 옮기기(`app.router.routes.extend(mcp_app.routes)`) | 루트 마운트(`app.mount("/", mcp_app)`) |
|---|---|---|
| `/healthz`(토큰 없이) | 200 | 200 |
| `/api/index` 토큰 없음 / read 토큰 | 401 / 200 | 401 / 200 |
| `/docs`(비활성화) | 404 | 404 |
| `POST /mcp` 토큰 없음 | 401 | 401 |
| MCP 클라이언트 접속(initialize, instructions, 도구 4개, `get_index`) | 정상 | 정상 |
| read 토큰으로 `submit_report` | 오류(권한) | 오류(권한) |

- **조건 1(필수)**: 부모 FastAPI 앱의 `lifespan`에서 `async with mcp.session_manager.run():`을 실행해야 한다. 이를 빼고 `/mcp`를 호출하면 **500**이 난다(MCP 앱의 lifespan은 하위 앱으로 붙이면 자동 실행되지 않음). 세션 관리자는 인스턴스당 한 번만 시작할 수 있다(`streamable_http_manager.py`의 `_has_started` 검사). 앱은 프로세스당 한 번만 만든다.
- **조건 2**: `streamable_http_app()`을 호출한 뒤에야 `mcp.session_manager`를 쓸 수 있다(지연 생성).
- **인증**: 기존 `BearerAuthMiddleware`를 `app.add_middleware(BearerAuthMiddleware, tokens=...)`로 그대로 쓸 수 있고, `/healthz`는 열어 두고 `/api/*`와 `/mcp`는 모두 토큰을 요구한다.
- **채택안**: **라우트 옮기기** 방식. `/mcp` 경로가 그대로 유지되고 명시적이며, 마운트 방식은 모르는 경로가 MCP 앱으로 흘러간다. 두 방식 모두 동작하므로 마운트로 바꿔도 된다.
- `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`으로 문서 화면을 끌 수 있다(설정으로 켜기 가능하게 구현할 것).
- 의존성: `pyproject.toml`에 `fastapi`를 추가해야 한다(위 버전으로 확인).
- 확인 스크립트는 저장소에 넣지 않았다(임시 작업 폴더에서 실행). 구현 계획에서 같은 시나리오를 테스트로 만든다.
