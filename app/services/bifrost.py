"""Bifrost LLM Gateway Client."""
from __future__ import annotations

from app.config import settings
from app.services.cache import TTLCache, make_key
from app.services.http import UpstreamError, post_json

_CACHE = TTLCache(ttl_seconds=getattr(settings, "cache_ttl_seconds", 300), maxsize=128)


def _normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url in ("https://groq.com", "http://groq.com", "https://api.groq.com", "http://api.groq.com"):
        return "https://api.groq.com/openai/v1"
    if url.endswith("/chat/completions"):
        url = url[:-17].rstrip("/")
    return url


def provider_input_tokens(usage) -> int | None:
    """Provider-reported prompt tokens, or None when the gateway omitted usage."""
    usage = usage or {}
    value = usage.get("prompt_tokens")
    if value is None:
        value = usage.get("input_tokens")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


class BifrostClient:
    def __init__(self, api_key=None, base_url=None, model=None, transport=None, retries=None, fallback_model=None):
        self.api_key = settings.bifrost_api_key if api_key is None else api_key
        self.base_url = _normalize_base_url(base_url or settings.bifrost_base_url)
        self.model = model or settings.bifrost_model
        self.fallback_model = getattr(settings, "bifrost_fallback_model", None) if fallback_model is None else fallback_model
        self.transport = transport
        self.retries = getattr(settings, "upstream_retries", 3) if retries is None else retries

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def complete(self, system_prompt: str, user_prompt: str, *, use_cache: bool = False, max_tokens=None, model=None):
        """Chat completion. use_cache=True serves identical prompts from memory (0 new tokens)."""
        if not self.configured:
            return {"configured": False, "content": "", "usage": {}, "message": "Bifrost is not configured. Add BIFROST_API_KEY and BIFROST_MODEL to .env."}
        chosen = model or self.model
        fallback = self.fallback_model if self.fallback_model and self.fallback_model != chosen else None
        try:
            return await self._complete_once(chosen, system_prompt, user_prompt, use_cache, max_tokens)
        except UpstreamError as exc:
            if fallback and (exc.retryable or (exc.status_code or 0) >= 500 or exc.status_code in (400, 404)):
                result = await self._complete_once(fallback, system_prompt, user_prompt, use_cache, max_tokens)
                return {**result, "fallback_used": True, "primary_model": chosen, "primary_error": exc.public()}
            raise

    async def _complete_once(self, model, system_prompt, user_prompt, use_cache, max_tokens):
        key = make_key(model, system_prompt, user_prompt, max_tokens)
        if use_cache:
            hit = _CACHE.get(key)
            if hit is not None:
                return {**hit, "cached": True, "usage": {}, "original_usage": hit.get("usage", {})}
        max_tok = max_tokens or getattr(settings, "max_output_tokens", 4096)
        payload = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": max_tok,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        }
        timeout_val = getattr(settings, "bifrost_timeout", 120.0)
        data, resp_headers = await post_json(
            "bifrost",
            f"{self.base_url}/chat/completions",
            payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout_val,
            transport=self.transport,
            retries=self.retries,
        )
        choices = data.get("choices") or []
        if not choices:
            raise UpstreamError("bifrost", "response contained no choices")
        content = (choices[0].get("message") or {}).get("content") or ""
        result = {
            "configured": True,
            "content": content,
            "usage": data.get("usage") or {},
            "model": data.get("model", model),
            "request_id": resp_headers.get("x-request-id") or data.get("id", ""),
            "cached": False,
        }
        if use_cache and content:
            _CACHE.set(key, result)
        return result
