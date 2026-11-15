from app.services.compress import clean_text, compress_sources, dedupe_sources, estimate_tokens, split_sentences

LONG = ("Skip to content. Subscribe to our newsletter. The `open_session()` call replaces connect() in version 2.7. "
        "Unrelated marketing text about our company culture and offices goes here for padding purposes only. " * 6
        + "Version 2.7.1 is the current stable release and requires Python 3.10. ")


def test_estimate_tokens_positive_and_monotonic():
    assert estimate_tokens("") == 0
    assert 0 < estimate_tokens("hello") < estimate_tokens("hello " * 50)


def test_clean_text_strips_boilerplate_and_urls():
    out = clean_text("Subscribe to our newsletter\nUse the API see https://x.example/a for [docs](https://d.example)\nAll rights reserved")
    assert "newsletter" not in out.lower() and "rights reserved" not in out.lower()
    assert "https://" not in out and "docs" in out


def test_dedupe_drops_same_url_and_near_duplicates():
    a = {"url": "https://docs.x.com/a/", "content": "alpha beta gamma delta epsilon zeta eta theta"}
    b = {"url": "https://www.docs.x.com/a", "content": "totally different words here today"}
    c = {"url": "https://y.com/z", "content": "alpha beta gamma delta epsilon zeta eta theta iota"}
    kept, dropped = dedupe_sources([a, b, c])
    assert len(kept) == 1 and dropped == 2


def test_compression_respects_budget_and_reports_savings():
    srcs = [{"title": "Docs", "url": "https://docs.a.com/1", "content": LONG, "score": .9}]
    out = compress_sources(srcs, "open_session version stable release", budget_tokens=80)
    assert out["compressed_tokens"] <= 100
    assert out["original_tokens"] > out["compressed_tokens"]
    assert out["saved_percent"] > 40
    joined = out["sources"][0]["content"]
    assert "2.7.1" in joined  # the version-bearing, task-relevant sentence is kept


def test_empty_sources_are_safe():
    out = compress_sources([], "anything")
    assert out["sources"] == [] and out["saved_percent"] == 0.0


def test_split_sentences_filters_fragments():
    assert split_sentences("Ok. This is a reasonably long sentence about versions. Hi.") == ["This is a reasonably long sentence about versions."]
