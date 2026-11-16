from urllib.parse import urlparse

from app.config import settings
from app.services.cache import TTLCache, make_key
from app.services.http import post_json

_CACHE = TTLCache(ttl_seconds=settings.cache_ttl_seconds, maxsize=256)


_DEPTHS = {"basic", "advanced"}
_TOPICS = {"general", "news"}
_RANGES = {"day", "week", "month", "year"}


def _domains(values, limit):
    out = []
    for v in values or ():
        d = str(v).strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if d and "/" not in d and d not in out:
            out.append(d)
    return out[:limit]


def build_search_payload(query: str, max_results: int = 4, cfg=None) -> dict:
    """Tavily request body. Defaults match the original behaviour; env settings add depth, topic, freshness window and domain filters."""
    cfg = cfg or settings  # resolved at call time so configuration changes apply
    depth = cfg.tavily_search_depth if cfg.tavily_search_depth in _DEPTHS else "basic"
    payload = {"query": query[:500], "search_depth": depth, "max_results": max(1, min(max_results, 8)),
               "include_answer": False, "include_raw_content": False}
    if cfg.tavily_topic in _TOPICS and cfg.tavily_topic != "general":
        payload["topic"] = cfg.tavily_topic
    if cfg.tavily_time_range in _RANGES:
        payload["time_range"] = cfg.tavily_time_range
    include, exclude = _domains(cfg.tavily_include_domains, 300), _domains(cfg.tavily_exclude_domains, 150)
    if include:
        payload["include_domains"] = include
    if exclude:
        payload["exclude_domains"] = [d for d in exclude if d not in include]
    return payload


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
        payload = build_search_payload(query, max_results)
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
               "request_id": data.get("request_id"), "cached": False, "search_depth": payload["search_depth"]}
        _CACHE.set(key, out)
        return out
