"""토큰별 슬라이딩 윈도 속도 제한(단일 프로세스용)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from wiki_mcp.core.errors import RateLimited  # noqa: F401 — 외부 임포트 경로 유지


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(f"요청이 너무 많습니다. {self.window:.0f}초 동안 최대 {self.limit}회입니다.")
            hits.append(now)
