import asyncio

import app.services.bifrost as bifrost_mod
import app.services.tavily as tavily_mod
from app.services.bifrost import BifrostClient, provider_input_tokens
from app.services.http import UpstreamError
from app.services.tavily import TavilyClient


def run(coro):
    return asyncio.run(coro)


def test_provider_input_tokens_variants():
    assert provider_input_tokens({"prompt_tokens": 12}) == 12
    assert provider_input_tokens({"input_tokens": 7}) == 7
    assert provider_input_tokens({}) is None and provider_input_tokens(None) is None
    assert provider_input_tokens({"prompt_tokens": True}) is None and provider_input_tokens({"prompt_tokens": -1}) is None


def test_bifrost_payload_cache_and_usage(monkeypatch=None):
    bifrost_mod._CACHE.clear()
    seen = []

    async def fake_post(service, url, **kw):
        seen.append((service, url, kw))
        return ({"model": "general", "choices": [{"message": {"content": "```python\nprint(1)\n```"}}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}}, {"x-request-id": "rid-1"})

    original = bifrost_mod.post_json
    bifrost_mod.post_json = fake_post
    try:
        client = BifrostClient(api_key="k", base_url="http://gw.test/v1", model="general")
        first = run(client.complete("sys", "task", use_cache=True))
        second = run(client.complete("sys", "task", use_cache=True))
        third = run(client.complete("sys", "task"))  # use_cache False must hit upstream
    finally:
        bifrost_mod.post_json = original
    service, url, kw = seen[0]
    assert service == "bifrost" and url == "http://gw.test/v1/chat/completions"
    assert kw["headers"]["Authorization"] == "Bearer k" and kw["payload"]["max_tokens"] > 0
    assert kw["payload"]["messages"][0]["role"] == "system"
    assert first["usage"]["prompt_tokens"] == 12 and first["request_id"] == "rid-1" and first["cached"] is False
    assert second["cached"] is True and second["usage"] == {} and second["original_usage"]["prompt_tokens"] == 12
    assert third["cached"] is False and len(seen) == 2


def test_bifrost_empty_choices_raises():
    async def fake_post(service, url, **kw):
        return ({"choices": []}, {})

    original = bifrost_mod.post_json
    bifrost_mod.post_json = fake_post
    try:
        run(BifrostClient(api_key="k").complete("s", "u"))
        raise AssertionError("expected UpstreamError")
    except UpstreamError:
        pass
    finally:
        bifrost_mod.post_json = original


def test_bifrost_unconfigured_makes_no_call():
    out = run(BifrostClient(api_key="").complete("s", "u"))
    assert out["configured"] is False and out["content"] == ""


def test_tavily_filters_bad_urls_caches_and_normalizes():
    tavily_mod._CACHE.clear()
    calls = []

    async def fake_post(service, url, **kw):
        calls.append(kw["payload"])
        return ({"results": [{"title": "Docs", "url": "https://docs.example/path", "content": "snippet", "score": .9},
                             {"title": "Unsafe", "url": "javascript:alert(1)", "content": "bad", "score": .8},
                             {"title": "Odd", "url": "https://ok.example", "content": "x", "score": "n/a"}]}, {})

    original = tavily_mod.post_json
    tavily_mod.post_json = fake_post
    try:
        client = TavilyClient(api_key="k")
        a = run(client.search("latest API", max_results=3))
        b = run(client.search("latest API", max_results=3))
    finally:
        tavily_mod.post_json = original
    assert len(a["results"]) == 2 and a["results"][0]["relevance"] == 0.9 and a["results"][1]["relevance"] == 0.0
    assert calls[0]["query"] == "latest API" and len(calls) == 1 and b["cached"] is True


def test_tavily_unconfigured_makes_no_call():
    assert run(TavilyClient(api_key="").search("x"))["results"] == []


def test_model_routing_override_and_fallback():
    bifrost_mod._CACHE.clear()
    seen = []

    async def fake_post(service, url, **kw):
        seen.append(kw["payload"]["model"])
        if kw["payload"]["model"] == "primary":
            raise UpstreamError("bifrost", "upstream returned an error", 503, retryable=True)
        return ({"model": kw["payload"]["model"], "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 5}}, {})

    original = bifrost_mod.post_json
    bifrost_mod.post_json = fake_post
    try:
        client = BifrostClient(api_key="k", model="primary", fallback_model="backup")
        r = run(client.complete("s", "u"))
        assert r["fallback_used"] is True and r["model"] == "backup" and r["primary_model"] == "primary" and seen == ["primary", "backup"]
        seen.clear()
        r2 = run(client.complete("s", "u2", model="cheap"))  # explicit override succeeds: no fallback
        assert seen == ["cheap"] and "fallback_used" not in r2
        seen.clear()
        try:
            run(BifrostClient(api_key="k", model="primary", fallback_model="").complete("s", "u3"))
            raise AssertionError("expected UpstreamError without a fallback")
        except UpstreamError:
            pass
        assert seen == ["primary"]
    finally:
        bifrost_mod.post_json = original


def test_auth_errors_do_not_trigger_fallback():
    seen = []

    async def fake_post(service, url, **kw):
        seen.append(kw["payload"]["model"])
        raise UpstreamError("bifrost", "upstream returned an error", 401, retryable=False)

    original = bifrost_mod.post_json
    bifrost_mod.post_json = fake_post
    try:
        try:
            run(BifrostClient(api_key="k", model="primary", fallback_model="backup").complete("s", "u"))
        except UpstreamError:
            pass
    finally:
        bifrost_mod.post_json = original
    assert seen == ["primary"]
