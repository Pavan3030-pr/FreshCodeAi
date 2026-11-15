# FreshCode AI v5.1: audit

Scope: the supplied v5.0 archive (unchanged). Audited by reading the code, running the Python and Node suites and the browser journeys, and viewing screenshots.

## Architecture (as found)
FastAPI app (`app/main.py` composition root, `app/api/v1.py` routes, `app/services/*` for auth, agent, Bifrost, Tavily, compressor, runner, freshness, eval, reports, trace, db), SQLite with versioned migrations, no-build static front-end, an in-repo emulator layer (`tests/support/`) so tests run without network. Core flow: Tavily research -> compression -> one Bifrost call -> test run -> optional one repair -> trace saved.

## Baseline (v5.0, this sandbox)
| Command | Result |
|---|---|
| `python3 tests/run_stdlib.py` | 176 passed, 0 failed, 1 module skipped (`test_demo.py`, needs pytest) |
| `node --test tests/js/*.test.js` | 27 passed |
| `python3 tests/e2e/run_e2e.py` | 18/18 journeys |

## Findings
| # | Area | Finding | Resolution in v5.1 |
|---|---|---|---|
| 1 | UI | Surfaces were ivory/white with a dark mode and a theme toggle; brief requires a tinted light-only system | New token system, tinted surfaces, dark mode removed |
| 2 | UI | Agent screen was one column: config, editor, results stacked | Three-region workspace, tabs below 1280 px |
| 3 | UI | Pipeline showed 4 coarse stages | 11 stages; 2-5 live events, 6-11 derived from result fields only |
| 4 | UI | Token tiles did not say measured vs estimated | Per-tile "MEASURED BY PROVIDER" / "ESTIMATED LOCALLY" |
| 5 | UI | Code shown as plain text | Escaping syntax highlighter, tabs for implementation/tests/notes, expand |
| 6 | UI | No elapsed time, no retry after a finished run | Elapsed timer, Retry |
| 7 | UI | Mobile used a horizontal-scroll nav | Drawer, plus collapsible desktop sidebar |
| 8 | UI | Top bar had no provider status | Bifrost / Tavily chips: unknown / not set / configured / verified |
| 9 | Overview | "Judge scorecard" table inside the product | Replaced by provider status, project activity, usage, recent reports |
| 10 | Landing | Fewer sections than the brief; no product screenshot | Rebuilt; hero image is a real screenshot of the app |
| 11 | Security | Sign-in throttle also counts successful sign-ins | Left as is, documented; tests reuse a session |
| 12 | Security | Docker isolation not verifiable here | Unchanged, reported as unverified |
| 13 | Tests | Dark-theme tests asserted a removed feature | Replaced by light-only and palette tests |

## Not found / not changed
No API bugs, auth bypasses or data-isolation failures were found by the existing tests or the new journeys. Backend code is unchanged except the version string.

## Open items (not fixed)
Freshness page has no separate "technical topic" field (the API takes only the answer text; adding one would change the backend contract). Evaluation charts are the existing bar rows, not a charting library. No live Bifrost/Tavily verification (no keys, no network here). Docker runner not exercised. Fonts are Latin subsets.
