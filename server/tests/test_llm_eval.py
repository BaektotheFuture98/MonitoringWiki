"""실제 LLM으로 기존 보고서를 컴파일해 보는 평가 사례(선택 실행).

실행(server/에서): WIKI_LLM_EVAL=1 python -m pytest tests/test_llm_eval.py -v
키와 모델은 환경 변수나 server/.env(ANTHROPIC_API_KEY, WIKI_LLM_MODEL)에서 읽는다.
raw/는 git에 없으므로 저장소의 raw 파일이 있는 서버에서만 의미가 있다.
"""
import os
from datetime import date
from pathlib import Path

import pytest

from wiki_mcp.core.config import load_env_file
from wiki_mcp.services.llm import AnthropicPlanGenerator, build_system_prompt
from wiki_mcp.core.masking import Masker
from wiki_mcp.core.plan import parse_plan

REPO = Path(__file__).resolve().parents[2]
EMPTY_INDEX = (
    "# 색인\n\n## 패턴\n| 패턴 | 요약 | 리소스 | 대표 시그니처 | confidence | last_seen |\n"
    "|---|---|---|---|---|---|\n"
)
CASES = [
    pytest.param(["raw/2025-03-24/133734.txt", "raw/2025-03-24/133734-2.txt"],
                 {"master"}, ["nori", "사전"], id="nori-dictionary"),
    pytest.param(["raw/2026-10-14/105317.txt"], {"query", "master"}, ["agg", "집계"], id="agg-query-slow"),
    pytest.param(["raw/2026-10-14/111932.txt"], {"query"}, ["템플릿"], id="template-conflict"),
]

pytestmark = pytest.mark.skipif(os.environ.get("WIKI_LLM_EVAL") != "1",
                                reason="WIKI_LLM_EVAL=1일 때만 실제 LLM을 호출한다")


@pytest.fixture(scope="module")
def generator():
    load_env_file()
    return AnthropicPlanGenerator(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ["WIKI_LLM_MODEL"],
        system_prompt=build_system_prompt((REPO / "AGENTS.md").read_text(encoding="utf-8")),
        timeout=300,
    )


@pytest.mark.parametrize("files, resources, keywords", CASES)
def test_compiles_known_report(generator, files, resources, keywords):
    paths = [REPO / name for name in files]
    if not all(path.exists() for path in paths):
        pytest.skip("raw 파일이 없습니다(raw/는 git에 없음).")
    masker = Masker()
    text = "\n\n".join(path.read_text(encoding="utf-8") for path in paths)
    data = generator.generate_plan(masker.mask(text), EMPTY_INDEX)
    plan = parse_plan(data, existing_ids=set(), masker=masker, today=date.today())
    first = plan.patterns[0]
    assert first.action == "create"
    assert resources <= set(first.resources)
    assert any(keyword in first.summary.lower() for keyword in keywords)
