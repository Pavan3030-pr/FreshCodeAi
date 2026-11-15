"""HTTP routes for /api/v1. Thin: validate, authorise, call services, persist, shape the response."""
import asyncio
import json
import logging
import sqlite3
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api import state
from app.api.deps import clear_session_cookie, client_ip, request_id, require_admin, require_session, session_token, set_session_cookie
from app.config import settings
from app.core.errors import AppError, AuthRequired, Conflict, CsrfFailed, NotFound, ValidationFailed
from app.core.security import redact
from app.schemas import (BenchmarkRequest, CodeRequest, DeleteAccount, LoginRequest, PasswordChange, ProfileUpdate, ProjectCreate, ProjectUpdate,
                         RegisterRequest, TestRequest, VerifyRequest)
from app.services import reports
from app.services.agent import build_solution
from app.services.benchmark import run_benchmark_suite
from app.services.bifrost import BifrostClient
from app.services.demo import run_demo
from app.services.evals import run_evals
from app.services.freshness import verify_text
from app.services.http import UpstreamError
from app.services.runner import run_tests
from app.services.tavily import TavilyClient

log = logging.getLogger("freshcode.api")
router = APIRouter(prefix="/api/v1")


def _secrets():
    return [settings.bifrost_api_key, settings.tavily_api_key]


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "display_name": u.get("display_name", ""), "role": u.get("role", "user")}


def _from_session(s: dict) -> dict:
    return {"id": s["user_id"], "email": s["email"], "display_name": s["display_name"], "role": s["role"]}


class _Upstream(AppError):
    status, code = 502, "upstream_error"


def _fail(exc: Exception, prefix: str) -> AppError:
    log.warning("%s: %s", prefix, redact(str(exc), _secrets()))
    if isinstance(exc, UpstreamError):
        return _Upstream(redact(exc.public(), _secrets()))
    return _Upstream(f"{prefix}: {redact(str(exc), _secrets())[:200]}")


async def _project_id(session: dict, project_id):
    if project_id is None:
        return None
    p = await asyncio.to_thread(state.store.get_project, project_id, session["user_id"])
    if not p:
        raise NotFound("Project not found.")
    return p["id"]


async def _record(session: dict, kind: str, title: str, status: str = "ok", project_id=None, **kw):
    try:
        return await asyncio.to_thread(state.store.add_run, kind, title, status, user_id=session["user_id"], project_id=project_id, **kw)
    except Exception:
        log.exception("history write failed")
        return None


async def _audit(request: Request, action: str, session=None, detail: str = ""):
    try:
        await asyncio.to_thread(state.store.add_audit, action, user_id=(session or {}).get("user_id"), detail=detail, ip=client_ip(request), request_id=request_id(request))
    except Exception:
        log.exception("audit write failed")


# ---------------------------------------------------------------- auth
@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    user, token, session = await asyncio.to_thread(state.auth.register, body.email, body.password, body.display_name,
                                                   ip=client_ip(request), user_agent=request.headers.get("user-agent", ""), request_id=request_id(request))
    resp = JSONResponse({"user": _public_user(user), "csrf": session["csrf"]}, status_code=201)
    set_session_cookie(resp, token)
    return resp


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    user, token, session = await asyncio.to_thread(state.auth.login, body.email, body.password,
                                                   ip=client_ip(request), user_agent=request.headers.get("user-agent", ""), request_id=request_id(request))
    resp = JSONResponse({"user": _public_user(user), "csrf": session["csrf"]})
    set_session_cookie(resp, token)
    return resp


@router.get("/auth/me")
async def me(request: Request):
    s = require_session(request)
    return {"user": _from_session(s), "csrf": s["csrf"], "usage": state.auth.usage(s["user_id"]), "registration_open": settings.allow_registration}


@router.post("/auth/logout")
async def logout(request: Request):
    s = require_session(request)
    state.auth.logout(session_token(request))
    await _audit(request, "logout", s)
    resp = JSONResponse({"ok": True})
    clear_session_cookie(resp)
    return resp


@router.patch("/auth/profile")
async def update_profile(body: ProfileUpdate, request: Request):
    s = require_session(request)
    u = await asyncio.to_thread(state.store.update_profile, s["user_id"], body.display_name.strip())
    await _audit(request, "profile_updated", s)
    return {"user": _public_user(u)}


@router.post("/auth/password")
async def change_password(body: PasswordChange, request: Request):
    s = require_session(request)
    revoked = await asyncio.to_thread(state.auth.change_password, s, body.current_password, body.new_password, ip=client_ip(request), request_id=request_id(request))
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/auth/sessions")
async def list_sessions(request: Request):
    s = require_session(request)
    rows = await asyncio.to_thread(state.store.list_sessions, s["user_id"])
    return {"sessions": [{**r, "current": r["id"] == s["id"]} for r in rows]}


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(session_id: int, request: Request):
    s = require_session(request)
    n = await asyncio.to_thread(state.store.delete_session_by_id, s["user_id"], session_id)
    if not n:
        raise NotFound("Session not found.")
    await _audit(request, "session_revoked", s, f"id={session_id}")
    return {"ok": True}


@router.post("/auth/sessions/revoke-others")
async def revoke_other_sessions(request: Request):
    s = require_session(request)
    n = await asyncio.to_thread(state.store.delete_user_sessions, s["user_id"], s["id"])
    await _audit(request, "sessions_revoked", s, f"count={n}")
    return {"revoked": n}


@router.post("/auth/delete-account")
async def delete_account(body: DeleteAccount, request: Request):
    s = require_session(request)
    await asyncio.to_thread(state.auth.delete_account, s, body.password, ip=client_ip(request), request_id=request_id(request))
    resp = JSONResponse({"ok": True})
    clear_session_cookie(resp)
    return resp


# ---------------------------------------------------------------- projects
def _integrity(exc: sqlite3.IntegrityError):
    return Conflict("A project with that name already exists.", code="project_exists") if "UNIQUE" in str(exc).upper() else ValidationFailed("Invalid project data.")


@router.get("/projects")
async def list_projects(request: Request, include_archived: bool = False, q: str = ""):
    s = require_session(request)
    return {"projects": await asyncio.to_thread(state.store.list_projects, s["user_id"], include_archived=include_archived, q=q[:80])}


@router.post("/projects")
async def create_project(body: ProjectCreate, request: Request):
    s = require_session(request)
    try:
        p = await asyncio.to_thread(state.store.create_project, s["user_id"], body.name.strip(), description=body.description, language=body.language,
                                    constraints=body.constraints, context_budget=body.context_budget)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc)
    await _audit(request, "project_created", s, f"id={p['id']}")
    return JSONResponse({"project": p}, status_code=201)


@router.get("/projects/{project_id}")
async def get_project(project_id: int, request: Request):
    s = require_session(request)
    p = await asyncio.to_thread(state.store.get_project, project_id, s["user_id"])
    if not p:
        raise NotFound("Project not found.")
    return {"project": p}


@router.patch("/projects/{project_id}")
async def update_project(project_id: int, body: ProjectUpdate, request: Request):
    s = require_session(request)
    fields = {k: v for k, v in body.__dict__.items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    try:
        p = await asyncio.to_thread(state.store.update_project, project_id, s["user_id"], **fields)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc)
    if not p:
        raise NotFound("Project not found.")
    await _audit(request, "project_updated", s, f"id={project_id} fields={','.join(sorted(fields))}")
    return {"project": p}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, request: Request):
    s = require_session(request)
    if not await asyncio.to_thread(state.store.delete_project, project_id, s["user_id"]):
        raise NotFound("Project not found.")
    await _audit(request, "project_deleted", s, f"id={project_id}")
    return {"ok": True}


# ---------------------------------------------------------------- engineering workspace
@router.post("/verify")
async def verify(body: VerifyRequest, request: Request):
    s = require_session(request)
    pid = await _project_id(s, body.project_id)
    state.auth.enforce_quota(s["user_id"])
    started = time.perf_counter()
    try:
        result = await verify_text(body.text, TavilyClient(), BifrostClient())
    except Exception as exc:
        raise _fail(exc, "Verification failed")
    sm = result.get("summary", {})
    result["run_id"] = await _record(s, "verify", body.text[:80], "ok", pid, latency_ms=round((time.perf_counter() - started) * 1000),
                                     summary=f"{result['claims_found']} claims · {sm.get('possibly_outdated', 0)} possibly outdated · {sm.get('contradicted', 0)} contradicted", payload=result)
    return result


async def _run_agent(req: CodeRequest, on_progress=None):
    return await asyncio.wait_for(build_solution(req, on_progress=on_progress), timeout=settings.agent_timeout_seconds)


def _code_status(result: dict) -> str:
    ver = result.get("verification") or {}
    return "setup_required" if result.get("mode") != "live" else ("ok" if ver.get("passed", True) else "tests_failed")


async def _record_code(s: dict, req: CodeRequest, result: dict, pid):
    usage, ver = result.get("provider_usage") or {}, result.get("verification") or {}
    return await _record(s, "code", req.task[:80], _code_status(result), pid, latency_ms=result.get("latency_ms"),
                         tokens_in=(result.get("token_report") or {}).get("provider_input_tokens"), tokens_total=usage.get("total_tokens"),
                         summary=f"{req.language} · {len(result.get('sources', []))} sources" + (" · tests passed" if ver.get("passed") else ""), payload=result)


@router.post("/code")
async def code(body: CodeRequest, request: Request):
    s = require_session(request)
    pid = await _project_id(s, body.project_id)
    state.auth.enforce_quota(s["user_id"])
    try:
        result = await _run_agent(body)
    except asyncio.TimeoutError:
        raise _Upstream(f"The agent run exceeded the {settings.agent_timeout_seconds}-second limit and was cancelled.")
    except Exception as exc:
        raise _fail(exc, "Agent request failed")
    result["run_id"] = await _record_code(s, body, result, pid)
    return result


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/code/stream")
async def code_stream(body: CodeRequest, request: Request):
    s = require_session(request)
    pid = await _project_id(s, body.project_id)
    state.auth.enforce_quota(s["user_id"])

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def worker():
            try:
                result = await _run_agent(body, on_progress=lambda e: queue.put_nowait(("progress", e)))
                result["run_id"] = await _record_code(s, body, result, pid)
                queue.put_nowait(("result", result))
            except asyncio.TimeoutError:
                queue.put_nowait(("error", {"message": f"The agent run exceeded the {settings.agent_timeout_seconds}-second limit and was cancelled."}))
            except Exception as exc:
                log.warning("stream failed: %s", redact(str(exc), _secrets()))
                msg = redact(exc.public(), _secrets()) if isinstance(exc, UpstreamError) else f"Agent request failed: {redact(str(exc), _secrets())[:200]}"
                queue.put_nowait(("error", {"message": msg}))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(worker())
        try:
            while True:
                try:
                    kind, data = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if kind == "done":
                    break
                yield _sse(kind, data)
        finally:  # client disconnect (Cancel button) or completion
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/benchmark")
async def benchmark(body: BenchmarkRequest, request: Request):
    s = require_session(request)
    pid = await _project_id(s, body.project_id)
    state.auth.enforce_quota(s["user_id"])
    started = time.perf_counter()
    tasks = [body.task] + [t for t in body.extra_tasks if t and len(t.strip()) >= 8]
    try:
        result = await run_benchmark_suite(tasks, body.language)
    except Exception as exc:
        raise _fail(exc, "Benchmark failed")
    if result.get("mode") == "live":
        agg = result.get("aggregate") or {}
        result["run_id"] = await _record(s, "benchmark", body.task[:80], "ok" if result.get("measured") else "unmeasured", pid,
                                         latency_ms=round((time.perf_counter() - started) * 1000), savings_pct=agg.get("median_savings_pct"),
                                         summary=(f"{agg.get('median_savings_pct')}% median provider-measured input saving over {agg.get('measured_tasks')} task(s)" if result.get("measured") else "provider usage unavailable"),
                                         payload=result)
    return result


@router.post("/test")
async def run_test(body: TestRequest, request: Request):
    s = require_session(request)
    pid = await _project_id(s, body.project_id)
    state.auth.enforce_quota(s["user_id"])
    result = await run_tests(body.language, body.code, body.tests)
    result["run_id"] = await _record(s, "test", f"{body.language.title()} test suite", "ok" if result.get("passed") else "failed", pid, latency_ms=result.get("duration_ms"),
                                     summary=f"{result.get('tests_passed', 0)} passed · {result.get('tests_failed', 0)} failed", payload={k: v for k, v in result.items() if k != "warning"})
    return result


@router.post("/demo")
async def demo(request: Request):
    """Public: fixed fixture + real local engine. Saved to history only for a signed-in user with a valid CSRF token."""
    result = await run_demo()
    try:
        s = state.auth.authenticate(session_token(request))
        state.auth.check_csrf(s, "POST", request.headers.get("x-csrf-token"))
        result["run_id"] = await _record(s, "demo", "Judge demo", "ok" if result["tests"].get("passed") else "failed", None, latency_ms=result["tests"].get("duration_ms"),
                                         summary="fixtures + real compression, drift check and tests", payload=result)
    except (AuthRequired, CsrfFailed):
        pass
    return result


@router.get("/eval")
async def evaluate():
    """Public, offline, deterministic self-check on labelled fixtures."""
    return await asyncio.to_thread(run_evals)


# ---------------------------------------------------------------- history, reports, usage, audit
@router.get("/runs")
async def list_runs(request: Request, limit: int = 50, offset: int = 0, kind: str = "", status: str = "", project_id: int = 0, q: str = ""):
    s = require_session(request)
    return {"runs": await asyncio.to_thread(state.store.list_runs, limit, kind or None, user_id=s["user_id"], project_id=project_id or None,
                                           status=status or None, q=q[:80], offset=offset)}


@router.get("/runs/export.csv")
async def export_runs(request: Request):
    s = require_session(request)
    rows = await asyncio.to_thread(state.store.list_runs, 500, None, user_id=s["user_id"])
    await _audit(request, "export_history", s, f"rows={len(rows)}")
    return Response(reports.runs_to_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="freshcode-history.csv"'})


@router.delete("/runs")
async def clear_runs(request: Request):
    s = require_session(request)
    n = await asyncio.to_thread(state.store.clear, s["user_id"])
    await _audit(request, "history_cleared", s, f"rows={n}")
    return {"deleted": n}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, request: Request):
    s = require_session(request)
    r = await asyncio.to_thread(state.store.get_run, run_id, s["user_id"])
    if not r:
        raise NotFound("Run not found.")
    return r


@router.get("/runs/{run_id}/report.md")
async def run_report(run_id: int, request: Request):
    s = require_session(request)
    r = await asyncio.to_thread(state.store.get_run, run_id, s["user_id"])
    if not r:
        raise NotFound("Run not found.")
    await _audit(request, "export_report", s, f"run={run_id}")
    return Response(reports.run_to_markdown(r), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="freshcode-run-{run_id}.md"'})


@router.get("/runs/{run_id}/benchmark.csv")
async def benchmark_csv(run_id: int, request: Request):
    s = require_session(request)
    r = await asyncio.to_thread(state.store.get_run, run_id, s["user_id"])
    if not r or r["kind"] != "benchmark":
        raise NotFound("Benchmark run not found.")
    return Response(reports.benchmark_to_csv(r["payload"]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="freshcode-benchmark-{run_id}.csv"'})


@router.get("/stats")
async def stats(request: Request):
    s = require_session(request)
    st = await asyncio.to_thread(state.store.stats, s["user_id"])
    if settings.price_in_per_mtok or settings.price_out_per_mtok:
        st["estimated_spend_usd"] = round(st["provider_tokens_in"] / 1e6 * settings.price_in_per_mtok + st["provider_tokens_out"] / 1e6 * settings.price_out_per_mtok, 4)
    return st


@router.get("/usage")
async def usage(request: Request):
    s = require_session(request)
    st = await stats(request)
    return {"quota": state.auth.usage(s["user_id"]), "totals": st, "rate_limits": {"per_minute": settings.rate_limit_per_minute, "heavy_per_minute": settings.heavy_rate_limit_per_minute}}


@router.get("/audit")
async def audit(request: Request, limit: int = 100, scope: str = "me"):
    s = require_session(request)
    if scope == "all":
        require_admin(s)
        return {"events": await asyncio.to_thread(state.store.list_audit, limit=limit, all_users=True), "scope": "all"}
    return {"events": await asyncio.to_thread(state.store.list_audit, user_id=s["user_id"], limit=limit), "scope": "me"}
