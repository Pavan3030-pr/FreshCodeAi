"""Runtime configuration. Every value comes from the environment (or .env)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at runtime
    def load_dotenv(*_a, **_k):
        return False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

APP_VERSION = "5.1.0"


def _clean(raw: str) -> str:
    """Drop inline comments ("VALUE  # note") and values that are only a comment."""
    raw = raw.strip()
    if raw.startswith("#"):
        return ""
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _env(name: str, default: str = "") -> str:
    return _clean(os.getenv(name, default))


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(_env(name, str(default)))
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


_APP_ENV = _env("APP_ENV", "development").lower()


@dataclass(frozen=True)
class Settings:
    bifrost_base_url: str = _env("BIFROST_BASE_URL", "http://localhost:4000/v1").rstrip("/")
    bifrost_api_key: str = _env("BIFROST_API_KEY")
    bifrost_model: str = _env("BIFROST_MODEL", "general")
    # Optional routing: a cheaper model for evidence assessment, and a fallback if the primary fails.
    bifrost_fast_model: str = _env("BIFROST_FAST_MODEL")
    bifrost_fallback_model: str = _env("BIFROST_FALLBACK_MODEL")
    price_in_per_mtok: float = _float("PRICE_INPUT_PER_MTOK", 0, 0, 1000)
    price_out_per_mtok: float = _float("PRICE_OUTPUT_PER_MTOK", 0, 0, 1000)
    tavily_api_key: str = _env("TAVILY_API_KEY")
    max_search_results: int = _int("MAX_SEARCH_RESULTS", 4, 1, 8)
    timeout_seconds: float = _float("REQUEST_TIMEOUT_SECONDS", 25, 3, 120)
    app_env: str = _APP_ENV
    # Cost / token controls
    max_output_tokens: int = _int("MAX_OUTPUT_TOKENS", 1800, 256, 8000)
    context_budget_tokens: int = _int("CONTEXT_BUDGET_TOKENS", 900, 200, 4000)
    cache_ttl_seconds: int = _int("CACHE_TTL_SECONDS", 900, 0, 86400)
    upstream_retries: int = _int("UPSTREAM_RETRIES", 2, 0, 5)
    # Abuse controls
    rate_limit_per_minute: int = _int("RATE_LIMIT_PER_MINUTE", 120, 1, 10000)
    heavy_rate_limit_per_minute: int = _int("HEAVY_RATE_LIMIT_PER_MINUTE", 20, 1, 1000)
    trust_proxy: bool = _bool("TRUST_PROXY", False)
    access_token: str = _env("APP_ACCESS_TOKEN")
    # Code execution is on by default for local development, off in production.
    enable_test_runner: bool = _bool("ENABLE_TEST_RUNNER", _APP_ENV != "production")
    runner_timeout_seconds: int = _int("RUNNER_TIMEOUT_SECONDS", 8, 2, 60)
    # Accounts and sessions
    allow_registration: bool = _bool("ALLOW_REGISTRATION", True)
    session_ttl_hours: int = _int("SESSION_TTL_HOURS", 12, 1, 720)       # sliding idle lifetime
    session_max_days: int = _int("SESSION_MAX_DAYS", 7, 1, 90)           # absolute lifetime
    cookie_secure: bool = _bool("COOKIE_SECURE", _APP_ENV == "production")
    login_max_attempts: int = _int("LOGIN_MAX_ATTEMPTS", 5, 1, 100)
    login_window_minutes: int = _int("LOGIN_WINDOW_MINUTES", 15, 1, 1440)
    daily_run_quota: int = _int("DAILY_RUN_QUOTA", 200, 1, 100000)       # per user, heavy runs per rolling 24h
    agent_timeout_seconds: int = _int("AGENT_TIMEOUT_SECONDS", 180, 10, 1800)
    # Code execution: off | local (AST policy + rlimits, NOT a sandbox) | docker (isolated container)
    runner_mode: str = _env("RUNNER_MODE", "").lower()
    runner_image: str = _env("RUNNER_IMAGE", "freshcode-runner:latest")
    # Persistence
    db_path: str = _env("DB_PATH", str(PROJECT_ROOT / "data" / "freshcode.db"))
    history_limit: int = _int("HISTORY_LIMIT", 500, 20, 5000)


settings = Settings()
