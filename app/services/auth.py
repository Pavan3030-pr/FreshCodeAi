"""Authentication, sessions, CSRF and quotas. Pure business logic: no HTTP types, no framework imports."""
from __future__ import annotations

import time
from typing import Callable, Optional

from app.core.errors import (AuthRequired, Conflict, CsrfFailed, Forbidden, InvalidCredentials, QuotaExceeded, TooManyAttempts,
                             ValidationFailed)
from app.core.security import (DUMMY_HASH, hash_password, new_token, normalize_email, safe_equal, token_hash, validate_password,
                               verify_password)
from app.services.db import Store
from app.services.ratelimit import SlidingWindowLimiter

HEAVY_KINDS = ("code", "verify", "benchmark", "test")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthService:
    def __init__(self, store: Store, settings, clock: Callable[[], float] = time.time):
        self.store, self.s, self.clock = store, settings, clock
        self._login_limiter = SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_minutes * 60, clock)

    # ---------- registration / login ----------
    def register(self, email: str, password: str, display_name: str = "", *, ip: str = "", user_agent: str = "", request_id: str = "") -> tuple[dict, str, dict]:
        if not self.s.allow_registration and self.store.count_users() > 0:
            raise Forbidden("Registration is closed on this deployment.", code="registration_closed")
        email = normalize_email(email)
        validate_password(password, email)
        if self.store.get_user_by_email(email):
            raise Conflict("An account with that email already exists.", code="email_taken")
        role = "admin" if self.store.count_users() == 0 else "user"  # the first account administers the deployment
        user = self.store.create_user(email, hash_password(password), display_name=display_name.strip(), role=role)
        self.store.add_audit("register", user_id=user["id"], detail=f"role={role}", ip=ip, request_id=request_id)
        token, session = self._new_session(user["id"], ip, user_agent)
        return user, token, session

    def login(self, email: str, password: str, *, ip: str = "", user_agent: str = "", request_id: str = "") -> tuple[dict, str, dict]:
        key = f"{normalize_email(email) if '@' in (email or '') else 'invalid'}|{ip}"
        ok, retry = self._login_limiter.check(key)
        if not ok:
            self.store.add_audit("login_throttled", detail=key.split("|")[0], ip=ip, request_id=request_id)
            raise TooManyAttempts(f"Too many sign-in attempts. Try again in {max(1, retry // 60)} minute(s).")
        try:
            email_n = normalize_email(email)
        except ValidationFailed:
            verify_password(password, DUMMY_HASH)
            raise InvalidCredentials("Incorrect email or password.")
        user = self.store.get_user_by_email(email_n, with_hash=True)
        valid = verify_password(password, user["password_hash"] if user else DUMMY_HASH)  # constant work whether or not the account exists
        if not (user and valid) or user["disabled"]:
            self.store.add_audit("login_failed", user_id=user["id"] if user else None, detail=email_n, ip=ip, request_id=request_id)
            raise InvalidCredentials("Incorrect email or password.")
        self.store.touch_login(user["id"])
        user.pop("password_hash", None)
        token, session = self._new_session(user["id"], ip, user_agent)
        self.store.add_audit("login", user_id=user["id"], ip=ip, request_id=request_id)
        return user, token, session

    def _new_session(self, user_id: int, ip: str, user_agent: str) -> tuple[str, dict]:
        token = new_token(32)
        session = self.store.create_session(user_id, token_hash(token), new_token(24), self.s.session_ttl_hours * 3600, ip=ip, user_agent=user_agent)
        return token, session

    # ---------- per-request authentication ----------
    def authenticate(self, token: Optional[str]) -> dict:
        if not token:
            raise AuthRequired("Sign in to continue.")
        sess = self.store.get_session(token_hash(token))
        now = self.clock()
        if not sess or sess["expires_at"] < now or sess["created_at"] + self.s.session_max_days * 86400 < now or sess["disabled"]:
            if sess:
                self.store.delete_session(token_hash(token))
            raise AuthRequired("Your session has expired. Sign in again.")
        if now - sess["last_seen_at"] > 60:  # sliding expiry, written at most once a minute
            new_exp = min(now + self.s.session_ttl_hours * 3600, sess["created_at"] + self.s.session_max_days * 86400)
            self.store.touch_session(sess["id"], new_exp)
        return sess

    @staticmethod
    def check_csrf(session: dict, method: str, supplied: Optional[str]) -> None:
        if method.upper() in SAFE_METHODS:
            return
        if not supplied or not safe_equal(supplied, session["csrf"]):
            raise CsrfFailed("Security token missing or invalid. Reload the page and try again.")

    def logout(self, token: Optional[str]) -> None:
        if token:
            self.store.delete_session(token_hash(token))

    # ---------- account ----------
    def change_password(self, session: dict, current: str, new: str, *, ip: str = "", request_id: str = "") -> int:
        user = self.store.get_user_secret(session["user_id"])
        if not user or not verify_password(current, user["password_hash"]):
            self.store.add_audit("password_change_failed", user_id=session["user_id"], ip=ip, request_id=request_id)
            raise InvalidCredentials("Current password is incorrect.")
        validate_password(new, user["email"])
        self.store.set_password(user["id"], hash_password(new))
        revoked = self.store.delete_user_sessions(user["id"], except_id=session["id"])
        self.store.add_audit("password_changed", user_id=user["id"], detail=f"revoked_sessions={revoked}", ip=ip, request_id=request_id)
        return revoked

    # ---------- quotas ----------
    def usage(self, user_id: int) -> dict:
        since = self.clock() - 86400
        used = self.store.count_runs_since(user_id, since, HEAVY_KINDS)
        limit = self.s.daily_run_quota
        return {"window": "rolling 24 hours", "runs_used": used, "runs_limit": limit, "runs_remaining": max(0, limit - used)}

    def enforce_quota(self, user_id: int) -> None:
        u = self.usage(user_id)
        if u["runs_remaining"] <= 0:
            raise QuotaExceeded(f"Daily run quota reached ({u['runs_limit']} runs in 24 hours).")

    def delete_account(self, session: dict, password: str, *, ip: str = "", request_id: str = "") -> None:
        user = self.store.get_user_secret(session["user_id"])
        if not user or not verify_password(password, user["password_hash"]):
            self.store.add_audit("account_delete_failed", user_id=session["user_id"], ip=ip, request_id=request_id)
            raise InvalidCredentials("Password is incorrect.")
        self.store.add_audit("account_deleted", detail=user["email"], ip=ip, request_id=request_id)  # kept anonymously for the operator
        self.store.delete_user(user["id"])
