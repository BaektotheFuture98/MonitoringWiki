import asyncio
from pathlib import Path

import pytest
from plans import FakePlanGenerator, plan_dict

from wiki_mcp.app import build_services
from wiki_mcp.instructions import extract_guide
from wiki_mcp.api.mcp_adapter import ASK_PROMPT_NAME, build_ask_prompt, create_mcp


GUIDE = extract_guide((Path(__file__).resolve().parents[2] / "AGENTS.md").read_text(encoding="utf-8"))


@pytest.fixture
def mcp(server_settings):
    return create_mcp(build_services(server_settings, generator=FakePlanGenerator(plan_dict())), "가이드")


def test_prompt_name_is_ask():
    assert ASK_PROMPT_NAME == "ask"


def test_strict_prompt_forces_wiki_procedure():
    text = build_ask_prompt("agg 쿼리가 느려요", allow_inference=False, guide=GUIDE)
    assert "agg 쿼리가 느려요" in text
    assert "get_index" in text and "get_pattern" in text
    assert "알려진 패턴 없음" in text
    assert "위키 외 추론은 하지 않습니다" in text
    # 가이드 자체에 '위키 외 추론(미검증)' 안내가 있으므로, 질문 조건 부분만 확인한다.
    conditions = text.split("# 이번 질문의 조건\n", 1)[1]
    assert "위키 외 추론(미검증)" not in conditions


def test_inference_prompt_allows_labeled_section_only_when_no_match():
    text = build_ask_prompt("agg 쿼리가 느려요", allow_inference=True, guide=GUIDE)
    assert "위키 외 추론(미검증)" in text
    assert "일치하는 패턴이 없을 때만" in text
    assert "위키 외 추론은 하지 않습니다" not in text


def test_prompt_embeds_guide_verbatim():
    text = build_ask_prompt("q", allow_inference=False, guide=GUIDE)
    assert GUIDE in text


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_question_rejected(blank):
    with pytest.raises(ValueError, match="질문"):
        build_ask_prompt(blank, allow_inference=False, guide=GUIDE)


def test_prompt_listed_with_arguments(mcp):
    prompts = asyncio.run(mcp.list_prompts())
    ask = next(p for p in prompts if p.name == "ask")
    assert {a.name for a in ask.arguments} == {"question", "allow_inference"}
    required = {a.name for a in ask.arguments if a.required}
    assert required == {"question"}


def test_rendered_prompt_is_a_user_message(mcp):
    result = asyncio.run(mcp.get_prompt("ask", {"question": "노드가 빠졌어요"}))
    assert len(result.messages) == 1
    message = result.messages[0]
    assert message.role == "user"
    assert "노드가 빠졌어요" in message.content.text
    assert "위키 외 추론은 하지 않습니다" in message.content.text


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes", "y", "예"])
def test_allow_inference_flag_values(mcp, flag):
    result = asyncio.run(mcp.get_prompt("ask", {"question": "q", "allow_inference": flag}))
    assert "위키 외 추론(미검증)" in result.messages[0].content.text


@pytest.mark.parametrize("flag", ["", "false", "0", "no", "아니오"])
def test_allow_inference_off_values(mcp, flag):
    result = asyncio.run(mcp.get_prompt("ask", {"question": "q", "allow_inference": flag}))
    assert "위키 외 추론은 하지 않습니다" in result.messages[0].content.text
