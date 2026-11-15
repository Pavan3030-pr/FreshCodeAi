import asyncio

from app.services import status
from app.services.cache import TTLCache, make_key
from app.services.db import Store
from app.services.http import UpstreamError, retry_async
from app.services.ratelimit import SlidingWindowLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_cache_ttl_and_lru():
    clock = Clock()
    c = TTLCache(ttl_seconds=10, maxsize=2, clock=clock)
    c.set("a", 1); c.set("b", 2); c.set("c", 3)
    assert c.get("a") is None and c.get("b") == 2  # LRU evicted a
    clock.t = 11
    assert c.get("b") is None  # expired
    assert make_key("x", 1) == make_key("x", 1) != make_key("x", 2)


def test_cache_disabled_when_ttl_zero():
    c = TTLCache(ttl_seconds=0)
    c.set("a", 1)
    assert c.get("a") is None


def test_rate_limiter_window():
    clock = Clock()
    lim = SlidingWindowLimiter(2, 60, clock)
    assert lim.check("ip")[0] and lim.check("ip")[0]
    ok, retry = lim.check("ip")
    assert not ok and 1 <= retry <= 60
    assert lim.check("other")[0]
    clock.t = 61
    assert lim.check("ip")[0]


def test_retry_retries_only_retryable_errors():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise UpstreamError("x", "boom", 503, retryable=True)
        return "ok"

    async def nosleep(_):
        return None

    assert asyncio.run(retry_async(flaky, attempts=3, sleep=nosleep)) == "ok" and calls["n"] == 3

    calls["n"] = 0

    async def fatal():
        calls["n"] += 1
        raise UpstreamError("x", "bad key", 401, retryable=False)

    try:
        asyncio.run(retry_async(fatal, attempts=3, sleep=nosleep))
        raise AssertionError("should raise")
    except UpstreamError as exc:
        assert exc.status_code == 401 and calls["n"] == 1


def test_retry_gives_up_after_attempts():
    calls = {"n": 0}

    async def always():
        calls["n"] += 1
        raise UpstreamError("x", "down", 503, retryable=True)

    async def nosleep(_):
        return None

    try:
        asyncio.run(retry_async(always, attempts=2, sleep=nosleep))
    except UpstreamError:
        pass
    assert calls["n"] == 3


def test_upstream_error_public_message_has_no_secrets():
    assert "HTTP 429" in UpstreamError("tavily", "upstream returned an error", 429).public()


def test_status_tracks_verified_only_after_success():
    status.reset()
    status.record("bifrost", False, 10, "timeout")
    assert status.snapshot()["bifrost"]["last_ok_at"] is None
    status.record("bifrost", True, 20)
    snap = status.snapshot()["bifrost"]
    assert snap["last_ok_seconds_ago"] is not None and snap["failures"] == 1 and snap["calls"] == 2


def test_store_roundtrip_stats_and_pruning():
    s = Store(":memory:", history_limit=3)
    for i in range(5):
        s.add_run("benchmark", f"b{i}", "ok", savings_pct=50.0 + i, tokens_total=100)
    s.add_run("test", "t", "ok")
    s.add_run("test", "t2", "failed")
    assert len(s.list_runs(50)) == 3  # pruned
    rid = s.add_run("code", "task", "ok", payload={"x": 1}, latency_ms=120)
    got = s.get_run(rid)
    assert got["payload"] == {"x": 1} and got["kind"] == "code"
    st = s.stats()
    assert st["total_runs"] == 3 and st["by_kind"]["code"] == 1
    assert s.list_runs(10, "code")[0]["id"] == rid
    assert s.clear() == 3 and s.stats()["total_runs"] == 0


def test_store_stats_savings_and_pass_rate():
    s = Store(":memory:")
    s.add_run("benchmark", "a", "ok", savings_pct=60.0)
    s.add_run("benchmark", "b", "ok", savings_pct=40.0)
    s.add_run("test", "ok", "ok")
    s.add_run("test", "bad", "failed")
    st = s.stats()
    assert st["avg_token_savings_pct"] == 50.0 and st["best_token_savings_pct"] == 60.0 and st["test_pass_rate"] == 50


def test_store_truncates_oversized_payload():
    s = Store(":memory:")
    rid = s.add_run("code", "big", "ok", payload={"blob": "x" * 300_000})
    assert s.get_run(rid)["payload"].get("truncated") is True


def test_store_reports_input_and_output_token_totals():
    s = Store(":memory:")
    s.add_run("code", "a", "ok", tokens_in=100, tokens_total=160)
    s.add_run("code", "b", "ok", tokens_in=50, tokens_total=80)
    s.add_run("verify", "c", "ok")
    st = s.stats()
    assert st["provider_tokens_in"] == 150 and st["provider_tokens_out"] == 90 and st["provider_tokens_total"] == 240
