"""Token-efficient, self-verifying coding agent.

research (Tavily) -> compress context -> generate (Bifrost) -> run tests -> one compact repair if needed.
"""
from __future__ import annotations

import re
import time

from app.config import settings
from app.services.bifrost import BifrostClient, provider_input_tokens
from app.services.compress import compress_sources, estimate_tokens as _estimate
from app.services.tavily import TavilyClient
from app.services.trace import Trace

SYSTEM_PROMPT = ("You are FreshCode, a precise senior engineer. Smallest sufficient solution; standard library first. "
                 "Use the supplied evidence for version-sensitive details and never invent API details.")

OUTPUT_SPEC = ("Reply with: (1) one line of assumptions, (2) exactly one fenced code block with the implementation "
               "in a file named solution, (3) exactly one fenced pytest block that does `from solution import ...` "
               "and covers edge cases. No other prose.")


JS_OUTPUT_SPEC = ("Reply with: (1) one line of assumptions, (2) exactly one fenced javascript block with the implementation as "
                  "CommonJS in solution.js (module.exports / exports.name), (3) exactly one fenced javascript block with tests using "
                  "`const test = require('node:test'); const assert = require('node:assert');` and `require('./solution')`. "
                  "No other prose, no network, no file system, no child processes.")
JS_LANGS = {"javascript", "js", "node", "nodejs"}


def is_js(language: str) -> bool:
    return (language or "").strip().lower() in JS_LANGS


def estimate_tokens(text: str) -> int:
    return _estimate(text)


def compact_task(task: str, language: str, constraints: str, sources: list, budget: int = 900):
    """Build the bounded prompt (string only). See build_context for compression stats."""
    return build_context(task, language, constraints, sources, budget)[0]


def build_context(task: str, language: str, constraints: str, sources: list, budget: int = 900):
    """Return (prompt, compression_stats)."""
    stats = compress_sources(sources, f"{task} {constraints or ''}", budget_tokens=budget) if sources else \
        {"sources": [], "original_tokens": 0, "compressed_tokens": 0, "dropped_duplicates": 0, "saved_percent": 0.0}
    evidence = "\n".join(f"- {s['title']}: {s['content']} ({s['url']})" for s in stats["sources"])
    prompt = (f"TASK ({language}): {task.strip()}\nCONSTRAINTS: {(constraints or 'None')[:800]}\n"
              f"EVIDENCE (verify relevance before use):\n{evidence or 'No live sources supplied.'}\n{JS_OUTPUT_SPEC if is_js(language) else OUTPUT_SPEC}")
    return prompt, stats


_FENCE = re.compile(r"```([\w+#.-]*)[ \t]*\n(.*?)```", re.S)


def extract_blocks(text: str) -> list[tuple[str, str]]:
    return [(lang.lower(), body.strip()) for lang, body in _FENCE.findall(text or "") if body.strip()]


def extract_code(text: str):
    blocks = extract_blocks(text)
    return blocks[0][1] if blocks else ""


def split_code_and_tests(text: str) -> tuple[str, str]:
    """Return (implementation, tests). Tests = first block that defines test_ functions."""
    code, tests = "", ""
    for _, body in extract_blocks(text):
        if (re.search(r"^\s*def test_\w+", body, re.M) or re.search(r"^\s*import pytest", body, re.M)
                or re.search(r"node:test|^\s*(?:test|it|describe)\s*\(", body, re.M)):
            tests = tests or body
        else:
            code = code or body
    return code, tests


def _sum_usage(usages: list[dict]) -> dict:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    seen = False
    for u in usages:
        if not u:
            continue
        pt = provider_input_tokens(u)
        if pt is None and "total_tokens" not in u:
            continue
        seen = True
        total["prompt_tokens"] += pt or 0
        total["completion_tokens"] += int(u.get("completion_tokens") or 0)
        total["total_tokens"] += int(u.get("total_tokens") or ((pt or 0) + int(u.get("completion_tokens") or 0)))
    return total if seen else {}


def _repair_prompt(task: str, code: str, tests: str, failure: str, language: str = "python") -> str:
    js = is_js(language)
    lang, fname = ("javascript", "solution.js") if js else ("python", "solution.py")
    return (f"The tests failed. Fix the implementation only.\nTASK: {task.strip()[:600]}\n"
            f"CURRENT {fname}:\n```{lang}\n{code[:5000]}\n```\nTESTS:\n```{lang}\n{tests[:3500]}\n```\n"
            f"FAILURE OUTPUT (truncated):\n{failure[-1400:]}\n"
            f"Reply with exactly one fenced code block containing the corrected {fname}. No prose.")


async def build_solution(payload, bifrost=None, tavily=None, on_progress=None):
    llm = bifrost or BifrostClient()
    searcher = tavily or TavilyClient()
    started = time.perf_counter()
    trace = Trace()

    def emit(stage, message, state="running", **data):
        if on_progress:
            on_progress({"stage": stage, "message": message, "state": state, **data})

    sources: list = []
    emit("research", "Checking current technical references")
    research_error = None
    research_meta = None
    with trace.span("research", enabled=bool(payload.verify_facts and searcher.configured)) as a:
        if payload.verify_facts and searcher.configured:
            try:
                research = await searcher.search(f"Official documentation and current API guidance for: {payload.task[:300]}", max_results=3)
                sources = research.get("results", [])
                research_meta = {"request_id": research.get("request_id"), "response_time": research.get("response_time"), "cached": bool(research.get("cached"))}
                a["sources"], a["cached"] = len(sources), bool(research.get("cached"))
                emit("research", f"Retrieved {len(sources)} source(s)" + (" (cached)" if research.get("cached") else ""), "done", sources=len(sources))
            except Exception as exc:  # degrade gracefully: continue without research
                research_error = str(exc)[:200]
                a["error"] = research_error
                emit("research", f"Research failed, continuing without sources: {research_error}", "done", sources=0)
        else:
            emit("research", "Research skipped or Tavily is not configured", "done", sources=0)

    emit("optimize", "Compressing evidence into a token budget")
    budget = getattr(payload, "context_budget", settings.context_budget_tokens)
    with trace.span("compress", budget=budget) as a:
        prompt, comp = build_context(payload.task, payload.language, payload.constraints or "", sources, budget)
        estimated_input = estimate_tokens(SYSTEM_PROMPT + prompt)
        a.update(original_tokens_est=comp["original_tokens"], compressed_tokens_est=comp["compressed_tokens"], duplicates_dropped=comp["dropped_duplicates"])
    emit("optimize", f"Evidence {comp['original_tokens']} → {comp['compressed_tokens']} est. tokens", "done",
         original_tokens=comp["original_tokens"], compressed_tokens=comp["compressed_tokens"], saved_percent=comp["saved_percent"])
    token_report = {"estimated_input_tokens": estimated_input, "context_original_tokens_est": comp["original_tokens"],
                    "context_compressed_tokens_est": comp["compressed_tokens"], "context_saved_percent_est": comp["saved_percent"],
                    "duplicates_dropped": comp["dropped_duplicates"], "estimate_note": "Estimates only; provider usage is reported separately."}

    if not llm.configured:
        emit("generate", "Bifrost credentials are not configured", "error")
        return {"mode": "setup_required", "message": "Configure Bifrost credentials to enable live code generation. Research and prompt preparation still ran.",
                "prompt_preview": prompt, "estimated_input_tokens": estimated_input, "provider_usage": {}, "sources": sources,
                "compression": comp, "token_report": token_report, "trace": trace.to_dict(), "code": "", "tests": "", "answer": "",
                "research_configured": searcher.configured, "research_error": research_error, "research_meta": research_meta}

    emit("generate", "Sending compact request to Bifrost")
    usages, calls = [], 0
    with trace.span("generate", model=getattr(llm, "model", None)) as a:
        result = await llm.complete(SYSTEM_PROMPT, prompt, use_cache=True)
        a.update(cached=bool(result.get("cached")), provider_input_tokens=provider_input_tokens(result.get("usage")), model=result.get("model"),
                 fallback_used=bool(result.get("fallback_used")))
    calls += 1
    usages.append(result.get("usage", {}))
    answer = result.get("content", "")
    cache_hit = bool(result.get("cached"))
    emit("generate", "Served from cache — 0 new tokens" if cache_hit else "Bifrost response received", "done", cached=cache_hit)
    code, tests = split_code_and_tests(answer)
    if not code:
        code = extract_code(answer)

    verification = {"ran": False, "reason": "not_python_or_no_tests"}
    is_python = payload.language.strip().lower() in {"python", "py", "python3"}
    testable = is_python or is_js(payload.language)
    if payload.auto_test and testable and code and tests:
        import app.services.runner as runner_mod  # resolved at call time so tests can substitute the runner
        async def run_fn(c, t):  # dispatches to the local or container runner; resolved at call time
            return await runner_mod.run_tests(payload.language, c, t)
        emit("verify", "Running generated tests")
        with trace.span("test", language=payload.language) as a:
            run = await run_fn(code, tests)
            a.update(passed=run["passed"], tests_passed=run.get("tests_passed", 0), tests_failed=run.get("tests_failed", 0), blocked=run.get("blocked", False))
        attempts, repaired = 1, False
        if not run["passed"] and not run.get("blocked") and payload.auto_repair:
            emit("verify", "Tests failed — requesting one compact repair", "running")
            with trace.span("repair") as a:
                fix = await llm.complete(SYSTEM_PROMPT, _repair_prompt(payload.task, code, tests, run["output"], payload.language))
                calls += 1
                usages.append(fix.get("usage", {}))
                new_code = extract_code(fix.get("content", ""))
                a["code_returned"] = bool(new_code)
                if new_code:
                    rerun = await run_fn(new_code, tests)
                    attempts += 1
                    better = rerun["passed"] or rerun["tests_passed"] > run["tests_passed"] or rerun["tests_failed"] < run["tests_failed"]
                    a.update(accepted=bool(better), tests_passed=rerun.get("tests_passed", 0), tests_failed=rerun.get("tests_failed", 0))
                    if better:  # never replace the original with a repair that is not strictly better
                        code, run, repaired = new_code, rerun, True
        verification = {"ran": True, "passed": run["passed"], "attempts": attempts, "repaired": repaired,
                        "tests_passed": run.get("tests_passed", 0), "tests_failed": run.get("tests_failed", 0),
                        "blocked": run.get("blocked", False), "output": run["output"], "duration_ms": run["duration_ms"]}
        emit("verify", ("Tests passed" if run["passed"] else "Tests did not pass") + (" after repair" if repaired and run["passed"] else ""),
             "done" if run["passed"] else "error")
    elif payload.auto_test and testable:
        verification = {"ran": False, "reason": "model_returned_no_tests" if code else "no_code_extracted"}
        emit("verify", "No runnable tests were returned; skipped", "done")
    else:
        emit("verify", "Automatic testing is available for Python and JavaScript", "done")

    usage = _sum_usage(usages)
    provider_in = sum(provider_input_tokens(u) or 0 for u in usages) if usage else None
    token_report.update({"provider_input_tokens": provider_in, "llm_calls": calls, "cache_hit": cache_hit})
    return {"mode": "live", "answer": answer, "code": code, "tests": tests, "verification": verification,
            "estimated_input_tokens": estimated_input, "provider_usage": usage, "token_report": token_report, "trace": trace.to_dict(),
            "compression": comp, "model": result.get("model"), "request_id": result.get("request_id"), "sources": sources,
            "research_configured": searcher.configured, "research_error": research_error, "research_meta": research_meta,
            "latency_ms": round((time.perf_counter() - started) * 1000)}
