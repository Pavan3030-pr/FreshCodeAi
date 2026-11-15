# Database schema (SQLite, migrations in `app/services/db.py`)

Versioned migrations run at startup (`schema_migrations`). Foreign keys are ON; deleting a user cascades to sessions, projects and runs; audit rows keep `user_id = NULL`.

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `users` | accounts | `email` UNIQUE, `password_hash` (scrypt), `role` CHECK in (user, admin), `disabled` |
| `sessions` | server-side sessions | `token_hash` UNIQUE (SHA-256 of the cookie token; the raw token is never stored), `csrf`, `expires_at`, `ip`, `user_agent`; index on `user_id`, `expires_at` |
| `projects` | per-user projects | UNIQUE(`user_id`, `name`), `language`, `constraints`, `context_budget`, `archived` |
| `runs` | every agent/freshness/benchmark/test/demo run | `user_id` → users CASCADE, `project_id` → projects SET NULL, `kind`, `status`, `latency_ms`, `tokens_in`, `tokens_total`, `savings_pct`, `payload` JSON (capped at 200 KB); indexes `(user_id, created_at)`, `project_id` |
| `audit_log` | security-relevant events | `action`, `detail`, `ip`, `request_id`, `user_id` SET NULL |

Transactions: every write uses `BEGIN IMMEDIATE … COMMIT` with rollback on error. History is pruned per user to `HISTORY_LIMIT`.

**Backups:** stop writes or use SQLite's online backup, e.g. `sqlite3 data/freshcode.db ".backup 'backup.db'"` (WAL mode: copy `-wal` too if copying files). Schedule it and keep copies off the host.
