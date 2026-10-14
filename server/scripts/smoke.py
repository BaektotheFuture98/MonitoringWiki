"""실행 중인 서버에 접속해 instructions, 도구 목록, get_index를 확인한다.

사용법: python scripts/smoke.py http://127.0.0.1:8000/mcp <read-토큰>
"""
import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url: str, token: str) -> None:
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("instructions 앞부분:", (init.instructions or "")[:80])
            tools = await session.list_tools()
            print("도구:", sorted(tool.name for tool in tools.tools))
            result = await session.call_tool("get_index", {})
            print("get_index isError:", result.isError)
            print(result.content[0].text[:200])


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    anyio.run(run, sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
