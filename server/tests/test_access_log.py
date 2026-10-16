import json
from datetime import datetime, timezone

from wiki_mcp.service.access_log import AccessLog, summarize_report


def test_writes_json_line(tmp_path):
    path = tmp_path / "logs" / "access.jsonl"
    log = AccessLog(path, clock=lambda: datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc))
    log.write(token="query-agent", tool="get_pattern", args={"id": "x"}, status="ok")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [{
        "time": "2026-10-14T02:00:00+00:00",
        "token": "query-agent",
        "tool": "get_pattern",
        "args": {"id": "x"},
        "status": "ok",
    }]


def test_summarize_report_has_no_body():
    summary = summarize_report("비밀 보고서 본문")
    assert summary["length"] == len("비밀 보고서 본문")
    assert len(summary["sha256_prefix"]) == 12
    assert "비밀" not in json.dumps(summary, ensure_ascii=False)
