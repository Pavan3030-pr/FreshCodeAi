# FreshCode AI v5.1: release report

## What changed
Front-end, tests and docs. Backend logic is untouched apart from the version string. v5.0 features, auth, isolation, persistence, Bifrost and Tavily integrations are preserved (all v5.0 tests still pass). See `CHANGELOG.md` and `docs/V5_1_AUDIT.md`.

## Integration status (honest)
| Integration | Status in this release |
|---|---|
| Bifrost | Code path unchanged and covered by tests with a stubbed network layer. **Not verified live**: no key or network in the build sandbox. The UI shows "configured", never "verified", until a real request succeeds. Run `make live` with your key. |
| Tavily | Same as above. |

## Known limitations
No live provider check; Docker isolation not run; `make test`/`doctor`/`audit` need pytest, FastAPI and network that the sandbox lacked (equivalent offline suites passed); no "technical topic" field on Freshness; evaluation visuals are HTML bars; Latin-only font subsets; no screen-reader or real-device testing; the landing screenshot shows stubbed data.

## Strict judge evaluation
Scores reflect evidence in this repository, not aspiration. The target of 9.5 is **not** reached overall.

| Category | Score | Evidence | Remaining weakness |
|---|---|---|---|
| Problem relevance | 8.5 | Stale AI answers and token waste are real; product addresses both end to end | Value rests on live results not yet shown |
| Innovation | 7.5 | Version-drift flags with sources; compression plus paired measurement; honest stage derivation | Individual pieces are known techniques |
| Bifrost integration | 7.5 | Essential to generation, assessment, benchmarks; measured usage labels; caching and fallback code | Never exercised against a real gateway in this release |
| Tavily integration | 7.5 | Powers research and claim checking; sources, dates, trust tier, request id shown | Same: no live verification here |
| Product completeness | 8.5 | 9 workspace views, projects, history, exports, accounts, audit, all journeys pass | No topic field, no MFA/reset email, charts are basic |
| UI/UX quality | 8.5 | Tinted light system, three-region agent, AA contrast tested, no overflow at 6 widths, real screenshots | Reviewed by one person by eye; no assistive-tech testing |
| Technical architecture | 8.0 | Small testable modules, no build step, unchanged CSP, pure helpers tested | `app.js` is 60 KB single file; SQLite only |
| Reliability | 8.0 | 178 + 30 tests and 19 journeys green; cancel, retry, graceful research failure | Offline emulator, not real FastAPI/uvicorn, ran the tests here |
| Security | 7.5 | CSRF, scoping, SSRF checks, redaction, escaping highlighter, policy-blocked code | Docker isolation unverified, no dependency audit, no pen test |
| Performance | 7.5 | No framework, about 250 KB fonts, about 190 KB static code | No measurements (no Lighthouse or load test) |
| Benchmark credibility | 7.0 | Paired, alternating, provider-reported tokens, raw CSV, limits stated | Small samples, input tokens only, no live numbers in repo |
| Demo quality | 8.5 | Recorded judge walkthrough and full journey, no-key guest demo | Videos use stubbed providers |
| **Overall** | **7.9** | | |

## Commands
```bash
# macOS setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # add BIFROST_API_KEY and TAVILY_API_KEY for live use
python -m playwright install chromium
# start
uvicorn app.main:app --reload --port 8000     # http://localhost:8000
# test
make test && make doctor && make e2e && make deploycheck && make audit
make record                                    # videos, screenshots, report under artifacts/
make live                                      # with real keys
```
