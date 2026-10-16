"""접근 로그(JSON lines). 보고서 본문은 기록하지 않는다."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from wiki_mcp.store.raw_store import content_hash


class AccessLog:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def write(self, *, token: str, tool: str, args: dict[str, Any], status: str) -> None:
        record = {
            "time": self._clock().isoformat(),
            "token": token,
            "tool": tool,
            "args": args,
            "status": status,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def summarize_report(text: str) -> dict[str, Any]:
    return {"length": len(text), "sha256_prefix": content_hash(text)[:12]}
