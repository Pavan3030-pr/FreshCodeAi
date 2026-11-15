"""Exportable evidence: Markdown reports per run and CSV for history and benchmark raw records. Pure functions."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

CSV_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(CSV_FORMULA) else s  # neutralise spreadsheet formula injection


def _iso(ts) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else ""


def runs_to_csv(runs: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["id", "created_at", "kind", "title", "status", "latency_ms", "tokens_in", "tokens_total", "savings_pct", "project_id", "summary"])
    for r in runs:
        w.writerow([_cell(x) for x in (r.get("id"), _iso(r.get("created_at")), r.get("kind"), r.get("title"), r.get("status"), r.get("latency_ms"),
                                       r.get("tokens_in"), r.get("tokens_total"), r.get("savings_pct"), r.get("project_id"), r.get("summary"))])
    return out.getvalue()


def benchmark_to_csv(payload: dict) -> str:
    """Raw records: one row per task x variant x trial. Estimated and measured columns are kept separate."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["task_index", "task", "variant", "trial", "provider_input_tokens", "estimated_prompt_tokens", "model"])
    for rec in payload.get("raw_records", []):
        w.writerow([_cell(x) for x in (rec.get("task_index"), rec.get("task"), rec.get("variant"), rec.get("trial"), rec.get("input_tokens"), rec.get("estimated_tokens"), payload.get("model"))])
    return out.getvalue()


def _table(headers, rows) -> str:
    esc = lambda x: str(x if x is not None else "—").replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows])


def run_to_markdown(run: dict) -> str:
    p = run.get("payload") or {}
    lines = [f"# FreshCode report — {run.get('title', '')}", "",
             f"- Run id: {run.get('id')} · kind: {run.get('kind')} · status: {run.get('status')}",
             f"- Created: {_iso(run.get('created_at'))} · latency: {run.get('latency_ms') if run.get('latency_ms') is not None else '—'} ms", ""]
    kind = run.get("kind")
    if kind == "code":
        tr = p.get("token_report") or {}
        lines += ["## Token accounting", "", _table(["Metric", "Value", "Source"], [
            ["Provider input tokens", tr.get("provider_input_tokens"), "measured (gateway usage)"],
            ["Provider total tokens", (p.get("provider_usage") or {}).get("total_tokens"), "measured (gateway usage)"],
            ["Evidence tokens before → after", f"{(p.get('compression') or {}).get('original_tokens')} → {(p.get('compression') or {}).get('compressed_tokens')}", "estimated (local)"],
            ["LLM calls", tr.get("llm_calls"), "measured"], ["Cache hit", tr.get("cache_hit"), "measured"]]), ""]
        v = p.get("verification") or {}
        if v.get("ran"):
            lines += ["## Verification", "", f"Passed: **{v.get('passed')}** · tests passed {v.get('tests_passed')} · failed {v.get('tests_failed')} · attempts {v.get('attempts')} · repaired {v.get('repaired')}", "", "```text", str(v.get("output", ""))[-2000:], "```", ""]
        if p.get("code"):
            lines += ["## Generated code", "", "```", p["code"], "```", ""]
        if p.get("tests"):
            lines += ["## Generated tests", "", "```", p["tests"], "```", ""]
        spans = (p.get("trace") or {}).get("spans") or []
        if spans:
            lines += ["## Execution trace", "", _table(["Step", "Start ms", "Duration ms", "Details"], [[s.get("name"), s.get("start_ms"), s.get("duration_ms"), "; ".join(f"{k}={v}" for k, v in (s.get("attrs") or {}).items())] for s in spans]), ""]
    elif kind == "verify":
        lines += ["## Claims", ""]
        for i, c in enumerate(p.get("claims") or [], 1):
            lines += [f"### {i}. {c.get('claim')}", f"- Kind: {c.get('kind')} · Verdict: {c.get('verdict')} · Possibly outdated: {c.get('possibly_outdated')}"]
            if c.get("version_drift", {}).get("detail"):
                lines.append(f"- Version drift: {c['version_drift']['detail']}")
            if c.get("suggested_correction"):
                lines.append(f"- Suggested correction (confirm first): {c['suggested_correction']['corrected']}")
            for s in c.get("sources") or []:
                lines.append(f"- Source [{s.get('trust', 'unclassified')}]: {s.get('title')} <{s.get('url')}> ({s.get('published_date') or 'date unavailable'})")
            lines.append("")
        lines.append(f"_{p.get('note', '')}_")
    elif kind == "benchmark":
        lines += _benchmark_md(p)
    elif kind == "test":
        lines += ["## Test result", "", f"Passed: **{p.get('passed')}** · {p.get('tests_passed')} passed · {p.get('tests_failed')} failed · blocked: {p.get('blocked')}", "", "```text", str(p.get("output", ""))[-3000:], "```"]
    else:
        lines += ["```json", str(p)[:3000], "```"]
    lines += ["", "---", "_Measured values come from provider usage or real executions. Estimates are labelled. Heuristic checks need confirmation against the official source._"]
    return "\n".join(lines)


def _benchmark_md(p: dict) -> list[str]:
    agg = p.get("aggregate") or {}
    lines = ["## Benchmark summary", "", f"Model: {p.get('model')} · tasks: {len(p.get('tasks', [])) or 1} · paired samples per task: {p.get('repetitions')}", "",
             _table(["Metric", "Value"], [["Tasks measured", agg.get("measured_tasks")], ["Median input-token saving", agg.get("median_savings_pct")], ["Mean", agg.get("mean_savings_pct")],
                                          ["Range", f"{agg.get('min_savings_pct')} … {agg.get('max_savings_pct')}"], ["Tasks where FreshCode used fewer tokens", agg.get("tasks_improved")]]), ""]
    if p.get("tasks"):
        lines += ["## Per task", "", _table(["#", "Task", "Baseline median", "FreshCode median", "Saving %", "Measured"],
                                            [[i + 1, t.get("task", "")[:70], t.get("baseline_input_tokens"), t.get("optimized_input_tokens"), t.get("token_savings_percent"), t.get("measured")] for i, t in enumerate(p["tasks"])]), ""]
    lines += ["## Limitations", "", p.get("statistical_note") or p.get("note") or ""]
    return lines
