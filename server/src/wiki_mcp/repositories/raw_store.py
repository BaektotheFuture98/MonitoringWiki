"""승인된 보고서 원문을 raw/에 저장한다. git 작업은 하지 않는다."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from filelock import FileLock

from wiki_mcp.core.errors import ReportRejected, ReportTooLarge

PENDING_MESSAGE = "raw 저장 완료. 자동 컴파일 대기열에 넣었습니다."
DUPLICATE_MESSAGE = "동일한 내용의 보고서가 이미 저장되어 있어 저장하지 않았습니다."
LOCK_NAME = ".submit.lock"
IGNORED_NAMES = {LOCK_NAME, ".gitkeep"}


@dataclass(frozen=True)
class SaveResult:
    status: str
    path: str
    message: str


def normalize_for_hash(text: str) -> str:
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    return "\n".join(lines).rstrip("\n")


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


class RawStore:
    def __init__(
        self,
        root: Path,
        tz: str,
        max_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root
        self.raw_dir = root / "raw"
        self.tz = ZoneInfo(tz)
        self.max_bytes = max_bytes
        self._now = now or (lambda: datetime.now(self.tz))
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._file_lock = FileLock(str(self.raw_dir / LOCK_NAME))

    def save(self, text: str) -> SaveResult:
        self._validate(text)
        digest = content_hash(text)
        with self._thread_lock, self._file_lock:
            existing = self._find_duplicate(digest)
            if existing is not None:
                return SaveResult("duplicate", existing, DUPLICATE_MESSAGE)
            path = self._create_file(text)
        return SaveResult("saved", path, PENDING_MESSAGE)

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def iter_raw_files(self) -> Iterator[Path]:
        for path in sorted(self.raw_dir.rglob("*")):
            if path.is_file() and path.name not in IGNORED_NAMES:
                yield path

    def _validate(self, text: str) -> None:
        if not text.strip():
            raise ReportRejected("빈 보고서는 저장할 수 없습니다.")
        if "\x00" in text:
            raise ReportRejected("NUL 문자가 포함된 보고서는 저장할 수 없습니다.")
        size = len(text.encode("utf-8"))
        if size > self.max_bytes:
            raise ReportTooLarge(f"보고서가 너무 큽니다: {size} bytes (상한 {self.max_bytes})")

    def _find_duplicate(self, digest: str) -> str | None:
        for path in self.iter_raw_files():
            existing = path.read_text(encoding="utf-8")
            if content_hash(existing) == digest:
                return self._relative(path)
        return None

    def _create_file(self, text: str) -> str:
        now = self._now().astimezone(self.tz)
        day_dir = self.raw_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        base = now.strftime("%H%M%S")
        attempt = 1
        while True:
            name = f"{base}.txt" if attempt == 1 else f"{base}-{attempt}.txt"
            target = day_dir / name
            try:
                with open(target, "x", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except FileExistsError:
                attempt += 1
                continue
            return self._relative(target)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()
