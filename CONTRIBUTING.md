# Contributing

1. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`
2. `make test` (pytest + node tests) must pass. `make e2e` runs the browser journeys (needs `playwright install chromium`).
3. Keep layers separate: `app/api` (HTTP only) → `app/services` (business logic, no HTTP types) → `app/core` (security primitives, errors).
4. Every behaviour change needs a test. Security-relevant changes need a negative test (the attack that must fail).
5. Never log or return secrets; use `app.core.security.redact`. Never add inline scripts/handlers (strict CSP).
6. Do not present estimates as measurements; label them in the UI and in reports.
