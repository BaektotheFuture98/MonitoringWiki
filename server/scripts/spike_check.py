"""설치된 mcp SDK가 설계가 기대는 API를 제공하는지 확인한다."""
import importlib.metadata
import inspect

import anyio


async def check_tool_error() -> tuple[bool, str]:
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.memory import create_connected_server_and_client_session

    server = FastMCP("spike")

    @server.tool()
    def boom() -> str:
        raise ValueError("의도된 오류")

    async with create_connected_server_and_client_session(server._mcp_server) as client:
        result = await client.call_tool("boom", {})
        return bool(result.isError), result.content[0].text


def main() -> int:
    from mcp.server.fastmcp import Context, FastMCP  # noqa: F401
    from mcp.shared.context import RequestContext

    checks: list[tuple[str, bool]] = []
    print("mcp version:", importlib.metadata.version("mcp"))

    init_params = inspect.signature(FastMCP.__init__).parameters
    checks.append(("FastMCP(instructions=...)", "instructions" in init_params))
    checks.append(("FastMCP.streamable_http_app", hasattr(FastMCP, "streamable_http_app")))
    checks.append(("FastMCP.tool(description=...)", "description" in inspect.signature(FastMCP.tool).parameters))
    fields = getattr(RequestContext, "__dataclass_fields__", {})
    checks.append(("RequestContext.request", "request" in fields))

    is_error, text = anyio.run(check_tool_error)
    print("tool error text:", text)
    checks.append(("도구 예외 → isError", is_error))

    for name, ok in checks:
        print(f"{'OK      ' if ok else 'MISMATCH'} {name}")
    all_ok = all(ok for _, ok in checks)
    print("ALL OK" if all_ok else "MISMATCH 있음: 진행 중단 후 보고")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
