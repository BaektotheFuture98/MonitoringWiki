from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from plans import create_item, to_plan, update_item

from wiki_mcp.core.plan import PlanError
from wiki_mcp.wiki.wiki_store import FileWikiStore
from wiki_mcp.wiki.wiki_writer import WikiWriter

NOW = datetime(2026, 10, 15, 9, 30, tzinfo=ZoneInfo("Asia/Seoul"))
RAW = "raw/2026-10-15/093000.txt"


class RecordingStore(FileWikiStore):
    """스냅샷과 쓰기 순서를 기록한다."""

    def __init__(self, root):
        super().__init__(root)
        self.events = []

    def write_atomic(self, path, text):
        self.events.append(("write", path))
        super().write_atomic(path, text)

    def snapshot(self, dest):
        self.events.append(("snapshot", dest.name))
        super().snapshot(dest)


@pytest.fixture
def store(wiki_root):
    return RecordingStore(wiki_root)


@pytest.fixture
def writer(store, tmp_path):
    return WikiWriter(store, tmp_path / "snapshots", 20, lambda: NOW)


def test_create_writes_snapshot_page_index_log_in_order(store, writer, tmp_path):
    result = writer.apply_plan(to_plan(create_item()), raw_path=RAW, job_id="abc123def456")
    assert (result.created, result.updated) == (("new-pattern",), ())
    assert result.snapshot == "20261015-093000-abc123def456"
    assert store.events == [
        ("snapshot", result.snapshot),
        ("write", "wiki/patterns/new-pattern.md"),
        ("write", "wiki/index.md"),
        ("write", "wiki/log.md"),
    ]
    assert "sources: [raw/2026-10-15/093000.txt]" in store.read("wiki/patterns/new-pattern.md")
    index = store.read("wiki/index.md")
    assert "| [new-pattern](patterns/new-pattern.md) | 새 증상과 원인 요약 | master |" in index
    assert "- 패턴: 2" in index
    assert ("## [2026-10-15 09:30] ingest | raw/2026-10-15/093000.txt\n"
            "- 자동 컴파일(작업 abc123def456). 생성: new-pattern / 갱신: 없음") in store.read("wiki/log.md")
    snapshot_index = (tmp_path / "snapshots" / result.snapshot / "index.md").read_text(encoding="utf-8")
    assert "new-pattern" not in snapshot_index


def test_update_merges_page_and_index_row(store, writer):
    result = writer.apply_plan(to_plan(update_item()), raw_path=RAW, job_id="j1")
    assert result.updated == ("sample-pattern",)
    page = store.read("wiki/patterns/sample-pattern.md")
    assert "occurrences: 2" in page and "resources: [query, data]" in page
    assert ("| [sample-pattern](patterns/sample-pattern.md) | 샘플 요약 | query, data | "
            "query: `샘플 시그니처` | medium | 2026-10-12 |") in store.read("wiki/index.md")


def test_related_link_added_to_other_page_without_counting(store, writer):
    writer.apply_plan(to_plan(create_item(related=[{"id": "sample-pattern"}])), raw_path=RAW, job_id="j1")
    sample = store.read("wiki/patterns/sample-pattern.md")
    assert "- [new-pattern](new-pattern.md) — 동시 관측, 연관 미확인" in sample
    assert "occurrences: 1" in sample
    assert "- [sample-pattern](sample-pattern.md) — 동시 관측, 연관 미확인" in store.read(
        "wiki/patterns/new-pattern.md")


def test_infra_candidates_noted_in_log(store, writer):
    plan = to_plan(create_item(), infra_candidates=[{"item": "데이터 노드 수", "report_value": "98"}])
    writer.apply_plan(plan, raw_path=RAW, job_id="j1")
    assert "- 인프라 갱신 후보 1건은 위키에 반영하지 않고 작업 결과로만 보고했습니다." in store.read("wiki/log.md")


def test_stale_action_rejected_before_any_write(store, writer):
    plan = to_plan(create_item())
    writer.apply_plan(plan, raw_path=RAW, job_id="j1")
    store.events.clear()
    with pytest.raises(PlanError, match="이미 있는"):
        writer.apply_plan(plan, raw_path=RAW, job_id="j2")
    assert store.events == []


def test_snapshots_pruned_to_keep(store, tmp_path):
    writer = WikiWriter(store, tmp_path / "snapshots", 2, lambda: NOW)
    names = [
        writer.apply_plan(to_plan(create_item(id=f"p{i}")), raw_path=RAW, job_id=f"j{i}").snapshot
        for i in range(3)
    ]
    assert sorted(path.name for path in (tmp_path / "snapshots").iterdir()) == names[1:]


def test_same_label_in_same_second_gets_suffix(writer):
    first = writer.write_infra("a\n", summary="s", as_of=NOW.date(), source="API(t)")
    second = writer.write_infra("b\n", summary="s", as_of=NOW.date(), source="API(t)")
    assert (first, second) == ("20261015-093000-infra", "20261015-093000-infra-2")


def test_write_infra_updates_page_index_and_log(store, writer):
    snapshot = writer.write_infra("---\nid: infra-cluster\n---\n# 새 구성\n",
                                  summary="Elasticsearch 9.0.0, 10노드", as_of=NOW.date(), source="API(web-backend)")
    assert store.read("wiki/infra/cluster.md") == "---\nid: infra-cluster\n---\n# 새 구성\n"
    assert "— Elasticsearch 9.0.0, 10노드 (기준일 2026-10-15)" in store.read("wiki/index.md")
    assert ("infra | 클러스터 구성 갱신\n- API(web-backend) 입력으로 `wiki/infra/cluster.md`를 덮어썼습니다"
            in store.read("wiki/log.md"))
    assert store.events == [
        ("snapshot", snapshot),
        ("write", "wiki/infra/cluster.md"),
        ("write", "wiki/index.md"),
        ("write", "wiki/log.md"),
    ]
