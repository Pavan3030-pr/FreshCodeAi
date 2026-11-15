"""Deterministic context compression for the token-efficient agent.

Pipeline: clean -> de-duplicate sources -> rank sentences against the task -> keep the best
sentences (original order) within a token budget. No model calls, fully testable.
Token counts here are ESTIMATES; only provider usage is ever reported as measured.
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

_WORD = re.compile(r"[A-Za-z0-9_.+#-]+")
_STOP = frozenset("""a an the and or but if then else for to of in on at by with from as is are was were be been being
this that these those it its into over under about how what which who when where why can could should would will
do does did use using used write build create make function method class code example please need want""".split())
_BOILER = re.compile(
    r"(cookie|subscribe|newsletter|sign up|log in|skip to|privacy policy|terms of (use|service)|all rights reserved|"
    r"share on|follow us|advertisement|read more|click here)", re.I)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://)[^)]+\)")
_URL = re.compile(r"https?://\S+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`(\[])|\n{2,}|\n(?=\s*(?:[-*]|\d+[.)])\s)")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: max of chars/4 and 1.3*words (never provider telemetry)."""
    if not text:
        return 0
    words = len(text.split())
    return max(1, round(max(len(text) / 4, words * 1.3)))


def keywords(text: str) -> set[str]:
    return {w.lower().strip(".,-") for w in _WORD.findall(text or "") if len(w) > 2 and w.lower() not in _STOP}


def clean_text(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text or "")
    text = _URL.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not (len(ln) < 90 and _BOILER.search(ln))]
    return "\n".join(lines).strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return [p for p in parts if len(p) >= 20 and not (len(p) < 90 and _BOILER.search(p))]


def _score(sentence: str, terms: set[str]) -> float:
    words = keywords(sentence)
    if not words:
        return 0.0
    overlap = len(words & terms)
    score = overlap * 2.0 + (overlap / max(1, len(terms))) * 3.0
    if re.search(r"\bv?\d+\.\d+(?:\.\d+)?\b", sentence):
        score += 1.2  # versions are what stale answers get wrong
    if re.search(r"`[^`]+`|\b\w+\(\)|--[a-z-]+|/[a-z0-9_/{}-]{3,}", sentence):
        score += 0.8  # code-ish tokens: endpoints, flags, calls
    if re.search(r"\b(deprecated|removed|replaced|breaking|requires?|must|new in|since|as of|migrat)", sentence, re.I):
        score += 1.0
    return score


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _canon_url(url: str) -> str:
    p = urlparse(url or "")
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def dedupe_sources(sources: Iterable[dict]) -> tuple[list[dict], int]:
    kept: list[dict] = []
    seen_urls: set[str] = set()
    dropped = 0
    for src in sources:
        url_key = _canon_url(str(src.get("url", "")))
        words = keywords(str(src.get("content", "")))
        if (url_key and url_key in seen_urls) or any(_jaccard(words, keywords(k.get("content", ""))) > 0.8 for k in kept):
            dropped += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        kept.append(src)
    return kept, dropped


def compress_sources(sources: list[dict], query: str, budget_tokens: int = 900, max_sources: int = 3) -> dict:
    """Return {'sources': [...], 'original_tokens', 'compressed_tokens', 'dropped_duplicates', 'saved_percent'}."""
    original = sum(estimate_tokens(str(s.get("content", "")) + str(s.get("title", ""))) for s in sources)
    unique, dropped = dedupe_sources(sources)
    terms = keywords(query)
    ranked = sorted(unique, key=lambda s: (float(s.get("score") or 0), len(keywords(s.get("content", "")) & terms)), reverse=True)
    ranked = ranked[:max_sources]
    out: list[dict] = []
    seen_sentences: set[str] = set()
    if ranked:
        per_source = max(60, budget_tokens // len(ranked))
        for src in ranked:
            sentences = []
            for sent in split_sentences(clean_text(str(src.get("content", "")))):
                norm = re.sub(r"\W+", " ", sent.lower()).strip()
                if norm in seen_sentences:  # repeated boilerplate / copy-pasted lines cost tokens for no new information
                    continue
                seen_sentences.add(norm)
                sentences.append(sent)
            indexed = sorted(enumerate(sentences), key=lambda t: _score(t[1], terms), reverse=True)
            chosen, used = [], 0
            for idx, sent in indexed:
                cost = estimate_tokens(sent)
                if used + cost > per_source:
                    if not chosen and cost > per_source:  # a single long sentence: truncate rather than drop
                        sent = sent[: per_source * 4]
                        chosen.append((idx, sent))
                        used += estimate_tokens(sent)
                    continue
                chosen.append((idx, sent))
                used += cost
            text = " ".join(s for _, s in sorted(chosen))
            out.append({"title": str(src.get("title", "Source"))[:100], "url": str(src.get("url", "")),
                        "content": text, "tokens": used})
    compressed = sum(s["tokens"] for s in out)
    saved = round(100 * (original - compressed) / original, 1) if original > 0 else 0.0
    return {"sources": out, "original_tokens": original, "compressed_tokens": compressed,
            "dropped_duplicates": dropped, "saved_percent": max(0.0, saved)}
