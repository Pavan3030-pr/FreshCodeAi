"""Container execution for generated code (RUNNER_MODE=docker).

Each run uses a disposable container: no network, read-only root filesystem, dropped capabilities, no-new-privileges,
non-root user, CPU/memory/PID limits, source mounted read-only, no environment secrets, killed on timeout.
UNVERIFIED IN THE DEVELOPMENT SANDBOX (no Docker daemon there): the command builder is unit-tested; the live path needs a
Docker host. See docs/SECURITY.md.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import settings

WARNING = "Executed in a disposable container (no network, read-only filesystem, non-root, CPU/memory/PID limits)."


def build_docker_command(workdir: str, name: str, language: str, *, image: str, memory_mb: int = 256, cpus: float = 1.0, pids: int = 64) -> list[str]:
    js = language in {"javascript", "js", "node"}
    inner = (["node", "--max-old-space-size=192", "--test", "--test-reporter=tap", "solution.test.js"] if js
             else ["python", "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "test_solution.py"])
    return ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(pids), "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m", "--cpus", str(cpus),
            "--user", "65534:65534", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
            "-v", f"{workdir}:/work:ro", "-w", "/work", image, *inner]


def _run(code: str, tests: str, language: str, timeout: int) -> dict:
    from app.services.runner import parse_summary
    js = language in {"javascript", "js", "node"}
    started = time.perf_counter()
    name = "fc-" + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="freshcode-box-") as tmp:
        os.chmod(tmp, 0o755)
        (Path(tmp) / ("solution.js" if js else "solution.py")).write_text(code, encoding="utf-8")
        (Path(tmp) / ("solution.test.js" if js else "test_solution.py")).write_text(tests, encoding="utf-8")
        for f in Path(tmp).iterdir():
            os.chmod(f, 0o644)
        cmd = build_docker_command(tmp, name, language, image=settings.runner_image)
        timed_out = False
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)  # +8s allows container start-up
            out, err, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
            out, err, rc = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "", 124
        except FileNotFoundError:
            return {"passed": False, "exit_code": 127, "output": "Docker is not installed or not on PATH on this server.", "duration_ms": 0,
                    "tests_passed": 0, "tests_failed": 0, "blocked": True, "warning": WARNING}
    output = ((out or "") + "\n" + (err or "")).strip()[-5000:]
    if timed_out:
        output = f"Test execution exceeded the {timeout}-second limit and the container was killed.\n" + output
    if "Unable to find image" in output or "pull access denied" in output:
        return {"passed": False, "exit_code": 125, "output": f"Runner image '{settings.runner_image}' is missing. Build it with: docker build -f runner/Dockerfile -t {settings.runner_image} runner", "duration_ms": 0,
                "tests_passed": 0, "tests_failed": 0, "blocked": True, "warning": WARNING}
    import re
    if js:
        p = sum(int(n) for n in re.findall(r"^(?:#|ℹ)\s*pass (\d+)", output, re.M)); f = sum(int(n) for n in re.findall(r"^(?:#|ℹ)\s*fail (\d+)", output, re.M))
        passed = rc == 0 and f == 0 and p > 0
    else:
        c = parse_summary(output); p, f = c["passed"], c["failed"] + c["errors"]; passed = rc == 0
    return {"passed": passed, "exit_code": rc, "output": output, "duration_ms": round((time.perf_counter() - started) * 1000), "tests_passed": p,
            "tests_failed": f, "blocked": False, "timed_out": timed_out, "warning": WARNING}


_sem = None


async def run_docker_tests(language: str, code: str, tests: str) -> dict:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(2)
    async with _sem:
        return await asyncio.to_thread(_run, code, tests, language, settings.runner_timeout_seconds)
