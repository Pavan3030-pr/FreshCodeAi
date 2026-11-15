import asyncio

from app.services.freshness import (classify_claim, detect_version_drift, extract_claims, source_trust, validate_assessments,
                                    verify_text)


def run(coro):
    return asyncio.run(coro)


class FakeTavily:
    configured = True

    async def search(self, query, max_results=3):
        return {"configured": True, "results": [{"title": "Official docs", "url": "https://docs.example.com", "content": "Current documentation",
                                                 "score": .94, "published_date": "2099-01-01"}]}


def test_extracts_version_and_pricing_claims():
    claims = extract_claims("The latest version is 4.2.1.\nThis product pricing is $19 per month.")
    assert len(claims) == 2
    assert any("version" in c.lower() for c in claims) and any("pricing" in c.lower() for c in claims)


def test_ignores_generic_sentence():
    assert extract_claims("A list is a useful data structure.") == []


def test_claim_cap_keeps_highest_risk_in_reading_order():
    text = "\n".join(f"Filler sentence number {i} mentions the policy somewhere." for i in range(8)) + "\nThe latest stable release is v9.9.9 today."
    claims = extract_claims(text, limit=3)
    assert len(claims) == 3 and any("9.9.9" in c for c in claims)


def test_classify_claim_kinds():
    assert classify_claim("The service costs $19 per month.") == "pricing"
    assert classify_claim("Spring Boot 3.4 is the latest stable version.") == "version"
    assert classify_claim("The CEO of Acme is Jane.") == "leadership"
    assert classify_claim("Nothing special here at all.") == "general"


def test_version_drift_detects_newer_version_for_same_product():
    d = detect_version_drift("Spring Boot 3.4 is the latest stable version.",
                             [{"title": "Spring Boot 3.5.1 released", "content": "Spring Boot 3.5.1 is now available."}])
    assert d["status"] == "newer_version_found" and d["newer_version"] == "3.5.1" and d["claims_latest"] is True


def test_version_drift_ignores_other_products_and_same_version():
    other = detect_version_drift("Python 3.12 is the latest.", [{"title": "t", "content": "Django 5.1 was released."}])
    assert other["status"] == "no_version_signal"
    same = detect_version_drift("Python 3.12 is the latest.", [{"title": "t", "content": "Python 3.12 documentation."}])
    assert same["status"] == "version_mentioned_in_sources"
    assert detect_version_drift("The sky is blue today.", [])["status"] == "no_version_in_claim"


def test_version_drift_does_not_flag_older_versions():
    d = detect_version_drift("Node 22.1 is the latest.", [{"title": "t", "content": "Node 18.2 reached end of life."}])
    assert d["status"] == "no_version_signal"


def test_source_trust_tiers():
    assert source_trust("https://docs.spring.io/x") == "primary"
    assert source_trust("https://www.nasa.gov/a") == "primary"
    assert source_trust("https://stackoverflow.com/q/1") == "community"
    assert source_trust("https://someblog.com/p") == "secondary"


def test_verify_returns_recent_source_and_score():
    report = run(verify_text("The latest API version is 4.2.1.", FakeTavily()))
    claim = report["claims"][0]
    assert report["claims_found"] == 1 and claim["status"] == "sources_found" and claim["verdict"] == "unassessed"
    assert claim["freshness_status"] == "very_recent_sources" and report["overall_freshness"] == 100
    assert claim["sources"][0]["url"].startswith("https://") and claim["sources"][0]["trust"] == "primary"
    assert claim["kind"] == "version"


def test_unconfigured_search_does_not_claim_verified():
    class Offline:
        configured = False

        async def search(self, *a, **k):
            return {"configured": False, "results": []}

    report = run(verify_text("The latest API version is 4.2.1.", Offline()))
    assert report["claims"][0]["status"] == "not_checked" and report["overall_freshness"] is None


def test_recent_source_is_not_mistaken_for_factual_support():
    report = run(verify_text("The latest API version is 4.2.1.", FakeTavily()))
    assert report["claims"][0]["freshness_score"] == 100 and report["claims"][0]["verdict"] == "unassessed"
    assert "separate signals" in report["note"]


def test_search_failure_for_one_claim_does_not_abort_others():
    class Flaky:
        configured = True

        async def search(self, query, max_results=3):
            if "pricing" in query:
                raise RuntimeError("boom")
            return await FakeTavily().search(query)

    report = run(verify_text("The latest API version is 4.2.1.\nThis product pricing is $19 per month.", Flaky()))
    by = {c["kind"]: c for c in report["claims"]}
    assert by["pricing"]["status"] == "no_sources" and by["pricing"]["error"] and by["version"]["status"] == "sources_found"


def test_llm_evidence_assessor_can_return_verdict():
    class FakeLLM:
        configured = True

        async def complete(self, system, user):
            return {"content": '[{"verdict":"supported","confidence":91,"reason":"Explicit.","supporting_source_indexes":[0],"contradicting_source_indexes":[]}]'}

    report = run(verify_text("The latest API version is 4.2.1.", FakeTavily(), FakeLLM()))
    assert report["assessment_available"] is True and report["claims"][0]["verdict"] == "supported" and report["claims"][0]["confidence"] == 91
    assert report["summary"]["supported"] == 1


def test_invalid_source_urls_are_not_shown_as_evidence():
    class Unsafe:
        configured = True

        async def search(self, *a, **k):
            return {"configured": True, "results": [{"title": "bad", "url": "javascript:alert(1)", "content": "unsafe"}]}

    report = run(verify_text("The latest API version is 4.2.1.", Unsafe()))
    assert report["claims"][0]["sources"] == [] and report["claims"][0]["verdict"] == "unassessed"


def test_assessment_source_indexes_are_bounded():
    class Assessor:
        configured = True

        async def complete(self, system, user):
            return {"content": '[{"verdict":"supported","confidence":99,"reason":"ok","supporting_source_indexes":[0,99,-1],"contradicting_source_indexes":[]}]'}

    claim = run(verify_text("The latest API version is 4.2.1.", FakeTavily(), Assessor()))["claims"][0]
    assert claim["verdict"] == "supported" and len(claim["supporting_sources"]) == 1


def test_supported_verdict_without_valid_citation_is_downgraded():
    class Uncited:
        configured = True

        async def complete(self, system, user):
            return {"content": '[{"verdict":"supported","confidence":99,"reason":"Trust me.","supporting_source_indexes":[88],"contradicting_source_indexes":[]}]'}

    claim = run(verify_text("The latest API version is 4.2.1.", FakeTavily(), Uncited()))["claims"][0]
    assert claim["verdict"] == "insufficient_evidence" and claim["confidence"] is None and claim["supporting_sources"] == []


def test_malformed_assessor_output_leaves_claims_unassessed():
    class Garbage:
        configured = True

        async def complete(self, system, user):
            return {"content": "I think it's fine!"}

    report = run(verify_text("The latest API version is 4.2.1.", FakeTavily(), Garbage()))
    assert report["assessment_available"] is False and report["claims"][0]["verdict"] == "unassessed"


def test_assessor_exception_is_contained():
    class Down:
        configured = True

        async def complete(self, system, user):
            raise RuntimeError("gateway down")

    assert run(verify_text("The latest API version is 4.2.1.", FakeTavily(), Down()))["claims"][0]["verdict"] == "unassessed"


def test_verify_flags_possibly_outdated_without_any_llm():
    class Newer:
        configured = True

        async def search(self, *a, **k):
            return {"configured": True, "results": [{"title": "Spring Boot 3.5.1 released", "url": "https://spring.io/blog", "content": "Spring Boot 3.5.1 is out."}]}

    report = run(verify_text("Spring Boot 3.4 is the latest stable version.", Newer()))
    c = report["claims"][0]
    assert c["possibly_outdated"] is True and c["verdict"] == "unassessed" and report["summary"]["possibly_outdated"] == 1


def test_validate_assessments_rejects_length_mismatch():
    assert validate_assessments([{"verdict": "supported"}], [{"sources": []}, {"sources": []}]) == []


def test_claim_not_asserting_currency_is_not_flagged_outdated():
    class Newer:
        configured = True

        async def search(self, *a, **k):
            return {"configured": True, "results": [{"title": "t", "url": "https://spring.io/b", "content": "Spring Boot 3.5.1 is out."}]}

    c = run(verify_text("Spring Boot 3.4 requires Java 17 or newer.", Newer()))["claims"][0]
    assert c["version_drift"]["status"] == "newer_version_found" and c["possibly_outdated"] is False


def test_bare_major_and_prerelease_handling():
    assert detect_version_drift("React 17 is the current version.", [{"title": "", "content": "React 18.3 is the latest release."}])["status"] == "newer_version_found"
    assert detect_version_drift("React 17 is the current version.", [{"title": "", "content": "React 17.0 docs."}])["status"] == "version_mentioned_in_sources"
    assert detect_version_drift("Python 3.12 is the latest stable.", [{"title": "", "content": "Python 3.14 beta 1 is available."}])["status"] != "newer_version_found"


def test_suggest_correction_rewrites_only_stale_latest_claims():
    from app.services.freshness import apply_corrections, suggest_correction
    claim = "Spring Boot 3.4 is the latest stable version."
    drift = detect_version_drift(claim, [{"title": "", "content": "Spring Boot 3.5.1 is now available."}])
    c = suggest_correction(claim, drift)
    assert c["corrected"] == "Spring Boot 3.5.1 is the latest stable version." and c["from"] == "3.4" and c["to"] == "3.5.1"
    assert "Confirm" in c["note"]
    assert suggest_correction("Spring Boot 3.4 requires Java 17.", detect_version_drift("Spring Boot 3.4 requires Java 17.", [{"title": "", "content": "Spring Boot 3.5.1 is out."}])) is None
    assert apply_corrections("Intro. " + claim + " Outro.", [c]) == "Intro. Spring Boot 3.5.1 is the latest stable version. Outro."
    assert apply_corrections("unrelated text", [c]) == "unrelated text"


def test_suggest_correction_does_not_touch_longer_versions():
    from app.services.freshness import suggest_correction
    drift = {"status": "newer_version_found", "claims_latest": True, "claimed_version": "3.4", "newer_version": "3.5"}
    assert suggest_correction("Foo 3.45 is the latest.", drift) is None


def test_verify_returns_corrected_text_for_stale_claim():
    class Newer:
        configured = True

        async def search(self, *a, **k):
            return {"configured": True, "results": [{"title": "Spring Boot 3.5.1 released", "url": "https://spring.io/blog", "content": "Spring Boot 3.5.1 is out."}]}

    text = "Spring Boot 3.4 is the latest stable version."
    r = run(verify_text(text, Newer()))
    assert r["corrections_count"] == 1 and r["corrected_text"] == "Spring Boot 3.5.1 is the latest stable version."
    assert r["claims"][0]["suggested_correction"]["to"] == "3.5.1"
    assert run(verify_text("The service costs $19 per month.", Newer()))["corrected_text"] is None


def test_claims_carry_proof_of_retrieval():
    class Tav:
        configured = True

        async def search(self, *a, **k):
            return {"configured": True, "request_id": "req-9", "response_time": 0.42, "cached": False,
                    "results": [{"title": "Docs", "url": "https://docs.example.com", "content": "Current documentation", "score": .9}]}

    c = run(verify_text("The latest API version is 4.2.1.", Tav()))["claims"][0]
    assert c["retrieval"] == {"request_id": "req-9", "response_time": 0.42, "cached": False}
