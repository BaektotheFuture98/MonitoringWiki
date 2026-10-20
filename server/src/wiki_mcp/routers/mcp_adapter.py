"""MCP 어댑터: 도구와 `ask` 프롬프트를 등록하고 공용 처리기를 부른다.

처리기(파일 읽기, 컴파일 대기)는 이벤트 루프를 막지 않도록 스레드에서 실행한다.
"""
from __future__ import annotations

import json

from anyio import to_thread
from mcp.server.fastmcp import Context, FastMCP

from wiki_mcp.repositories.store import WikiStore
from wiki_mcp.services.compile_service import (
    Services,
    handle_get_index,
    handle_get_infra,
    handle_get_pattern,
    handle_submit_report,
)

GUIDE_MD_PATH = "docs/mcp-agent-guide.md"


class InstructionsError(Exception):
    """가이드 파일을 찾지 못했거나 비어 있음."""


def load_instructions(store: WikiStore) -> str:
    try:
        text = store.read(GUIDE_MD_PATH)
    except FileNotFoundError as exc:
        raise InstructionsError(f"{GUIDE_MD_PATH}가 없습니다.") from exc
    # 첫 번째 # 제목 줄은 MCP instructions에서 제외한다.
    lines = text.split("\n")
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith("# ")), 0)
    body = "\n".join(lines[start:]).strip()
    if not body:
        raise InstructionsError(f"{GUIDE_MD_PATH}가 비어 있습니다.")
    return body

GET_INDEX_DESCRIPTION = "장애 패턴 위키의 색인 전체를 반환합니다. 요약과 대표 시그니처 열을 보고 입력과 의미가 같은 패턴을 고르세요."
GET_PATTERN_DESCRIPTION = "패턴 페이지를 반환합니다. sections로 원인, 증상, 해결방법, 관련 패턴 중 일부만 요청할 수 있습니다."
GET_INFRA_DESCRIPTION = "현재 클러스터 구성(티어, 역할별 노드 수, 버전)을 반환합니다. 패턴 일치 판단의 근거로는 쓰지 마세요."
SUBMIT_DESCRIPTION = (
    "사람이 승인한 장애 보고서 전체(원인 판단·결론·권장 조치 포함)를 원문 그대로 제출합니다. "
    "질문에는 절대 사용하지 마세요. 서버가 즉시 마스킹·컴파일해 위키에 반영하고 결과(status, job_id, "
    "생성·갱신한 패턴)를 돌려줍니다. 대기 시간 안에 끝나지 않으면 status가 queued 또는 running이며 처리는 계속됩니다."
)

ASK_PROMPT_NAME = "ask"
ASK_PROMPT_DESCRIPTION = (
    "장애 증상이나 로그를 위키 기준으로만 답하게 합니다. 항상 색인을 먼저 읽고 후보 패턴을 확인하며, "
    "위키에 없는 내용은 '알려진 패턴 없음'으로 답합니다. allow_inference에 true를 주면 일치가 없을 때만 "
    "'위키 외 추론(미검증)'을 분리해 덧붙입니다."
)
_TRUE_VALUES = {"true", "1", "yes", "y", "예", "네"}

_ASK_PREFACE = (
    "위키 전용 질문입니다. 일반 지식, 웹 검색, 다른 도구로 답하지 말고 아래 가이드를 반드시 따르세요. "
    "가장 먼저 get_index로 색인 전체를 읽고, 위키에서 확인된 내용만 답합니다."
)
_ASK_STRICT = "이번 질문에서는 가이드의 '위키 외 추론'을 하지 않습니다. 일치하는 패턴이 없으면 \"알려진 패턴 없음\"이라고만 답합니다. 위키 외 추론은 하지 않습니다."
_ASK_INFERENCE = (
    "일치하는 패턴이 없을 때만 `위키 외 추론(미검증)` 소제목으로 분리해 질문 내용만 근거로 한 분석을 덧붙일 수 있습니다. "
    "위키 기록과 섞어 쓰지 않습니다."
)


def build_ask_prompt(question: str, allow_inference: bool, guide: str) -> str:
    """질문 절차는 AGENTS.md의 외부 에이전트용 가이드(서버 instructions와 같은 글)를 그대로 쓴다."""
    if not question.strip():
        raise ValueError("질문이 비어 있습니다.")
    closing = _ASK_INFERENCE if allow_inference else _ASK_STRICT
    parts = [
        _ASK_PREFACE,
        f"# 가이드\n{guide.strip()}",
        f"# 이번 질문의 조건\n{closing}",
        f"질문:\n{question.strip()}",
    ]
    return "\n\n".join(parts)


def _authorization(ctx: Context) -> str | None:
    request = ctx.request_context.request
    if request is None:
        return None
    return request.headers.get("authorization")


def create_mcp(svc: Services, instructions: str) -> FastMCP:
    mcp = FastMCP("monitoring-wiki", instructions=instructions)

    # ctx는 이벤트 루프 스레드에서 읽고, 처리기만 작업 스레드로 넘긴다.
    @mcp.tool(description=GET_INDEX_DESCRIPTION)
    async def get_index(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_index(svc, authorization))

    @mcp.tool(description=GET_PATTERN_DESCRIPTION)
    async def get_pattern(id: str, ctx: Context, sections: list[str] | None = None) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_pattern(svc, authorization, id, sections))

    @mcp.tool(description=GET_INFRA_DESCRIPTION)
    async def get_infra(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_infra(svc, authorization))

    @mcp.tool(description=SUBMIT_DESCRIPTION)
    async def submit_report(text: str, ctx: Context) -> str:
        authorization = _authorization(ctx)
        wait = svc.settings.mcp_compile_wait_seconds
        result = await to_thread.run_sync(lambda: handle_submit_report(svc, authorization, text, wait=wait))
        return json.dumps(result, ensure_ascii=False)

    @mcp.prompt(name=ASK_PROMPT_NAME, title="위키로만 답하기", description=ASK_PROMPT_DESCRIPTION)
    def ask(question: str, allow_inference: str = "") -> str:
        return build_ask_prompt(question, allow_inference.strip().lower() in _TRUE_VALUES, instructions)

    return mcp
