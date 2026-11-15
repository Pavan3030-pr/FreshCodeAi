"""Operational endpoints: public liveness/readiness (no secrets) and an authenticated detailed system view."""
import asyncio
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.services.bifrost as bifrost_mod
import app.services.tavily as tavily_mod
from app.api import state
from app.api.deps import require_session
from app.config import APP_VERSION, settings
from app.services import runner, status as upstream_status

router = APIRouter()
STARTED_AT = time.time()


@router.get("/api/health")
async def health():
    """Public liveness. Deliberately minimal: no hosts, models, keys or counts."""
    first_run = (await asyncio.to_thread(state.store.count_users)) == 0
    return {"status": "ok", "app": "FreshCode AI", "version": APP_VERSION, "uptime_seconds": round(time.time() - STARTED_AT),
            "registration_open": settings.allow_registration or first_run, "first_run": first_run, "environment": settings.app_env}


@router.get("/api/v1/ready")
async def ready():
    """Readiness: database reachable and migrations applied."""
    try:
        ok = await asyncio.to_thread(state.store.ping)
        version = await asyncio.to_thread(state.store.schema_version)
    except Exception:
        return JSONResponse({"ready": False, "database": "unreachable"}, status_code=503)
    from app.services.db import MIGRATIONS
    return JSONResponse({"ready": bool(ok and version == MIGRATIONS[-1][0]), "database": "ok", "schema_version": version}, status_code=200 if ok else 503)


@router.get("/api/v1/system")
async def system(request: Request):
    require_session(request)
    b, t = bool(settings.bifrost_api_key), bool(settings.tavily_api_key)
    snap = upstream_status.snapshot()
    mode = runner.effective_mode()
    return {
        "version": APP_VERSION, "environment": settings.app_env, "uptime_seconds": round(time.time() - STARTED_AT),
        "bifrost_configured": b, "tavily_configured": t, "bifrost_model": settings.bifrost_model, "bifrost_host": urlparse(settings.bifrost_base_url).netloc,
        "bifrost_fast_model": settings.bifrost_fast_model or None, "bifrost_fallback_model": settings.bifrost_fallback_model or None,
        "bifrost_verified": bool(snap.get("bifrost", {}).get("last_ok_at")), "tavily_verified": bool(snap.get("tavily", {}).get("last_ok_at")), "upstream": snap,
        "runner_mode": mode, "runner_isolated": runner.isolated(), "test_languages": ["python", "javascript"] if mode != "off" else [],
        "cache": {"bifrost": {"hits": bifrost_mod._CACHE.hits, "misses": bifrost_mod._CACHE.misses, "size": len(bifrost_mod._CACHE)},
                  "tavily": {"hits": tavily_mod._CACHE.hits, "misses": tavily_mod._CACHE.misses, "size": len(tavily_mod._CACHE)}},
        "limits": {"per_minute": settings.rate_limit_per_minute, "heavy_per_minute": settings.heavy_rate_limit_per_minute, "daily_runs": settings.daily_run_quota,
                   "agent_timeout_seconds": settings.agent_timeout_seconds, "session_ttl_hours": settings.session_ttl_hours},
        "database": {"engine": "sqlite", "schema_version": state.store.schema_version()},
        "service_state_semantics": "configured = credentials present; verified = at least one successful upstream request since startup",
    }
