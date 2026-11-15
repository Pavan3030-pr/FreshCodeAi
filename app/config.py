"""Runtime configuration. Every value comes from the environment (or .env)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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
    """Drop inline comments ("VALUE # note") and values that are only a comment."""
    raw = raw.strip()
    if raw.startswith("#"):
        return ""
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _env(name: str, default: str = "") -> str:
    return _clean(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    val = _env(name, str(default))
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = _env(name, str(default))
    try:
        return float(val)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = _env(name, str(default)).lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url in ("https://groq.com", "http://groq.com", "https://api.groq.com", "http://api.groq.com"):
        return "https://api.groq.com/openai/v1"
    if url.endswith("/chat/completions"):
        url = url[:-17].rstrip("/")
    return url


@dataclass(frozen=True)
class Settings:
    app_name: str = "FreshCodeAI"
    app_version: str = APP_VERSION
    environment: str = _env("ENVIRONMENT", "development")
    log_level: str = _env("LOG_LEVEL", "INFO")
    secret_key: str = _env("SECRET_KEY", "dev-secret-key-change-in-production")

    cors_origins: list[str] = field(
        default_factory=lambda: [
            origin.strip()
            for origin in _env(
                "CORS_ORIGINS",
                "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,https://freshcodeai.onrender.com",
            ).split(",")
            if origin.strip()
        ]
    )

    tavily_api_key: str = _env("TAVILY_API_KEY", "")

    bifrost_base_url: str = _normalize_base_url(_env("BIFROST_BASE_URL", "http://localhost:4000/v1"))
    bifrost_api_key: str = _env("BIFROST_API_KEY", "dummy-key")
    bifrost_model: str = _env("BIFROST_MODEL", "bifrost-default")
    bifrost_timeout: float = _env_float("BIFROST_TIMEOUT", 120.0)

    max_execution_sec: int = _env_int("MAX_EXECUTION_SEC", 30)

    web_dir: Path = PROJECT_ROOT / "app" / "static"


settings = Settings()
