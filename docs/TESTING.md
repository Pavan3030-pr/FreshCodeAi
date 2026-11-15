# Testing

```bash
make test        # pytest (Python) + node --test (front-end)
make e2e         # 19 browser journeys with Playwright + Chromium (python -m playwright install chromium first)
make record      # e2e with video + trace, the judge demo recording, screenshots and an HTML report under artifacts/
make doctor      # boots the real app in-process and walks the primary journey
make live        # with real keys: verifies Bifrost + Tavily and writes docs/live-results.json
make deploycheck && make audit
```
Offline fallback (no pip/network): `python3 tests/run_stdlib.py` runs every Python test against the in-repo FastAPI/Pydantic/httpx emulators; `node --test tests/js/*.test.js` runs the front-end tests.

Policy: no test is skipped silently. The browser journeys stub only the Bifrost and Tavily *network* calls (deterministic responses); auth, database, agent, runner, reports and UI run for real. Live-provider behaviour is verified only by `make live` with your keys.

## Browser evidence (`make record`)
Writes `artifacts/browser-recordings/full-user-journey.webm`, `judge-demo.webm`, `full-user-journey-trace.zip` (open with `playwright show-trace`), `artifacts/screenshots/*.png`, `artifacts/recordings-index.json` and `artifacts/playwright-report/index.html` (a generated summary of the journeys, not the @playwright/test reporter). A failing journey also saves `FAILED_<n>.png`.

## What the v5.1 journeys assert
Landing sections and the product screenshot load; no `data-theme` attribute and no white body; three workspace regions and 11 stage rows; stages 6-11 derive from real result fields; copy puts code on the clipboard; downloads have the right names; measured vs estimated labels; responsive matrix (1440, 1280, 1024, 768, 390, 360 px) with zero horizontal overflow on landing, sign-in and all nine workspace views; mobile drawer; collapsible sidebar; panes as tabs at <=1280 px.
