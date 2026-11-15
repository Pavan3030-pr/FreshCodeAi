from types import SimpleNamespace

from app.core.errors import (AuthRequired, Conflict, CsrfFailed, Forbidden, InvalidCredentials, QuotaExceeded, TooManyAttempts, ValidationFailed)
from app.core.security import token_hash
from app.services.auth import AuthService
from app.services.db import Store

PW = "a sufficiently long phrase"


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def svc(**over):
    base = dict(allow_registration=True, session_ttl_hours=12, session_max_days=7, login_max_attempts=3, login_window_minutes=15, daily_run_quota=3)
    base.update(over)
    clock = Clock()
    return AuthService(Store(":memory:", clock=clock), SimpleNamespace(**base), clock), clock


def err(cls, fn, *a, **k):
    try:
        fn(*a, **k)
    except cls as e:
        return e
    raise AssertionError(f"expected {cls.__name__}")


def test_first_user_is_admin_later_users_are_not_and_hash_is_stored():
    a, _ = svc()
    u1, tok, sess = a.register("Ada@Example.com", PW, "Ada")
    u2, _, _ = a.register("bob@example.com", PW)
    assert u1["role"] == "admin" and u2["role"] == "user" and u1["email"] == "ada@example.com" and "password_hash" not in u1
    assert a.store.get_user_by_email("ada@example.com", with_hash=True)["password_hash"].startswith("scrypt$") and sess["csrf"]
    assert a.store.get_session(token_hash(tok)) is not None and a.store.get_session(tok) is None  # raw token is never stored


def test_registration_validation_and_duplicates_and_closed_mode():
    a, _ = svc()
    a.register("a@example.com", PW)
    err(Conflict, a.register, "A@example.com", PW)
    err(ValidationFailed, a.register, "b@example.com", "short")
    err(ValidationFailed, a.register, "not-an-email", PW)
    closed, _ = svc(allow_registration=False)
    closed.register("first@example.com", PW)  # bootstrapping the very first admin is still possible
    assert err(Forbidden, closed.register, "second@example.com", PW).code == "registration_closed"


def test_login_success_wrong_password_unknown_user_and_disabled_use_one_message():
    a, _ = svc(login_max_attempts=50)
    a.register("a@example.com", PW)
    user, token, _ = a.login("a@example.com", PW)
    assert user["email"] == "a@example.com" and a.authenticate(token)["user_id"] == user["id"]
    m1 = str(err(InvalidCredentials, a.login, "a@example.com", "wrong password here"))
    m2 = str(err(InvalidCredentials, a.login, "nobody@example.com", PW))
    m3 = str(err(InvalidCredentials, a.login, "garbage", PW))
    assert m1 == m2 == m3
    with a.store._tx() as c:
        c.execute("UPDATE users SET disabled=1 WHERE email='a@example.com'")
    err(InvalidCredentials, a.login, "a@example.com", PW)
    actions = [x["action"] for x in a.store.list_audit(all_users=True)]
    assert "login" in actions and actions.count("login_failed") >= 3


def test_login_throttling_per_email_and_ip():
    a, clock = svc(login_max_attempts=3)
    a.register("a@example.com", PW)
    for _ in range(3):
        err(InvalidCredentials, a.login, "a@example.com", "bad password!!", ip="1.2.3.4")
    err(TooManyAttempts, a.login, "a@example.com", PW, ip="1.2.3.4")  # even the right password is refused while throttled
    a.login("a@example.com", PW, ip="5.6.7.8")  # a different source is not blocked
    clock.t += 16 * 60
    a.login("a@example.com", PW, ip="1.2.3.4")


def test_session_expiry_sliding_and_absolute_limits():
    a, clock = svc()
    _, token, _ = a.register("a@example.com", PW)
    err(AuthRequired, a.authenticate, None)
    err(AuthRequired, a.authenticate, "forged-token")
    clock.t += 13 * 3600
    err(AuthRequired, a.authenticate, token)  # idle expiry
    assert a.store.get_session(token_hash(token)) is None  # and the dead session is removed
    _, token2, sess2 = a.login("a@example.com", PW)
    for _ in range(20):  # keep it alive by activity every 11 hours...
        clock.t += 11 * 3600
        try:
            a.authenticate(token2)
        except AuthRequired:
            break
    assert clock.t - sess2["created_at"] <= 8 * 86400
    err(AuthRequired, a.authenticate, token2)  # ...the absolute 7-day cap still applies


def test_csrf_required_for_unsafe_methods_only():
    a, _ = svc()
    _, token, sess = a.register("a@example.com", PW)
    a.check_csrf(sess, "GET", None)
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        err(CsrfFailed, a.check_csrf, sess, m, None)
        err(CsrfFailed, a.check_csrf, sess, m, "wrong")
        a.check_csrf(sess, m, sess["csrf"])


def test_logout_invalidates_session():
    a, _ = svc()
    _, token, _ = a.register("a@example.com", PW)
    a.logout(token)
    err(AuthRequired, a.authenticate, token)
    a.logout(None)


def test_change_password_revokes_other_sessions_and_audits():
    a, _ = svc()
    _, t1, s1 = a.register("a@example.com", PW)
    _, t2, _ = a.login("a@example.com", PW)
    err(InvalidCredentials, a.change_password, s1, "wrong current pw", "another long phrase!")
    err(ValidationFailed, a.change_password, s1, PW, "short")
    assert a.change_password(s1, PW, "another long phrase!") == 1
    a.authenticate(t1)
    err(AuthRequired, a.authenticate, t2)
    a.login("a@example.com", "another long phrase!")
    err(InvalidCredentials, a.login, "a@example.com", PW)


def test_quota_counts_heavy_runs_per_user_in_a_rolling_window():
    a, clock = svc(daily_run_quota=3)
    u1, _, _ = a.register("a@example.com", PW); u2, _, _ = a.register("b@example.com", PW)
    for i in range(3):
        a.enforce_quota(u1["id"])
        a.store.add_run("code", f"t{i}", user_id=u1["id"])
    a.store.add_run("demo", "demo does not count", user_id=u1["id"])
    err(QuotaExceeded, a.enforce_quota, u1["id"])
    a.enforce_quota(u2["id"])  # another user is unaffected
    assert a.usage(u1["id"]) == {"window": "rolling 24 hours", "runs_used": 3, "runs_limit": 3, "runs_remaining": 0}
    clock.t += 90000
    assert a.usage(u1["id"])["runs_used"] == 0  # the 24-hour window has rolled past those runs
    a.enforce_quota(u1["id"])
