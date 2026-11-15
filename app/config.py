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


def _int(name: str, default: int, min_val: int = None, max_val: int = None) -> int:
    raw = os.getenv(name, None)
    if raw is None or _clean(raw) == "":
        return default
    try:
        val = int(_clean(raw))
    except ValueError:
        return default
    if min_val is not None and val < min_val:
        return min_val
    if max_val is not None and val > max_val:
        return max_val
    return val


def _float(name: str, default: float, min_val: float = None, max_val: float = None) -> float:
    raw = os.getenv(name, None)
    if raw is None or _clean(raw) == "":
        return default
    try:
        val = float(_clean(raw))
    except ValueError:
        return default
    if min_val is not None and val < min_val:
        return min_val
    if max_val is not None and val > max_val:
        return max_val
    return val


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, None)
    if raw is None or _clean(raw) == "":
        return default
    cleaned = _clean(raw).lower()
    if cleaned in ("true", "1", "yes", "on"):
        return True
    if cleaned in ("false", "0", "no", "off"):
        return False
    return default


_APP_ENV = _env("APP_ENV", "development").lower()


def _normalize_bifrost_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return "https://api.groq.com/openai/v1"
    if "groq.com" in url and not url.endswith("/openai/v1"):
        return "https://api.groq.com/openai/v1"
    return url


@dataclass(frozen=True)
class Settings:
    app_name: str = "FreshCodeAi"
    app_version: str = APP_VERSION
    environment: str = _APP_ENV
    log_level: str = _env("LOG_LEVEL", "INFO")
    secret_key: str = _env("SECRET_KEY", "dev-secret-key")
    cors_origins: str = _env("CORS_ORIGINS", "*")
    bifrost_base_url: str = _normalize_bifrost_base_url(_env("BIFROST_BASE_URL", "https://api.groq.com/openai/v1"))
    bifrost_api_key: str = _env("BIFROST_API_KEY")
    bifrost_model: str = _env("BIFROST_MODEL", "general")
    bifrost_fast_model: str = _env("BIFROST_FAST_MODEL")
    bifrost_fallback_model: str = _env("BIFROST_FALLBACK_MODEL")
    bifrost_timeout: int = _int("BIFROST_TIMEOUT", 30, 5, 300)
    price_in_per_mtok: float = _float("PRICE_INPUT_PER_MTOK", 0, 0, 1000)
    price_out_per_mtok: float = _float("PRICE_OUTPUT_PER_MTOK", 0, 0, 1000)
    tavily_api_key: str = _env("TAVILY_API_KEY")
    max_search_results: int = _int("MAX_SEARCH_RESULTS", 4, 1, 8)
    timeout_seconds: float = _float("REQUEST_TIMEOUT_SECONDS", 25, 3, 120)
    max_execution_sec: int = _int("MAX_EXECUTION_SEC", 120, 10, 600)
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
    session_ttl_hours: int = _int("SESSION_TTL_HOURS", 12, 1, 720)  # sliding idle lifetime
    session_max_days: int = _int("SESSION_MAX_DAYS", 7, 1, 90)  # absolute lifetime
    cookie_secure: bool = _bool("COOKIE_SECURE", _APP_ENV == "production")
    login_max_attempts: int = _int("LOGIN_MAX_ATTEMPTS", 5, 1, 100)
    login_window_minutes: int = _int("LOGIN_WINDOW_MINUTES", 15, 1, 1440)
    daily_run_quota: int = _int("DAILY_RUN_QUOTA", 200, 1, 100000)  # per user, heavy runs per rolling 24h
    agent_timeout_seconds: int = _int("AGENT_TIMEOUT_SECONDS", 180, 10, 1800)
    # Code execution: off | local (AST policy + rlimits, NOT a sandbox) | docker (isolated container)
    runner_mode: str = _env("RUNNER_MODE", "").lower()
    runner_image: str = _env("RUNNER_IMAGE", "freshcode-runner:latest")
    web_dir: str = _env("WEB_DIR", "static")
    # Persistence
    db_path: str = _env("DB_PATH", str(PROJECT_ROOT / "data" / "freshcode.db"))
    history_limit: int = _int("HISTORY_LIMIT", 500, 20, 5000)


settings = Settings()
