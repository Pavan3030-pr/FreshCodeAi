"""Truthful upstream status: a service is 'verified' only after a real successful call."""
from __future__ import annotations

import threading
import time
from typing import Optional

_lock = threading.Lock()
_state: dict[str, dict] = {}


def record(service: str, ok: bool, latency_ms: float, error: Optional[str] = None) -> None:
    with _lock:
        s = _state.setdefault(service, {"calls": 0, "failures": 0, "last_ok_at": None, "last_error": None,
                                         "last_error_at": None, "last_latency_ms": None})
        s["calls"] += 1
        s["last_latency_ms"] = round(latency_ms)
        if ok:
            s["last_ok_at"] = time.time()
        else:
            s["failures"] += 1
            s["last_error"] = (error or "unknown error")[:200]
            s["last_error_at"] = time.time()


def snapshot() -> dict:
    now = time.time()
    with _lock:
        out = {}
        for name, s in _state.items():
            item = dict(s)
            item["last_ok_seconds_ago"] = round(now - s["last_ok_at"]) if s["last_ok_at"] else None
            out[name] = item
        return out


def reset() -> None:
    with _lock:
        _state.clear()
