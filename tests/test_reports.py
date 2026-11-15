from app.services.reports import benchmark_to_csv, run_to_markdown, runs_to_csv


def test_csv_neutralises_formula_injection_and_escapes():
    rows = [{"id": 1, "created_at": 0, "kind": "code", "title": '=HYPERLINK("http://evil")', "status": "ok", "summary": "a,b"},
            {"id": 2, "created_at": 0, "kind": "code", "title": "+SUM(1)", "status": "ok", "summary": "@x"}]
    out = runs_to_csv(rows)
    assert out.splitlines()[0].startswith("id,created_at,kind,title")
    assert "'=HYPERLINK" in out and "'+SUM(1)" in out and "'@x" in out and '"a,b"' in out


def test_code_report_distinguishes_measured_from_estimated():
    md = run_to_markdown({"id": 5, "kind": "code", "title": "Add", "status": "ok", "created_at": 1700000000, "latency_ms": 1200, "payload": {
        "token_report": {"provider_input_tokens": 1204, "llm_calls": 2, "cache_hit": False}, "provider_usage": {"total_tokens": 1500},
        "compression": {"original_tokens": 2310, "compressed_tokens": 842}, "code": "def f(): pass", "tests": "def test_f(): pass",
        "verification": {"ran": True, "passed": True, "tests_passed": 1, "tests_failed": 0, "attempts": 1, "repaired": False, "output": "1 passed"},
        "trace": {"spans": [{"name": "generate", "start_ms": 0, "duration_ms": 900, "attrs": {"model": "m"}}]}}})
    assert "measured (gateway usage)" in md and "estimated (local)" in md and "def f(): pass" in md and "| generate |" in md and "Estimates are labelled" in md


def test_verify_report_lists_sources_with_trust_and_corrections():
    md = run_to_markdown({"id": 2, "kind": "verify", "title": "t", "status": "ok", "created_at": 1.0, "payload": {"note": "n", "claims": [{
        "claim": "X 1.0 is the latest.", "kind": "version", "verdict": "unassessed", "possibly_outdated": True, "version_drift": {"detail": "X 2.0 appears"},
        "suggested_correction": {"corrected": "X 2.0 is the latest."}, "sources": [{"title": "Rel", "url": "https://x.dev/r", "trust": "primary", "published_date": "2026-01-01"}]}]}})
    assert "Possibly outdated: True" in md and "confirm first" in md and "[primary]" in md and "<https://x.dev/r>" in md
