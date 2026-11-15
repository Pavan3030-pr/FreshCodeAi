"""Offline, deterministic self-evaluation on small HAND-WRITTEN labelled sets (no network, no keys).

Directional evidence only: the sets are small and written by the authors. They exist so the detector's behaviour is
measurable and regressions are caught, not to claim benchmark-grade accuracy.
"""
from __future__ import annotations

from app.services.compress import compress_sources, estimate_tokens
from app.services.freshness import detect_version_drift, extract_claims

# (id, claim, source snippets, expected_outdated)
DRIFT_CASES = [
    ("spring-newer", "Spring Boot 3.4 is the latest stable version.", ["Spring Boot 3.5.2 is now available for download."], True),
    ("python-newer", "Python 3.11 is the newest release.", ["Python 3.13 was released with a new interpreter mode."], True),
    ("node-newer", "Node.js 18.0 is the latest LTS.", ["Node.js 22.11 is the current LTS line."], True),
    ("django-newer", "Django 4.1 is the latest stable release.", ["Django 5.1 release notes: new features."], True),
    ("k8s-newer", "Kubernetes 1.28 is the current version.", ["Kubernetes 1.31 is now generally available."], True),
    ("terraform-v-prefix", "Terraform 1.5 is the latest.", ["Download Terraform v1.9.5 for your platform."], True),
    ("go-newer", "Go 1.20 is the newest release.", ["Go 1.23 is released with range-over-func."], True),
    ("same-version", "Python 3.12 is the latest.", ["Python 3.12 documentation index."], False),
    ("older-only", "Node 22.1 is the latest.", ["Node 18.2 reached end of life."], False),
    ("other-product", "Django 5.0 is the latest.", ["Flask 3.1 was released this week."], False),
    ("no-version", "The service costs $19 per month.", ["Plans start at $19 per month."], False),
    ("same-spring", "Spring Boot 3.5 is the latest.", ["Spring Boot 3.5 reference documentation."], False),
    ("rust-vs-cargo", "Rust 1.70 is the latest.", ["Cargo 1.80 ships with improved resolver."], False),
    ("not-claiming-latest", "Spring Boot 3.4 requires Java 17.", ["Spring Boot 3.5.2 is now available."], False),
    ("nextjs-newer", "Next.js 13.4 is the latest stable.", ["Next.js 14.2 is now available."], True),
    ("react-bare-major", "React 17 is the current version.", ["React 18.3 is the latest release."], True),  # known limitation: bare majors
    ("beta-not-stable", "Python 3.12 is the latest stable.", ["Python 3.14 beta 1 is available for testing."], False),  # known limitation: pre-releases
    ("history-claim", "We migrated off Java 8.0 in 2021.", ["Java 21.0 is the current LTS."], False),
]

# (id, query, sources, fact that must survive compression)
COMPRESSION_CASES = [
    ("version-fact", "AcmeSDK latest stable", [
        {"title": "Releases", "url": "https://d.example/r", "score": .9, "content": "Subscribe to our newsletter. " + "We love shipping software and thanking our community for years of support. " * 6 + "AcmeSDK 2.7.1 is the current stable release. All rights reserved."}], "2.7.1"),
    ("deprecation", "migrate connect open_session", [
        {"title": "Guide", "url": "https://d.example/g", "score": .9, "content": "Welcome to the guide. " * 8 + "The connect() call is deprecated since 2.5 and removed in 3.0; use open_session() instead. " + "Cookie policy and unrelated marketing copy follow. " * 5}], "open_session()"),
    ("duplicate-sources", "rate limit headers", [
        {"title": "A", "url": "https://d.example/a", "score": .9, "content": "The API returns X-RateLimit-Remaining on every response and enforces 100 requests per minute."},
        {"title": "A mirror", "url": "https://www.d.example/a/", "score": .8, "content": "The API returns X-RateLimit-Remaining on every response and enforces 100 requests per minute."}], "X-RateLimit-Remaining"),
    ("endpoint", "create account endpoint", [
        {"title": "API", "url": "https://d.example/api", "score": .9, "content": "Intro text that says very little of value to anyone. " * 8 + "Use POST /v2/accounts to create an account; the include parameter is required. " + "Footer links and legal notices. " * 6}], "/v2/accounts"),
    ("requirement", "python minimum version", [
        {"title": "Install", "url": "https://d.example/i", "score": .9, "content": "Thanks for visiting our installation page today friends. " * 8 + "The library requires Python 3.10 or newer since version 4.0. " + "Share on social media and follow us everywhere. " * 5}], "Python 3.10"),
    ("pricing", "pro plan price", [
        {"title": "Pricing", "url": "https://d.example/p", "score": .9, "content": "Our plans are designed for teams of every size and shape. " * 8 + "The Pro plan costs $29 per month billed annually. " + "Contact sales for enterprise details and demos. " * 5}], "$29"),
]

# (text, should_extract_a_claim)
EXTRACTION_CASES = [
    ("Spring Boot 3.4 is the latest stable version.", True),
    ("The service costs $19 per month on the Pro plan.", True),
    ("As of 2024 the free tier allows 1,000 requests per day.", True),
    ("The CEO of Acme Robotics is Jane Doe.", True),
    ("The old endpoint is deprecated and will be removed in v3.0.", True),
    ("The current API requires the include parameter on every call.", True),
    ("Python is a popular programming language for beginners.", False),
    ("Use a for loop to iterate over the list items one by one.", False),
    ("I really enjoy walking in the park on sunny afternoons.", False),
    ("A hash map stores key value pairs for fast lookups.", False),
    ("Our team shipped the latest design draft to the client yesterday afternoon.", False),  # known limitation: "latest" outside tech context
    ("React Router now requires Node 18 or higher to install.", True),  # known limitation: bare majors / "requires"
]


def run_evals() -> dict:
    cases, tp, fp, fn, tn = [], 0, 0, 0, 0
    for cid, claim, snippets, expected in DRIFT_CASES:
        d = detect_version_drift(claim, [{"title": "", "content": s} for s in snippets])
        predicted = d["status"] == "newer_version_found" and bool(d.get("claims_latest"))
        tp += predicted and expected
        fp += predicted and not expected
        fn += (not predicted) and expected
        tn += (not predicted) and not expected
        cases.append({"id": cid, "claim": claim, "expected_outdated": expected, "predicted_outdated": predicted, "pass": predicted == expected})
    n = len(DRIFT_CASES)
    drift = {"cases": n, "accuracy": round(100 * (tp + tn) / n, 1), "precision": round(100 * tp / (tp + fp), 1) if tp + fp else None,
             "recall": round(100 * tp / (tp + fn), 1) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "details": cases}
    comp_cases, kept, saved = [], 0, []
    for cid, query, sources, fact in COMPRESSION_CASES:
        c = compress_sources(sources, query, budget_tokens=60)
        text = " ".join(s["content"] for s in c["sources"])
        retained = fact.lower() in text.lower()
        kept += retained
        saved.append(c["saved_percent"])
        comp_cases.append({"id": cid, "fact": fact, "retained": retained, "original_tokens": c["original_tokens"], "compressed_tokens": c["compressed_tokens"], "saved_percent": c["saved_percent"]})
    m = len(COMPRESSION_CASES)
    compression = {"cases": m, "fact_retention": round(100 * kept / m, 1), "avg_saved_percent": round(sum(saved) / m, 1), "details": comp_cases}
    ext_details, e_tp, e_fp, e_fn, e_tn = [], 0, 0, 0, 0
    for text, expected in EXTRACTION_CASES:
        got = bool(extract_claims(text))
        e_tp += got and expected
        e_fp += got and not expected
        e_fn += (not got) and expected
        e_tn += (not got) and not expected
        ext_details.append({"text": text, "expected": expected, "extracted": got, "pass": got == expected})
    k = len(EXTRACTION_CASES)
    extraction = {"cases": k, "recall": round(100 * e_tp / (e_tp + e_fn), 1) if e_tp + e_fn else None,
                  "false_positive_rate": round(100 * e_fp / (e_fp + e_tn), 1) if e_fp + e_tn else None,
                  "accuracy": round(100 * (e_tp + e_tn) / k, 1), "details": ext_details}
    return {"drift_detector": drift, "claim_extraction": extraction, "compression": compression,
            "note": "Small hand-written labelled sets, run offline and deterministically. The detector was developed against these cases, so the figures are optimistic and directional, not a benchmark-grade accuracy claim. Token counts are estimates."}
