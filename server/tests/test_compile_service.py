import itertools
import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from plans import FakePlanGenerator, create_item, plan_dict

from wiki_mcp.service.access_log import AccessLog
from wiki_mcp.service.compile_service import (
    RESTART_ERROR,
    CompileService,
    Job,
    JobNotFound,
    JobNotRetryable,
    JobStore,
)
from wiki_mcp.service.masking import Masker
from wiki_mcp.store.raw_store import DUPLICATE_MESSAGE, RawStore
from wiki_mcp.store.wiki_store import FileWikiStore
from wiki_mcp.store.wiki_writer import WikiWriter

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
REPORT = "승인된 보고서\nuser=kim@example.com host=10.0.0.1\n결론: 새 원인"
INVALID = plan_dict(create_item(id="Bad_ID"))


def build(root, state, generator, *, timeout=300.0, clock=time.monotonic):
    wiki = FileWikiStore(root)
    return CompileService(
        raw_store=RawStore(root, "Asia/Seoul", 10_000, now=lambda: NOW),
        wiki=wiki,
        writer=WikiWriter(wiki, state / "snapshots", 20, lambda: NOW),
        generator=generator,
        masker=Masker(),
        jobs=JobStore(state / "jobs"),
        log=AccessLog(state / "access.jsonl"),
        timeout=timeout,
        now=lambda: NOW,
        clock=clock,
    )


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def make_service(wiki_root, state):
    started = []

    def make(generator, **kwargs):
        service = build(wiki_root, state, generator, **kwargs)
        service.start()
        started.append(service)
        return service

    yield make
    for service in started:
        service.stop()


def wait_finished(service, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    view = service.get(job_id)
    while view["status"] not in ("compiled", "failed") and time.monotonic() < deadline:
        time.sleep(0.01)
        view = service.get(job_id)
    return view


def test_submit_compiles_and_registers(make_service, wiki_root, state):
    generator = FakePlanGenerator(plan_dict(create_item()))
    view = make_service(generator).submit(REPORT, token="web", wait=5)
    assert view["status"] == "compiled"
    assert (view["created"], view["updated"], view["attempts"]) == (["new-pattern"], [], 1)
    assert view["raw_path"].startswith("raw/2026-10-15/")
    assert (wiki_root / view["raw_path"]).read_text(encoding="utf-8") == REPORT
    assert (wiki_root / "wiki" / "patterns" / "new-pattern.md").exists()
    sent = generator.calls[0]["masked_text"]
    assert "kim@example.com" not in sent and "10.0.0.1" not in sent and "user=<USER>" in sent
    assert "[sample-pattern]" in generator.calls[0]["index_text"]
    log_text = (state / "access.jsonl").read_text(encoding="utf-8")
    record = json.loads(log_text.splitlines()[-1])
    assert (record["token"], record["tool"], record["status"]) == ("web", "compile", "compiled")
    assert record["args"] == {"job_id": view["job_id"], "raw_path": view["raw_path"]}
    assert "승인된 보고서" not in log_text
    saved = json.loads((state / "jobs" / f"{view['job_id']}.json").read_text(encoding="utf-8"))
    assert saved["status"] == "compiled"


def test_duplicate_is_not_compiled(make_service):
    generator = FakePlanGenerator(plan_dict(create_item()))
    service = make_service(generator)
    first = service.submit(REPORT, token="web", wait=5)
    second = service.submit(REPORT + "\n", token="web", wait=5)
    assert second == {"status": "duplicate", "raw_path": first["raw_path"], "message": DUPLICATE_MESSAGE}
    assert len(generator.calls) == 1


def test_invalid_plan_retried_with_feedback(make_service):
    generator = FakePlanGenerator(INVALID, plan_dict(create_item()))
    assert make_service(generator).submit(REPORT, token="web", wait=5)["status"] == "compiled"
    assert generator.calls[0]["feedback"] is None
    assert "id 형식" in generator.calls[1]["feedback"]


def test_two_invalid_plans_fail_and_keep_raw(make_service, wiki_root):
    before = (wiki_root / "wiki" / "index.md").read_text(encoding="utf-8")
    view = make_service(FakePlanGenerator(INVALID)).submit(REPORT, token="web", wait=5)
    assert view["status"] == "failed"
    assert view["error"].startswith("PlanError:")
    assert (wiki_root / view["raw_path"]).exists()
    assert (wiki_root / "wiki" / "index.md").read_text(encoding="utf-8") == before


def test_llm_error_fails_job(make_service):
    view = make_service(FakePlanGenerator(RuntimeError("연결 실패"))).submit(REPORT, token="web", wait=5)
    assert view["status"] == "failed"
    assert "연결 실패" in view["error"]


def test_retry_failed_job(make_service):
    generator = FakePlanGenerator(RuntimeError("일시 오류"))
    service = make_service(generator)
    failed = service.submit(REPORT, token="web", wait=5)
    generator.responses = [plan_dict(create_item())]
    retried = service.retry(failed["job_id"], token="web", wait=5)
    assert (retried["status"], retried["attempts"]) == ("compiled", 2)
    assert retried["raw_path"] == failed["raw_path"]
    assert "error" not in retried
    with pytest.raises(JobNotRetryable):
        service.retry(failed["job_id"], token="web", wait=5)


@pytest.mark.parametrize("job_id", ["0123456789ab", "../etc", "XYZ"])
def test_unknown_job(make_service, job_id):
    service = make_service(FakePlanGenerator(plan_dict()))
    with pytest.raises(JobNotFound):
        service.get(job_id)
    with pytest.raises(JobNotFound):
        service.retry(job_id, token="web", wait=1)


def test_wait_timeout_returns_unfinished_then_completes(make_service):
    release = threading.Event()

    class BlockingGenerator:
        def generate_plan(self, masked_text, index_text, feedback=None):
            release.wait(5)
            return plan_dict(create_item())

    service = make_service(BlockingGenerator())
    view = service.submit(REPORT, token="web", wait=0.05)
    assert view["status"] in ("queued", "running")
    release.set()
    assert wait_finished(service, view["job_id"])["status"] == "compiled"


def test_jobs_run_one_at_a_time(make_service):
    lock = threading.Lock()
    active = {"now": 0, "max": 0}
    numbers = itertools.count()

    class CountingGenerator:
        def generate_plan(self, masked_text, index_text, feedback=None):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
                number = next(numbers)
            time.sleep(0.05)
            with lock:
                active["now"] -= 1
            return plan_dict(create_item(id=f"p{number}"))

    service = make_service(CountingGenerator())
    results = []
    threads = [
        threading.Thread(target=lambda i=i: results.append(service.submit(f"보고서 {i}", token="web", wait=5)))
        for i in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert active["max"] == 1
    assert sorted(view["status"] for view in results) == ["compiled"] * 3


def test_restart_marks_unfinished_jobs_failed(wiki_root, state):
    JobStore(state / "jobs").save(Job(
        id="0123456789ab", raw_path="raw/2026-10-15/100000.txt", token="web",
        status="running", created_at="t", updated_at="t", attempts=1,
    ))
    service = build(wiki_root, state, FakePlanGenerator(plan_dict()))
    service.start()
    try:
        view = service.get("0123456789ab")
    finally:
        service.stop()
    assert (view["status"], view["error"]) == ("failed", RESTART_ERROR)


def test_timeout_fails_job(make_service):
    ticks = {"value": 0.0}

    class SlowGenerator:
        def generate_plan(self, masked_text, index_text, feedback=None):
            ticks["value"] += 1000
            return plan_dict(create_item())

    view = make_service(SlowGenerator(), timeout=300, clock=lambda: ticks["value"]).submit(
        REPORT, token="web", wait=5)
    assert view["status"] == "failed"
    assert view["error"].startswith("CompileTimeout:")
