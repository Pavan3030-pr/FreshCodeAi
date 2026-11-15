"""Composition root: middleware, error mapping, static files and page routes. Business logic lives in app/services,
HTTP routes in app/api."""
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import state, system, v1
from app.api.deps import client_ip
from app.config import APP_VERSION, settings
from app.core import config_check, logging as app_logging
from app.core.errors import AppError
from app.core.security import redact
from app.services.ratelimit import SlidingWindowLimiter

app_logging.configure([settings.bifrost_api_key, settings.tavily_api_key])
log = logging.getLogger("freshcode")
for _level, _id, _msg in config_check.check(settings):
    if _level != "OK":
        log.warning("config %s: %s", _id, _msg)

BASE = Path(__file__).resolve().parent.parent
limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)
heavy_limiter = SlidingWindowLimiter(settings.heavy_rate_limit_per_minute)
HEAVY = {"/api/v1/code", "/api/v1/code/stream", "/api/v1/verify", "/api/v1/benchmark", "/api/v1/test", "/api/v1/demo",
         "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/password", "/api/v1/auth/delete-account"}

app = FastAPI(title="FreshCode AI", version=APP_VERSION, openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url=None,
              description="AI engineering reliability platform: token-efficient agent, live freshness verification, reproducible benchmarks.")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(system.router)
app.include_router(v1.router)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


def _error(status: int, code: str, message: str, headers=None) -> JSONResponse:
    return JSONResponse({"detail": message, "error": {"code": code, "message": message}}, status_code=status, headers=headers)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return _error(exc.status, exc.code, str(exc))


@app.middleware("http")
async def guard(request: Request, call_next):
    supplied = re.sub(r"[^A-Za-z0-9._-]", "", request.headers.get("x-request-id", ""))[:32]  # never echo attacker-controlled characters
    rid = supplied or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    path = request.url.path
    started = time.perf_counter()
    if path.startswith("/api/") and path != "/api/health":
        ip = client_ip(request)
        ok, retry = limiter.check(ip)
        if ok and path in HEAVY and request.method == "POST":
            ok, retry = heavy_limiter.check(ip)
        if not ok:
            return _error(429, "rate_limited", f"Rate limit reached. Try again in {retry}s.", {"Retry-After": str(retry), "X-Request-ID": rid})
    try:
        response = await call_next(request)
    except Exception as exc:  # never leak internals
        log.error("unhandled error on %s %s: %s", request.method, path, redact(repr(exc), [settings.bifrost_api_key, settings.tavily_api_key]))
        response = _error(500, "internal_error", "Something went wrong on our side. The error was logged.")
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if not path.startswith("/api/v1/docs") and not path.startswith("/api/v1/openapi"):
        response.headers["Content-Security-Policy"] = CSP
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    log.info("%s %s %s %dms rid=%s", request.method, path, response.status_code, (time.perf_counter() - started) * 1000, rid)
    return response


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((BASE / "static" / name).read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def landing():
    return _page("landing.html")


@app.api_route("/login", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def login_page():
    return _page("login.html")


@app.get("/signup")
async def signup_page():
    return RedirectResponse("/login#signup")


@app.api_route("/app", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def workspace():
    return _page("index.html")
