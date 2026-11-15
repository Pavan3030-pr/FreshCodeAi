"""Shared upstream HTTP helpers: typed errors and retry with exponential backoff + jitter."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Awaitable, Callable, Optional, Tuple, TypeVar

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
    attempts: int = 2,
    base_delay: float = 0.4,
    max_delay: float = 4.0,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
) -> T:
    """Runs factory() once, then retries up to `attempts` more times (exponential backoff + jitter) on retryable errors."""
    sleep_fn = sleep or asyncio.sleep
    attempts = max(0, int(attempts))
    for attempt in range(attempts + 1):
        try:
            return await factory()
        except Exception as exc:
            retryable = is_retryable(exc) if is_retryable else getattr(exc, "retryable", False)
            if attempt >= attempts or not retryable:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            await sleep_fn(delay + random.uniform(0, delay * 0.2))
    raise RuntimeError("retry_async failed without exception")  # pragma: no cover


async def post_json(
    service: str,
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
    transport=None,
    retries: Optional[int] = None,
    **_ignored,
) -> Tuple[dict, dict]:
    """POSTs a JSON payload and returns (json_body, response_headers).

    Raises UpstreamError (never a raw httpx error). 408/409/425/429/5xx and network errors are retryable;
    other 4xx (e.g. a bad API key) are not. `retries` = extra attempts after the first.
    """
    import httpx

    req_headers = {"Content-Type": "application/json", "User-Agent": "FreshCodeAi/5.1", **(headers or {})}
    if retries is None:
        retries = 2

    async def _single_post() -> Tuple[dict, dict]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                res = await client.post(url, json=payload, headers=req_headers)
        except httpx.HTTPError as exc:
            status.record(service, False, (time.perf_counter() - started) * 1000, repr(exc))
            raise UpstreamError(service, "network error talking to upstream", None, retryable=True) from exc
        elapsed = (time.perf_counter() - started) * 1000
        if res.status_code >= 400:
            status.record(service, False, elapsed, f"HTTP {res.status_code}")
            # Upstream bodies can echo request details; keep the public message generic.
            raise UpstreamError(service, "upstream returned an error", res.status_code,
                                retryable=res.status_code in RETRYABLE_STATUS)
        try:
            data = res.json()
        except ValueError as exc:
            status.record(service, False, elapsed, "invalid JSON")
            raise UpstreamError(service, "upstream returned invalid JSON", res.status_code, retryable=False) from exc
        if not isinstance(data, dict):
            status.record(service, False, elapsed, "unexpected JSON shape")
            raise UpstreamError(service, "upstream returned an unexpected response", res.status_code, retryable=False)
        status.record(service, True, elapsed)
        return data, {k.lower(): v for k, v in res.headers.items()}

    return await retry_async(_single_post, attempts=retries)
