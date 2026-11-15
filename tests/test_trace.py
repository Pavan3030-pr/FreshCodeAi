from app.services.trace import Trace


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_spans_have_offsets_durations_and_attrs():
    c = Clock()
    t = Trace(c)
    with t.span("a", x=1) as attrs:
        c.t = 0.25
        attrs["y"] = 2
    c.t = 0.30
    t.event("decision", accepted=True)
    d = t.to_dict()
    a, ev = d["spans"]
    assert a == {"name": "a", "start_ms": 0, "duration_ms": 250, "attrs": {"x": 1, "y": 2}}
    assert ev["event"] is True and ev["start_ms"] == 300 and d["total_ms"] == 300


def test_span_records_error_and_reraises():
    t = Trace(Clock())
    try:
        with t.span("boom"):
            raise ValueError("bad")
    except ValueError:
        pass
    assert "ValueError: bad" in t.to_dict()["spans"][0]["error"]
