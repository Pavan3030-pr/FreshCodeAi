from app.services.evals import COMPRESSION_CASES, DRIFT_CASES, run_evals


def test_eval_sets_are_balanced_and_non_trivial():
    assert len(DRIFT_CASES) >= 15 and len(COMPRESSION_CASES) >= 5
    flags = [c[3] for c in DRIFT_CASES]
    assert 0.3 < sum(flags) / len(flags) < 0.7  # both classes well represented


def test_drift_detector_meets_quality_floor_on_labelled_set():
    d = run_evals()["drift_detector"]
    assert d["accuracy"] >= 90 and d["precision"] >= 85 and d["recall"] >= 85, d
    assert d["tp"] + d["fp"] + d["fn"] + d["tn"] == d["cases"]


def test_compression_keeps_answer_bearing_facts_and_saves_tokens():
    c = run_evals()["compression"]
    assert c["fact_retention"] == 100.0 and c["avg_saved_percent"] >= 50, c


def test_eval_report_is_honest_about_its_limits():
    assert "hand-written" in run_evals()["note"]


def test_claim_extraction_meets_floor_and_reports_known_limits():
    e = run_evals()["claim_extraction"]
    assert e["cases"] >= 10 and e["recall"] >= 80 and e["false_positive_rate"] <= 40 and e["accuracy"] >= 80, e
