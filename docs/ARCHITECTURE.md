# Architecture

```
 Browser ── landing / login / app (static HTML + vanilla JS, strict CSP, no inline scripts)
    │  cookie session (HttpOnly) + X-CSRF-Token header · SSE for agent progress
    ▼
 FastAPI  app/main.py        middleware: request id · rate limits · security headers · error mapping (no internals leak)
    ├─ app/api/system.py     /api/health (public, minimal) · /api/v1/ready · /api/v1/system (auth)
    └─ app/api/v1.py         auth · projects · agent · verify · benchmark · test · runs/reports · usage · audit
          │  thin routes: validate → authorise (require_session: cookie + CSRF) → call service → persist → shape response
          ▼
 app/services (business logic, no HTTP types)
    auth.py        register/login/throttle/sessions/CSRF/password/quota
    agent.py       research → compress → generate → test → one repair, with a span trace (trace.py)
    freshness.py   claim extraction · trust tiers · version-drift detector · optional LLM verdicts with validated citations
    benchmark.py   paired alternating suite over several tasks · raw records
    compress.py    deterministic evidence compressor (estimated tokens, labelled)
    bifrost.py / tavily.py / http.py   provider clients: cache · retry/backoff · fallback model · typed errors · status
    runner.py      off | local (AST/regex policy + rlimits; NOT a sandbox) | docker (runner_docker.py)
    reports.py     Markdown reports · CSV (formula-injection safe)
    db.py          SQLite · versioned migrations · per-user scoped queries
 app/core          security.py (scrypt, tokens, redaction, SSRF validation) · errors.py (typed) · config_check.py · logging.py
```

## Why two sponsor technologies are necessary
- **Bifrost** is the single gateway for every model call: usage telemetry (the only source of *measured* token numbers), model routing and fallback, caching.
- **Tavily** supplies current evidence. Without it the agent works from stale context and the freshness engine has nothing to check against.

## Key decisions
- **Estimates vs measurements.** Local token counts drive compression but are always labelled *estimated*; savings are claimed only from provider usage on paired, alternating runs.
- **Isolation by construction.** Every repository method that touches user data takes `user_id`; there is no unscoped read path.
- **Fail soft.** Research failures degrade, history/audit write failures never break a request, one claim's search failure does not abort the rest.
- **Stdlib-first core.** Hashing, sessions, cache, limiter, DB, compression and the runner use only the standard library, so they are testable without network or heavy dependencies.
- **SQLite with portable SQL.** PostgreSQL is **not** implemented in this release (see Known limitations).

## Front-end (v5.1)
No build step, no framework: `static/style.css` (design tokens + components), `landing.css`, `auth.css`, `lib.js` (pure helpers including `highlight` and `finalStages`, tested in Node), `app.js` (workspace), `account.js`, `theme.js` (reduced-motion preference only). Fonts (Lora, Inter, JetBrains Mono; Latin subsets, OFL) are served from `/static/fonts`; the CSP is unchanged (`script-src 'self'`). The Engineering Agent is three regions (`.ws-config`, `.ws-main`, `.ws-exec`); at 1280 px and below they become tabs. Code is highlighted by tokenising raw text and escaping each token; model output is never injected as HTML.
