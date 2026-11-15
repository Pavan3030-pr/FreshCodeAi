"""Run before a demo: `python scripts/preflight.py`. Boots the real app in-process (temp database) and walks the primary journey."""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "preflight.db")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000"); os.environ.setdefault("HEAVY_RATE_LIMIT_PER_MINUTE", "100000")
os.environ["APP_ENV"] = "development"
results = []


def check(name, fn):
    try:
        detail = fn()
        if isinstance(detail, tuple) and detail[0] == "WARN":
            results.append(("warn", name, detail[1]))
        else:
            results.append((True, name, detail or ""))
    except Exception as exc:
        results.append((False, name, f"{type(exc).__name__}: {exc}"))


def deps():
    missing = [m for m in ("fastapi", "httpx", "pydantic", "uvicorn", "pytest") if importlib.util.find_spec(m) is None]
    if missing:
        raise RuntimeError("missing packages: " + ", ".join(missing) + "  ->  pip install -r requirements.txt")
    return f"python {sys.version.split()[0]}"


check("dependencies installed", deps)
if results[0][0] is True:
    from fastapi.testclient import TestClient
    import app.main as main
    c = TestClient(main.app)
    PW = "preflight long passphrase"

    def must(r, code=200):
        assert r.status_code == code, f"{r.request.method if hasattr(r, 'request') else ''} -> HTTP {r.status_code}: {r.text[:160]}"
        return r

    check("landing, login and app pages", lambda: [must(c.get(p)) for p in ("/", "/login", "/app")] and "ok")
    check("static assets", lambda: [must(c.get(f"/static/{f}")) for f in ("app.js", "account.js", "auth.js", "theme.js", "style.css")] and "ok")
    check("public health + readiness", lambda: f"ready={must(c.get('/api/v1/ready')).json()['ready']}")
    check("security headers", lambda: "CSP present" if "script-src 'self'" in c.get("/").headers.get("content-security-policy", "") else (_ for _ in ()).throw(AssertionError("no CSP")))
    check("API refuses anonymous access", lambda: must(c.get("/api/v1/projects"), 401) and "401")
    csrf = {}

    def register():
        r = must(c.post("/api/v1/auth/register", json={"email": "preflight@example.com", "password": PW}), 201)
        csrf["t"] = r.json()["csrf"]
        return "first account is admin" if r.json()["user"]["role"] == "admin" else "registered"

    check("register and sign in", register)
    H = lambda: {"X-CSRF-Token": csrf["t"]}
    check("CSRF protection active", lambda: must(c.post("/api/v1/projects", json={"name": "x"}), 403) and "403 without token")
    check("create a project", lambda: must(c.post("/api/v1/projects", json={"name": "Preflight"}, headers=H()), 201) and "ok")
    check("offline self-check", lambda: f"drift accuracy {must(c.get('/api/v1/eval')).json()['drift_detector']['accuracy']}%")

    def demo():
        t = must(c.post("/api/v1/demo", json={}, headers=H())).json()["tests"]
        assert t["passed"], "demo tests failed:\n" + t["output"]
        return f"{t['tests_passed']} real tests passed in {t['duration_ms']} ms"

    check("judge demo executes real pytest", demo)

    def stream():
        r = must(c.post("/api/v1/code/stream", json={"task": "Write a Python function that adds two numbers", "language": "python", "verify_facts": False}, headers=H()))
        assert "event: progress" in r.text
        if "event: result" in r.text:
            return "SSE ok (result received)"
        if "event: error" in r.text:
            msg = r.text.split("event: error\ndata: ", 1)[1].split("\n", 1)[0]
            return ("WARN", "stream works but the live model call failed: " + msg[:160] + "  -> check BIFROST_BASE_URL and that your gateway is running")
        raise AssertionError("stream ended without result or error")

    check("agent SSE stream", stream)
    check("history saved and exportable", lambda: f"{len(must(c.get('/api/v1/runs')).json()['runs'])} run(s), csv {len(must(c.get('/api/v1/runs/export.csv')).text)} bytes")
    check("runner blocks unsafe code", lambda: must(c.post("/api/v1/test", json={"code": "import os", "tests": "def test_a(): pass"}, headers=H())).json()["blocked"] or (_ for _ in ()).throw(AssertionError("not blocked")))
    check("audit trail recorded", lambda: f"{len(must(c.get('/api/v1/audit')).json()['events'])} event(s)")
    check("sign out ends the session", lambda: (must(c.post("/api/v1/auth/logout", json={}, headers=H())), must(c.get("/api/v1/auth/me"), 401)) and "ok")
    from app.config import settings
    results.append((True, "live services", f"Bifrost {'configured' if settings.bifrost_api_key else 'NOT configured'} · Tavily {'configured' if settings.tavily_api_key else 'NOT configured'} (run scripts/live_check.py to verify them)"))

w = max(len(n) for _, n, _ in results)
for ok, name, detail in results:
    print(f"{'WARN' if ok == 'warn' else 'PASS' if ok else 'FAIL'}  {name.ljust(w)}  {detail}")
failed = [r for r in results if r[0] is False]
warned = [r for r in results if r[0] == "warn"]
print(f"\n{len(results) - len(failed) - len(warned)}/{len(results)} checks passed, {len(warned)} warning(s)")
sys.exit(1 if failed else 0)
