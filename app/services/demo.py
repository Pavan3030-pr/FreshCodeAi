"""Credential-free judge demo.

HONESTY CONTRACT: the LLM output and the search results below are fixtures and are labelled as such.
Everything else is REAL and executed live: evidence compression, version-drift detection, and the pytest run.
"""
from __future__ import annotations

from app.services.compress import compress_sources
from app.services.freshness import apply_corrections, classify_claim, detect_version_drift, source_trust, suggest_correction
from app.services.runner import run_python_tests

CODE = '''def normalize_email(value: str) -> str:
    """Normalize an email address for case-insensitive comparison."""
    if not isinstance(value, str):
        raise TypeError("email must be a string")
    value = value.strip()
    if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
        raise ValueError("invalid email address")
    local, domain = value.split("@")
    return f"{local.lower()}@{domain.lower()}"
'''

TESTS = '''import pytest
from solution import normalize_email


def test_normalizes_case_and_whitespace():
    assert normalize_email("  PAVAN@Example.COM ") == "pavan@example.com"


def test_rejects_invalid_email():
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_rejects_non_string():
    with pytest.raises(TypeError):
        normalize_email(None)
'''

CLAIM = "AcmeSDK 2.3 is the latest stable version."

# Fixture "search results" for a fictional product, so no real-world fact is asserted.
FIXTURE_SOURCES = [
    {"title": "AcmeSDK release notes", "url": "https://docs.acmesdk.example/releases", "score": 0.93, "published_date": None,
     "content": ("Skip to content. Subscribe to our newsletter. AcmeSDK 2.7.1 is the current stable release. "
                 "AcmeSDK 2.7 replaces the legacy `connect()` handshake with `open_session()`. "
                 "The `connect()` call is deprecated since 2.5 and will be removed in 3.0. "
                 "All rights reserved. Cookie policy. Click here to read more about our company history and many unrelated announcements. "
                 "Upgrade guides for 2.3 through 2.7 are available in the migration section.")},
    {"title": "AcmeSDK release notes (mirror)", "url": "https://docs.acmesdk.example/releases/", "score": 0.7, "published_date": None,
     "content": "AcmeSDK 2.7.1 is the current stable release. AcmeSDK 2.7 replaces the legacy `connect()` handshake with `open_session()`."},
    {"title": "Community thread: which AcmeSDK version?", "url": "https://stackoverflow.com/q/0", "score": 0.4, "published_date": None,
     "content": "I am still on AcmeSDK 2.3 and everything seems to work. Does anyone know whether 2.7 is stable enough to upgrade today?"},
]


async def run_demo() -> dict:
    tests = await run_python_tests(CODE, TESTS)
    comp = compress_sources(FIXTURE_SOURCES, "AcmeSDK latest stable version connect open_session", budget_tokens=120)
    drift = detect_version_drift(CLAIM, FIXTURE_SOURCES)
    sources = [{**s, "trust": source_trust(s["url"])} for s in FIXTURE_SOURCES]
    correction = suggest_correction(CLAIM, drift)
    return {
        "mode": "demo",
        "notice": ("DEMO FIXTURE — no Bifrost inference or Tavily live search was performed. The search results and the code are fixtures "
                   "for a fictional SDK; evidence compression, version-drift detection and the pytest run below are real, executed just now."),
        "workflow_id": "freshcode-demo-002",
        "pipeline": [
            {"stage": "research", "state": "done", "message": "Loaded 3 fixture search results (not a live search)."},
            {"stage": "optimize", "state": "done", "message": f"REAL compression: {comp['original_tokens']} → {comp['compressed_tokens']} est. tokens, {comp['dropped_duplicates']} duplicate source dropped."},
            {"stage": "generate", "state": "done", "message": "Loaded a deterministic sample implementation (not an LLM response)."},
            {"stage": "test", "state": "done" if tests.get("passed") else "error", "message": f"REAL pytest run: {tests.get('tests_passed', 0)} passed, {tests.get('tests_failed', 0)} failed."},
        ],
        "coding": {"language": "python", "task": "Normalize email addresses and reject malformed inputs.", "code": CODE,
                   "answer": "Deterministic sample: trims whitespace, lowercases local part and domain, rejects malformed input.",
                   "estimated_input_tokens": comp["compressed_tokens"] + 60, "provider_usage": {}, "model": "demo-fixture (no model call)",
                   "sources": [], "mode": "demo"},
        "verification": {"claims_found": 1, "corrections_count": 1 if correction else 0, "corrected_text": apply_corrections(CLAIM, [correction]) if correction else None, "overall_freshness": None, "assessment_available": False, "live_verification": False,
                         "note": "Fixture sources for a fictional SDK. Version drift is a REAL deterministic check; no LLM verdict was produced.",
                         "summary": {"possibly_outdated": 1 if drift["status"] == "newer_version_found" else 0, "contradicted": 0, "supported": 0, "needs_review": 0},
                         "claims": [{"claim": CLAIM, "kind": classify_claim(CLAIM), "status": "demo_fixture", "verdict": "unassessed", "confidence": None,
                                     "reason": "No LLM assessor ran in demo mode. The version-drift check below is deterministic.",
                                     "freshness_score": None, "freshness_status": "not_measured_demo", "version_drift": drift,
                                     "possibly_outdated": drift["status"] == "newer_version_found", "suggested_correction": correction, "sources": sources}]},
        "compression": comp,
        "benchmark": {"measured": False, "baseline": {"input_tokens": None}, "optimized": {"input_tokens": None}, "token_savings_percent": None,
                      "evidence_compression_percent_est": comp["saved_percent"], "samples": 0,
                      "note": "Evidence compression is a real local computation using estimated tokens. It is NOT provider telemetry and not a measured billing saving."},
        "tests": tests, "test_code": TESTS,
    }
