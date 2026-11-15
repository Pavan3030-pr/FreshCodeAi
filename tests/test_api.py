"""HTTP-level tests of API v1. Run against real FastAPI/httpx in CI; against a small emulator in the offline sandbox."""
import json

from fastapi.testclient import TestClient

import app.main as main
from app.api import state
from app.config import APP_VERSION, settings
from app.services.db import Store
from app.services.ratelimit import SlidingWindowLimiter

PW = "a sufficiently long phrase"


def fresh(**settings_over):
    import dataclasses
    state.configure(Store(":memory:"), dataclasses.replace(settings, **settings_over) if settings_over else None)
    return TestClient(main.app)


def signup(client, email="ada@example.com", pw=PW):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": pw, "display_name": email.split("@")[0]})
    assert r.status_code == 201, r.text
    return r.json()["csrf"]


def H(csrf):
    return {"X-CSRF-Token": csrf}


def code_body(**kw):
    return {"task": "Write a Python function that adds two numbers", "language": "python", "verify_facts": False, **kw}


# ---------------- public surface ----------------
def test_health_is_public_and_minimal():
    c = fresh()
    h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["version"] == APP_VERSION
    for leaked in ("bifrost_host", "bifrost_model", "upstream", "cache", "bifrost_base_url", "tavily_configured"):
        assert leaked not in h


def test_ready_reports_database_state():
    c = fresh()
    r = c.get("/api/v1/ready").json()
    assert r["ready"] is True and r["database"] == "ok" and r["schema_version"] >= 2


def test_pages_and_security_headers():
    c = fresh()
    for path, needle in (("/", "Lean tokens."), ("/login", "Sign in"), ("/app", 'id="view-overview"')):
        r = c.get(path)
        assert r.status_code == 200 and needle in r.text, path
    r = c.get("/")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["x-request-id"]
    assert "script-src 'self'" in h["content-security-policy"] and "object-src 'none'" in h["content-security-policy"]
    assert c.get("/api/health").headers["cache-control"] == "no-store"
    for f in ("theme.js", "app.js", "lib.js", "auth.js", "account.js", "style.css", "landing.css", "landing.js"):
        assert c.get(f"/static/{f}").status_code == 200, f
    assert c.get("/static/../app/config.py").status_code in (404, 403)


def test_eval_and_demo_are_public():
    c = fresh()
    assert c.get("/api/v1/eval").json()["drift_detector"]["cases"] >= 15
    d = c.post("/api/v1/demo", json={}).json()
    assert d["mode"] == "demo" and "run_id" not in d  # guests are not persisted


# ---------------- authentication ----------------
def test_protected_endpoints_require_a_session():
    c = fresh()
    bodies = {"/api/v1/code": code_body(), "/api/v1/verify": {"text": "Spring Boot 3.4 is the latest stable."}, "/api/v1/test": {"code": "x=1", "tests": "y"}}
    for method, path in (("GET", "/api/v1/auth/me"), ("GET", "/api/v1/projects"), ("GET", "/api/v1/runs"), ("GET", "/api/v1/stats"), ("GET", "/api/v1/usage"),
                         ("GET", "/api/v1/audit"), ("GET", "/api/v1/system"), ("POST", "/api/v1/code"), ("POST", "/api/v1/verify"), ("POST", "/api/v1/test"),
                         ("GET", "/api/v1/runs/export.csv"), ("DELETE", "/api/v1/runs")):
        r = c.request(method, path, json=bodies.get(path))
        assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required", (method, path, r.status_code)


def test_register_login_logout_journey_and_cookie_flags():
    c = fresh()
    r = c.post("/api/v1/auth/register", json={"email": "Ada@Example.com", "password": PW, "display_name": "Ada"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "admin" and r.json()["user"]["email"] == "ada@example.com"
    cookie = r.headers.get("set-cookie", "")
    if cookie:  # header casing/format differs between clients; assert flags when visible
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    me = c.get("/api/v1/auth/me").json()
    assert me["user"]["email"] == "ada@example.com" and me["usage"]["runs_remaining"] == settings.daily_run_quota
    csrf = me["csrf"]
    assert c.post("/api/v1/auth/logout", json={}).status_code == 403  # CSRF required even for logout
    assert c.post("/api/v1/auth/logout", json={}, headers=H(csrf)).status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401
    r2 = c.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PW})
    assert r2.status_code == 200 and c.get("/api/v1/auth/me").status_code == 200


def test_login_errors_are_uniform_and_registration_validates():
    c = fresh()
    signup(c)
    bad = TestClient(main.app)
    m1 = bad.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong password!!"}).json()["detail"]
    m2 = bad.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": PW}).json()["detail"]
    assert m1 == m2 == "Incorrect email or password."
    assert bad.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}).status_code == 422
    assert bad.post("/api/v1/auth/register", json={"email": "ada@example.com", "password": PW}).status_code == 409
    assert bad.post("/api/v1/auth/register", json={"email": "nope", "password": PW}).status_code == 422
    assert bad.post("/api/v1/auth/login", json={"email": "ada@example.com"}).status_code == 422  # missing field


def test_login_throttle_returns_429():
    c = fresh(login_max_attempts=3)
    signup(c)
    other = TestClient(main.app)
    codes = [other.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "bad password!!"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_registration_can_be_closed_after_the_first_admin():
    c = fresh(allow_registration=False)
    signup(c)  # bootstrap admin
    r = TestClient(main.app).post("/api/v1/auth/register", json={"email": "b@example.com", "password": PW})
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_closed"


def test_csrf_is_enforced_on_every_state_changing_route():
    c = fresh()
    csrf = signup(c)
    for method, path, body in (("POST", "/api/v1/projects", {"name": "p"}), ("POST", "/api/v1/code", code_body()), ("POST", "/api/v1/test", {"code": "x=1", "tests": "y"}),
                               ("DELETE", "/api/v1/runs", None), ("PATCH", "/api/v1/auth/profile", {"display_name": "x"}), ("POST", "/api/v1/auth/password", {"current_password": PW, "new_password": "another long phrase"})):
        no = c.request(method, path, json=body)
        bad = c.request(method, path, json=body, headers=H("forged"))
        assert no.status_code == 403 and bad.status_code == 403 and no.json()["error"]["code"] == "csrf_failed", (method, path)
    assert c.post("/api/v1/projects", json={"name": "p"}, headers=H(csrf)).status_code == 201
    assert c.get("/api/v1/projects").status_code == 200  # safe methods need no token


# ---------------- projects + isolation ----------------
def test_project_crud_validation_and_conflicts():
    c = fresh()
    csrf = signup(c)
    r = c.post("/api/v1/projects", json={"name": "Gateway", "language": "java", "context_budget": 600, "description": "d"}, headers=H(csrf))
    p = r.json()["project"]
    assert r.status_code == 201 and p["language"] == "java" and p["run_count"] == 0
    assert c.post("/api/v1/projects", json={"name": "Gateway"}, headers=H(csrf)).status_code == 409
    assert c.post("/api/v1/projects", json={"name": ""}, headers=H(csrf)).status_code == 422
    assert c.post("/api/v1/projects", json={"name": "x", "language": "py; rm -rf /"}, headers=H(csrf)).status_code == 422
    assert c.post("/api/v1/projects", json={"name": "x", "context_budget": 99999}, headers=H(csrf)).status_code == 422
    u = c.patch(f"/api/v1/projects/{p['id']}", json={"name": "Renamed", "archived": True}, headers=H(csrf)).json()["project"]
    assert u["name"] == "Renamed" and u["archived"] is True
    assert c.get("/api/v1/projects").json()["projects"] == []
    assert len(c.get("/api/v1/projects?include_archived=true").json()["projects"]) == 1
    assert c.get("/api/v1/projects?include_archived=true&q=Rena").json()["projects"][0]["id"] == p["id"]
    assert c.delete(f"/api/v1/projects/{p['id']}", headers=H(csrf)).status_code == 200
    assert c.get(f"/api/v1/projects/{p['id']}").status_code == 404


def test_users_cannot_see_or_touch_each_others_data():
    a = fresh()
    csrf_a = signup(a, "a@example.com")
    b = TestClient(main.app)
    csrf_b = signup(b, "b@example.com")
    pa = a.post("/api/v1/projects", json={"name": "A-private"}, headers=H(csrf_a)).json()["project"]
    run_a = a.post("/api/v1/test", json={"code": "import os", "tests": "x", "project_id": pa["id"]}, headers=H(csrf_a)).json()["run_id"]
    # B cannot read, modify, delete, or attach runs to A's project
    assert b.get("/api/v1/projects").json()["projects"] == []
    assert b.get(f"/api/v1/projects/{pa['id']}").status_code == 404
    assert b.patch(f"/api/v1/projects/{pa['id']}", json={"name": "hijack"}, headers=H(csrf_b)).status_code == 404
    assert b.delete(f"/api/v1/projects/{pa['id']}", headers=H(csrf_b)).status_code == 404
    assert b.post("/api/v1/test", json={"code": "x=1", "tests": "y", "project_id": pa["id"]}, headers=H(csrf_b)).status_code == 404
    assert b.get(f"/api/v1/runs/{run_a}").status_code == 404 and b.get(f"/api/v1/runs/{run_a}/report.md").status_code == 404
    assert b.get("/api/v1/runs").json()["runs"] == [] and b.get("/api/v1/stats").json()["total_runs"] == 0
    assert "A-private" not in b.get("/api/v1/runs/export.csv").text
    assert b.delete("/api/v1/runs", headers=H(csrf_b)).json()["deleted"] == 0
    assert len(a.get("/api/v1/runs").json()["runs"]) == 1  # B's clear did not touch A
    assert a.get(f"/api/v1/projects/{pa['id']}").json()["project"]["run_count"] == 1


# ---------------- agent, runs, reports ----------------
def test_agent_stream_requires_auth_and_returns_trace():
    c = fresh()
    assert c.post("/api/v1/code/stream", json=code_body()).status_code == 401
    csrf = signup(c)
    r = c.post("/api/v1/code/stream", json=code_body(), headers=H(csrf))
    assert r.status_code == 200 and "event: progress" in r.text and "event: result" in r.text
    payload = json.loads(r.text.split("event: result\ndata: ", 1)[1].split("\n", 1)[0])
    assert [s["name"] for s in payload["trace"]["spans"]][:2] == ["research", "compress"] and payload["run_id"]
    assert c.post("/api/v1/code", json={"task": "short", "language": "python"}, headers=H(csrf)).status_code == 422
    assert c.post("/api/v1/code", json=code_body(language="py; rm"), headers=H(csrf)).status_code == 422


def test_runs_search_filter_export_and_reports():
    c = fresh()
    csrf = signup(c)
    c.post("/api/v1/code", json=code_body(), headers=H(csrf))
    c.post("/api/v1/test", json={"code": "import os", "tests": "x"}, headers=H(csrf))
    c.post("/api/v1/demo", json={}, headers=H(csrf))
    runs = c.get("/api/v1/runs").json()["runs"]
    assert {r["kind"] for r in runs} == {"code", "test", "demo"}
    assert [r["kind"] for r in c.get("/api/v1/runs?kind=test").json()["runs"]] == ["test"]
    assert c.get("/api/v1/runs?q=adds").json()["runs"][0]["kind"] == "code"
    assert c.get("/api/v1/runs?status=setup_required").json()["runs"][0]["kind"] == "code"
    assert [r["kind"] for r in c.get("/api/v1/runs?status=failed&kind=test").json()["runs"]] == ["test"]
    csv_r = c.get("/api/v1/runs/export.csv")
    assert csv_r.status_code == 200 and csv_r.text.startswith("id,created_at,kind") and "text/csv" in csv_r.headers["content-type"]
    rid = runs[-1]["id"]
    md = c.get(f"/api/v1/runs/{rid}/report.md")
    assert md.status_code == 200 and "# FreshCode report" in md.text and "text/markdown" in md.headers["content-type"]
    assert c.get(f"/api/v1/runs/{rid}/benchmark.csv").status_code == 404  # not a benchmark run
    assert c.get("/api/v1/runs/999999").status_code == 404


def test_test_endpoint_blocks_malicious_code_and_validates_language():
    c = fresh()
    csrf = signup(c)
    for lang, code in (("python", "import os\nos.system('id')"), ("javascript", "require('child_process')")):
        r = c.post("/api/v1/test", json={"language": lang, "code": code, "tests": "x"}, headers=H(csrf))
        assert r.status_code == 200 and r.json()["blocked"] is True
    assert c.post("/api/v1/test", json={"language": "ruby", "code": "x", "tests": "y"}, headers=H(csrf)).status_code == 422


def test_usage_quota_blocks_with_429_and_is_per_user():
    c = fresh(daily_run_quota=2)
    csrf = signup(c)
    for _ in range(2):
        assert c.post("/api/v1/test", json={"code": "import os", "tests": "x"}, headers=H(csrf)).status_code == 200
    r = c.post("/api/v1/test", json={"code": "import os", "tests": "x"}, headers=H(csrf))
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    u = c.get("/api/v1/usage").json()
    assert u["quota"]["runs_used"] == 2 and u["quota"]["runs_remaining"] == 0 and "totals" in u
    other = TestClient(main.app)
    csrf2 = signup(other, "b@example.com")
    assert other.post("/api/v1/test", json={"code": "import os", "tests": "x"}, headers=H(csrf2)).status_code == 200


def test_rate_limit_returns_429_with_retry_after():
    c = fresh()
    original = main.heavy_limiter
    main.heavy_limiter = SlidingWindowLimiter(1)
    try:
        c.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
        r = c.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
    finally:
        main.heavy_limiter = original
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["error"]["code"] == "rate_limited"


# ---------------- account, sessions, audit ----------------
def test_password_change_revokes_other_sessions():
    a = fresh()
    csrf = signup(a)
    b = TestClient(main.app)
    b.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PW})
    assert b.get("/api/v1/auth/me").status_code == 200
    assert a.post("/api/v1/auth/password", json={"current_password": "wrong password", "new_password": "another long phrase"}, headers=H(csrf)).status_code == 401
    r = a.post("/api/v1/auth/password", json={"current_password": PW, "new_password": "another long phrase"}, headers=H(csrf))
    assert r.status_code == 200 and r.json()["revoked_sessions"] == 1
    assert a.get("/api/v1/auth/me").status_code == 200 and b.get("/api/v1/auth/me").status_code == 401


def test_session_list_revoke_and_isolation():
    a = fresh()
    csrf = signup(a)
    b = TestClient(main.app)
    csrf_b = b.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PW}).json()["csrf"]
    sess = a.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(sess) == 2 and sum(1 for s in sess if s["current"]) == 1
    other = [s for s in sess if not s["current"]][0]
    stranger = TestClient(main.app)
    sc = signup(stranger, "z@example.com")
    assert stranger.delete(f"/api/v1/auth/sessions/{other['id']}", headers=H(sc)).status_code == 404  # cannot revoke someone else's
    assert a.delete(f"/api/v1/auth/sessions/{other['id']}", headers=H(csrf)).status_code == 200
    assert b.get("/api/v1/auth/me").status_code == 401


def test_audit_trail_is_scoped_and_admin_can_see_all():
    a = fresh()
    csrf = signup(a, "admin@example.com")
    b = TestClient(main.app)
    csrf_b = signup(b, "user@example.com")
    a.post("/api/v1/projects", json={"name": "p"}, headers=H(csrf))
    mine = a.get("/api/v1/audit").json()["events"]
    assert {e["action"] for e in mine} >= {"register", "project_created"} and all(e["email"] == "admin@example.com" for e in mine)
    theirs = b.get("/api/v1/audit").json()["events"]
    assert all(e["email"] == "user@example.com" for e in theirs)
    assert b.get("/api/v1/audit?scope=all").status_code == 403
    allv = a.get("/api/v1/audit?scope=all").json()["events"]
    assert {e["email"] for e in allv} >= {"admin@example.com", "user@example.com"}


def test_delete_account_removes_data_and_ends_session():
    c = fresh()
    csrf = signup(c)
    c.post("/api/v1/projects", json={"name": "p"}, headers=H(csrf))
    assert c.post("/api/v1/auth/delete-account", json={"password": "wrong password"}, headers=H(csrf)).status_code == 401
    assert c.post("/api/v1/auth/delete-account", json={"password": PW}, headers=H(csrf)).status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PW}).status_code == 401
    assert state.store.count_users() == 0 and state.store.list_projects(1, include_archived=True) == []


def test_system_endpoint_needs_auth_and_exposes_runner_isolation_status():
    c = fresh()
    csrf = signup(c)
    s = c.get("/api/v1/system").json()
    assert s["version"] == APP_VERSION and "runner_isolated" in s and s["database"]["engine"] == "sqlite" and "bifrost_api_key" not in json.dumps(s)


def test_unhandled_errors_do_not_leak_internals():
    c = fresh()
    csrf = signup(c)
    original = state.store.list_projects

    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail /etc/passwd")

    state.store.list_projects = boom
    try:
        r = c.get("/api/v1/projects")
    finally:
        state.store.list_projects = original
    assert r.status_code == 500 and "secret-internal-detail" not in r.text and r.json()["error"]["code"] == "internal_error"
