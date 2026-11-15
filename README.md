# FreshCode AI — v5.1

**An AI engineering reliability platform:** generate better code, use fewer tokens, verify changing technical information, and prove the results work.

- **Bifrost — token-efficient engineering agent:** research → compress → generate → test → diagnose → one repair → trace, with provider-reported token usage.
- **Tavily — live freshness intelligence:** extract claims, retrieve current sources, flag outdated versions, show evidence and suggested corrections.
- **Evidence:** multi-task paired benchmarks, saved history, Markdown/CSV exports, audit trail.

**New in v5.1:** a warm, colour-rich light design system (lavender, lilac, peach, sage, sand, cream, plum), a three-region Engineering Agent with an 11-stage execution trace, syntax-highlighted code with copy/download, measured-vs-estimated token labels, a collapsible sidebar and mobile drawer, a rebuilt landing page and sign-in. Dark mode was removed. See [the v5.1 release report](docs/V5_1_RELEASE_REPORT.md).

Public site (`/`), sign-in (`/login`), and the authenticated workspace (`/app`): Overview · Projects · Engineering agent · Freshness · Evaluation lab · History & reports · Test lab · Integrations · Account (profile, security, usage, audit, preferences).

## Setup

**macOS / Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # add keys; everything is optional for the guest demo
uvicorn app.main:app --reload --port 8000
```
**Windows (PowerShell)**
```powershell
py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000. The first account you create becomes the administrator. Docs: `/api/v1/docs`.

## Verify it
```bash
make test && make doctor      # (no make on Windows: python -m pytest -q ; node --test tests/js/*.test.js ; python scripts/preflight.py)
python -m playwright install chromium && make e2e
make record                   # videos, screenshots, trace and report under artifacts/
make live                     # with real keys: verifies Bifrost + Tavily, writes docs/live-results.json
make deploycheck && make audit
```

## Environment variables
See `.env.example` (all documented, placeholders only). Key groups: providers (`BIFROST_*`, `TAVILY_API_KEY`), accounts (`ALLOW_REGISTRATION`, `SESSION_*`, `COOKIE_SECURE`, `LOGIN_*`), limits (`RATE_LIMIT_*`, `DAILY_RUN_QUOTA`, `AGENT_TIMEOUT_SECONDS`), execution (`RUNNER_MODE=off|local|docker`), storage (`DB_PATH`).

## Documentation
[Architecture](docs/ARCHITECTURE.md) · [Database](docs/DATABASE.md) · [API](docs/API.md) · [Security](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) · [Testing](docs/TESTING.md) · [Judge demo](docs/JUDGE_DEMO.md) · [v5.1 audit](docs/V5_1_AUDIT.md) · [UI/UX review](docs/V5_1_UI_UX_REVIEW.md) · [Test evidence](docs/V5_1_TEST_EVIDENCE.md) · [Release report](docs/V5_1_RELEASE_REPORT.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## Known limitations (stated plainly)
- **PostgreSQL is not implemented.** Persistence is SQLite (WAL) with versioned migrations and portable SQL.
- **The local code runner is not a sandbox.** Container isolation (`RUNNER_MODE=docker`) is implemented and its command is unit-tested, but was not run in the development sandbox (no Docker there). Public deployments should keep execution off.
- Benchmarks compare provider-reported **input** tokens on small paired samples (directional); output tokens, answer quality and correctness are not compared; no significance test. Multiple-model and context-budget comparison grids are not implemented.
- Claim extraction and version-drift detection are heuristics; verdicts from the LLM assessor need Bifrost. Confirm on official sources.
- No MFA, email verification or password-reset email; login throttling is in memory; no Notifications page and no pricing page (not meaningful for this release).
- The Freshness page has no separate "technical topic" field; Evaluation Lab bars are plain HTML, not a charting library; fonts are Latin subsets.
- Live Bifrost/Tavily behaviour is verified only by `make live` with your keys.

License: MIT.
