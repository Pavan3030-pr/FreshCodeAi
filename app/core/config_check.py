"""Deployment readiness checks (pure). Used at startup (warnings) and by scripts/deploycheck.py (exit code)."""
from __future__ import annotations

from urllib.parse import urlparse

from app.core.errors import ValidationFailed
from app.core.security import validate_outbound_url


def check(settings, *, resolver=None) -> list[tuple[str, str, str]]:
    """Return [(level, id, message)] where level is FAIL | WARN | OK."""
    out: list[tuple[str, str, str]] = []
    prod = settings.app_env == "production"
    add = lambda lvl, cid, msg: out.append((lvl, cid, msg))

    add("OK" if settings.bifrost_api_key else "WARN", "bifrost_key", "Bifrost key configured" if settings.bifrost_api_key else "BIFROST_API_KEY is not set: live generation and benchmarks are unavailable")
    add("OK" if settings.tavily_api_key else "WARN", "tavily_key", "Tavily key configured" if settings.tavily_api_key else "TAVILY_API_KEY is not set: live freshness verification is unavailable")

    url = settings.bifrost_base_url
    try:
        kw = {"allow_private": not prod}
        if resolver:
            kw["resolver"] = resolver
        validate_outbound_url(url, **kw)
        if prod and urlparse(url).scheme != "https":
            add("WARN", "bifrost_tls", "BIFROST_BASE_URL is not https in production")
        else:
            add("OK", "bifrost_url", "Bifrost URL passes outbound-URL validation" + ("" if prod else " (private addresses allowed outside production)"))
    except ValidationFailed as exc:
        add("FAIL" if prod else "WARN", "bifrost_url", f"BIFROST_BASE_URL rejected: {exc}")

    if prod:
        add("OK" if settings.cookie_secure else "FAIL", "cookie_secure", "Session cookies are Secure" if settings.cookie_secure else "COOKIE_SECURE must be on in production (HTTPS only)")
        add("OK" if settings.trust_proxy else "WARN", "trust_proxy", "TRUST_PROXY on" if settings.trust_proxy else "TRUST_PROXY is off: behind a reverse proxy every client shares one IP for rate limits")
        mode = (settings.runner_mode or "").lower() or ("local" if settings.enable_test_runner else "off")
        add({"docker": "OK", "off": "OK", "local": "FAIL"}.get(mode, "WARN"), "runner", {"docker": "Code runs in isolated containers", "off": "Code execution is disabled", "local": "The local runner is NOT a sandbox: do not enable it for public traffic (use RUNNER_MODE=docker or off)"}.get(mode, f"Unknown RUNNER_MODE {mode!r}"))
        add("OK" if not settings.db_path.startswith("/tmp") else "WARN", "db_path", "Database path is not in /tmp" if not settings.db_path.startswith("/tmp") else "DB_PATH is under /tmp: data is lost on restart (mount a persistent volume)")
        add("OK" if not settings.allow_registration else "WARN", "registration", "Registration is closed" if not settings.allow_registration else "Open registration: anyone can create an account (set ALLOW_REGISTRATION=0 after creating your admin)")
    else:
        add("OK", "environment", f"APP_ENV={settings.app_env}: production-only checks skipped")
    add("OK" if settings.daily_run_quota <= 1000 else "WARN", "quota", f"Per-user daily run quota is {settings.daily_run_quota}")
    return out


def exit_code(results) -> int:
    return 1 if any(level == "FAIL" for level, _, _ in results) else 0
