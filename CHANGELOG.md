# Changelog

## v5.1.0 — Premium colour-rich light UI, three-region engineering workspace
**Design system:** new warm light theme (lavender, lilac, peach, sage, sand, cream, plum, violet) with semantic tokens, self-hosted Lora / Inter / JetBrains Mono, tinted surfaces everywhere, WCAG AA contrast checked in tests. Dark mode, the theme toggle and saved dark preference were removed.
**Engineering Agent:** configuration / editor / execution-intelligence regions (tabs on narrow screens); 11-stage trace derived only from real backend events; elapsed timer; stop and retry; implementation / tests / notes tabs with syntax highlighting, copy, download and expandable viewer; measured vs estimated token labels.
**Shell:** collapsible sidebar, mobile drawer, real Bifrost / Tavily status chips, overview with provider status, project activity, usage and recent reports (all from API data).
**Pages:** landing page rebuilt (workflow, Bifrost, Tavily, compression, verification, freshness, evidence, security, architecture, FAQ) with a real product screenshot; sign-in / sign-up redesigned with password-strength feedback.
**Tests:** light-only, palette, workspace-structure and highlighter / stage-derivation tests added; dark-theme tests removed because the feature was removed.
**Fixes (CI / startup):** dependency pins no longer conflict (`fastapi` 0.115 required `starlette<0.47` while `starlette>=0.47.2` was requested, so `pip install` failed); `post_json` now returns `(body, headers)` as its callers expect, no longer turns 4xx errors into retryable 500s, and retries are counted as extra attempts; freshness test fakes accept the routed `model` argument; `venv/` is git-ignored.
**Fixes (demo / probes):** the guest demo now reports a disabled runner as skipped ("Blocked") instead of a failed test run, and its notice no longer claims pytest was executed; the `/`, `/login` and `/app` pages answer HEAD requests (uptime monitors previously got HTTP 405).
**Fixes (trace labels):** when code execution is disabled on a deployment, the Engineering Agent trace now shows the test and final-verification stages as not run ("runner disabled") instead of a green 0-passed result and a red "Blocked by policy"; real runner-policy violations still show as errors.
**Fixes (container):** the Docker image now installs pytest, so `RUNNER_MODE=local` can run generated Python tests on a hosted deployment (previously it would fail with "No module named pytest"); opt-in steps documented in docs/DEPLOYMENT.md.

**Upgrades (unreleased):** Tavily search is now tunable (`TAVILY_SEARCH_DEPTH`, `TAVILY_TOPIC`, `TAVILY_TIME_RANGE`, `TAVILY_INCLUDE_DOMAINS`, `TAVILY_EXCLUDE_DOMAINS`; defaults unchanged). Bifrost calls send a correlation `x-request-id`, an optional virtual key (`x-bf-vk`) and optional native `fallbacks`; the `x-bifrost-*` response headers are recorded as `routing` (provider, model, fallback index, upstream latency, cache) in run results, the trace and the UI. New stale-answer CLI (`scripts/stale_check.py`, exit code 1 when stale claims are found). Fixed a version-drift false positive where another product's version in the same sentence (e.g. "FastAPI 0.133 adds Starlette 1.0") was attributed to the claimed product. README rewritten with architecture diagram, screenshots and challenge mapping. CI hardened (least-privilege permissions, concurrency, timeouts, weekly scheduled audit, readiness retry loop) and Dependabot added for pip, Actions and Docker.

## v5.0.0 — AI engineering reliability platform
**Accounts and isolation:** registration/sign-in with scrypt, HttpOnly session cookie, per-session CSRF token, login throttling, sliding+absolute session expiry, session list/revoke, password change, account deletion; every query on user data is scoped by user; first account is admin.
**Projects:** per-user projects (create/edit/archive/delete) with saved defaults; runs can be filed under a project; searchable, filterable history.
**API v1:** versioned routes, typed errors with stable codes, OpenAPI at `/api/v1/docs`, readiness endpoint, minimal public health.
**Evidence:** multi-task paired evaluation lab with raw records, statistical limits, per-task table; Markdown reports and CSV exports (formula-injection safe); per-user usage, quota and audit trail.
**Execution safety:** `RUNNER_MODE=off|local|docker`; container runner (no network, read-only, non-root, resource limits) with unit-tested command; local runner clearly labelled not a sandbox.
**Security:** SSRF-safe URL validation, secret redaction in logs and errors, request-id sanitising, strict CSP + HSTS, deployment readiness checker.
**UI:** landing page, sign-in/up, workspace with Projects, History & reports, Account (profile/security/usage/audit/preferences), confirmation dialogs, cancel for agent runs, guest demo, warm ivory/lavender theme with peach accent (light default, dark optional), mobile layouts verified in a browser.
**Bugs found by browser end-to-end tests and fixed:** a wrong password was treated as an expired session; duplicate trace-slot ids; mobile grid overflow; mobile top bar clipping.
**Quality:** versioned DB migrations (upgrade from v4 verified), 176 Python tests, 27 front-end tests, 18 browser journeys, CI (tests, e2e, pip-audit, docker build).

## v4.8.0 — design pass verified in a real browser
Rendered every page in Chromium (desktop, phone, dark) and fixed what was visibly wrong: broken pipeline steps and an unstyled Home link in the app; a landing page made of identical cards. New landing page with a product window, proof strip, alternating bands, feature showcase and strong CTA; compact app overview with a clean stepper; Freshness lab shows the corrected answer first and collapses unflagged sources; mobile header and bottom nav fixed; low-contrast CTA band fixed in dark mode.

## v4.7.0 — landing page, warm light theme restored, labelled toggles
**Landing page** at `/` (problem → target KPI, one-line pipeline, before/after, features, measured-vs-estimated, ROI calculator, architecture, FAQ); the app lives at `/app` (`/app#demo` runs the demo). Live proof panel reads `/api/eval`.
**Theme:** warm light is the default again; dark is an option. Labelled Light/Dark toggle in the app and landing header, plus a Preferences card (theme, reduce motion) remembered across pages via a shared `theme.js` that applies before first paint.
**Proof of live data:** terminal-style activity log on the agent page; Tavily request id / response time / cache status shown with evidence.

## v4.6.0 — visual redesign
Dark-first aurora theme with glass surfaces and gradient accents, SVG navigation icons, connected pipeline steps, proof chips, redesigned buttons/KPIs/cards. Light theme retained (toggle, remembered). Cache-busting asset version bumped.

## v4.5.0 — glass-box traces, routing, extended evals
**Glass-box traces:** every agent run records a span tree (research, compress, generate, test, repair) with timings, token numbers, cache hits and the repair accept/reject decision; shown as a waterfall and stored with the run.
**Model routing:** optional `BIFROST_FAST_MODEL` for evidence assessment and `BIFROST_FALLBACK_MODEL` used once on server/model errors (never on auth errors).
**Evals:** claim-extraction eval (with known-hard cases) added to the offline self-check. Optional spend estimate from `PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK`.
**Consistency:** one version number (APP_VERSION) enforced by a test across app, UI and docs.

## v4.0–4.4 — winner-grade rebuild
**Token efficiency:** deterministic evidence compressor (boilerplate strip, URL + near-duplicate dedupe, task-aware sentence ranking, per-request budget), prompt/response cache (0 new tokens on repeats), output-token cap, compact repair prompts.
**Correctness:** self-verifying agent (generate → run generated pytest → one compact repair), repair accepted only if strictly better.
**Freshness:** claims ranked by risk and classified; source trust tiers; deterministic *newer-version* detector that works without any LLM; validated, cited LLM verdicts retained.
**Reliability:** retries with backoff for 429/5xx/timeouts, typed upstream errors, graceful degradation when research fails, truthful *verified* status only after a real upstream success.
**Security:** runner policy scan + resource limits + process-group kill + concurrency cap + off-by-default in production; optional access token; rate limits; CSP and security headers; request IDs; language input validation.
**Persistence:** SQLite run history, stats and JSON export.
**UI/UX:** new design system, dark mode, command palette (Ctrl K), keyboard shortcuts, example presets, live pipeline, token bars, claim cards, mobile bottom navigation, accessibility pass, no external font requests.
**Evidence:** `/api/eval` labelled self-check (18 drift cases incl. known-hard ones, 6 compression cases), ROI calculator, markdown report export, PITCH.md. Detector only flags *possibly outdated* when a claim asserts currency; bare majors and pre-releases handled.
**Auto-correction:** stale version claims get a deterministic suggested rewrite plus a corrected answer (clearly marked: confirm on the official source).
**JavaScript auto-testing:** generated `node:test` suites run with a regex policy, timeout and process-group kill (Python AST policy is stronger; both defence in depth).
**Observability:** cache hit/miss stats in Connections.
**Verification tooling:** `make doctor` (in-process end-to-end preflight), `make live` (real Bifrost/Tavily check + benchmark evidence file), static WCAG AA contrast audit in both themes and CSS/HTML/JS class-coverage tests.
**Quality:** 103 Python tests runnable without network + API/runner integration tests + 25 front-end tests; CI workflow.
**Fixes:** `.env` inline comments no longer become values (config strips them; example file rewritten); tests are hermetic and ignore a local `.env`; runner no longer blocks the event loop; broken health/base-URL display; stream endpoint rewritten with keep-alive.

## v3.x
See git history: judge demo, honest status wording, paired benchmark, warm light theme.
