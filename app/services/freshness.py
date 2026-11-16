"""Stale-answer detector.

Three independent signals are kept separate on purpose (a recent source is NOT proof):
  1. source recency   - how new the retrieved sources are (only when publication dates exist)
  2. version drift    - deterministic check: do sources mention a NEWER version than the claim states?
  3. evidence verdict - optional LLM assessor restricted to the retrieved snippets, with validated citations
"""
from __future__ import annotations

import json
import re
from asyncio import gather
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

RISK_TERMS = re.compile(
    r"\b(latest|current|currently|newest|stable|price|pricing|costs?|version|deprecated|deprecation|released?|API|endpoint|"
    r"supports?|requires?|requirements?|law|regulation|CEO|founder|policy|as of|default|limit|quota|free tier|"
    r"202[4-9]|20[3-9]\d)\b", re.I)
VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")
LATEST_RE = re.compile(r"\b(latest|current(?:ly)?|newest|stable|most recent|up[- ]to[- ]date)\b", re.I)

KIND_RULES = [
    ("version", re.compile(r"\bv?\d+\.\d+|\bversion|\blatest\b|\bstable\b|\breleased?\b", re.I)),
    ("pricing", re.compile(r"[$€£₹]\s?\d|\bprice|\bpricing|\bcosts?\b|\bfree tier|\bper month", re.I)),
    ("api", re.compile(r"\bAPI\b|\bendpoint|\bparameter|\bSDK\b|/v\d", re.I)),
    ("deprecation", re.compile(r"\bdeprecat|\bremoved\b|\bend[- ]of[- ]life|\bsunset", re.I)),
    ("policy", re.compile(r"\blaw\b|\bregulation|\bpolicy|\bcompliance", re.I)),
    ("leadership", re.compile(r"\bCEO\b|\bfounder\b|\bpresident\b|\bchairman", re.I)),
]
OFFICIAL_HOSTS = ("docs.", "developer.", "developers.", "learn.microsoft.com", "github.com", "pypi.org", "npmjs.com",
                  "readthedocs", "kubernetes.io", "python.org", "nodejs.org", "spring.io", "openjdk.org", "oracle.com",
                  "mozilla.org", "w3.org", "ietf.org", "rust-lang.org", "go.dev", "golang.org", "apache.org", "postgresql.org")
COMMUNITY_HOSTS = ("reddit.com", "stackoverflow.com", "stackexchange.com", "quora.com", "medium.com", "dev.to",
                   "hashnode", "news.ycombinator.com", "facebook.com", "x.com", "twitter.com")


def source_trust(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if host.endswith((".gov", ".edu")) or ".gov." in host or any(h in host for h in OFFICIAL_HOSTS):
        return "primary"
    if any(h in host for h in COMMUNITY_HOSTS):
        return "community"
    return "secondary"


def classify_claim(claim: str) -> str:
    for kind, pattern in KIND_RULES:
        if pattern.search(claim):
            return kind
    return "general"


def _risk_score(chunk: str) -> int:
    score = len(RISK_TERMS.findall(chunk))
    if VERSION_RE.search(chunk):
        score += 2
    if LATEST_RE.search(chunk):
        score += 2
    if re.search(r"[$€£₹]\s?\d", chunk):
        score += 1
    return score


def extract_claims(text: str, limit: int = 6) -> list[str]:
    chunks = [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", x).strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text)]
    scored = []
    for order, chunk in enumerate(chunks):
        if len(chunk) >= 24 and (RISK_TERMS.search(chunk) or VERSION_RE.search(chunk)):
            scored.append((order, chunk[:420]))
    unique = list(dict.fromkeys(scored))
    if len(unique) > limit:  # keep the highest-risk claims, preserve reading order
        top = sorted(unique, key=lambda t: _risk_score(t[1]), reverse=True)[:limit]
        unique = sorted(top)
    return list(dict.fromkeys(c for _, c in unique))


def _vtuple(v: str) -> tuple:
    parts = [int(x) for x in v.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))  # "17" == "17.0.0"


BARE_MAJOR_RE = re.compile(r"\bv?(\d{1,2})\b(?!\.\d)")
PRERELEASE_RE = re.compile(r"^[\s-]*(alpha|beta|rc\d*|preview|nightly|dev|snapshot|canary|pre-?release)\b", re.I)


def _product_terms(claim: str, version: str) -> tuple[list[str], str]:
    """Words directly before the version, e.g. 'Spring Boot 3.4' -> (['spring', 'boot'], 'Spring Boot')."""
    m = re.search(r"((?:[A-Za-z][\w.+#-]*\s+){1,3})v?" + re.escape(version), claim)
    if not m:
        return [], ""
    stop = {"is", "the", "a", "an", "to", "in", "of", "and", "uses", "use", "version", "latest", "current", "stable", "at", "as", "now", "was", "are"}
    words = [w for w in m.group(1).split() if w.lower() not in stop][-2:]
    return [w.lower() for w in words], " ".join(words)


_FILLER_WORDS = {"version", "versions", "ver", "v", "release", "released", "releases", "is", "now", "at", "latest", "stable", "to", "the", "of", "in",
                 "current", "currently", "as", "was", "edition", "update", "updated", "upgrade", "upgraded", "available", "build", "and", "or"}


def _names_product(window: str, product: list) -> bool:
    """True when the product is the name nearest to the version, so "FastAPI 0.133 adds Starlette 1.0" is not read as FastAPI 1.0."""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9.+#_-]*", window) if w not in _FILLER_WORDS and not re.fullmatch(r"v?\d[\d.]*", w)]
    nearest = " ".join(words[-max(1, len(product)):])
    return all(term in nearest for term in product)


def detect_version_drift(claim: str, sources: list[dict]) -> dict:
    """Deterministic: flag when a source mentions the same product at a NEWER version than the claim."""
    claimed = VERSION_RE.findall(claim)
    bare = False
    if not claimed:  # fall back to a bare major ("React 17") only when it directly follows a product name
        for m in BARE_MAJOR_RE.finditer(claim):
            if _product_terms(claim, m.group(1))[0]:
                claimed, bare = [m.group(1)], True
                break
    if not claimed:
        return {"status": "no_version_in_claim"}
    claimed_v = max(claimed, key=_vtuple)
    product, display = _product_terms(claim, claimed_v)
    if not product:
        return {"status": "product_unclear", "claimed_version": claimed_v}
    newer: Optional[tuple] = None
    same_found = False
    for idx, src in enumerate(sources):
        text = f"{src.get('title', '')}. {src.get('content', '')}"
        low = text.lower()
        for m in VERSION_RE.finditer(text):
            window = low[max(0, m.start() - 48): m.start()]
            if not all(term in window for term in product) or not _names_product(window, product):
                continue
            if PRERELEASE_RE.match(text[m.end(): m.end() + 16]):
                continue  # beta / rc / preview builds are not "the latest stable"
            v = m.group(1)
            if _vtuple(v) == _vtuple(claimed_v):
                same_found = True
            elif _vtuple(v) > _vtuple(claimed_v) and _vtuple(v)[0] - _vtuple(claimed_v)[0] < 20:
                if newer is None or _vtuple(v) > _vtuple(newer[0]):
                    newer = (v, idx)
    asks_latest = bool(LATEST_RE.search(claim))
    if newer:
        return {"status": "newer_version_found", "claimed_version": claimed_v, "newer_version": newer[0],
                "source_index": newer[1], "claims_latest": asks_latest, "product": " ".join(product),
                "detail": f"{display} {newer[0]} appears in a retrieved source; the claim states {claimed_v}"
                          + (" as the latest." if asks_latest else ".")}
    if same_found:
        return {"status": "version_mentioned_in_sources", "claimed_version": claimed_v, "product": " ".join(product),
                "detail": f"A retrieved source mentions {claimed_v} for this product and none mention a newer version."}
    return {"status": "no_version_signal", "claimed_version": claimed_v, "product": " ".join(product)}


def suggest_correction(claim: str, drift: dict):
    """Deterministic rewrite of a stale version claim; a suggestion to confirm, never an authoritative fact."""
    if drift.get("status") != "newer_version_found" or not drift.get("claims_latest"):
        return None
    old, new = drift["claimed_version"], drift["newer_version"]
    pattern = re.compile(r"(?<![\d.])v?" + re.escape(old) + r"(?!\d|\.\d)")
    corrected, n = pattern.subn(new, claim, count=1)
    if not n or corrected == claim:
        return None
    return {"original": claim, "corrected": corrected, "from": old, "to": new,
            "note": "Suggested from a retrieved snippet. Confirm on the official release page before publishing."}


def apply_corrections(text: str, corrections: list) -> str:
    for c in corrections:
        if c and c["original"] in text:
            text = text.replace(c["original"], c["corrected"], 1)
    return text


def _age_days(published):
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(str(published))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - dt).days)
        except (ValueError, TypeError):
            return None


def _source_freshness(results):
    dated = [a for a in (_age_days(r.get("published_date")) for r in results) if a is not None]
    if not dated:
        return None, "date_unavailable"
    age = min(dated)
    if age <= 7:
        return 100, "very_recent_sources"
    if age <= 30:
        return 90, "recent_sources"
    if age <= 90:
        return 75, "aging_sources"
    if age <= 180:
        return 60, "old_sources"
    return 30, "older_sources"


def _parse_assessment(content: str):
    if not content:
        return []
    match = re.search(r"\[[\s\S]*\]", content)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


VALID_VERDICTS = {"supported", "contradicted", "mixed", "insufficient_evidence"}


def validate_assessments(candidates: list, evidence_payload: list) -> list:
    """Bound citations to real source indexes; downgrade verdicts that cite nothing valid."""
    if len(candidates) != len(evidence_payload):
        return []
    cleaned = []
    for item, evidence in zip(candidates, evidence_payload):
        if not isinstance(item, dict) or item.get("verdict") not in VALID_VERDICTS:
            return []
        n = len(evidence["sources"])

        def idx(values):
            return [i for i in values if type(i) is int and 0 <= i < n] if isinstance(values, list) else []

        item["supporting_source_indexes"] = idx(item.get("supporting_source_indexes", []))
        item["contradicting_source_indexes"] = idx(item.get("contradicting_source_indexes", []))
        v = item["verdict"]
        sup, con = bool(item["supporting_source_indexes"]), bool(item["contradicting_source_indexes"])
        if not ((v == "supported" and sup) or (v == "contradicted" and con) or (v == "mixed" and sup and con) or v == "insufficient_evidence"):
            item["verdict"] = "insufficient_evidence"
            item["confidence"] = None
            item["reason"] = "The assessor did not provide valid source citations for its verdict; manual review is required."
        cleaned.append(item)
    return cleaned


async def verify_text(text: str, tavily=None, bifrost=None):
    """Find evidence per claim; recency, version drift and factual support are separate dimensions."""
    from app.services.tavily import TavilyClient
    client = tavily or TavilyClient()
    claims = extract_claims(text)
    if not claims:
        return {"claims": [], "corrections_count": 0, "corrected_text": None, "overall_freshness": None, "claims_found": 0, "live_verification": client.configured,
                "assessment_available": False, "summary": {"possibly_outdated": 0, "contradicted": 0, "supported": 0, "needs_review": 0},
                "note": "No obvious change-sensitive claims were detected. This does not mean every other statement is correct."}

    async def search_one(claim):
        try:
            return await client.search(claim, max_results=3)
        except Exception as exc:  # upstream failure must not abort the other claims
            return {"configured": client.configured, "results": [], "error": str(exc)[:180]}

    searches = await gather(*(search_one(c) for c in claims))
    evidence_payload = []
    for claim, search in zip(claims, searches):
        safe = []
        for source in search.get("results", [])[:3]:
            url = str(source.get("url") or "")
            if not url.startswith(("https://", "http://")):
                continue
            safe.append({"title": str(source.get("title") or "Untitled source")[:180], "url": url[:1000],
                         "content": str(source.get("content") or "")[:900], "published_date": source.get("published_date"),
                         "relevance": source.get("relevance", source.get("score")), "trust": source_trust(url)})
        evidence_payload.append({"claim": claim, "sources": safe,
                                 "retrieval": {"request_id": search.get("request_id"), "response_time": search.get("response_time"), "cached": bool(search.get("cached"))}})

    assessments, assessment_available = [], False
    llm = bifrost
    if llm is None:
        from app.services.bifrost import BifrostClient
        llm = BifrostClient()
    if llm.configured and any(item["sources"] for item in evidence_payload):
        system = ("You are a cautious evidence auditor. For each claim, assess ONLY whether supplied source snippets directly support or contradict it. "
                  "A source being recent is not proof. Return ONLY a JSON array with one object per claim in input order: "
                  '{"verdict":"supported|contradicted|mixed|insufficient_evidence","confidence":0-100,"reason":"short reason","supporting_source_indexes":[0],"contradicting_source_indexes":[]}. '
                  "Do not infer missing facts. If snippets are indirect or incomplete, use insufficient_evidence.")
        slim = [{"claim": e["claim"], "sources": [{"title": s["title"], "content": s["content"], "published_date": s["published_date"]} for s in e["sources"]]} for e in evidence_payload]
        try:
            from app.config import settings as _settings
            route = {"model": _settings.bifrost_fast_model} if _settings.bifrost_fast_model else {}  # cheap model for evidence assessment
            result = await llm.complete(system, json.dumps(slim, ensure_ascii=False), **route)
            assessments = validate_assessments(_parse_assessment(result.get("content", "")), evidence_payload)
            assessment_available = len(assessments) == len(claims)
        except Exception:
            assessments = []

    verified, freshness_values = [], []
    summary = {"possibly_outdated": 0, "contradicted": 0, "supported": 0, "needs_review": 0}
    for i, (claim, search) in enumerate(zip(claims, searches)):
        sources = evidence_payload[i]["sources"]
        score, freshness_status = _source_freshness(sources)
        if score is not None:
            freshness_values.append(score)
        assessment = assessments[i] if i < len(assessments) and isinstance(assessments[i], dict) else {}
        verdict = assessment.get("verdict", "unassessed")
        if verdict not in VALID_VERDICTS:
            verdict = "unassessed"
        confidence = assessment.get("confidence")
        try:
            confidence = max(0, min(100, int(confidence))) if confidence is not None else None
        except (ValueError, TypeError):
            confidence = None
        drift = detect_version_drift(claim, sources)
        possibly_outdated = drift["status"] == "newer_version_found" and bool(drift.get("claims_latest"))  # only when the claim asserts currency
        correction = suggest_correction(claim, drift)
        if possibly_outdated:
            summary["possibly_outdated"] += 1
        if verdict == "contradicted":
            summary["contradicted"] += 1
        elif verdict == "supported" and not possibly_outdated:
            summary["supported"] += 1
        elif not possibly_outdated:
            summary["needs_review"] += 1
        verified.append({
            "claim": claim, "kind": classify_claim(claim),
            "status": "sources_found" if sources else ("not_checked" if not client.configured else "no_sources"),
            "verdict": verdict, "confidence": confidence,
            "reason": str(assessment.get("reason", "Evidence requires manual review."))[:260],
            "freshness_score": score, "freshness_status": freshness_status,
            "version_drift": drift, "possibly_outdated": possibly_outdated, "suggested_correction": correction,
            "supporting_sources": [sources[j] for j in assessment.get("supporting_source_indexes", []) if j < len(sources)],
            "contradicting_sources": [sources[j] for j in assessment.get("contradicting_source_indexes", []) if j < len(sources)],
            "sources": sources, "retrieval": evidence_payload[i].get("retrieval"), "error": search.get("error")})
    overall = round(sum(freshness_values) / len(freshness_values)) if freshness_values else None
    corrections = [v["suggested_correction"] for v in verified if v.get("suggested_correction")]
    corrected_text = apply_corrections(text, corrections) if corrections else None
    return {"claims": verified, "corrections_count": len(corrections), "corrected_text": corrected_text, "overall_freshness": overall, "claims_found": len(verified), "summary": summary,
            "live_verification": client.configured, "assessment_available": assessment_available,
            "note": "Source recency, version drift and evidence verdicts are separate signals. Version drift is a deterministic text check; verdicts need the LLM assessor; unassessed claims require manual review."}
