"""Glass-box run traces: every agent run records what it did, how long each step took and the decisions it made."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable


class Trace:
    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self._clock = clock
        self._t0 = clock()
        self.spans: list[dict] = []

    def _now_ms(self) -> int:
        return round((self._clock() - self._t0) * 1000)

    @contextmanager
    def span(self, name: str, **attrs):
        """Time a step. The yielded dict is the span's attributes; add results to it inside the block."""
        rec = {"name": name, "start_ms": self._now_ms(), "duration_ms": 0, "attrs": dict(attrs)}
        self.spans.append(rec)
        try:
            yield rec["attrs"]
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            raise
        finally:
            rec["duration_ms"] = max(0, self._now_ms() - rec["start_ms"])

    def event(self, name: str, **attrs) -> None:
        self.spans.append({"name": name, "start_ms": self._now_ms(), "duration_ms": 0, "attrs": dict(attrs), "event": True})

    def to_dict(self) -> dict:
        return {"spans": self.spans, "total_ms": self._now_ms()}
