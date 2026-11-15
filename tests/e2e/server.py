"""E2E server: the REAL app code behind a stdlib HTTP adapter (offline sandbox has no uvicorn), with the Bifrost and Tavily
NETWORK calls replaced by a deterministic stub. Nothing else is faked: auth, sessions, CSRF, DB, agent, runner, reports are real."""
import asyncio
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import conftest  # noqa: E402,F401  (hermetic env + emulator when FastAPI is absent)
os.environ.update({"BIFROST_API_KEY": "e2e-bifrost-key", "TAVILY_API_KEY": "tvly-e2e-key", "BIFROST_MODEL": "e2e-model", "DB_PATH": str(Path(tempfile.mkdtemp()) / "e2e.db"),
                   "RATE_LIMIT_PER_MINUTE": "100000", "HEAVY_RATE_LIMIT_PER_MINUTE": "100000", "CACHE_TTL_SECONDS": "0", "RUNNER_TIMEOUT_SECONDS": "6"})

import app.services.bifrost as bifrost_mod  # noqa: E402
import app.services.tavily as tavily_mod  # noqa: E402
import app.main as main  # noqa: E402

LONG = ("Skip to content. Subscribe to our newsletter. " + "Spring Boot is a framework for building production-ready applications quickly and reliably. " * 12 +
        "Spring Boot 3.5.1 is now available and is the current stable release. Requires Java 17 or later. All rights reserved. Cookie policy.")
BUGGY = "exports.slugify = (s) => s.toLowerCase().replace(/ /g, '_');"          # wrong separator on purpose
FIXED = "exports.slugify = (s) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');"
TESTS = ("const test = require('node:test');\nconst assert = require('node:assert');\nconst { slugify } = require('./solution');\n"
         "test('slugifies words', () => { assert.equal(slugify('Hello World'), 'hello-world'); });\n"
         "test('trims edges', () => { assert.equal(slugify('  A b  '), 'a-b'); });\n")


async def fake_tavily(service, url, **kw):
    q = kw["payload"]["query"]
    return ({"request_id": "tvly-req-" + str(abs(hash(q)) % 9999), "response_time": 0.41, "results": [
        {"title": "Spring Boot 3.5.1 released", "url": "https://spring.io/blog/spring-boot-3-5-1", "content": LONG, "score": 0.93, "published_date": "2026-05-22"},
        {"title": "Spring Boot reference documentation", "url": "https://docs.spring.io/spring-boot/reference/", "content": LONG[:600] + " Reference documentation for 3.5.1.", "score": 0.88},
        {"title": "Which Spring Boot version?", "url": "https://stackoverflow.com/q/1", "content": "I am on Spring Boot 3.4 and it works.", "score": 0.4}]}, {})


async def fake_bifrost(service, url, **kw):
    msgs = kw["payload"]["messages"]; user = msgs[-1]["content"]; system = msgs[0]["content"]
    tokens = max(1, (len(system) + len(user)) // 4)
    if "evidence auditor" in system:
        content = "[]"
    elif "The tests failed" in user:
        content = "```javascript\n" + FIXED + "\n```"
    else:
        content = "Assumes ASCII.\n```javascript\n" + BUGGY + "\n```\n```javascript\n" + TESTS + "```"
    return ({"model": kw["payload"]["model"], "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": tokens, "completion_tokens": 60, "total_tokens": tokens + 60}}, {"x-request-id": "bifrost-req-1"})


bifrost_mod.post_json = fake_bifrost
tavily_mod.post_json = fake_tavily
app = main.app


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _serve(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        resp = asyncio.run(app.handle(method, self.path, headers, body, self.client_address[0]))
        data = resp.body
        if hasattr(resp, "gen"):
            async def drain():
                return b"".join([(c.encode() if isinstance(c, str) else c) async for c in resp.gen])
            data = asyncio.run(drain())
        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        for c in resp.cookies_out:
            self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self): self._serve("GET")
    def do_POST(self): self._serve("POST")
    def do_PATCH(self): self._serve("PATCH")
    def do_DELETE(self): self._serve("DELETE")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    if hasattr(app, "handle"):  # offline emulator in use: serve through the stdlib adapter
        ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    else:  # real FastAPI installed: serve the same app (with the same provider stubs) through uvicorn
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
