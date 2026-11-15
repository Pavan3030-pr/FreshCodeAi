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
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
) -> T:
    """Executes factory() up to attempts times using exponential backoff + jitter."""
    last_exc: Optional[Exception] = None
    sleep_fn = sleep or asyncio.sleep
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as exc:
            last_exc = exc
            retryable = is_retryable(exc) if is_retryable else getattr(exc, "retryable", False)
            if attempt >= attempts or not retryable:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay * 0.2)
            await sleep_fn(delay + jitter)
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_async failed without exception")


async def post_json(
    service: str,
    url: str,
    payload: dict,
    headers: dict = None,
    timeout: float = 30.0,
    transport=None,
    **kwargs,
) -> dict:
    """Posts JSON payload to url using httpx (if available) or urllib fallback."""
    headers = headers or {}
    start_t = time.perf_counter()
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("User-Agent", "FreshCodeAi/5.1")
    retries = kwargs.get("retries", None)

    async def _single_post() -> dict:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                res = await client.post(url, json=payload, headers=headers)
                status_code = res.status_code
                if status_code >= 400:
                    raise UpstreamError(
                        service,
                        res.text,
                        status_code=status_code,
                        retryable=status_code in RETRYABLE_STATUS,
                    )
                status.record(service, True, (time.perf_counter() - start_t) * 1000)
                return res.json()
        except ImportError:
            import json
            import urllib.request
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    status.record(service, True, (time.perf_counter() - start_t) * 1000)
                    return data
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise UpstreamError(
                    service,
                    body,
                    status_code=exc.code,
                    retryable=exc.code in RETRYABLE_STATUS,
                )
        except Exception as exc:
            status.record(service, False, 0, str(exc))
            raise UpstreamError(service, str(exc), status_code=500, retryable=True)

    if retries and retries > 1:
        return await retry_async(_single_post, attempts=retries)
    return await _single_post()
