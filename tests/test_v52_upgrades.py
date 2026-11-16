"""Tests for Tavily search tuning, Bifrost routing/fallback options and the stale-answer CLI."""
import asyncio
import dataclasses
import io
import sys
from pathlib import Path

import app.services.bifrost as bifrost_mod
import app.services.tavily as tavily_mod
from app.config import settings
from app.services.bifrost import BifrostClient, parse_routing
from app.services.tavily import TavilyClient, build_search_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stale_check  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def cfg(**kw):
    return dataclasses.replace(settings, **kw)


def test_tavily_payload_defaults_are_unchanged():
    p = build_search_payload("fastapi latest", 3, cfg(tavily_search_depth="basic", tavily_topic="general", tavily_time_range="",
                                                      tavily_include_domains=(), tavily_exclude_domains=()))
    assert p == {"query": "fastapi latest", "search_depth": "basic", "max_results": 3, "include_answer": False, "include_raw_content": False}


def test_tavily_payload_uses_depth_topic_range_and_domains():
    c = cfg(tavily_search_depth="advanced", tavily_topic="news", tavily_time_range="month",
            tavily_include_domains=("https://Docs.Python.org/", "docs.python.org", "bad/path"), tavily_exclude_domains=("docs.python.org", "spam.example"))
    p = build_search_payload("x" * 900, 99, c)
    assert p["search_depth"] == "advanced" and p["topic"] == "news" and p["time_range"] == "month"
    assert p["include_domains"] == ["docs.python.org"]          # normalised, de-duplicated, path entries dropped
    assert p["exclude_domains"] == ["spam.example"]             # an included domain is never also excluded
    assert len(p["query"]) == 500 and p["max_results"] == 8


def test_tavily_payload_ignores_invalid_values():
    p = build_search_payload("q", 2, cfg(tavily_search_depth="turbo", tavily_topic="sports", tavily_time_range="decade"))
    assert p["search_depth"] == "basic" and "topic" not in p and "time_range" not in p


def test_tavily_client_reports_search_depth_and_sends_filters():
    tavily_mod._CACHE.clear()
    seen = []

    async def fake_post(service, url, **kw):
        seen.append(kw["payload"])
        return ({"results": [{"title": "T", "url": "https://docs.example/a", "content": "c", "score": .5}]}, {})

    original, original_settings = tavily_mod.post_json, tavily_mod.settings
    tavily_mod.post_json, tavily_mod.settings = fake_post, cfg(tavily_search_depth="advanced", tavily_time_range="week")
    try:
        out = run(TavilyClient(api_key="k").search("latest release"))
    finally:
        tavily_mod.post_json, tavily_mod.settings = original, original_settings
    assert seen[0]["search_depth"] == "advanced" and seen[0]["time_range"] == "week" and out["search_depth"] == "advanced"


def test_parse_routing_reads_bifrost_headers():
    r = parse_routing({"X-Bifrost-Routing-Info-Provider": "openai", "x-bifrost-routing-info-model": "gpt-4o-mini",
                       "x-bifrost-fallback-index": "1", "x-bifrost-upstream-latency-ms": "812.4", "x-bifrost-cache-hit": "true"})
    assert r == {"provider": "openai", "model": "gpt-4o-mini", "fallback_index": 1, "upstream_latency_ms": 812, "cache": {"hit": "true"}}
    assert parse_routing({}) == {} and parse_routing(None) == {} and parse_routing({"x-bifrost-fallback-index": "n/a"}) == {}


def _bifrost_call(headers_out, **settings_kw):
    bifrost_mod._CACHE.clear()
    seen = {}

    async def fake_post(service, url, **kw):
        seen.update(kw)
        return ({"model": "m", "choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3}}, headers_out)

    original, original_settings = bifrost_mod.post_json, bifrost_mod.settings
    bifrost_mod.post_json, bifrost_mod.settings = fake_post, cfg(**settings_kw)
    try:
        out = run(BifrostClient(api_key="k", base_url="http://gw.test/v1", model="openai/gpt-4o-mini",
                                fallback_model="anthropic/claude-3-5-haiku").complete("s", "u"))
    finally:
        bifrost_mod.post_json, bifrost_mod.settings = original, original_settings
    return out, seen


def test_bifrost_sends_correlation_id_and_optional_virtual_key():
    _, seen = _bifrost_call({}, bifrost_virtual_key="sk-bf-demo", bifrost_native_fallbacks=False)
    assert seen["headers"]["x-bf-vk"] == "sk-bf-demo" and seen["headers"]["x-request-id"].startswith("fc-")
    assert "fallbacks" not in seen["payload"]
    _, seen2 = _bifrost_call({}, bifrost_virtual_key="", bifrost_native_fallbacks=False)
    assert "x-bf-vk" not in seen2["headers"]


def test_bifrost_native_fallbacks_are_opt_in_and_need_provider_model_format():
    _, seen = _bifrost_call({}, bifrost_native_fallbacks=True)
    assert seen["payload"]["fallbacks"] == ["anthropic/claude-3-5-haiku"]


def test_bifrost_result_exposes_routing_and_fallback_use():
    out, _ = _bifrost_call({"x-bifrost-request-id": "bf-1", "x-bifrost-routing-info-provider": "anthropic",
                            "x-bifrost-routing-info-model": "claude-3-5-haiku", "x-bifrost-fallback-index": "1"})
    assert out["request_id"] == "bf-1" and out["routing"]["provider"] == "anthropic" and out["fallback_used"] is True
    plain, _ = _bifrost_call({})
    assert "routing" not in plain and not plain.get("fallback_used")


class FakeTavily:
    configured = True

    async def search(self, query, max_results=3):
        return {"results": [{"title": "FastAPI release notes", "url": "https://fastapi.tiangolo.com/release-notes/",
                             "content": "FastAPI 0.133.0 adds Starlette 1.0 support.", "score": .9, "published_date": "2026-03-01"}]}


class FakeLLM:
    configured = False


def test_stale_check_cli_flags_stale_claim_and_returns_exit_1(capsys=None):
    buf = io.StringIO("FastAPI 0.100.0 is the latest stable version.")
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        code = stale_check.main(["-"], tavily=FakeTavily(), bifrost=FakeLLM(), stdin=buf)
    finally:
        sys.stdout = old
    text = out.getvalue()
    assert code == 1 and "STALE" in text and "0.133.0" in text and "fastapi.tiangolo.com" in text


def test_stale_check_cli_fix_and_json_modes():
    for flag, needle in (("--fix", "0.133.0"), ("--json", '"possibly_outdated": 1')):
        out, old = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            stale_check.main(["-", flag], tavily=FakeTavily(), bifrost=FakeLLM(), stdin=io.StringIO("FastAPI 0.100.0 is the latest stable version."))
        finally:
            sys.stdout = old
        assert needle in out.getvalue()


def test_stale_check_cli_setup_errors_return_2():
    class Off:
        configured = False
    assert stale_check.main(["-"], tavily=Off(), stdin=io.StringIO("Python 3.8 is the latest.")) == 2
    assert stale_check.main(["-"], tavily=FakeTavily(), stdin=io.StringIO("   ")) == 2
    assert stale_check.main(["/nonexistent/file.txt"], tavily=FakeTavily()) == 2


def test_drift_does_not_attribute_another_products_version():
    from app.services.freshness import detect_version_drift
    claim = "FastAPI 0.100.0 is the latest stable version."
    other = [{"title": "Release notes", "content": "FastAPI 0.133.0 adds Starlette 1.0 support."}]
    d = detect_version_drift(claim, other)
    assert d["status"] == "newer_version_found" and d["newer_version"] == "0.133.0"   # not Starlette's 1.0
    only_other = [{"title": "Starlette", "content": "Starlette 1.0 is out; FastAPI users should read the notes."}]
    assert detect_version_drift(claim, only_other)["status"] != "newer_version_found"
    phrased = [{"title": "Docs", "content": "The latest FastAPI version 0.133.0 was released today."}]
    assert detect_version_drift(claim, phrased)["newer_version"] == "0.133.0"
