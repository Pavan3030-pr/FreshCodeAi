"""Verify real Bifrost + Tavily and capture benchmark evidence: `python scripts/live_check.py "your task"`.

Writes docs/live-results.json (commit it or screenshot it for judges). Uses only provider-reported token usage.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.benchmark import run_benchmark  # noqa: E402
from app.services.bifrost import BifrostClient  # noqa: E402
from app.services.freshness import verify_text  # noqa: E402
from app.services.tavily import TavilyClient  # noqa: E402

TASK = "Write a Python function that validates an ISO 8601 date string and returns a datetime, with pytest tests for edge cases."
CLAIMS = "Python 3.11 is the latest stable version. The requests library current release is 2.28."


async def main():
    llm, search = BifrostClient(), TavilyClient()
    task = sys.argv[1] if len(sys.argv) > 1 else TASK
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "bifrost_configured": llm.configured, "tavily_configured": search.configured}
    if not (llm.configured and search.configured):
        print("Set BIFROST_API_KEY, BIFROST_BASE_URL, BIFROST_MODEL and TAVILY_API_KEY in .env first.")
        return 2
    print("1/2 Freshness (live Tavily)…")
    v = await verify_text(CLAIMS, search, llm)
    out["freshness"] = {"claims": v["claims_found"], "summary": v["summary"], "assessment_available": v["assessment_available"],
                        "flags": [{"claim": c["claim"], "possibly_outdated": c["possibly_outdated"], "detail": c["version_drift"].get("detail")} for c in v["claims"]]}
    print(json.dumps(out["freshness"], indent=2))
    print("2/2 Paired token benchmark (6 Bifrost calls)…")
    b = await run_benchmark(task, "python", llm, search)
    out["benchmark"] = {k: b.get(k) for k in ("measured", "model", "repetitions", "samples", "token_savings_percent", "compression", "sources_used")}
    out["benchmark"]["baseline_median_input_tokens"] = b["baseline"]["input_tokens"]
    out["benchmark"]["freshcode_median_input_tokens"] = b["optimized"]["input_tokens"]
    print(json.dumps(out["benchmark"], indent=2))
    path = Path(__file__).resolve().parents[1] / "docs" / "live-results.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved {path}")
    if not b.get("measured"):
        print("WARNING: the gateway did not return usage for every call; no saving can be claimed.")
        return 1
    return 0


sys.exit(asyncio.run(main()))
