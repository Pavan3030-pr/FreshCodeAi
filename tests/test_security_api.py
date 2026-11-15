"""Negative security tests: each attack here must FAIL."""
import dataclasses
import threading
import time

from fastapi.testclient import TestClient

import app.main as main
from app.api import deps, state
from app.config import settings
from app.services.db import Store

PW = "a sufficiently long phrase"


def fresh():
    state.configure(Store(":memory:"))
    return TestClient(main.app)


def signup(c, email="ada@example.com"):
    return c.post("/api/v1/auth/register", json={"email": email, "password": PW}).json()["csrf"]


def test_sql_injection_strings_are_treated_as_data():
    c = fresh(); csrf = signup(c)
    c.post("/api/v1/projects", json={"name": "ok"}, headers={"X-CSRF-Token": csrf})
    for evil in ("' OR 1=1 --", "'; DROP TABLE runs; --", "%' UNION SELECT password_hash FROM users --"):
        r = c.get("/api/v1/runs?q=" + evil.replace(" ", "%20").replace("'", "%27").replace(";", "%3B").replace("%'", "%25%27"))
        assert r.status_code == 200 and r.json()["runs"] == [], evil
        assert c.get("/api/v1/projects?q=" + evil.replace(" ", "%20").replace("'", "%27")).status_code == 200
    assert c.get("/api/v1/projects").json()["projects"][0]["name"] == "ok"  # tables intact
    r = c.post("/api/v1/projects", json={"name": "x'); DROP TABLE users; --"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201 and state.store.count_users() == 1


def test_stored_markup_is_returned_as_inert_json_text():
    c = fresh(); csrf = signup(c)
    payload = "<img src=x onerror=alert(1)>"
    p = c.post("/api/v1/projects", json={"name": payload, "description": payload}, headers={"X-CSRF-Token": csrf}).json()["project"]
    assert p["name"] == payload  # stored verbatim; the UI escapes on render (covered by lib/DOM tests and E2E)
    assert "application/json" in c.get("/api/v1/projects").headers["content-type"]


def test_request_id_header_is_sanitised():
    c = fresh()
    r = c.get("/api/health", headers={"X-Request-ID": "abc\r\nSet-Cookie: pwn=1"})
    rid = r.headers["x-request-id"]
    assert "\r" not in rid and "\n" not in rid and " " not in rid and ":" not in rid and len(rid) <= 32


def test_oversized_and_malformed_inputs_are_rejected():
    c = fresh(); csrf = signup(c)
    h = {"X-CSRF-Token": csrf}
    assert c.post("/api/v1/code", json={"task": "x" * 7000, "language": "python"}, headers=h).status_code == 422
    assert c.post("/api/v1/test", json={"code": "x" * 30000, "tests": "y"}, headers=h).status_code == 422
    assert c.post("/api/v1/verify", json={"text": "short"}, headers=h).status_code == 422
    assert c.post("/api/v1/auth/register", json={"email": "a" * 400 + "@example.com", "password": PW}).status_code == 422
    assert c.post("/api/v1/benchmark", json={"task": "Write a function please", "extra_tasks": ["x" * 20] * 9}, headers=h).status_code == 422


def test_forged_and_stale_session_cookies_are_rejected():
    c = fresh(); signup(c)
    other = TestClient(main.app)
    other.cookies["fc_session"] = "A" * 43
    assert other.get("/api/v1/auth/me").status_code == 401
    other.cookies["fc_session"] = "'; DROP TABLE sessions; --"
    assert other.get("/api/v1/auth/me").status_code == 401 and state.store.ping()


def test_session_is_rotated_on_every_login_no_fixation():
    c = fresh(); signup(c)
    first = c.cookies.get("fc_session")
    c2 = TestClient(main.app)
    c2.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PW})
    assert c2.cookies.get("fc_session") and c2.cookies.get("fc_session") != first
    c2.cookies["fc_session"] = "attacker-chosen-value"
    assert c2.get("/api/v1/auth/me").status_code == 401  # a pre-set cookie value is never accepted


def test_session_cookie_flags():
    captured = {}

    class R:
        def set_cookie(self, key, value, **kw):
            captured.update(kw, key=key)

    deps.set_session_cookie(R(), "tok")
    assert captured["httponly"] is True and captured["samesite"] == "lax" and captured["path"] == "/" and captured["key"] == "fc_session"
    assert captured["secure"] == settings.cookie_secure
    original = deps.settings
    deps.settings = dataclasses.replace(original, cookie_secure=True)
    try:
        deps.set_session_cookie(R(), "tok")
    finally:
        deps.settings = original
    assert captured["secure"] is True


def test_security_headers_present_on_errors_too():
    c = fresh()
    for r in (c.get("/api/v1/projects"), c.get("/does-not-exist")):
        assert r.headers["x-content-type-options"] == "nosniff" and "content-security-policy" in r.headers


def test_concurrent_authenticated_requests_do_not_lose_data_or_cross_users():
    state.configure(Store(":memory:"))
    users = []
    for i in range(6):
        c = TestClient(main.app)
        users.append((c, signup(c, f"user{i}@example.com")))
    errors, started = [], time.perf_counter()

    def work(idx):
        c, csrf = users[idx]
        try:
            for n in range(8):
                r = c.post("/api/v1/test", json={"code": "import os", "tests": "x"}, headers={"X-CSRF-Token": csrf})
                assert r.status_code == 200
                assert c.get("/api/v1/runs").status_code == 200
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(users))]
    [t.start() for t in threads]; [t.join() for t in threads]
    elapsed = time.perf_counter() - started
    assert not errors, errors[:2]
    for i, (c, _) in enumerate(users):
        runs = c.get("/api/v1/runs?limit=100").json()["runs"]
        assert len(runs) == 8, (i, len(runs))  # every write landed, only in its owner's history
    assert elapsed < 30, f"96 requests took {elapsed:.1f}s"
