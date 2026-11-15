import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from app.services.db import MIGRATIONS, Store


def mk():
    s = Store(":memory:")
    a = s.create_user("a@example.com", "h", display_name="Ada")
    b = s.create_user("b@example.com", "h")
    return s, a, b


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    return False


def test_migrations_apply_once_and_report_version():
    s = Store(":memory:")
    assert s.schema_version() == MIGRATIONS[-1][0] and s.migrate() == [] and s.ping()


def test_upgrade_from_a_v4_database_keeps_old_rows():
    d = tempfile.mkdtemp()
    path = str(Path(d) / "old.db")
    c = sqlite3.connect(path)
    c.executescript(MIGRATIONS[0][2])  # exactly the v4.x schema
    c.execute("INSERT INTO runs(created_at,kind,title,status,summary,payload) VALUES(1,'demo','old','ok','','{}')")
    c.commit(); c.close()
    s = Store(path)
    assert s.schema_version() == MIGRATIONS[-1][0]
    assert s.list_runs(10, user_id=None)[0]["title"] == "old"  # legacy rows remain under the system owner (NULL)
    u = s.create_user("x@example.com", "h")
    assert s.list_runs(10, user_id=u["id"]) == []  # and are not visible to any real user


def test_user_uniqueness_and_secret_hash_never_leaks_by_default():
    s, a, _ = mk()
    assert raises(sqlite3.IntegrityError, s.create_user, "a@example.com", "h")
    assert "password_hash" not in a and "password_hash" not in s.get_user_by_email("a@example.com")
    assert s.get_user_by_email("a@example.com", with_hash=True)["password_hash"] == "h"
    assert raises(sqlite3.IntegrityError, s.create_user, "c@example.com", "h", role="superuser")


def test_runs_are_isolated_between_users():
    s, a, b = mk()
    ra = s.add_run("code", "A's secret task", "ok", user_id=a["id"], payload={"k": 1})
    rb = s.add_run("code", "B's task", "ok", user_id=b["id"])
    assert [r["id"] for r in s.list_runs(10, user_id=a["id"])] == [ra]
    assert s.get_run(ra, user_id=b["id"]) is None and s.get_run(ra, user_id=a["id"])["payload"] == {"k": 1}
    assert s.list_runs(10, user_id=b["id"], q="secret") == []
    assert s.stats(a["id"])["total_runs"] == 1 and s.stats(b["id"])["total_runs"] == 1
    assert s.clear(a["id"]) == 1 and s.get_run(rb, user_id=b["id"]) is not None


def test_history_pruning_is_per_user():
    s = Store(":memory:", history_limit=3)
    a, b = s.create_user("a@example.com", "h"), s.create_user("b@example.com", "h")
    for i in range(6):
        s.add_run("code", f"a{i}", user_id=a["id"])
    s.add_run("code", "b0", user_id=b["id"])
    assert len(s.list_runs(50, user_id=a["id"])) == 3 and len(s.list_runs(50, user_id=b["id"])) == 1


def test_search_and_filters_escape_wildcards():
    s, a, _ = mk()
    s.add_run("verify", "100% sure", "ok", user_id=a["id"], summary="x")
    s.add_run("code", "plain", "failed", user_id=a["id"])
    assert len(s.list_runs(10, user_id=a["id"], q="%")) == 1 and len(s.list_runs(10, user_id=a["id"], q="_")) == 0
    assert [r["title"] for r in s.list_runs(10, user_id=a["id"], status="failed")] == ["plain"]
    assert [r["title"] for r in s.list_runs(10, user_id=a["id"], kind="verify")] == ["100% sure"]


def test_projects_crud_scoping_and_cascade_to_runs():
    s, a, b = mk()
    p = s.create_project(a["id"], "API gateway", description="d", language="java", context_budget=600)
    assert p["language"] == "java" and p["archived"] is False and p["run_count"] == 0
    assert raises(sqlite3.IntegrityError, s.create_project, a["id"], "API gateway")  # unique per user
    assert s.create_project(b["id"], "API gateway")["id"] != p["id"]  # different users may reuse a name
    assert s.get_project(p["id"], b["id"]) is None and s.update_project(p["id"], b["id"], name="hijack") is None
    assert s.update_project(p["id"], a["id"], name="Renamed", archived=True)["archived"] is True
    assert s.list_projects(a["id"]) == [] and len(s.list_projects(a["id"], include_archived=True)) == 1
    r = s.add_run("code", "t", user_id=a["id"], project_id=p["id"])
    assert s.get_project(p["id"], a["id"])["run_count"] == 1 and len(s.list_runs(10, user_id=a["id"], project_id=p["id"])) == 1
    assert s.delete_project(p["id"], b["id"]) is False and s.delete_project(p["id"], a["id"]) is True
    assert s.get_run(r, user_id=a["id"])["project_id"] is None  # run survives, link cleared


def test_deleting_a_user_cascades_everything_but_keeps_anonymous_audit():
    s, a, b = mk()
    p = s.create_project(a["id"], "p"); s.add_run("code", "t", user_id=a["id"], project_id=p["id"])
    s.create_session(a["id"], "hash1", "csrf", 60); s.add_audit("login", user_id=a["id"])
    s.delete_user(a["id"])
    assert s.list_runs(10, user_id=a["id"]) == [] and s.list_projects(a["id"], include_archived=True) == [] and s.get_session("hash1") is None
    assert s.list_audit(all_users=True)[0]["user_id"] is None and s.get_user(b["id"]) is not None


def test_sessions_lifecycle():
    s, a, b = mk()
    s1 = s.create_session(a["id"], "h1", "c1", 60, ip="1.1.1.1", user_agent="UA")
    s.create_session(a["id"], "h2", "c2", 60); s.create_session(b["id"], "h3", "c3", 60)
    assert s1["email"] == "a@example.com" and s1["csrf"] == "c1" and len(s.list_sessions(a["id"])) == 2
    assert s.delete_session_by_id(b["id"], s1["id"]) == 0  # cannot revoke someone else's session
    assert s.delete_user_sessions(a["id"], except_id=s1["id"]) == 1 and [x["id"] for x in s.list_sessions(a["id"])] == [s1["id"]]
    assert s.get_session("h3") is not None
    s.create_session(a["id"], "old", "c", -5)
    assert s.list_sessions(a["id"]) and s.purge_expired_sessions() == 1 and s.get_session("old") is None


def test_transaction_rolls_back_on_error():
    s, a, _ = mk()
    try:
        with s._tx() as c:
            c.execute("INSERT INTO projects(user_id,name,created_at,updated_at) VALUES(?,?,?,?)", (a["id"], "half", time.time(), time.time()))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert s.list_projects(a["id"], include_archived=True) == []


def test_audit_is_scoped_per_user_and_truncates():
    s, a, b = mk()
    s.add_audit("login", user_id=a["id"], detail="x" * 1000, ip="9.9.9.9"); s.add_audit("login", user_id=b["id"])
    mine = s.list_audit(user_id=a["id"])
    assert len(mine) == 1 and len(mine[0]["detail"]) == 300 and len(s.list_audit(all_users=True)) == 2


def test_concurrent_writes_are_serialised_without_loss():
    s, a, _ = mk()
    s.history_limit = 10_000
    errs = []

    def work(n):
        try:
            for i in range(25):
                s.add_run("code", f"t{n}-{i}", user_id=a["id"])
        except Exception as e:  # pragma: no cover
            errs.append(e)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errs and s.stats(a["id"])["total_runs"] == 200
