from statistics import median

from app.services.agent import SYSTEM_PROMPT, build_context, estimate_tokens
from app.services.bifrost import BifrostClient, provider_input_tokens
from app.services.tavily import TavilyClient


def _input_tokens(result):
    return provider_input_tokens(result.get("usage"))


async def run_benchmark(task: str, language: str, bifrost=None, tavily=None, repetitions: int = 3):
    """Repeated paired prompt-size benchmark; estimates are never labelled as telemetry."""
    llm = bifrost or BifrostClient()
    searcher = tavily or TavilyClient()
    if not llm.configured:
        return {"mode": "setup_required", "message": "Configure Bifrost before running a provider-usage benchmark."}
    sources = []
    if searcher.configured:
        try:
            found = await searcher.search(f"Official current technical documentation relevant to: {task[:300]}", max_results=3)
            sources = found.get("results", [])
        except Exception:
            sources = []
    compact, comp = build_context(task, language, "", sources)
    full_evidence = "\n\n".join(
        f"SOURCE: {s.get('title', 'Documentation')}\nURL: {s.get('url', '')}\nCONTENT: {s.get('content', '')[:1800]}" for s in sources[:3]
    ) or "No live sources available."
    baseline = ("You are an expert senior software engineer. Carefully analyze the requirements, identify assumptions,\n"
                "enumerate edge cases, explain trade-offs, and provide a complete implementation with tests.\n"
                f"\nTASK ({language}): {task}\n\nTECHNICAL REFERENCE MATERIAL:\n{full_evidence}\n"
                "Review the supplied context and explain assumptions before the implementation.")
    prompts = {"baseline": baseline, "optimized": compact}
    samples = {"baseline": [], "optimized": []}
    answers = {"baseline": [], "optimized": []}
    model_names = set()
    for trial in range(max(2, min(int(repetitions), 5))):  # alternate order to reduce drift
        order = ("baseline", "optimized") if trial % 2 == 0 else ("optimized", "baseline")
        for variant in order:
            result = await llm.complete(SYSTEM_PROMPT, prompts[variant])  # default use_cache=False: telemetry needed
            samples[variant].append(_input_tokens(result))
            answers[variant].append(result.get("content", ""))
            if result.get("model"):
                model_names.add(result["model"])
    same_model = len(model_names) <= 1
    measured = same_model and all(all(v is not None and v > 0 for v in vals) for vals in samples.values())
    b_med = median(samples["baseline"]) if all(v is not None for v in samples["baseline"]) else None
    o_med = median(samples["optimized"]) if all(v is not None for v in samples["optimized"]) else None
    savings = round((b_med - o_med) / b_med * 100, 1) if measured and b_med else None
    return {
        "mode": "live", "measured": measured, "same_model": same_model,
        "model": next(iter(model_names)) if len(model_names) == 1 else ("; ".join(sorted(model_names)) if model_names else None),
        "repetitions": len(samples["baseline"]), "samples": samples,
        "baseline": {"input_tokens": b_med, "estimated_tokens": estimate_tokens(SYSTEM_PROMPT + baseline), "answer": answers["baseline"][-1] if answers["baseline"] else ""},
        "optimized": {"input_tokens": o_med, "estimated_tokens": estimate_tokens(SYSTEM_PROMPT + compact), "answer": answers["optimized"][-1] if answers["optimized"] else ""},
        "compression": {k: comp[k] for k in ("original_tokens", "compressed_tokens", "dropped_duplicates", "saved_percent")},
        "token_savings_percent": savings, "sources_used": len(sources),
        "note": "Paired samples with alternating call order; medians of provider-reported input tokens. Measures prompt efficiency, not answer quality or coding correctness.",
    }


async def run_benchmark_suite(tasks: list[str], language: str, bifrost=None, tavily=None, repetitions: int = 3):
    """Several tasks, each a paired alternating benchmark. Returns per-task results, raw records and an honest aggregate."""
    tasks = [t for t in (tasks or []) if t and t.strip()][:5]
    results, raw, per_task = [], [], []
    for idx, task in enumerate(tasks):
        r = await run_benchmark(task, language, bifrost, tavily, repetitions)
        if r.get("mode") != "live":
            return r
        results.append(r)
        for variant in ("baseline", "optimized"):
            for trial, tok in enumerate(r["samples"][variant]):
                raw.append({"task_index": idx + 1, "task": task[:120], "variant": variant, "trial": trial + 1, "input_tokens": tok,
                            "estimated_tokens": r[variant]["estimated_tokens"]})
        per_task.append({"task": task, "measured": r["measured"], "baseline_input_tokens": r["baseline"]["input_tokens"],
                         "optimized_input_tokens": r["optimized"]["input_tokens"], "token_savings_percent": r["token_savings_percent"],
                         "compression": r["compression"], "sources_used": r["sources_used"]})
    savings = sorted(t["token_savings_percent"] for t in per_task if t["measured"] and t["token_savings_percent"] is not None)
    n = len(savings)
    med = (savings[n // 2] if n % 2 else (savings[n // 2 - 1] + savings[n // 2]) / 2) if n else None
    models = {r.get("model") for r in results}
    price = None
    try:
        from app.config import settings
        price = settings.price_in_per_mtok or None
    except Exception:  # pragma: no cover
        pass
    return {
        "mode": "live", "model": next(iter(models)) if len(models) == 1 else "; ".join(sorted(m for m in models if m)),
        "repetitions": results[0]["repetitions"] if results else 0, "tasks": per_task, "raw_records": raw,
        "aggregate": {"measured_tasks": n, "total_tasks": len(per_task), "median_savings_pct": round(med, 1) if med is not None else None,
                      "mean_savings_pct": round(sum(savings) / n, 1) if n else None, "min_savings_pct": savings[0] if n else None,
                      "max_savings_pct": savings[-1] if n else None, "tasks_improved": sum(1 for t in per_task if t["measured"] and (t["baseline_input_tokens"] or 0) > (t["optimized_input_tokens"] or 0)),
                      "estimated_cost_saved_per_1k_runs_usd": (round(sum((t["baseline_input_tokens"] - t["optimized_input_tokens"]) for t in per_task if t["measured"]) / max(1, n) * 1000 / 1e6 * price, 4) if price and n else None)},
        "statistical_note": ("Small-sample, paired, alternating-order comparison on provider-reported INPUT tokens. No significance test is performed; with "
                             f"{n} measured task(s) and {results[0]['repetitions'] if results else 0} pairs each, treat the range as directional. Output tokens, answer quality and "
                             "correctness are not compared here. Cost is an estimate from PRICE_INPUT_PER_MTOK when set."),
        "measured": n > 0 and n == len(per_task),
    }
