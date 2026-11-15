# Security

## Implemented (each has tests; see the matrix below)
| Control | Detail |
|---|---|
| Passwords | scrypt (N=2^14, r=8, p=1), per-user salt, constant-work login even for unknown accounts, policy (≥10 chars, common/all-digit/low-variety rejected) |
| Sessions | random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in production); only the SHA-256 is stored; sliding idle expiry + absolute cap; revocation per session; password change signs out other sessions |
| CSRF | synchronizer token per session in `X-CSRF-Token` for every non-GET request, plus SameSite cookies |
| Authorization | every query on user data is scoped by `user_id`; admin-only audit view; first account is admin |
| Brute force | per email+IP login throttle (429), global and heavy-endpoint rate limits, per-user daily run quota |
| Input/output | schema validation (422), language allow-pattern, escaped output in the UI, only http(s) links rendered, CSV formula-injection neutralised |
| SSRF | `validate_outbound_url` blocks non-http(s), credentials in URLs, private/loopback/link-local/metadata addresses (used to validate `BIFROST_BASE_URL` in production). The app never fetches user-supplied URLs |
| Secrets | redaction filter on all log output and on provider error text; keys never returned by any endpoint; public health reveals nothing but status/version |
| Headers | strict CSP (`script-src 'self'`, no inline scripts), HSTS when secure cookies are on, nosniff, frame deny, referrer/permissions/COOP |
| Errors | typed errors; unexpected exceptions return a generic 500 and are logged redacted |
| Audit | register/login/failed login/throttle/password/profile/project/session/export/clear/delete events with IP and request id |
| Supply chain | pinned dependencies; `pip-audit` runs in CI (`make audit`) |

## Code execution — read this
Generated code is untrusted. Three modes (`RUNNER_MODE`):
- `off` — nothing is executed (default in production).
- `local` — **not a sandbox.** An AST/regex policy, resource limits, timeout and process-group kill reduce accidents but a determined attacker can escape. Development only.
- `docker` — disposable container per run: `--network none`, read-only root, `--cap-drop ALL`, `no-new-privileges`, non-root uid 65534, 256 MB / 1 CPU / 64 PIDs, source mounted read-only, no secrets in the environment, killed on timeout, max 2 concurrent. **The command builder is unit-tested; running it needs a Docker host and was not exercised in the development sandbox.** Mounting the Docker socket into the app container gives that container control of the host: prefer running the app on a host with Docker, or a dedicated runner service.

## Test matrix (what actually runs)
Unit: security core, auth service, DB isolation/migrations, runner policy and limits · API: auth, CSRF on every mutating route, cross-user access, quotas, rate limits, error leakage, headers · Browser E2E: registration, isolation between two users, CSRF refusal, session revocation, account deletion, sign-out · see README for the exact commands and `docs/TESTING.md` for results policy.

## Not done / remaining
PostgreSQL; MFA and password reset by email; per-IP+account lockout persistence across restarts (throttle is in memory); distributed rate limiting; live container-runner verification; external penetration test; dependency audit result (needs network — run `make audit`).

## v5.1 review notes
- No backend security code changed in v5.1: the change set is front-end, tests and docs. Sessions and CSRF, per-user query scoping, SSRF URL validation, secret redaction, CSP and HSTS are unchanged and their tests pass.
- New front-end code renders model output only through `esc()` or the escaping highlighter (a Node test feeds markup through it). No new inline scripts and no new external origins: fonts are self-hosted.
- The sign-in throttle counts attempts per window, including successful ones (six sign-ins from one address were refused in the browser tests). It is kept; tests reuse a session.
- Execution: the local runner is labelled "NOT A SANDBOX" in Test Lab and the agent. Docker isolation is implemented and unit-tested at the command level only. It was NOT run on a Docker host in this release.
- Not performed: dependency audit (`make audit` needs network), external penetration test, load test.
