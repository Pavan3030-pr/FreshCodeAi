import asyncio
import dataclasses
import sys
import time

import app.services.runner as runner
from app.services.runner import parse_summary, run_command, run_python_tests, scan_policy


def run(coro):
    return asyncio.run(coro)


def test_policy_allows_ordinary_code():
    assert scan_policy("import math\nfrom collections import Counter\n\ndef f(x):\n    return math.sqrt(x)\n") is None


def test_policy_blocks_dangerous_imports_calls_and_attributes():
    assert "blocked" in scan_policy("import os\nos.system('id')")
    assert "blocked" in scan_policy("from subprocess import run")
    assert "blocked" in scan_policy("import socket")
    assert "blocked" in scan_policy("eval('1+1')")
    assert "blocked" in scan_policy("__import__('os')")
    assert "blocked" in scan_policy("open('/etc/passwd').read()")
    assert "blocked" in scan_policy("().__class__.__bases__[0].__subclasses__()")


def test_policy_reports_syntax_errors():
    assert "syntax error" in scan_policy("def broken(:\n")


def test_blocked_code_never_reaches_a_subprocess():
    r = run(run_python_tests("import os\n", "def test_x():\n    assert True\n"))
    assert r["blocked"] is True and r["passed"] is False and r["exit_code"] == 126 and "os" in r["output"]
    r2 = run(run_python_tests("x = 1\n", "import subprocess\n"))
    assert r2["blocked"] is True and "test_solution.py" in r2["output"]


def test_runner_can_be_disabled():
    original = runner.settings
    runner.settings = dataclasses.replace(original, enable_test_runner=False)
    try:
        r = run(run_python_tests("x = 1", "def test_a():\n    assert True"))
    finally:
        runner.settings = original
    assert r["blocked"] is True and "disabled" in r["output"]


def test_run_command_success_and_exit_code():
    ok = run_command([sys.executable, "-c", "print('hi')"], ".", 10)
    assert ok["returncode"] == 0 and "hi" in ok["stdout"] and not ok["timed_out"]
    bad = run_command([sys.executable, "-c", "import sys; sys.exit(3)"], ".", 10)
    assert bad["returncode"] == 3


def test_run_command_kills_runaway_process_group_quickly():
    started = time.perf_counter()
    r = run_command([sys.executable, "-c", "import time\nwhile True:\n    time.sleep(0.05)"], ".", 1)
    assert r["timed_out"] is True and r["returncode"] == 124 and time.perf_counter() - started < 6


def test_run_command_cpu_bound_loop_is_stopped():
    r = run_command([sys.executable, "-c", "while True:\n    pass"], ".", 1)
    assert r["timed_out"] is True


def test_run_command_memory_hog_is_contained():
    code = "x = []\nwhile True:\n    x.append(bytearray(50_000_000))"
    r = run_command([sys.executable, "-c", code], ".", 5)
    assert r["returncode"] != 0  # MemoryError, OOM-kill, or timeout: never success


def test_parse_summary():
    assert parse_summary("2 failed, 3 passed in 0.1s") == {"passed": 3, "failed": 2, "errors": 0}
    assert parse_summary("1 error in 0.01s")["errors"] == 1


def _node():
    import shutil
    return shutil.which("node")


JS_OK = "exports.add = (a, b) => a + b;"
JS_TESTS = ("const test = require('node:test');\nconst assert = require('node:assert');\nconst { add } = require('./solution');\n"
            "test('adds', () => { assert.equal(add(2, 3), 5); });\ntest('negatives', () => { assert.equal(add(-1, 1), 0); });\n")


def test_js_policy_blocks_dangerous_constructs():
    from app.services.runner import scan_js_policy
    assert scan_js_policy("exports.a = 1;") is None
    for bad in ("require('child_process')", "require(\"node:fs\")", "eval('1')", "new Function('x')", "process.exit(1)", "fetch('http://x')",
                "import('fs')", "globalThis.process", "import x from 'node:os'"):
        assert "blocked" in scan_js_policy(bad), bad


def test_js_blocked_code_never_reaches_a_subprocess():
    from app.services.runner import run_javascript_tests
    r = run(run_javascript_tests("const cp = require('child_process');", JS_TESTS))
    assert r["blocked"] is True and r["exit_code"] == 126


def test_js_runner_passes_fails_and_times_out_for_real():
    if not _node():
        return  # Node.js not installed on this machine
    import dataclasses
    from app.services.runner import run_javascript_tests
    ok = run(run_javascript_tests(JS_OK, JS_TESTS))
    assert ok["passed"] is True and ok["tests_passed"] == 2 and ok["tests_failed"] == 0, ok["output"]
    bad = run(run_javascript_tests("exports.add = (a, b) => a - b;", JS_TESTS))
    assert bad["passed"] is False and bad["tests_failed"] >= 1
    original = runner.settings
    runner.settings = dataclasses.replace(original, runner_timeout_seconds=2)
    try:
        hang = run(run_javascript_tests("exports.add = () => { while (true) {} };", JS_TESTS))
    finally:
        runner.settings = original
    assert hang["passed"] is False and hang.get("timed_out") is True


def test_run_tests_dispatches_by_language():
    r = run(runner.run_tests("javascript", "require('child_process')", "x"))
    assert r["blocked"] and "solution.js" in r["output"]
    r2 = run(runner.run_tests("python", "import os", "x"))
    assert r2["blocked"] and "solution.py" in r2["output"]


def test_effective_mode_selection():
    import dataclasses
    original = runner.settings
    try:
        for kw, want in (({"runner_mode": "docker"}, "docker"), ({"runner_mode": "off", "enable_test_runner": True}, "off"),
                         ({"runner_mode": "", "enable_test_runner": True}, "local"), ({"runner_mode": "", "enable_test_runner": False}, "off"),
                         ({"runner_mode": "bogus", "enable_test_runner": False}, "off")):
            runner.settings = dataclasses.replace(original, **kw)
            assert runner.effective_mode() == want, kw
    finally:
        runner.settings = original


def test_off_mode_refuses_everything():
    import dataclasses
    original = runner.settings
    runner.settings = dataclasses.replace(original, runner_mode="off")
    try:
        for lang in ("python", "javascript"):
            r = run(runner.run_tests(lang, "x = 1", "def test_a(): pass"))
            assert r["blocked"] is True and "disabled" in r["output"]
    finally:
        runner.settings = original


def test_docker_command_is_locked_down():
    from app.services.runner_docker import build_docker_command
    cmd = build_docker_command("/tmp/box", "fc-abc", "python", image="img:1")
    joined = " ".join(cmd)
    for must in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit 64", "--memory 256m", "--user 65534:65534", "/tmp/box:/work:ro", "--rm"):
        assert must in joined, must
    assert "--privileged" not in cmd and "-p" not in cmd[:20] and "--env-file" not in cmd and cmd[cmd.index("img:1") + 1:][:2] == ["python", "-I"]
    assert [c for c in cmd if c == "-e"].__len__() == 2 and "SECRET" not in joined and "KEY" not in joined  # only two benign env vars, no secrets
    js = build_docker_command("/tmp/box", "fc-abc", "javascript", image="img:1")
    assert js[-1] == "solution.test.js" and "node" in js and "pytest" not in " ".join(js)
