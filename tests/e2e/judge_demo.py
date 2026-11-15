"""Judge demo: a ~2 minute guided browser walkthrough recorded as judge-demo.webm.
Usage: python tests/e2e/judge_demo.py <recording_dir> <screenshot_dir>. Providers are stubbed by tests/e2e/server.py (labelled in the UI/docs)."""
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REC = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/judge"); REC.mkdir(parents=True, exist_ok=True)
SHOT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/judge-shots"); SHOT.mkdir(parents=True, exist_ok=True)
PORT = 8772; BASE = f"http://127.0.0.1:{PORT}"
PW = "judge demo passphrase 42"
server = subprocess.Popen([sys.executable, str(Path(__file__).parent / "server.py"), str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(80):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1); break
        except Exception:
            time.sleep(.25)
    with sync_playwright() as p:
        b = p.chromium.launch(slow_mo=350)
        c = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(REC / "_raw"), record_video_size={"width": 1440, "height": 900})
        pg = c.new_page(); hold = lambda ms=1200: pg.wait_for_timeout(ms)
        pg.goto(BASE + "/"); hold(); pg.locator("#bifrost").scroll_into_view_if_needed(); hold(); pg.locator("#tavily").scroll_into_view_if_needed(); hold(); pg.evaluate("window.scrollTo(0,0)")
        pg.click("header >> text=Get started"); pg.fill("#su-name", "Judge Demo"); pg.fill("#su-email", "judge.demo@example.com"); pg.fill("#su-password", PW); hold(600); pg.screenshot(path=SHOT / "judge_registration.png"); pg.click("#su-submit")
        pg.wait_for_url(re.compile(r"/app")); pg.wait_for_selector("#user-chip:not([hidden])"); hold()
        pg.click('[data-view="agent"]'); pg.click("[data-preset=agent-2]"); pg.select_option("#language", "javascript")
        pg.fill("#task", "Write a JavaScript function slugify(text) that lowercases, trims and joins words with hyphens. Include tests."); hold(600)
        pg.click("#generate"); pg.wait_for_selector("text=Self-repaired", timeout=40000); hold(2500)
        pg.click("[data-code-tab=tests]"); hold(1500); pg.click("[data-code-tab=impl]"); hold(800)
        pg.click('[data-view="verify"]'); hold(); pg.click("[data-preset=verify-1]"); pg.click("#verify-btn"); pg.wait_for_selector("#verify-result .claim", timeout=30000); hold(3000)
        pg.click('[data-view="history"]'); hold(2000)
        pg.click('[data-view="settings"]'); hold(2000)
        pg.click('[data-view="overview"]'); hold(1500)
        vpath = pg.video.path(); c.close(); Path(vpath).replace(REC / "judge-demo.webm"); b.close()
    print("judge demo recorded:", REC / "judge-demo.webm")
finally:
    server.terminate()
