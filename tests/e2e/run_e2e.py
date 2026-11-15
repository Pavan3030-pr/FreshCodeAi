"""Browser end-to-end journeys (Playwright + Chromium) against tests/e2e/server.py.

Run: python tests/e2e/run_e2e.py [screenshot_dir]
Environment: E2E_RECORD_DIR=<dir> records Chromium video of the main journey (full-user-journey.webm) and a Playwright trace; E2E_SLOWMO=<ms> slows actions so recordings are watchable.
The Bifrost/Tavily NETWORK calls are stubbed by the server; everything else (auth, DB, agent, runner, reports, UI) is real.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/e2e")
OUT.mkdir(parents=True, exist_ok=True)
RECORD = Path(os.environ["E2E_RECORD_DIR"]) if os.environ.get("E2E_RECORD_DIR") else None
SLOWMO = int(os.environ.get("E2E_SLOWMO", "0"))
if RECORD:
    RECORD.mkdir(parents=True, exist_ok=True)
PORT = 8771
BASE = f"http://127.0.0.1:{PORT}"
PW = "a sufficiently long phrase"
results = []


def until(pred, timeout=8.0, msg="condition not met"):
    """Poll a Python-side predicate (page.wait_for_function would need eval, which the app's strict CSP forbids)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return
        except Exception:
            pass
        time.sleep(0.15)
    raise AssertionError(msg)


def overflow(page):
    return page.evaluate("""() => { if (document.documentElement.scrollWidth <= window.innerWidth + 2) return [];
      return Array.from(document.querySelectorAll('body *')).filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 2 && !e.closest('.nav') && !e.closest('.table-wrap'); })
        .slice(0, 6).map(e => (e.id ? '#' + e.id : '') + '.' + String(e.className).slice(0, 30) + ' <' + e.tagName + '> right=' + Math.round(e.getBoundingClientRect().right)); }""")


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
                results.append((True, name, ""))
            except Exception as exc:  # record and continue so one failure does not hide the rest
                try:
                    pg.screenshot(path=OUT / f"FAILED_{name[:2]}.png", full_page=True)
                except Exception:
                    pass
                results.append((False, name, f"{type(exc).__name__}: {str(exc)[:300]}"))
        return run
    return deco


server = subprocess.Popen([sys.executable, str(ROOT / "tests/e2e/server.py"), str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.25)

try:
    with sync_playwright() as p:
        b = p.chromium.launch(slow_mo=SLOWMO)

        def ctx(w=1440, h=900, record=False, state=None):
            kw = {"record_video_dir": str(RECORD / "_raw"), "record_video_size": {"width": w, "height": h}} if (record and RECORD) else {}
            c = b.new_context(viewport={"width": w, "height": h}, permissions=["clipboard-read", "clipboard-write"], storage_state=state, **kw)
            if record and RECORD:
                c.tracing.start(screenshots=True, snapshots=False, sources=False)
            pg = c.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and not re.search(r"\b(401|403|404|409|422)\b", m.text) else None)
            return c, pg, errs

        c1, pg, errs = ctx(record=True)

        @step("01 landing page loads and leads to sign-up")
        def landing():
            pg.goto(BASE + "/")
            pg.wait_for_selector("text=Lean tokens.")
            for sec in ("how", "bifrost", "tavily", "compression", "verification", "freshness", "evidence", "security", "architecture", "faq"):
                pg.locator(f"#{sec}").scroll_into_view_if_needed(); pg.wait_for_timeout(250 if SLOWMO else 0)
            assert pg.locator("img.l-shot").evaluate("i => i.complete && i.naturalWidth > 0"), "hero product screenshot did not load"
            assert pg.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(255, 255, 255)"
            pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(300)
            pg.screenshot(path=OUT / "01_landing.png")
            pg.click("header >> text=Get started")
            pg.wait_for_url(re.compile(r"/login#signup"))
        landing()

        @step("02 anonymous /app redirects to /login; API refuses without a session")
        def anon():
            pg.goto(BASE + "/app")
            pg.wait_for_url(re.compile(r"/login\?next="))
            r = pg.request.get(BASE + "/api/v1/projects")
            assert r.status == 401, r.status
        anon()

        @step("03 register: weak password rejected, strong accepted, lands in the app")
        def register():
            pg.goto(BASE + "/login#signup")
            pg.fill("#su-name", "Ada Lovelace"); pg.fill("#su-email", "ada@example.com"); pg.fill("#su-password", "short")
            pg.click("#su-submit")
            pg.wait_for_selector("#auth-error:not([hidden])")
            assert "10 characters" in pg.inner_text("#auth-error")
            pg.screenshot(path=OUT / "02_registration_error.png")
            pg.fill("#su-password", PW)
            assert "Strength" in pg.inner_text("#pw-label")
            pg.click("#su-submit")
            pg.wait_for_url(re.compile(r"/app"))
            pg.wait_for_selector("#user-chip:not([hidden])")
            assert "Ada Lovelace" in pg.inner_text("#user-name")
            pg.wait_for_timeout(500)
            pg.screenshot(path=OUT / "03_overview.png", full_page=True)
            assert pg.evaluate("document.documentElement.hasAttribute('data-theme')") is False
        register()

        @step("04 projects: create, duplicate refused, edit, archive/restore, confirm-delete")
        def projects():
            pg.click('[data-view="projects"]')
            pg.wait_for_selector("#empty-new")
            pg.screenshot(path=OUT / "04_projects_empty.png")
            pg.click("#empty-new")
            pg.fill("#pf-name", "Token gateway"); pg.select_option("#pf-language", "javascript"); pg.fill("#pf-constraints", "Node 22, no dependencies"); pg.fill("#pf-budget", "600")
            pg.click("#pf-save")
            pg.wait_for_selector(".project-card:has-text('Token gateway')")
            pg.click("[data-pact=edit]")
            pg.fill("#pf-name", "Token gateway v2")
            pg.click("#pf-save")
            pg.wait_for_selector(".project-card:has-text('Token gateway v2')")
            pg.click("#project-new")
            pg.fill("#pf-name", "Token gateway v2")
            pg.click("#pf-save")
            pg.wait_for_selector("#pf-error:not([hidden])")
            assert "already exists" in pg.inner_text("#pf-error")
            pg.click("#pf-cancel")
            pg.screenshot(path=OUT / "05_projects.png")
            pg.click("[data-pact=archive]")
            pg.wait_for_selector("#empty-new")
            pg.check("#project-archived")
            pg.wait_for_selector(".project-card.archived")
            pg.click("[data-pact=archive]")  # restore
            pg.uncheck("#project-archived")
            pg.wait_for_selector(".project-card:has-text('Token gateway v2')")
            pg.click("[data-pact=delete]")
            pg.wait_for_selector("#confirm:not([hidden])")
            pg.click("#confirm-cancel")
            assert pg.locator(".project-card").count() == 1
            pg.click("[data-pact=delete]")
            pg.click("#confirm-ok")
            pg.wait_for_selector("#empty-new")
            pg.click("#empty-new")
            pg.fill("#pf-name", "Slug service"); pg.select_option("#pf-language", "javascript"); pg.fill("#pf-budget", "700")
            pg.click("#pf-save")
            pg.wait_for_selector(".project-card:has-text('Slug service')")
        projects()

        @step("05 agent: three regions, project defaults, tests fail then one repair succeeds, 11-stage trace, code tabs, copy, download")
        def agent():
            pg.select_option("#project-select", label="Slug service")
            pg.click('[data-view="agent"]')
            assert pg.input_value("#language") == "javascript" and pg.input_value("#budget") == "700"
            assert pg.input_value("#agent-project") == pg.input_value("#project-select")
            for region in (".ws-config", ".ws-main", ".ws-exec"):
                assert pg.is_visible(region), region
            assert pg.locator("#pipeline li").count() == 11
            pg.screenshot(path=OUT / "05_agent_empty.png")
            pg.fill("#task", "Write a JavaScript function slugify(text) that lowercases, trims and joins words with hyphens. Include tests.")
            pg.click("#generate")
            pg.wait_for_selector("text=Self-repaired", timeout=30000)
            body = pg.inner_text("#agent-result")
            for needle in ("Run trace", "repair", "PROVIDER INPUT TOKENS", "MEASURED BY PROVIDER", "ESTIMATED LOCALLY", "TESTS PASSED", "Tavily sources"):
                assert needle in body, needle
            assert "slugify" in pg.inner_text("#agent-output")
            assert pg.locator("#pipeline li.done").count() >= 9, pg.locator("#pipeline li.done").count()
            assert pg.locator("#pipeline li.error").count() == 0
            assert pg.is_visible("#retry-run") and pg.inner_text("#run-state") == "Complete"
            pg.click("summary:has-text('Activity log')")
            log = pg.inner_text("#activity")
            assert "[verify]" in log and "[generate]" in log
            pg.screenshot(path=OUT / "06_engineering_agent.png")
            
            pg.click("[data-code-tab=tests]"); pg.wait_for_selector("[data-pane-id=tests]:not([hidden])")
            assert "slugify" in pg.inner_text("[data-pane-id=tests]") and "tk-" in pg.inner_html("[data-pane-id=tests]")
            pg.click("[data-code-tab=impl]")
            pg.click("[data-act=copy-code]")
            until(lambda: "slugify" in pg.evaluate("navigator.clipboard.readText()"), msg="clipboard did not receive the code")
            with pg.expect_download() as dl:
                pg.click("[data-act=download-code]")
            assert dl.value.suggested_filename.endswith(".js")
            with pg.expect_download() as dl2:
                pg.click("[data-act=download-tests]")
            assert ".test." in dl2.value.suggested_filename
            pg.click("[data-act=expand]")
            assert pg.locator("#code-card .code-block.expanded").count() >= 1
            pg.locator("#agent-result").scroll_into_view_if_needed()
            pg.screenshot(path=OUT / "08_execution_trace.png", full_page=True)
            pg.evaluate("window.scrollTo(0,0)")
        agent()

        @step("06 a run can be cancelled")
        def cancel():
            pg.fill("#task", "Write a JavaScript function slugify(text) again, worded differently so that it is not served from cache.")
            # in-page timing, so the stop click lands mid-run even when E2E_SLOWMO slows Playwright's own actions
            pg.evaluate("() => { document.getElementById('generate').click(); setTimeout(() => document.getElementById('cancel-run').click(), 100); }")
            pg.wait_for_selector("text=Run stopped", timeout=8000)
            assert pg.inner_text("#run-state") == "Stopped" and pg.is_visible("#retry-run")
        cancel()

        @step("07 freshness: outdated claim flagged, correction suggested, sources cited with proof of retrieval")
        def verify():
            pg.click('[data-view="verify"]')
            pg.fill("#verify-text", "Spring Boot 3.4 is the latest stable version. The service costs $19 per month.")
            pg.click("#verify-btn")
            pg.wait_for_selector("#verify-result .claim", timeout=30000)
            txt = pg.inner_text("#verify-result")
            assert "Possibly outdated" in txt or "POSSIBLY OUTDATED" in txt.upper()
            for needle in ("3.5.1", "Suggested correction", "Primary source", "Proof of live retrieval", "Corrected answer"):
                assert needle in txt, needle
            pg.screenshot(path=OUT / "09_freshness.png", full_page=True)
        verify()

        @step("08 evaluation lab: three-task paired benchmark, raw CSV export")
        def bench():
            pg.click('[data-view="benchmarks"]')
            pg.fill("#bench-task", "Write a JavaScript function that debounces another function with cancel support.")
            pg.fill("#bench-extra", "Write a JavaScript function that deep-clones plain objects safely.\nWrite a JavaScript function that groups an array by key.")
            pg.click("#bench-btn")
            pg.wait_for_selector("text=PROVIDER MEASURED", timeout=90000)
            txt = pg.inner_text("#bench-result")
            assert "median input-token saving" in txt and "3 task(s)" in txt and "Download raw CSV" in txt
            pg.screenshot(path=OUT / "10_evaluation_lab.png", full_page=True)
            href = pg.get_attribute("a:has-text('Download raw CSV')", "href")
            r = pg.request.get(BASE + href)
            assert r.status == 200 and r.text().startswith("task_index,task,variant")
            assert len(r.text().strip().splitlines()) == 19, len(r.text().strip().splitlines())  # header + 3 tasks x 2 variants x 3 trials
        bench()

        @step("09 test lab: safe JS passes, malicious JS is blocked by policy")
        def tests():
            pg.click('[data-view="tests"]')
            pg.select_option("#test-lang", "javascript")
            pg.fill("#test-code", "exports.add=(a,b)=>a+b;")
            pg.fill("#test-suite", "const test=require('node:test');const assert=require('node:assert');const {add}=require('./solution');test('a',()=>{assert.equal(add(1,2),3)});")
            pg.click("#test-btn")
            pg.wait_for_selector("text=ALL TESTS PASSED", timeout=20000)
            pg.fill("#test-code", "const cp = require('child_process'); exports.add=(a,b)=>a+b;")
            pg.click("#test-btn")
            pg.wait_for_selector("text=BLOCKED", timeout=20000)
            assert "NOT A SANDBOX" in pg.inner_text("#runner-mode") or "ISOLATED" in pg.inner_text("#runner-mode")
            pg.screenshot(path=OUT / "11_test_lab.png", full_page=True)
        tests()

        @step("10 history: filter, search, trace, Markdown report, CSV export, empty filter state")
        def history():
            pg.click('[data-view="history"]')
            pg.wait_for_selector("#history-list .list-item")
            n_all = pg.locator("#history-list .list-item").count()
            assert n_all >= 5, n_all
            pg.select_option("#hist-kind", "benchmark")
            pg.wait_for_timeout(700)
            assert pg.locator("#history-list .list-item").count() == 1
            pg.select_option("#hist-kind", "")
            pg.fill("#hist-q", "slugify")
            pg.wait_for_timeout(800)
            assert 1 <= pg.locator("#history-list .list-item").count() < n_all
            pg.click("[data-trace]")
            pg.wait_for_selector(".trace-slot .trace-row", timeout=5000)
            pg.screenshot(path=OUT / "12_history.png", full_page=True)
            href = pg.get_attribute("a:has-text('Report')", "href")
            r = pg.request.get(BASE + href)
            assert r.status == 200 and "# FreshCode report" in r.text()
            csv = pg.request.get(BASE + "/api/v1/runs/export.csv")
            assert csv.status == 200 and csv.text().startswith("id,created_at")
            pg.fill("#hist-q", "zzzz-nothing")
            pg.wait_for_selector("text=No runs match these filters")
        history()

        @step("10b integrations: honest provider status, no secrets shown")
        def integrations():
            pg.click('[data-view="settings"]')
            pg.wait_for_selector("#conn-grid .card")
            txt = pg.inner_text("#conn-grid") + pg.inner_text("#deploy-dl")
            assert "Bifrost gateway" in txt and "Tavily Search" in txt and "e2e-bifrost-key" not in txt and "tvly-e2e-key" not in txt
            assert txt.count("erified") >= 2 and "Configured" in txt  # every provider card states verified / not verified; nothing is faked
            pg.screenshot(path=OUT / "13_integrations.png", full_page=True)
        integrations()

        @step("11 account: profile, usage, audit trail, sessions, reduced-motion preference (no theme switch)")
        def account():
            pg.click('[data-view="account"]')
            pg.wait_for_selector("#pr-email")
            assert pg.input_value("#pr-email") == "ada@example.com"
            pg.fill("#pr-name", "Ada L.")
            pg.click("#profile-form button[type=submit]")
            until(lambda: pg.inner_text("#user-name") == "Ada L.", msg="header name did not update")
            pg.click('[data-acct="usage"]')
            pg.wait_for_selector("#usage-body .quota")
            txt = pg.inner_text("#usage-body")
            assert "/ 200" in txt and "RUNS REMAINING" in txt
            pg.screenshot(path=OUT / "10_usage.png")
            pg.click('[data-acct="audit"]')
            pg.wait_for_selector("#audit-list .list-item")
            a = pg.inner_text("#audit-list")
            assert "register" in a and "project created" in a.lower()
            pg.click('[data-acct="security"]')
            pg.wait_for_selector("#session-list .list-item")
            assert "This device" in pg.inner_text("#session-list")
            pg.screenshot(path=OUT / "14_account.png", full_page=True)
            pg.click('[data-acct="preferences"]')
            assert pg.locator("[data-theme-set]").count() == 0
            pg.check("[data-motion-toggle]")
            assert pg.evaluate("document.documentElement.dataset.motion") == "off"
            pg.uncheck("[data-motion-toggle]")
        account()

        @step("12 isolation: a second user sees none of the first user's data")
        def isolation():
            c2, p2, _ = ctx()
            p2.goto(BASE + "/login#signup")
            p2.fill("#su-email", "bob@example.com"); p2.fill("#su-password", PW)
            p2.click("#su-submit")
            p2.wait_for_url(re.compile(r"/app"))
            p2.wait_for_selector("#user-chip:not([hidden])")
            assert p2.request.get(BASE + "/api/v1/runs").json()["runs"] == []
            assert p2.request.get(BASE + "/api/v1/projects").json()["projects"] == []
            first_run = pg.request.get(BASE + "/api/v1/runs").json()["runs"][0]["id"]
            assert p2.request.get(BASE + f"/api/v1/runs/{first_run}").status == 404
            assert p2.request.get(BASE + f"/api/v1/runs/{first_run}/report.md").status == 404
            p2.click('[data-view="account"]')
            p2.click('[data-acct="audit"]')
            p2.wait_for_selector("#audit-list .list-item")
            assert "ada@example.com" not in p2.inner_text("#audit-list")
            assert p2.request.get(BASE + "/api/v1/audit?scope=all").status == 403
            c2.close()
        isolation()

        @step("13 CSRF: forged state-changing request without the token is refused")
        def csrf():
            r = pg.request.post(BASE + "/api/v1/projects", data={"name": "evil"})
            assert r.status == 403 and r.json()["error"]["code"] == "csrf_failed"
        csrf()

        @step("14 wrong password refused; revoking other sessions signs them out")
        def password():
            c3, p3, _ = ctx()
            p3.goto(BASE + "/login")
            p3.fill("#si-email", "ada@example.com"); p3.fill("#si-password", "wrong password!!")
            p3.click("#si-submit")
            p3.wait_for_selector("#auth-error:not([hidden])")
            assert "Incorrect email or password" in p3.inner_text("#auth-error")
            p3.fill("#si-password", PW)
            p3.click("#si-submit")
            p3.wait_for_url(re.compile(r"/app"))
            p3.wait_for_selector("#user-chip:not([hidden])")
            pg.click('[data-view="account"]')
            pg.click('[data-acct="security"]')
            pg.wait_for_selector("#session-list .list-item")
            pg.wait_for_timeout(300)
            pg.click('[data-acct="profile"]'); pg.click('[data-acct="security"]')
            until(lambda: pg.locator("#session-list .list-item").count() == 2, msg="expected 2 sessions")
            pg.click("#revoke-others")
            pg.wait_for_selector("#confirm:not([hidden])")
            pg.click("#confirm-ok")
            until(lambda: pg.locator("#session-list .list-item").count() == 1, msg="expected 1 session after revoke")
            assert p3.request.get(BASE + "/api/v1/auth/me").status == 401
            c3.close()
        password()

        @step("15 delete-account requires the right password and removes access")
        def delete_flow():
            c4, p4, _ = ctx()
            p4.goto(BASE + "/login#signup")
            p4.fill("#su-email", "tmp@example.com"); p4.fill("#su-password", PW)
            p4.click("#su-submit")
            p4.wait_for_url(re.compile(r"/app"))
            p4.wait_for_selector("#user-chip:not([hidden])")
            p4.click('[data-view="account"]'); p4.click('[data-acct="security"]'); p4.click("#delete-account")
            p4.wait_for_selector("#confirm-pw")
            p4.fill("#confirm-pw", "wrong password"); p4.click("#confirm-ok")
            p4.wait_for_selector("#toast.show")
            assert "/app" in p4.url
            p4.click("#delete-account"); p4.fill("#confirm-pw", PW); p4.click("#confirm-ok")
            p4.wait_for_url(BASE + "/")
            assert p4.request.post(BASE + "/api/v1/auth/login", data={"email": "tmp@example.com", "password": PW}).status == 401
            c4.close()
        delete_flow()

        @step("16 sign out ends access; guest demo works without an account")
        def logout():
            pg.click("#signout")
            pg.wait_for_url(re.compile(r"/login"))
            assert pg.request.get(BASE + "/api/v1/auth/me").status == 401
            pg.goto(BASE + "/app")
            pg.wait_for_url(re.compile(r"/login\?next="))
            pg.goto(BASE + "/login")
            pg.click("text=Try the guest demo")
            pg.wait_for_selector("text=End-to-end demo complete", timeout=25000)
            assert pg.is_visible("#guest-banner") and pg.is_disabled('[data-view="agent"]')
            pg.screenshot(path=OUT / "15_guest_demo.png")
        logout()

        @step("17 responsive matrix: no horizontal overflow at 1440/1280/1024/768/390/360 on landing, login, app views; mobile drawer works")
        def mobile():
            c0, p0, _ = ctx()  # sign in ONCE and reuse the session: the sign-in throttle (5 attempts / window) is a real security control
            p0.goto(BASE + "/login"); p0.fill("#si-email", "ada@example.com"); p0.fill("#si-password", PW); p0.click("#si-submit")
            p0.wait_for_url(re.compile(r"/app")); p0.wait_for_selector("#user-chip:not([hidden])")
            state = c0.storage_state(); c0.close()
            for (w, h) in ((1440, 900), (1280, 800), (1024, 768), (768, 1024), (390, 844), (360, 800)):
                cm, pm, _ = ctx(w, h)
                for path in ("/", "/login"):
                    pm.goto(BASE + path); pm.wait_for_timeout(250)
                    if path == "/login":
                        pm.wait_for_timeout(100)
                    assert not overflow(pm), f"overflow {w}px on {path}: {overflow(pm)}"
                    if w == 390 and path == "/":
                        pm.screenshot(path=OUT / "16_mobile_landing.png")
                    if w == 390 and path == "/login":
                        pm.screenshot(path=OUT / "17_mobile_login.png")
                cm.close()
                cm, pm, _ = ctx(w, h, state=state)
                pm.goto(BASE + "/app"); pm.wait_for_selector("#user-chip:not([hidden])"); pm.wait_for_timeout(400)
                narrow = w <= 900
                for view in ("overview", "projects", "agent", "verify", "benchmarks", "tests", "history", "settings", "account"):
                    if narrow:
                        pm.click("#menu-btn"); pm.wait_for_selector(f'#sidebar [data-view="{view}"]', state="visible"); pm.wait_for_timeout(250)
                    pm.click(f'#sidebar [data-view="{view}"]'); pm.wait_for_timeout(250)
                    assert not overflow(pm), f"overflow {w}px on #{view}: {overflow(pm)}"
                    if narrow:
                        assert pm.locator("#app-shell.drawer-open").count() == 0, "drawer should close after navigating"
                    if w == 390 and view in ("overview", "agent", "history"):
                        pm.screenshot(path=OUT / f"18_mobile_{view}.png")
                if w >= 1280:  # collapsible sidebar on desktop
                    pm.click("#collapse-nav"); assert pm.locator("#app-shell.collapsed").count() == 1
                    pm.click("#collapse-nav"); assert pm.locator("#app-shell.collapsed").count() == 0
                if w <= 1280:  # workspace panes become tabs
                    pm.click('#sidebar [data-view="agent"]') if not narrow else (pm.click("#menu-btn"), pm.click('#sidebar [data-view="agent"]'))
                    for pane in ("config", "exec", "main"):
                        pm.click(f'.ws-tabs [data-pane="{pane}"]')
                        assert pm.is_visible(f".ws-{pane}"), pane
                cm.close()
        mobile()

        @step("18 no unexpected JavaScript errors in the main browser session")
        def noerrors():
            assert not errs, errs[:3]
        noerrors()
        if RECORD:
            c1.tracing.stop(path=str(RECORD / "full-user-journey-trace.zip"))
            vpath = pg.video.path()
            c1.close()
            Path(vpath).replace(RECORD / "full-user-journey.webm")
        b.close()
finally:
    server.terminate()

width = max(len(n) for _, n, _ in results)
for ok, name, detail in results:
    print(("PASS " if ok else "FAIL ") + name.ljust(width) + ("" if ok else "  " + detail))
bad = [r for r in results if not r[0]]
print(f"\n{len(results) - len(bad)}/{len(results)} journeys passed")
sys.exit(1 if bad else 0)
