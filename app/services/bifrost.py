
from app.config import settings
from app.services.cache import TTLCache, make_key
from app.services.http import UpstreamError, post_json

_CACHE = TTLCache(ttl_seconds=settings.cache_ttl_seconds, maxsize=128)


def provider_input_tokens(usage) -> "int | None":
    """Provider-reported prompt tokens, or None when the gateway omitted usage."""
    usage = usage or {}
    value = usage.get("prompt_tokens")
    if value is None:
        value = usage.get("input_tokens")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


class BifrostClient:
    def __init__(self, api_key=None, base_url=None, model=None, transport=None, retries=None, fallback_model=None):
        self.api_key = settings.bifrost_api_key if api_key is None else api_key
        self.base_url = (base_url or settings.bifrost_base_url).rstrip("/")
        self.model = model or settings.bifrost_model
        self.fallback_model = settings.bifrost_fallback_model if fallback_model is None else fallback_model
        self.transport = transport
        self.retries = settings.upstream_retries if retries is None else retries

    @property
    def configured(self):
        return bool(self.api_key)

    async def complete(self, system_prompt: str, user_prompt: str, *, use_cache: bool = False, max_tokens=None, model=None):
        """Chat completion. use_cache=True serves identical prompts from memory (0 new tokens).

        `model` overrides the default (model routing). If the call fails with a retryable/server/model error and
        BIFROST_FALLBACK_MODEL is set, one attempt is made on the fallback model; the result says so.
        """
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
        payload = {"model": model, "temperature": 0.1,
                   "max_tokens": int(max_tokens or settings.max_output_tokens),
                   "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}
        data, headers = await post_json(
            "bifrost", f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload=payload, timeout=settings.timeout_seconds, transport=self.transport, retries=self.retries)
        choices = data.get("choices") or []
        if not choices:
            raise UpstreamError("bifrost", "response contained no choices")
        content = (choices[0].get("message") or {}).get("content") or ""
        result = {"configured": True, "content": content, "usage": data.get("usage") or {},
                  "model": data.get("model", model), "request_id": headers.get("x-request-id"), "cached": False}
        if use_cache and content:
            _CACHE.set(key, result)
        return result
