"""Request helpers: client IP, session cookie handling, authentication + CSRF for routes."""
from fastapi import Request

from app.api import state
from app.config import settings
from app.core.errors import Forbidden

COOKIE = "fc_session"


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def session_token(request: Request):
    return request.cookies.get(COOKIE)


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=settings.session_ttl_hours * 3600, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_session(request: Request) -> dict:
    """Authenticate the cookie session and enforce CSRF on unsafe methods. Raises typed errors."""
    session = state.auth.authenticate(session_token(request))
    state.auth.check_csrf(session, request.method, request.headers.get("x-csrf-token"))
    request.state.user_id = session["user_id"]
    return session


def require_admin(session: dict) -> None:
    if session.get("role") != "admin":
        raise Forbidden("Administrator access required.")
