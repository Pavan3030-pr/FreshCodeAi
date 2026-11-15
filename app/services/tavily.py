from urllib.parse import urlparse

from app.config import settings
from app.services.cache import TTLCache, make_key
from app.services.http import post_json

_CACHE = TTLCache(ttl_seconds=settings.cache_ttl_seconds, maxsize=256)


class TavilyClient:
    def __init__(self, api_key=None, transport=None, retries=None):
        self.api_key = settings.tavily_api_key if api_key is None else api_key
        self.transport = transport
        self.retries = settings.upstream_retries if retries is None else retries

    @property
    def configured(self):
        return bool(self.api_key)

    async def search(self, query: str, max_results: int = 4):
        if not self.configured:
            return {"configured": False, "results": [], "message": "Tavily API key is not configured. Add TAVILY_API_KEY to .env."}
        payload = {"query": query[:500], "search_depth": "basic", "max_results": max(1, min(max_results, 8)),
                   "include_answer": False, "include_raw_content": False}
        key = make_key("tavily", payload)
        hit = _CACHE.get(key)
        if hit is not None:
            return {**hit, "cached": True}
        data, _ = await post_json("tavily", "https://api.tavily.com/search",
                                  headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                  payload=payload, timeout=settings.timeout_seconds, transport=self.transport,
                                  retries=self.retries)
        results = []
        for item in data.get("results", []):
            url = str(item.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            try:
                relevance = float(item.get("score") or 0)
            except (TypeError, ValueError):
                relevance = 0.0
            results.append({"title": str(item.get("title") or "Untitled source")[:180], "url": url[:1000],
                            "content": str(item.get("content") or "")[:1800], "score": relevance,
                            "relevance": relevance, "published_date": item.get("published_date")})
        out = {"configured": True, "results": results, "response_time": data.get("response_time"),
               "request_id": data.get("request_id"), "cached": False}
        _CACHE.set(key, out)
        return out
