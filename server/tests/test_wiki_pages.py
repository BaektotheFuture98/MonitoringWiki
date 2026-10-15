from datetime import date, datetime

import pytest
from conftest import INDEX_MD, LOG_MD, PATTERN_MD
from plans import create_item, to_plan, update_item

from wiki_mcp import wiki_pages as wp

RAW = "raw/2026-10-15/100000.txt"
RECEIVED = date(2026, 10, 15)


def test_index_pattern_ids():
    assert wp.index_pattern_ids(INDEX_MD) == {"sample-pattern"}


def test_upsert_adds_row_after_last_row_and_escapes_pipe():
    text = wp.upsert_index_row(
        INDEX_MD, "new-pattern", confidence="low", last_seen=date(2026, 10, 11),
        resources=("master",), summary="요약 a|b", signature="master: `x | y`",
    )
    row = "| [new-pattern](patterns/new-pattern.md) | 요약 a\\|b | master | master: `x \\| y` | low | 2026-10-11 |"
    lines = text.split("\n")
    sample = next(i for i, line in enumerate(lines) if line.startswith("| [sample-pattern]"))
    assert lines[sample + 1] == row
    assert "- 패턴: 2" in text
    assert wp.index_pattern_ids(text) == {"sample-pattern", "new-pattern"}


def test_upsert_updates_row_keeping_summary_and_signature():
    text = wp.upsert_index_row(INDEX_MD, "sample-pattern", confidence="medium",
                               last_seen=date(2026, 10, 12), resources=("query", "data"))
    assert ("| [sample-pattern](patterns/sample-pattern.md) | 샘플 요약 | query, data | "
            "query: `샘플 시그니처` | medium | 2026-10-12 |") in text
    assert "- 패턴: 1" in text


def test_upsert_keeps_resources_cell_when_none():
    text = wp.upsert_index_row(INDEX_MD, "sample-pattern", confidence="low", last_seen=date(2026, 10, 2))
    assert "| 샘플 요약 | query | query: `샘플 시그니처` | low | 2026-10-02 |" in text


def test_upsert_errors():
    with pytest.raises(wp.PageFormatError, match="패턴 표"):
        wp.upsert_index_row("# 빈 색인\n", "x", confidence="low", last_seen=date(2026, 10, 1))
    with pytest.raises(wp.PageFormatError, match="요약"):
        wp.upsert_index_row(INDEX_MD, "new-pattern", confidence="low", last_seen=date(2026, 10, 1))


def test_update_index_infra_line():
    text = wp.update_index_infra_line(INDEX_MD, "Elasticsearch 8.12.2, 108노드", date(2026, 10, 15))
    assert "- [클러스터 구성](infra/cluster.md) — Elasticsearch 8.12.2, 108노드 (기준일 2026-10-15)" in text
    assert "샘플 구성" not in text


@pytest.mark.parametrize("count, occurrences, expected", [
    (1, 1, "low"), (2, 1, "medium"), (1, 3, "medium"), (2, 3, "high"), (4, 2, "medium"),
])
def test_confidence_for(count, occurrences, expected):
    assert wp.confidence_for(count, occurrences) == expected


def test_stronger_confidence():
    assert wp.stronger_confidence("high", "low") == "high"
    assert wp.stronger_confidence("low", "medium") == "medium"


def test_parse_frontmatter_inline_and_block_lists():
    fields = wp.parse_frontmatter([
        "id: x", "resources: [query, master]", "sources:", "  - raw/a.txt", "  - raw/b.txt", "summary: 요약: 콜론 포함",
    ])
    assert fields == {
        "id": "x",
        "resources": "[query, master]",
        "sources": "[raw/a.txt, raw/b.txt]",
        "summary": "요약: 콜론 포함",
    }
    assert wp.parse_list(fields["sources"]) == ["raw/a.txt", "raw/b.txt"]
    assert wp.format_list(["a", "b"]) == "[a, b]"


def test_render_new_pattern():
    pattern = to_plan(create_item(related=[{"id": "sample-pattern", "note": "같은 시간대"}])).patterns[0]
    assert wp.render_new_pattern(pattern, RAW) == """---
id: new-pattern
summary: 새 증상과 원인 요약
confidence: low
resources: [master]
first_seen: 2026-10-10
last_seen: 2026-10-11
occurrences: 1
sources: [raw/2026-10-15/100000.txt]
solution_origin: report
---
# 새 패턴

## 원인
(보고서 판단) 새 원인

## 증상
- **query**: 미관측(입력 없음)
- **master**: `<TS> WARN 새 시그니처`
- **data**: 미관측(입력 없음)
- **slowlog**: 미관측(입력 없음)

## 해결방법
(보고서 권장 조치) 새 해결

## 관련 패턴
- [sample-pattern](sample-pattern.md) — 같은 시간대
"""


def test_render_multiline_symptom_is_indented():
    pattern = to_plan(create_item(symptoms={"master": "첫 줄\n둘째 줄"})).patterns[0]
    assert "- **master**: 첫 줄\n  둘째 줄\n- **data**" in wp.render_new_pattern(pattern, RAW)


def test_merge_update_counts_and_new_resource_symptom():
    pattern = to_plan(update_item()).patterns[0]
    merged = wp.merge_pattern_update(PATTERN_MD, pattern, RAW, RECEIVED)
    assert "occurrences: 2" in merged.text
    assert "sources: [raw/2026-10-01/101010.txt, raw/2026-10-15/100000.txt]" in merged.text
    assert "resources: [query, data]" in merged.text
    assert "confidence: medium" in merged.text
    assert "first_seen: 2026-10-01" in merged.text and "last_seen: 2026-10-12" in merged.text
    assert "- **query**: 증상 본문\n- **data**: `<TS> data 증상`\n\n## 해결방법" in merged.text
    assert "새 보고서의 query 증상" not in merged.text
    assert "## 원인\n원인 본문\n\n## 증상" in merged.text
    assert merged.text.endswith("## 관련 패턴\n없음\n")
    assert (merged.resources, merged.resources_changed, merged.confidence, merged.last_seen) == (
        ("query", "data"), True, "medium", date(2026, 10, 12))


def test_merge_replaces_unobserved_line_only():
    page = PATTERN_MD.replace("- **query**: 증상 본문", "- **query**: 증상 본문\n- **data**: 미관측(수집 실패) — 접속 실패")
    text = wp.merge_pattern_update(page, to_plan(update_item()).patterns[0], RAW, RECEIVED).text
    assert "- **data**: `<TS> data 증상`" in text
    assert "미관측(수집 실패)" not in text


def test_merge_appends_different_cause_and_solution():
    pattern = to_plan(update_item(cause="보고서가 제시한 다른 원인", solution="다른 조치")).patterns[0]
    text = wp.merge_pattern_update(PATTERN_MD, pattern, RAW, RECEIVED).text
    assert "## 원인\n원인 본문\n\n(추가 보고서 2026-10-15) 보고서가 제시한 다른 원인\n\n## 증상" in text
    assert "## 해결방법\n해결 본문\n\n(추가 보고서 2026-10-15) 다른 조치\n\n## 관련 패턴" in text


def test_merge_same_source_and_resources():
    pattern = to_plan(update_item(resources=["query"], symptoms={"query": "같은 증상"})).patterns[0]
    merged = wp.merge_pattern_update(PATTERN_MD, pattern, "raw/2026-10-01/101010.txt", RECEIVED)
    assert merged.resources_changed is False
    assert "sources: [raw/2026-10-01/101010.txt]\n" in merged.text
    assert "confidence: low" in merged.text


def test_merge_rejects_page_without_frontmatter():
    with pytest.raises(wp.PageFormatError):
        wp.merge_pattern_update("# 제목만\n", to_plan(update_item()).patterns[0], RAW, RECEIVED)


def test_add_related_link_replaces_none_and_dedupes():
    once = wp.add_related_link(PATTERN_MD, "new-pattern", "동시 관측, 연관 미확인")
    assert once.endswith("## 관련 패턴\n- [new-pattern](new-pattern.md) — 동시 관측, 연관 미확인\n")
    assert once.startswith("---\nid: sample-pattern\n")
    assert wp.add_related_link(once, "new-pattern", "다른 메모") == once


def test_append_log():
    text = wp.append_log(LOG_MD, when=datetime(2026, 10, 15, 9, 5), kind="ingest",
                         target="raw/2026-10-15/090500.txt", lines=["자동 컴파일(작업 abc). 생성: a / 갱신: 없음"])
    assert text.endswith(
        "- 처리\n\n## [2026-10-15 09:05] ingest | raw/2026-10-15/090500.txt\n"
        "- 자동 컴파일(작업 abc). 생성: a / 갱신: 없음\n"
    )
