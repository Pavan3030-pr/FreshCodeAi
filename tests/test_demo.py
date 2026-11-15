"""Demo + runner integration tests that execute real pytest in a subprocess (pytest required)."""
import asyncio

import pytest  # noqa: F401  (ImportError => module skipped by the dependency-light runner)

from app.services.demo import run_demo
from app.services.runner import run_python_tests


def test_runner_passes_and_fails_real_suites():
    ok = asyncio.run(run_python_tests("def add(a, b):\n    return a + b\n", "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"))
    assert ok["passed"] is True and ok["tests_passed"] == 1
    bad = asyncio.run(run_python_tests("def add(a, b):\n    return a - b\n", "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"))
    assert bad["passed"] is False and bad["tests_failed"] == 1 and "assert" in bad["output"]


def test_runner_times_out_infinite_loops(monkeypatch=None):
    import dataclasses
    import app.services.runner as runner
    original = runner.settings
    runner.settings = dataclasses.replace(original, runner_timeout_seconds=2)
    try:
        r = asyncio.run(run_python_tests("def spin():\n    while True:\n        pass\n", "from solution import spin\n\ndef test_spin():\n    spin()\n"))
    finally:
        runner.settings = original
    assert r["passed"] is False and r.get("timed_out") is True


def test_demo_is_honest_and_real_parts_are_real():
    d = asyncio.run(run_demo())
    assert d["mode"] == "demo" and "DEMO FIXTURE" in d["notice"]
    assert d["tests"]["passed"] is True and d["tests"]["tests_passed"] == 3
    assert d["compression"]["dropped_duplicates"] == 1 and d["compression"]["saved_percent"] > 30
    drift = d["verification"]["claims"][0]["version_drift"]
    assert drift["status"] == "newer_version_found" and drift["newer_version"] == "2.7.1"
    assert d["benchmark"]["measured"] is False and d["benchmark"]["token_savings_percent"] is None
