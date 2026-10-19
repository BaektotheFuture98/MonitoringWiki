"""컴파일 작업 기록을 상태 폴더의 JSON 파일로 저장한다."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wiki_mcp.core.errors import JobNotFound

JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
UNFINISHED_STATUSES = ("queued", "running")


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
