"""SQLite persistence with versioned migrations and per-user scoped repositories (stdlib only).

One connection guarded by a lock; WAL for file databases; foreign keys ON. Every query that touches user data takes a
`user_id`, so one user can never read another user's rows. The SQL is portable by design (no SQLite-only features beyond
`IS ?` null-safe equality), but PostgreSQL is NOT implemented in this release.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

MAX_PAYLOAD = 200_000

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "runs baseline", """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  tokens_in INTEGER,
  tokens_total INTEGER,
  savings_pct REAL,
  summary TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_kind ON runs(kind);
"""),
    (2, "accounts, sessions, projects, audit", """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  last_login_at REAL
);
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  csrf TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_expiry ON sessions(expires_at);
CREATE TABLE projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'python',
  constraints TEXT NOT NULL DEFAULT '',
  context_budget INTEGER NOT NULL DEFAULT 900,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE (user_id, name)
);
CREATE INDEX idx_projects_user ON projects(user_id, archived);
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  request_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_audit_user_ts ON audit_log(user_id, ts DESC);
CREATE INDEX idx_audit_ts ON audit_log(ts DESC);
ALTER TABLE runs ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE runs ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
CREATE INDEX idx_runs_user_created ON runs(user_id, created_at DESC);
CREATE INDEX idx_runs_project ON runs(project_id);
"""),
]


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Store:
    def __init__(self, path: str = ":memory:", history_limit: int = 500, clock=time.time):
        self.path = path
        self.history_limit = history_limit
        self.clock = clock
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # explicit transactions
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    # ---------- infrastructure ----------
    @contextmanager
    def _tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _q(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)")
            done = {r["version"] for r in self._conn.execute("SELECT version FROM schema_migrations")}
        for version, name, sql in MIGRATIONS:
            if version in done:
                continue
            with self._tx() as c:
                for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
                    c.execute(stmt)
                c.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (version, name, self.clock()))
            applied.append(version)
        return applied

    def schema_version(self) -> int:
        rows = self._q("SELECT MAX(version) v FROM schema_migrations")
        return rows[0]["v"] or 0

    def ping(self) -> bool:
        return self._q("SELECT 1 x")[0]["x"] == 1

    # ---------- users ----------
    def create_user(self, email: str, password_hash: str, *, display_name: str = "", role: str = "user") -> dict:
        with self._tx() as c:
            cur = c.execute("INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES(?,?,?,?,?)",
                            (email, password_hash, display_name[:80], role, self.clock()))
            uid = cur.lastrowid
        return self.get_user(uid)

    def count_users(self) -> int:
        return self._q("SELECT COUNT(*) n FROM users")[0]["n"]

    @staticmethod
    def _user(row, secret: bool = False) -> Optional[dict]:
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        if not secret:
            d.pop("password_hash", None)
        return d

    def get_user(self, user_id: int) -> Optional[dict]:
        rows = self._q("SELECT * FROM users WHERE id=?", (user_id,))
        return self._user(rows[0]) if rows else None

    def get_user_by_email(self, email: str, *, with_hash: bool = False) -> Optional[dict]:
        rows = self._q("SELECT * FROM users WHERE email=?", (email,))
        return self._user(rows[0], secret=with_hash) if rows else None

    def get_user_secret(self, user_id: int) -> Optional[dict]:
        rows = self._q("SELECT * FROM users WHERE id=?", (user_id,))
        return self._user(rows[0], secret=True) if rows else None

    def set_password(self, user_id: int, password_hash: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))

    def update_profile(self, user_id: int, display_name: str) -> dict:
        with self._tx() as c:
            c.execute("UPDATE users SET display_name=? WHERE id=?", (display_name[:80], user_id))
        return self.get_user(user_id)

    def touch_login(self, user_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE users SET last_login_at=? WHERE id=?", (self.clock(), user_id))

    def delete_user(self, user_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM users WHERE id=?", (user_id,))

    # ---------- sessions ----------
    def create_session(self, user_id: int, token_hash: str, csrf: str, ttl_seconds: float, *, ip: str = "", user_agent: str = "") -> dict:
        now = self.clock()
        with self._tx() as c:
            c.execute("INSERT INTO sessions(user_id,token_hash,csrf,created_at,last_seen_at,expires_at,ip,user_agent) VALUES(?,?,?,?,?,?,?,?)",
                      (user_id, token_hash, csrf, now, now, now + ttl_seconds, ip[:64], user_agent[:200]))
        return self.get_session(token_hash)

    def get_session(self, token_hash: str) -> Optional[dict]:
        rows = self._q("SELECT s.*, u.email, u.display_name, u.role, u.disabled FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash,))
        return {k: rows[0][k] for k in rows[0].keys()} if rows else None

    def touch_session(self, session_id: int, new_expiry: float) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET last_seen_at=?, expires_at=? WHERE id=?", (self.clock(), new_expiry, session_id))

    def delete_session(self, token_hash: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def delete_session_by_id(self, user_id: int, session_id: int) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).rowcount

    def delete_user_sessions(self, user_id: int, except_id: Optional[int] = None) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM sessions WHERE user_id=? AND id IS NOT ?", (user_id, except_id)).rowcount

    def list_sessions(self, user_id: int) -> list[dict]:
        now = self.clock()
        return [{k: r[k] for k in ("id", "created_at", "last_seen_at", "expires_at", "ip", "user_agent")}
                for r in self._q("SELECT * FROM sessions WHERE user_id=? AND expires_at>? ORDER BY last_seen_at DESC", (user_id, now))]

    def purge_expired_sessions(self) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM sessions WHERE expires_at<?", (self.clock(),)).rowcount

    # ---------- projects ----------
    @staticmethod
    def _project(row) -> dict:
        d = {k: row[k] for k in row.keys()}
        d["archived"] = bool(d["archived"])
        return d

    def create_project(self, user_id: int, name: str, *, description: str = "", language: str = "python", constraints: str = "", context_budget: int = 900) -> dict:
        now = self.clock()
        with self._tx() as c:
            cur = c.execute("INSERT INTO projects(user_id,name,description,language,constraints,context_budget,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (user_id, name, description, language, constraints, context_budget, now, now))
            pid = cur.lastrowid
        return self.get_project(pid, user_id)

    def get_project(self, project_id: int, user_id: int) -> Optional[dict]:
        rows = self._q("SELECT p.*, (SELECT COUNT(*) FROM runs r WHERE r.project_id=p.id) AS run_count FROM projects p WHERE p.id=? AND p.user_id=?", (project_id, user_id))
        return self._project(rows[0]) if rows else None

    def list_projects(self, user_id: int, *, include_archived: bool = False, q: str = "") -> list[dict]:
        sql = "SELECT p.*, (SELECT COUNT(*) FROM runs r WHERE r.project_id=p.id) AS run_count FROM projects p WHERE p.user_id=?"
        params: list[Any] = [user_id]
        if not include_archived:
            sql += " AND p.archived=0"
        if q:
            sql += " AND (p.name LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\')"
            params += [_like(q), _like(q)]
        return [self._project(r) for r in self._q(sql + " ORDER BY p.archived, p.updated_at DESC", params)]

    def update_project(self, project_id: int, user_id: int, **fields) -> Optional[dict]:
        allowed = {"name", "description", "language", "constraints", "context_budget", "archived"}
        sets = {k: (int(v) if k == "archived" else v) for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.get_project(project_id, user_id)
        with self._tx() as c:
            cur = c.execute(f"UPDATE projects SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE id=? AND user_id=?",
                            (*sets.values(), self.clock(), project_id, user_id))
            if cur.rowcount == 0:
                return None
        return self.get_project(project_id, user_id)

    def delete_project(self, project_id: int, user_id: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).rowcount > 0

    # ---------- runs ----------
    def add_run(self, kind: str, title: str, status: str = "ok", *, latency_ms: Optional[int] = None, tokens_in: Optional[int] = None,
                tokens_total: Optional[int] = None, savings_pct: Optional[float] = None, summary: str = "", payload: Optional[dict] = None,
                user_id: Optional[int] = None, project_id: Optional[int] = None) -> int:
        body = json.dumps(payload or {}, ensure_ascii=False, default=str)
        if len(body) > MAX_PAYLOAD:
            body = json.dumps({"truncated": True, "note": "payload exceeded storage limit"})
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO runs(created_at,kind,title,status,latency_ms,tokens_in,tokens_total,savings_pct,summary,payload,user_id,project_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.clock(), kind, title[:200], status, latency_ms, tokens_in, tokens_total, savings_pct, summary[:500], body, user_id, project_id))
            rid = cur.lastrowid
            c.execute("DELETE FROM runs WHERE user_id IS ? AND id NOT IN (SELECT id FROM runs WHERE user_id IS ? ORDER BY id DESC LIMIT ?)",
                      (user_id, user_id, self.history_limit))
        return int(rid)

    @staticmethod
    def _row(row, with_payload: bool = False) -> dict:
        d = {k: row[k] for k in row.keys() if k != "payload"}
        if with_payload:
            try:
                d["payload"] = json.loads(row["payload"])
            except ValueError:
                d["payload"] = {}
        return d

    def list_runs(self, limit: int = 50, kind: Optional[str] = None, *, user_id: Optional[int] = None, project_id: Optional[int] = None,
                  status: Optional[str] = None, q: str = "", offset: int = 0) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        where, params = ["user_id IS ?"], [user_id]
        if kind:
            where.append("kind=?"); params.append(kind)
        if project_id is not None:
            where.append("project_id=?"); params.append(project_id)
        if status:
            where.append("status=?"); params.append(status)
        if q:
            where.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')"); params += [_like(q), _like(q)]
        rows = self._q(f"SELECT * FROM runs WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, max(0, int(offset))))
        return [self._row(r) for r in rows]

    def get_run(self, run_id: int, user_id: Optional[int] = None) -> Optional[dict]:
        rows = self._q("SELECT * FROM runs WHERE id=? AND user_id IS ?", (run_id, user_id))
        return self._row(rows[0], True) if rows else None

    def clear(self, user_id: Optional[int] = None) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM runs WHERE user_id IS ?", (user_id,)).rowcount

    def count_runs_since(self, user_id: int, since: float, kinds: Optional[Iterable[str]] = None) -> int:
        sql, params = "SELECT COUNT(*) n FROM runs WHERE user_id=? AND created_at>=?", [user_id, since]
        if kinds:
            ks = list(kinds)
            sql += f" AND kind IN ({','.join('?' * len(ks))})"; params += ks
        return self._q(sql, params)[0]["n"]

    def stats(self, user_id: Optional[int] = None) -> dict[str, Any]:
        u = (user_id,)
        by_kind = {r["kind"]: r["n"] for r in self._q("SELECT kind, COUNT(*) n FROM runs WHERE user_id IS ? GROUP BY kind", u)}
        agg = self._q("SELECT COUNT(*) total, AVG(latency_ms) avg_latency, SUM(tokens_total) tokens_total FROM runs WHERE user_id IS ?", u)[0]
        sav = self._q("SELECT AVG(savings_pct) avg_savings, MAX(savings_pct) best_savings, COUNT(*) n FROM runs WHERE user_id IS ? AND kind='benchmark' AND savings_pct IS NOT NULL", u)[0]
        toks = self._q("SELECT SUM(tokens_in) tin, SUM(tokens_total - tokens_in) tout FROM runs WHERE user_id IS ? AND tokens_in IS NOT NULL AND tokens_total IS NOT NULL", u)[0]
        tests = self._q("SELECT SUM(status='ok') passed, COUNT(*) n FROM runs WHERE user_id IS ? AND kind='test'", u)[0]
        return {
            "total_runs": agg["total"] or 0, "by_kind": by_kind,
            "avg_latency_ms": round(agg["avg_latency"]) if agg["avg_latency"] is not None else None,
            "provider_tokens_total": agg["tokens_total"] or 0, "provider_tokens_in": toks["tin"] or 0, "provider_tokens_out": max(0, toks["tout"] or 0),
            "benchmark_runs_measured": sav["n"] or 0,
            "avg_token_savings_pct": round(sav["avg_savings"], 1) if sav["avg_savings"] is not None else None,
            "best_token_savings_pct": round(sav["best_savings"], 1) if sav["best_savings"] is not None else None,
            "test_runs": tests["n"] or 0,
            "test_pass_rate": round(100 * (tests["passed"] or 0) / tests["n"]) if tests["n"] else None,
        }

    # ---------- audit ----------
    def add_audit(self, action: str, *, user_id: Optional[int] = None, detail: str = "", ip: str = "", request_id: str = "") -> None:
        with self._tx() as c:
            c.execute("INSERT INTO audit_log(ts,user_id,action,detail,ip,request_id) VALUES(?,?,?,?,?,?)", (self.clock(), user_id, action[:60], detail[:300], ip[:64], request_id[:32]))

    def list_audit(self, *, user_id: Optional[int] = None, limit: int = 100, all_users: bool = False) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        if all_users:
            rows = self._q("SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?", (limit,))
        else:
            rows = self._q("SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT ?", (user_id, limit))
        return [{k: r[k] for k in r.keys()} for r in rows]
