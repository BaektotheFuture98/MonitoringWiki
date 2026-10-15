import asyncio

import pytest
from conftest import make_settings, write_tokens

from wiki_mcp.app import ASK_PROMPT_NAME, build_ask_prompt, build_services, create_mcp


@pytest.fixture
def mcp(wiki_root, tmp_path):
    settings = make_settings(wiki_root, tmp_path)
    write_tokens(settings.tokens_file, ("query-agent", "read-secret", ["read"]))
    return create_mcp(build_services(settings), "가이드")


def test_prompt_name_is_ask():
    assert ASK_PROMPT_NAME == "ask"


def test_strict_prompt_forces_wiki_procedure():
    text = build_ask_prompt("agg 쿼리가 느려요", allow_inference=False)
    assert "agg 쿼리가 느려요" in text
    assert "get_index" in text and "get_pattern" in text
    assert "알려진 패턴 없음" in text
    assert "위키 외 추론은 하지 않습니다" in text
    assert "위키 외 추론(미검증)" not in text


def test_inference_prompt_allows_labeled_section_only_when_no_match():
    text = build_ask_prompt("agg 쿼리가 느려요", allow_inference=True)
    assert "위키 외 추론(미검증)" in text
    assert "일치하는 패턴이 없을 때만" in text
    assert "위키 외 추론은 하지 않습니다" not in text


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_question_rejected(blank):
    with pytest.raises(ValueError, match="질문"):
        build_ask_prompt(blank, allow_inference=False)


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
