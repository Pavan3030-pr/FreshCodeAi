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


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.4,
    max_delay: float = 4.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run `factory()` up to attempts+1 times; retry only UpstreamError(retryable=True)."""
    last: Optional[BaseException] = None
    for attempt in range(attempts + 1):
        try:
            return await factory()
        except UpstreamError as exc:
            last = exc
            if not exc.retryable or attempt == attempts:
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            jitter = random.uniform(0, delay * 0.25)
            await sleep(delay + jitter)
        except Exception as exc:
            raise exc
    if last:
        raise last
    raise RuntimeError("retry loop exited without result or exception")


async def post_json(
    service: str,
    url: str,
    payload: dict,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 30.0,
    transport=None,
) -> dict:
    """Issue an async HTTP POST with JSON body and return parsed JSON."""
    import httpx

    start = time.monotonic()
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=True) as client:
            response = await client.post(url, json=payload, headers=req_headers)
    except httpx.TimeoutException as exc:
        elapsed = (time.monotonic() - start) * 1000
        status.record(service, False, elapsed, "timeout")
        raise UpstreamError(service, "request timed out", retryable=True) from exc
    except httpx.RequestError as exc:
        elapsed = (time.monotonic() - start) * 1000
        status.record(service, False, elapsed, str(exc))
        raise UpstreamError(service, f"network error: {exc}", retryable=True) from exc

    elapsed = (time.monotonic() - start) * 1000

    if response.status_code >= 400:
        status.record(service, False, elapsed, f"HTTP {response.status_code}")
        err_detail = ""
        try:
            err_detail = response.text[:200]
        except Exception:
            pass
        msg = f"upstream returned an error: {err_detail}" if err_detail else "upstream returned an error"
        raise UpstreamError(service, msg, response.status_code, retryable=response.status_code in RETRYABLE_STATUS)

    status.record(service, True, elapsed, "200 OK")
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError(service, "invalid JSON returned from upstream") from exc
