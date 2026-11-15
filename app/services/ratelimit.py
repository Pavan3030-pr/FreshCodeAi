"""Sliding-window rate limiter (in-memory, per key)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(max(1, round(q[0] + self.window - now)))
                return False, retry
            q.append(now)
            if len(self._hits) > 5000:  # bound memory under key churn
                for k in [k for k, v in self._hits.items() if not v][:1000]:
                    self._hits.pop(k, None)
            return True, 0
