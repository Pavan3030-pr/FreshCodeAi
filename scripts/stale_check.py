#!/usr/bin/env python3
"""Stale-answer detector CLI.

Checks a piece of text (an AI answer, a README, release notes) for change-sensitive claims, retrieves current
sources with Tavily and reports claims that look outdated (e.g. "FastAPI 0.100 is the latest version").

    python scripts/stale_check.py answer.txt            # Markdown report
    cat answer.txt | python scripts/stale_check.py -    # read stdin
    python scripts/stale_check.py answer.txt --json     # machine-readable
    python scripts/stale_check.py answer.txt --fix      # print the text with suggested corrections applied

Exit codes: 0 nothing stale, 1 stale or contradicted claims found, 2 setup problem (no input or TAVILY_API_KEY missing).
Use it in CI to fail a build when documentation or generated answers go out of date.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LABELS = {"stale": "STALE", "contradicted": "CONTRADICTED", "ok": "OK", "review": "REVIEW"}


def classify(claim: dict) -> str:
    if claim.get("possibly_outdated"):
        return "stale"
    if claim.get("verdict") == "contradicted":
        return "contradicted"
    if claim.get("verdict") == "supported":
        return "ok"
    return "review"


def exit_code(result: dict) -> int:
    summary = result.get("summary") or {}
    return 1 if (summary.get("possibly_outdated", 0) or summary.get("contradicted", 0)) else 0


def render_markdown(result: dict) -> str:
    s = result.get("summary") or {}
    lines = ["# Stale-answer report", "",
             f"Claims checked: **{result.get('claims_found', 0)}** · stale: **{s.get('possibly_outdated', 0)}** · "
             f"contradicted: **{s.get('contradicted', 0)}** · supported: **{s.get('supported', 0)}** · needs review: **{s.get('needs_review', 0)}**", ""]
    if not result.get("claims"):
        lines.append(result.get("note") or "No change-sensitive claims were found.")
    for c in result.get("claims", []):
        kind = classify(c)
        lines.append(f"- **{LABELS[kind]}** — {c['claim']}")
        drift = c.get("version_drift") or {}
        if kind == "stale" and drift.get("detail"):
            lines.append(f"  - {drift['detail']}")
        fix = c.get("suggested_correction")
        if fix:
            lines.append(f"  - Suggested: {fix['corrected']}")
        src = (c.get("sources") or [None])[0]
        if src and kind in ("stale", "contradicted"):
            lines.append(f"  - Source: {src['url']}")
    if not result.get("live_verification"):
        lines += ["", "_Tavily is not configured, so no live sources were checked._"]
    lines += ["", f"_{result.get('note', '')}_"]
    return "\n".join(lines)


def main(argv=None, tavily=None, bifrost=None, stdin=None) -> int:
    ap = argparse.ArgumentParser(description="Detect stale claims in text using Tavily evidence.")
    ap.add_argument("file", help="text file to check, or - for stdin")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--fix", action="store_true", help="print the text with suggested version corrections applied")
    args = ap.parse_args(argv)
    try:
        text = (stdin or sys.stdin).read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Cannot read input: {exc}", file=sys.stderr)
        return 2
    if not text.strip():
        print("Input is empty.", file=sys.stderr)
        return 2
    from app.services.freshness import verify_text
    from app.services.tavily import TavilyClient
    client = tavily or TavilyClient()
    if not client.configured:
        print("TAVILY_API_KEY is not set. Add it to .env or the environment.", file=sys.stderr)
        return 2
    result = asyncio.run(verify_text(text, tavily=client, bifrost=bifrost))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.fix:
        print(result.get("corrected_text") or text)
    else:
        print(render_markdown(result))
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
