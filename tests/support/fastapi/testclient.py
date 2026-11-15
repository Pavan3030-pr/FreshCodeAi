import asyncio
import json as _json

from fastapi.responses import StreamingResponse


class _Resp:
    def __init__(self, status_code, headers, content):
        self.status_code, self.headers, self.content = status_code, headers, content

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return _json.loads(self.content)


class TestClient:
    __test__ = False

    def __init__(self, app, client="127.0.0.1"):
        self.app, self.cookies, self._client = app, {}, client

    def request(self, method, url, json=None, headers=None, **_):
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if self.cookies:
            h["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        body = _json.dumps(json).encode() if json is not None else b""

        async def go():
            resp = await self.app.handle(method, url, h, body, self._client)
            data = resp.body
            if isinstance(resp, StreamingResponse):
                chunks = []
                async for part in resp.gen:
                    chunks.append(part.encode() if isinstance(part, str) else part)
                data = b"".join(chunks)
            return resp, data

        resp, data = asyncio.run(go())
        for c in resp.cookies_out:
            name, rest = c.split("=", 1)
            if "Max-Age=0" in c:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = rest.split(";", 1)[0]
        return _Resp(resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, data)

    def get(self, url, **k): return self.request("GET", url, **k)
    def head(self, url, **k): return self.request("HEAD", url, **k)
    def post(self, url, **k): return self.request("POST", url, **k)
    def patch(self, url, **k): return self.request("PATCH", url, **k)
    def delete(self, url, **k): return self.request("DELETE", url, **k)
