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
