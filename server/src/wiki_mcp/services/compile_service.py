"""승인된 보고서를 받아 raw 저장 → 마스킹 → LLM 계획 → 검증 → 위키 적용을 단일 워커로 처리한다."""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from wiki_mcp.services.access_log import AccessLog
from wiki_mcp.services.llm import PlanGenerator
from wiki_mcp.core.masking import Masker
from wiki_mcp.core.plan import CompilePlan, PlanError, parse_plan
from wiki_mcp.wiki.raw_store import DUPLICATE_MESSAGE, RawStore
from wiki_mcp.wiki.wiki_pages import index_pattern_ids
from wiki_mcp.wiki.wiki_reader import INDEX_PATH
from wiki_mcp.wiki.wiki_store import WikiStore
from wiki_mcp.wiki.wiki_writer import WikiWriter

PLAN_ATTEMPTS = 2
JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
UNFINISHED_STATUSES = ("queued", "running")
RESTART_ERROR = "서버가 재시작되어 작업이 중단되었습니다. retry로 다시 처리하세요."
STOP_TIMEOUT_SECONDS = 5.0


class JobNotFound(LookupError):
    """작업 ID에 해당하는 기록이 없음."""


class JobNotRetryable(ValueError):
    """실패하지 않은 작업은 다시 시도할 수 없음."""


class CompileTimeout(TimeoutError):
    """작업 전체 제한 시간을 넘음."""


@dataclass
class Job:
    id: str
    raw_path: str
    token: str
    status: str
    created_at: str
    updated_at: str
    attempts: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None


def job_view(job: Job) -> dict[str, Any]:
    view: dict[str, Any] = {"status": job.status, "job_id": job.id, "raw_path": job.raw_path, "attempts": job.attempts}
    if job.result is not None:
        view.update(job.result)
    if job.error is not None:
        view["error"] = job.error
    return view


class JobStore:
    """작업 기록을 <상태 폴더>/jobs/<작업ID>.json에 둔다(PoC는 영속 큐 없이 기록만 남긴다)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, job: Job) -> None:
        target = self.directory / f"{job.id}.json"
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def load(self, job_id: str) -> Job:
        if not JOB_ID_RE.fullmatch(job_id):
            raise JobNotFound(f"작업이 없습니다: {job_id!r}")
        try:
            data = json.loads((self.directory / f"{job_id}.json").read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise JobNotFound(f"작업이 없습니다: {job_id}") from exc
        return Job(**data)

    def unfinished(self) -> list[Job]:
        jobs = [Job(**json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.directory.glob("*.json"))]
        return [job for job in jobs if job.status in UNFINISHED_STATUSES]


class CompileService:
    def __init__(
        self,
        *,
        raw_store: RawStore,
        wiki: WikiStore,
        writer: WikiWriter,
        generator: PlanGenerator,
        masker: Masker,
        jobs: JobStore,
        log: AccessLog,
        timeout: float,
        now: Callable[[], datetime],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.raw_store = raw_store
        self.wiki = wiki
        self.writer = writer
        self.generator = generator
        self.masker = masker
        self.jobs = jobs
        self.log = log
        self.timeout = timeout
        self._now = now
        self._clock = clock
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._active: dict[str, Job] = {}
        self._done: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # 수명 주기 -----------------------------------------------------------

    def start(self) -> None:
        # 영속 큐가 없으므로 이전 프로세스에서 끝나지 않은 작업은 실패로 바꿔 retry 대상으로 만든다.
        for job in self.jobs.unfinished():
            job.status, job.error, job.updated_at = "failed", RESTART_ERROR, self._stamp()
            self.jobs.save(job)
        self._thread = threading.Thread(target=self._work, name="compile-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=STOP_TIMEOUT_SECONDS)
        self._thread = None

    # 요청 -----------------------------------------------------------------

    def submit(self, text: str, *, token: str, wait: float) -> dict[str, Any]:
        saved = self.raw_store.save(text)
        if saved.status == "duplicate":
            return {"status": "duplicate", "raw_path": saved.path, "message": DUPLICATE_MESSAGE}
        stamp = self._stamp()
        job = Job(id=uuid.uuid4().hex[:12], raw_path=saved.path, token=token, status="queued",
                  created_at=stamp, updated_at=stamp)
        with self._lock:
            done = self._register(job)
        return self._wait(job.id, done, wait)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._active.get(job_id)
            if job is not None:
                return job_view(job)
        return job_view(self.jobs.load(job_id))

    def retry(self, job_id: str, *, token: str, wait: float) -> dict[str, Any]:
        with self._lock:
            if job_id in self._active:
                raise JobNotRetryable("이미 처리 중인 작업입니다.")
            job = self.jobs.load(job_id)
            if job.status != "failed":
                raise JobNotRetryable(f"실패한 작업만 다시 시도할 수 있습니다(현재 {job.status}).")
            job.status, job.token, job.result, job.error = "queued", token, None, None
            job.updated_at = self._stamp()
            done = self._register(job)
        return self._wait(job_id, done, wait)

    def _register(self, job: Job) -> threading.Event:
        """self._lock을 잡은 상태에서 부른다."""
        done = threading.Event()
        self._active[job.id] = job
        self._done[job.id] = done
        self.jobs.save(job)
        self._queue.put(job.id)
        return done

    def _wait(self, job_id: str, done: threading.Event, wait: float) -> dict[str, Any]:
        done.wait(timeout=wait)
        return self.get(job_id)

    # 워커 -----------------------------------------------------------------

    def _work(self) -> None:
        while (job_id := self._queue.get()) is not None:
            self._process(job_id)

    def _process(self, job_id: str) -> None:
        with self._lock:
            job = self._active[job_id]
            job.status, job.attempts, job.updated_at = "running", job.attempts + 1, self._stamp()
            self.jobs.save(job)
        try:
            result = self._compile(job)
        except Exception as exc:  # 한 작업의 실패로 워커가 멈추지 않도록 모두 작업 기록에 남긴다
            self._finish(job, status="failed", error=f"{type(exc).__name__}: {exc}")
        else:
            self._finish(job, status="compiled", result=result)

    def _finish(self, job: Job, *, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._lock:
            job.status, job.result, job.error, job.updated_at = status, result, error, self._stamp()
            self.jobs.save(job)
            del self._active[job.id]
            done = self._done.pop(job.id)
        self.log.write(token=job.token, tool="compile", args={"job_id": job.id, "raw_path": job.raw_path},
                       status=status)
        done.set()

    def _compile(self, job: Job) -> dict[str, Any]:
        deadline = self._clock() + self.timeout
        text = (self.raw_store.root / job.raw_path).read_text(encoding="utf-8")
        masked = self.masker.mask(text)
        index_text = self.wiki.read(INDEX_PATH)
        plan = self._plan(masked, index_text, deadline)
        self._check_deadline(deadline)
        applied = self.writer.apply_plan(plan, raw_path=job.raw_path, job_id=job.id)
        return {
            "created": list(applied.created),
            "updated": list(applied.updated),
            "snapshot": applied.snapshot,
            "infra_candidates": [dict(candidate) for candidate in plan.infra_candidates],
            "unclassified": list(plan.unclassified),
            "notes": list(plan.notes),
        }

    def _plan(self, masked: str, index_text: str, deadline: float) -> CompilePlan:
        existing = index_pattern_ids(index_text)
        today = self._now().date()
        feedback: str | None = None
        for _ in range(PLAN_ATTEMPTS):
            self._check_deadline(deadline)
            data = self.generator.generate_plan(masked, index_text, feedback)
            try:
                return parse_plan(data, existing_ids=existing, masker=self.masker, today=today)
            except PlanError as exc:
                feedback = str(exc)
        raise PlanError(f"계획 검증에 {PLAN_ATTEMPTS}회 실패했습니다: {feedback}")

    def _check_deadline(self, deadline: float) -> None:
        if self._clock() > deadline:
            raise CompileTimeout(f"작업 제한 시간 {self.timeout:.0f}초를 넘었습니다.")

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")
