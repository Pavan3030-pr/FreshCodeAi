"""Shared upstream HTTP helpers: typed errors and retry with exponential backoff + jitter."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Awaitable, Callable, Optional, TypeVar

from app.services import status

T = TypeVar("T")
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class UpstreamError(Exception):
    def __init__(self, service: str, message: str, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.service = service
        self.status_code = status_code
        self.retryable = retryable

    def public(self) -> str:
        code = f" (HTTP {self.status_code})" if self.status_code else ""
        return f"{self.service} request failed{code}: {str(self)[:200]}"


async def retry_async(factory: Callable[[], Awaitable[T]], *, attempts: int = 3, base_delay: float = 0.4,
                      max_delay: float = 4.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> T:
    """Run `factory()` up to attempts+1 times; retry only UpstreamError(retryable=True)."""
    last: Optional[BaseException] = None
    for attempt in range(attempts + 1):
        try:
            return await factory()
        except UpstreamError as exc:
            last = exc
            if not exc.retryable or attempt >= attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt)) * (0.75 + random.random() * 0.5)
            await sleep(delay)
    raise last  # pragma: no cover


async def post_json(service: str, url: str, *, headers: dict, payload: dict, timeout: float, transport=None,
                    retries: int = 2) -> tuple[dict, dict]:
    """POST JSON with retries; returns (json_body, response_headers). Records upstream status."""
    import httpx  # imported lazily so pure-logic modules stay importable without it

    async def once():
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            status.record(service, False, (time.perf_counter() - started) * 1000, "timeout")
            raise UpstreamError(service, "timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            status.record(service, False, (time.perf_counter() - started) * 1000, type(exc).__name__)
            raise UpstreamError(service, f"network error ({type(exc).__name__})", retryable=True) from exc
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            status.record(service, False, elapsed, f"HTTP {response.status_code}")
            raise UpstreamError(service, "upstream returned an error", response.status_code,
                                retryable=response.status_code in RETRYABLE_STATUS)
        try:
            body = response.json()
        except ValueError as exc:
            status.record(service, False, elapsed, "invalid JSON")
            raise UpstreamError(service, "returned invalid JSON", response.status_code) from exc
        status.record(service, True, elapsed)
        return body, dict(response.headers)

    return await retry_async(once, attempts=retries)
