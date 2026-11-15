"""Test runner for generated Python code.

DEFENCE IN DEPTH, NOT A SANDBOX: static policy scan + POSIX resource limits + process-group kill
+ timeout + minimal environment + concurrency cap. For hostile multi-tenant use, run it inside an
isolated container/VM (see SECURITY.md).
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from app.config import settings

DENY_IMPORTS = frozenset({
    "os", "subprocess", "socket", "shutil", "ctypes", "multiprocessing", "urllib", "http", "requests", "httpx",
    "ftplib", "smtplib", "telnetlib", "pty", "signal", "resource", "importlib", "builtins", "asyncio.subprocess",
    "webbrowser", "sqlite3", "pathlib", "glob", "tempfile", "socketserver", "xmlrpc", "imaplib", "poplib",
})
DENY_CALLS = frozenset({"exec", "eval", "compile", "__import__", "open", "input", "breakpoint", "globals", "locals", "vars"})
DENY_ATTRS = frozenset({"__subclasses__", "__globals__", "__builtins__", "__class__", "__bases__", "__mro__", "__code__",
                        "__dict__", "__import__", "system", "popen", "fork", "execv", "execve", "spawn"})
WARNING = ("Local runner: defence-in-depth runner (static policy, resource limits, timeout). Not a hardened sandbox: for untrusted "
           "public traffic, execute inside an isolated container/VM with no network.")


def scan_policy(source: str, label: str = "code") -> Optional[str]:
    """Return a human-readable violation string, or None when the source passes the policy."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"{label}: syntax error at line {exc.lineno}: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DENY_IMPORTS:
                    return f"{label}: import of '{alias.name}' is blocked by the runner policy (line {node.lineno})"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in DENY_IMPORTS:
                return f"{label}: import from '{node.module}' is blocked by the runner policy (line {node.lineno})"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DENY_CALLS:
            return f"{label}: call to '{node.func.id}()' is blocked by the runner policy (line {node.lineno})"
        elif isinstance(node, ast.Attribute) and node.attr in DENY_ATTRS:
            return f"{label}: attribute '{node.attr}' is blocked by the runner policy (line {node.lineno})"
    return None


def _limits(memory: bool = True):  # pragma: no cover - runs in the child process
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (settings.runner_timeout_seconds, settings.runner_timeout_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (5_000_000, 5_000_000))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if memory:  # V8 reserves large virtual ranges, so Node is limited with --max-old-space-size instead
            try:
                resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
            except (ValueError, OSError):
                pass  # not enforceable on every platform (e.g. macOS)
    except Exception:
        pass


def run_command(cmd: list[str], cwd: str, timeout: float, env: Optional[dict] = None, memory_limit: bool = True) -> dict:
    """Run a command in its own session with limits; kill the whole process group on timeout."""
    started = time.perf_counter()
    posix = os.name == "posix"
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                            start_new_session=posix, preexec_fn=(lambda: _limits(memory_limit)) if posix else None)
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            pass
        out, err = proc.communicate()
    return {"stdout": out or "", "stderr": err or "", "returncode": 124 if timed_out else proc.returncode,
            "timed_out": timed_out, "duration_ms": round((time.perf_counter() - started) * 1000)}


def parse_summary(output: str) -> dict:
    counts = {"passed": 0, "failed": 0, "errors": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|error|errors)", output):
        key = "errors" if word.startswith("error") else word
        counts[key] = int(n)
    return counts


_sem: Optional[asyncio.Semaphore] = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(2)
    return _sem


def effective_mode() -> str:
    """off | local | docker. Explicit RUNNER_MODE wins; otherwise the legacy ENABLE_TEST_RUNNER flag decides local vs off."""
    mode = (settings.runner_mode or "").lower()
    if mode in {"off", "local", "docker"}:
        return mode
    return "local" if settings.enable_test_runner else "off"


def isolated() -> bool:
    return effective_mode() == "docker"


def _blocked(reason: str, started: float) -> dict:
    return {"passed": False, "exit_code": 126, "output": reason, "duration_ms": round((time.perf_counter() - started) * 1000),
            "tests_passed": 0, "tests_failed": 0, "blocked": True, "warning": WARNING}


def _execute(code: str, tests: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="freshcode-test-") as tmp:
        root = Path(tmp)
        (root / "solution.py").write_text(code, encoding="utf-8")
        (root / "test_solution.py").write_text(tests, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "HOME": tmp, "PYTHONHASHSEED": "0"}
        cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "test_solution.py"]
        r = run_command(cmd, tmp, timeout, env)
    output = (r["stdout"] + "\n" + r["stderr"]).strip()[-5000:]
    if r["timed_out"]:
        output = f"Test execution exceeded the {timeout}-second limit and was terminated.\n" + output
    counts = parse_summary(output)
    return {"passed": r["returncode"] == 0, "exit_code": r["returncode"], "output": output, "duration_ms": r["duration_ms"],
            "tests_passed": counts["passed"], "tests_failed": counts["failed"] + counts["errors"], "blocked": False,
            "timed_out": r["timed_out"], "warning": WARNING}


JS_DENY = re.compile(
    r"""(\brequire\s*\(\s*['"`](?:node:)?(?:child_process|fs|fs/promises|net|http|https|http2|dgram|dns|os|cluster|worker_threads|vm|v8|inspector|tls|repl|readline|module|perf_hooks|async_hooks)['"`]\s*\))"""
    r"""|(\bfrom\s+['"`](?:node:)?(?:child_process|fs|fs/promises|net|http|https|http2|dgram|dns|os|cluster|worker_threads|vm|v8|inspector|tls|repl|readline|module)['"`])"""
    r"""|(\bimport\s*\()|(\beval\s*\()|(\bnew\s+Function\b)|(\bFunction\s*\()|(\bprocess\s*\.\s*(?:binding|dlopen|kill|exit|env|mainModule|chdir|abort|exec))"""
    r"""|(\bglobalThis\b)|(\bconstructor\s*\.\s*constructor\b)|(\b__proto__\b)|(\bfetch\s*\()|(\bWebSocket\b)|(\bXMLHttpRequest\b)""")


def scan_js_policy(source: str, label: str = "code") -> Optional[str]:
    """Regex policy for JavaScript. Weaker than the Python AST scan; defence in depth only."""
    m = JS_DENY.search(source)
    if m:
        line = source.count("\n", 0, m.start()) + 1
        return f"{label}: '{m.group(0).strip()[:40]}' is blocked by the runner policy (line {line})"
    return None


def _execute_js(code: str, tests: str, timeout: int) -> dict:
    import shutil
    node = shutil.which("node")
    if not node:
        return {"passed": False, "exit_code": 127, "output": "Node.js was not found on this server, so JavaScript tests cannot run.", "duration_ms": 0,
                "tests_passed": 0, "tests_failed": 0, "blocked": True, "warning": WARNING}
    with tempfile.TemporaryDirectory(prefix="freshcode-js-") as tmp:
        root = Path(tmp)
        (root / "solution.js").write_text(code, encoding="utf-8")
        (root / "solution.test.js").write_text(tests, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "NODE_ENV": "test"}
        cmd = [node, "--max-old-space-size=256", "--test", "--test-reporter=tap", "solution.test.js"]
        r = run_command(cmd, tmp, timeout, env, memory_limit=False)
    output = (r["stdout"] + "\n" + r["stderr"]).strip()[-5000:]
    if r["timed_out"]:
        output = f"Test execution exceeded the {timeout}-second limit and was terminated.\n" + output
    passed = sum(int(n) for n in re.findall(r"^(?:#|ℹ)\s*pass (\d+)", output, re.M))
    failed = sum(int(n) for n in re.findall(r"^(?:#|ℹ)\s*fail (\d+)", output, re.M))
    return {"passed": r["returncode"] == 0 and failed == 0 and passed > 0, "exit_code": r["returncode"], "output": output, "duration_ms": r["duration_ms"],
            "tests_passed": passed, "tests_failed": failed, "blocked": False, "timed_out": r["timed_out"], "warning": WARNING}


async def run_javascript_tests(code: str, tests: str) -> dict:
    started = time.perf_counter()
    if effective_mode() != "local":
        return _blocked("The local test runner is disabled on this deployment. It executes supplied code.", started)
    for label, src in (("solution.js", code), ("solution.test.js", tests)):
        violation = scan_js_policy(src, label)
        if violation:
            return _blocked(violation, started)
    async with _semaphore():
        return await asyncio.to_thread(_execute_js, code, tests, settings.runner_timeout_seconds)


async def run_tests(language: str, code: str, tests: str) -> dict:
    lang = (language or "python").strip().lower()
    mode = effective_mode()
    if mode == "off":
        return _blocked("Code execution is disabled on this deployment (set RUNNER_MODE=docker with the runner image to enable isolated execution).", time.perf_counter())
    if mode == "docker":
        from app.services.runner_docker import run_docker_tests
        return await run_docker_tests(lang, code, tests)
    if lang in {"javascript", "js", "node"}:
        return await run_javascript_tests(code, tests)
    return await run_python_tests(code, tests)


async def run_python_tests(code: str, tests: str) -> dict:
    started = time.perf_counter()
    if effective_mode() != "local":
        return _blocked("The local test runner is disabled on this deployment. It executes supplied code.", started)
    for label, src in (("solution.py", code), ("test_solution.py", tests)):
        violation = scan_policy(src, label)
        if violation:
            return _blocked(violation, started)
    async with _semaphore():
        return await asyncio.to_thread(_execute, code, tests, settings.runner_timeout_seconds)
