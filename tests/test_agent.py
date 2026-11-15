import asyncio
from types import SimpleNamespace

import app.services.runner as runner_mod
from app.services.agent import (build_solution, compact_task, estimate_tokens, extract_blocks, extract_code,
                                split_code_and_tests)
from app.services.benchmark import run_benchmark


def run(coro):
    return asyncio.run(coro)


def req(**kw):
    base = dict(task="Write a Python function to add two numbers", language="python", constraints="", verify_facts=False,
                auto_test=True, auto_repair=True, context_budget=900)
    base.update(kw)
    return SimpleNamespace(**base)


class OfflineLLM:
    configured = False


class OfflineSearch:
    configured = False


ANSWER = "Assumes ints.\n```python\ndef add(a, b):\n    return a + b\n```\n```python\nfrom solution import add\n\ndef test_add():\n    assert add(1, 2) == 3\n```"


class LLM:
    configured = True

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def complete(self, system, prompt, **kw):
        self.calls.append((prompt, kw))
        content = self.replies.pop(0)
        return {"content": content, "model": "m", "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, "cached": False}


class PatchRunner:
    """Swap run_python_tests with a scripted fake for the duration of a test."""

    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __enter__(self):
        self.orig = runner_mod.run_python_tests

        async def fake(code, tests):
            self.calls.append(code)
            return self.results.pop(0)

        runner_mod.run_python_tests = fake
        return self

    def __exit__(self, *a):
        runner_mod.run_python_tests = self.orig


PASS = {"passed": True, "exit_code": 0, "output": "1 passed", "duration_ms": 5, "tests_passed": 1, "tests_failed": 0, "blocked": False}
FAIL = {"passed": False, "exit_code": 1, "output": "1 failed\nassert 2 == 3", "duration_ms": 5, "tests_passed": 0, "tests_failed": 1, "blocked": False}
BLOCKED = {"passed": False, "exit_code": 126, "output": "blocked", "duration_ms": 1, "tests_passed": 0, "tests_failed": 0, "blocked": True}


def test_compact_prompt_bounds_source_context():
    prompt = compact_task("Write a function", "python", "", [{"title": "Docs", "content": "The function must be fast. " * 400, "url": "https://docs.example"}])
    assert len(prompt) < 600 and "EVIDENCE" in prompt  # 400 identical sentences collapse to one
    big = " ".join(f"Sentence {i} explains parameter{i} behaviour in detail for this release." for i in range(400))
    bounded = compact_task("Write a function", "python", "", [{"title": "Docs", "content": big, "url": "https://docs.example"}], budget=200)
    assert len(bounded) < 1800


def test_token_estimate_is_rough_and_positive():
    assert estimate_tokens("hello world") > 0


def test_extract_helpers():
    assert extract_code("Example:\n```python\ndef add(a,b): return a+b\n```").startswith("def add")
    assert len(extract_blocks(ANSWER)) == 2
    code, tests = split_code_and_tests(ANSWER)
    assert code.startswith("def add") and "def test_add" in tests


def test_agent_reports_setup_required_without_key():
    result = run(build_solution(req(), OfflineLLM(), OfflineSearch()))
    assert result["mode"] == "setup_required" and result["estimated_input_tokens"] > 0 and "token_report" in result


def test_agent_emits_real_pipeline_events():
    events = []
    run(build_solution(req(), OfflineLLM(), OfflineSearch(), events.append))
    assert [e["stage"] for e in events] == ["research", "research", "optimize", "optimize", "generate"]
    assert events[-1]["state"] == "error"


def test_live_flow_runs_tests_and_sums_usage():
    llm = LLM([ANSWER])
    with PatchRunner([PASS]):
        r = run(build_solution(req(), llm, OfflineSearch()))
    assert r["mode"] == "live" and r["verification"]["passed"] is True and r["verification"]["repaired"] is False
    assert r["provider_usage"]["total_tokens"] == 120 and r["token_report"]["llm_calls"] == 1
    assert r["code"].startswith("def add") and r["tests"].startswith("from solution")
    assert llm.calls[0][1].get("use_cache") is True


def test_failed_tests_trigger_one_compact_repair_and_aggregate_usage():
    llm = LLM([ANSWER, "```python\ndef add(a, b):\n    return a + b  # fixed\n```"])
    with PatchRunner([FAIL, PASS]) as pr:
        r = run(build_solution(req(), llm, OfflineSearch()))
    assert r["verification"]["repaired"] is True and r["verification"]["passed"] is True and r["verification"]["attempts"] == 2
    assert r["token_report"]["llm_calls"] == 2 and r["provider_usage"]["total_tokens"] == 240
    assert "fixed" in r["code"] and len(pr.calls) == 2
    repair_prompt = llm.calls[1][0]
    assert "FAILURE OUTPUT" in repair_prompt and len(repair_prompt) < 3000


def test_repair_that_does_not_help_keeps_original_code():
    llm = LLM([ANSWER, "```python\ndef add(a, b):\n    return 0\n```"])
    with PatchRunner([FAIL, FAIL]):
        r = run(build_solution(req(), llm, OfflineSearch()))
    assert r["verification"]["passed"] is False and r["verification"]["repaired"] is False and "return a + b" in r["code"]


def test_blocked_run_is_never_repaired():
    llm = LLM([ANSWER])
    with PatchRunner([BLOCKED]):
        r = run(build_solution(req(), llm, OfflineSearch()))
    assert r["verification"]["blocked"] is True and r["token_report"]["llm_calls"] == 1


def test_auto_repair_can_be_disabled_and_auto_test_skipped_for_other_languages():
    with PatchRunner([FAIL]):
        r = run(build_solution(req(auto_repair=False), LLM([ANSWER]), OfflineSearch()))
    assert r["verification"]["passed"] is False and r["token_report"]["llm_calls"] == 1
    r2 = run(build_solution(req(language="java"), LLM(["```java\nclass A {}\n```"]), OfflineSearch()))
    assert r2["verification"]["ran"] is False


def test_missing_tests_in_reply_is_reported_not_faked():
    r = run(build_solution(req(), LLM(["```python\ndef add(a,b): return a+b\n```"]), OfflineSearch()))
    assert r["verification"] == {"ran": False, "reason": "model_returned_no_tests"}


def test_research_failure_degrades_gracefully_and_compresses_sources():
    class BadSearch:
        configured = True

        async def search(self, *a, **k):
            raise RuntimeError("tavily down")

    with PatchRunner([PASS]):
        r = run(build_solution(req(verify_facts=True), LLM([ANSWER]), BadSearch()))
    assert r["mode"] == "live" and "tavily down" in r["research_error"]

    class GoodSearch:
        configured = True

        async def search(self, *a, **k):
            body = "Filler about nothing in particular here. " * 40 + "The add function requires two integer arguments in version 2.1. "
            return {"results": [{"title": "D", "url": "https://docs.e/a", "content": body, "score": .9},
                                {"title": "D2", "url": "https://docs.e/a/", "content": body, "score": .8}]}

    with PatchRunner([PASS]):
        r2 = run(build_solution(req(verify_facts=True, context_budget=200), LLM([ANSWER]), GoodSearch()))
    tr = r2["token_report"]
    assert tr["context_compressed_tokens_est"] < tr["context_original_tokens_est"] and tr["duplicates_dropped"] == 1


class BenchLLM:
    configured = True

    def __init__(self, usage=True, models=("demo-model",)):
        self.calls, self.usage, self.models = 0, usage, models

    async def complete(self, system, prompt, **kw):
        self.calls += 1
        tokens = 900 if "Carefully analyze" in prompt else 300
        return {"content": "ok", "model": self.models[self.calls % len(self.models)], "usage": {"prompt_tokens": tokens, "total_tokens": tokens + 20} if self.usage else {}}


def test_benchmark_uses_provider_usage_for_savings():
    llm = BenchLLM()
    result = run(run_benchmark("Write a Java method to merge two sorted arrays", "java", llm, OfflineSearch()))
    assert llm.calls == 6 and result["measured"] is True and result["repetitions"] == 3 and result["token_savings_percent"] == 66.7


def test_benchmark_without_usage_is_not_measured():
    result = run(run_benchmark("Write a Java method to merge two sorted arrays", "java", BenchLLM(usage=False), OfflineSearch()))
    assert result["measured"] is False and result["token_savings_percent"] is None


def test_benchmark_with_mixed_models_is_not_measured():
    result = run(run_benchmark("Write a Java method to merge two sorted arrays", "java", BenchLLM(models=("a", "b")), OfflineSearch()))
    assert result["same_model"] is False and result["measured"] is False


def test_benchmark_requires_bifrost():
    assert run(run_benchmark("Write a function please", "python", OfflineLLM(), OfflineSearch()))["mode"] == "setup_required"


def test_javascript_flow_uses_js_runner_and_spec():
    reply = ("Assumes numbers.\n```javascript\nexports.add = (a, b) => a + b;\n```\n"
             "```javascript\nconst test = require('node:test');\nconst assert = require('node:assert');\nconst { add } = require('./solution');\n"
             "test('adds', () => { assert.equal(add(1, 2), 3); });\n```")
    code, tests = split_code_and_tests(reply)
    assert code.startswith("exports.add") and "node:test" in tests
    calls = []
    orig = runner_mod.run_javascript_tests

    async def fake_js(c, t):
        calls.append(c)
        return dict(PASS)

    runner_mod.run_javascript_tests = fake_js
    try:
        llm = LLM([reply])
        r = run(build_solution(req(language="javascript", task="Write a JavaScript add function"), llm, OfflineSearch()))
    finally:
        runner_mod.run_javascript_tests = orig
    assert r["verification"]["passed"] is True and len(calls) == 1
    assert "node:test" in llm.calls[0][0] and "pytest" not in llm.calls[0][0]


def test_repair_prompt_matches_language():
    from app.services.agent import _repair_prompt
    assert "solution.js" in _repair_prompt("t", "c", "x", "boom", "javascript") and "solution.py" in _repair_prompt("t", "c", "x", "boom")


def test_trace_records_every_stage_with_decisions():
    llm = LLM([ANSWER, "```python\ndef add(a, b):\n    return a + b  # fixed\n```"])
    with PatchRunner([FAIL, PASS]):
        r = run(build_solution(req(), llm, OfflineSearch()))
    names = [sp["name"] for sp in r["trace"]["spans"]]
    assert names == ["research", "compress", "generate", "test", "repair"]
    repair = r["trace"]["spans"][-1]["attrs"]
    assert repair["accepted"] is True and repair["code_returned"] is True
    gen = r["trace"]["spans"][2]["attrs"]
    assert gen["provider_input_tokens"] == 100 and gen["cached"] is False
    assert r["trace"]["total_ms"] >= r["trace"]["spans"][-1]["start_ms"]
    assert all(sp["start_ms"] >= 0 and sp["duration_ms"] >= 0 for sp in r["trace"]["spans"])


def test_trace_present_when_setup_required_and_marks_research_errors():
    r = run(build_solution(req(), OfflineLLM(), OfflineSearch()))
    assert [sp["name"] for sp in r["trace"]["spans"]] == ["research", "compress"]

    class BadSearch:
        configured = True

        async def search(self, *a, **k):
            raise RuntimeError("tavily down")

    r2 = run(build_solution(req(verify_facts=True), OfflineLLM(), BadSearch()))
    assert "tavily down" in r2["trace"]["spans"][0]["attrs"]["error"]


def test_agent_exposes_research_proof_metadata():
    class Tav:
        configured = True

        async def search(self, *a, **k):
            return {"request_id": "req-1", "response_time": 0.3, "cached": True, "results": [{"title": "D", "url": "https://docs.e/a", "content": "The add function requires two integer arguments in version 2.1. " * 3, "score": .9}]}

    with PatchRunner([PASS]):
        r = run(build_solution(req(verify_facts=True), LLM([ANSWER]), Tav()))
    assert r["research_meta"] == {"request_id": "req-1", "response_time": 0.3, "cached": True}


def test_benchmark_suite_aggregates_tasks_and_exports_raw_records():
    from app.services.benchmark import run_benchmark_suite
    from app.services.reports import benchmark_to_csv, run_to_markdown
    llm = BenchLLM()
    r = run(run_benchmark_suite(["Write a Java method to merge sorted arrays", "Write a Java method to reverse a linked list"], "java", llm, OfflineSearch()))
    assert llm.calls == 12 and r["measured"] is True and len(r["tasks"]) == 2 and len(r["raw_records"]) == 12
    assert r["aggregate"]["median_savings_pct"] == 66.7 and r["aggregate"]["tasks_improved"] == 2 and "directional" in r["statistical_note"]
    csv_text = benchmark_to_csv(r)
    assert csv_text.splitlines()[0].startswith("task_index,task,variant") and len(csv_text.splitlines()) == 13
    md = run_to_markdown({"id": 1, "kind": "benchmark", "title": "t", "status": "ok", "created_at": 1.0, "payload": r})
    assert "Median input-token saving" in md and "Limitations" in md


def test_suite_without_usage_claims_no_saving():
    from app.services.benchmark import run_benchmark_suite
    r = run(run_benchmark_suite(["Write a Java method to merge sorted arrays"], "java", BenchLLM(usage=False), OfflineSearch()))
    assert r["measured"] is False and r["aggregate"]["median_savings_pct"] is None and r["aggregate"]["measured_tasks"] == 0
