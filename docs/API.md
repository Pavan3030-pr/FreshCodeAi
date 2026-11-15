# API v1

Interactive OpenAPI: `/api/v1/docs` (schema at `/api/v1/openapi.json`). All routes except those marked *public* need the `fc_session` cookie; state-changing requests also need `X-CSRF-Token` (returned by login/register/`/auth/me`).

| Area | Endpoints |
|---|---|
| Ops | `GET /api/health` (public, minimal) · `GET /api/v1/ready` (public) · `GET /api/v1/system` |
| Auth | `POST /auth/register` · `POST /auth/login` · `GET /auth/me` · `POST /auth/logout` · `PATCH /auth/profile` · `POST /auth/password` · `GET /auth/sessions` · `DELETE /auth/sessions/{id}` · `POST /auth/sessions/revoke-others` · `POST /auth/delete-account` |
| Projects | `GET/POST /projects` · `GET/PATCH/DELETE /projects/{id}` |
| Workspace | `POST /code` · `POST /code/stream` (SSE) · `POST /verify` · `POST /benchmark` · `POST /test` · `POST /demo` (public) · `GET /eval` (public) |
| Records | `GET /runs` (`q`, `kind`, `status`, `project_id`, `limit`, `offset`) · `GET /runs/{id}` · `DELETE /runs` · `GET /runs/export.csv` · `GET /runs/{id}/report.md` · `GET /runs/{id}/benchmark.csv` |
| Account data | `GET /stats` · `GET /usage` · `GET /audit?scope=me|all` (all = admin) |

Errors are JSON: `{"detail": "...", "error": {"code": "...", "message": "..."}}` with codes such as `auth_required`, `csrf_failed`, `invalid_credentials`, `forbidden`, `not_found`, `conflict`, `quota_exceeded`, `rate_limited`, `upstream_error`, `internal_error`. Validation failures are HTTP 422.
