# Five-minute judge demonstration

Prepare: `make run`, sign up (first account becomes admin), keys in `.env`, `make live` once to capture `docs/live-results.json`.

| Min | Show | What the judge should see |
|---|---|---|
| 0:00 | Landing page | The problem in one sentence; why both Bifrost and Tavily are needed |
| 0:30 | Projects → create "Demo" | Saved defaults (language, constraints, context budget) |
| 1:00 | Engineering agent → run an example | Live pipeline + activity log; Tavily request id with the sources; evidence compressed (estimated) → provider-measured input tokens; tests run; if red, one repair; the **Run trace** |
| 2:15 | Freshness → "Outdated framework answer" | Claim flagged *possibly outdated* with the newer version from a primary source, a suggested correction (to confirm) and the cited snippets |
| 3:00 | Evaluation lab → 3 tasks | Paired, alternating, provider-measured result with range, raw CSV and the stated statistical limits |
| 4:00 | History & reports | Search/filter, open the trace, download the Markdown report and CSV |
| 4:30 | Account → Security/Audit; open `/api/v1/docs` | Sessions, audit trail, per-user isolation; the architecture and security notes in `docs/` |

Honest framing to say out loud: savings are measured from gateway usage on small paired samples (directional); stale-claim detection is a heuristic with a labelled self-check; the local runner is not a sandbox and container isolation needs a Docker host.

## v5.1 additions
1. Open `/` and scroll the landing page: each section is backed by something in the product (Bifrost usage labels, Tavily source cards, compression numbers, test results).
2. `make record` produces `artifacts/browser-recordings/judge-demo.webm`, a recorded walkthrough of: sign up, Engineering Agent run (tests fail once, one repair succeeds), generated tests tab, freshness check, history, integrations, overview. Providers are stubbed on the test server; the video shows real UI, real auth, real database, real test execution.
3. In the agent, watch the 11-stage trace. Stages 2-5 are live server events; stages 6-11 are derived only from fields in the result (for example "Repair attempt" is skipped when no repair span exists). Token tiles say MEASURED BY PROVIDER or ESTIMATED LOCALLY.
4. With real keys, `make live` records a live Bifrost + Tavily check. Until then the status chips say "configured", never "verified".
