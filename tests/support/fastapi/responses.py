import json


class Response:
    def __init__(self, content=b"", status_code=200, headers=None, media_type=None):
        self.body = content.encode() if isinstance(content, str) else content
        self.status_code = status_code
        self.headers = {}
        self.cookies_out = []
        for k, v in (headers or {}).items():
            self.headers[k] = v
        if media_type:
            self.headers["content-type"] = media_type

    def set_cookie(self, key, value, max_age=None, httponly=False, secure=False, samesite=None, path="/"):
        c = f"{key}={value}; Path={path}" + (f"; Max-Age={max_age}" if max_age is not None else "") + ("; HttpOnly" if httponly else "") + ("; Secure" if secure else "") + (f"; SameSite={samesite}" if samesite else "")
        self.cookies_out.append(c)

    def delete_cookie(self, key, path="/"):
        self.cookies_out.append(f"{key}=; Path={path}; Max-Age=0")


class JSONResponse(Response):
    def __init__(self, content, status_code=200, headers=None):
        super().__init__(json.dumps(content).encode(), status_code, headers, "application/json")


class HTMLResponse(Response):
    def __init__(self, content="", status_code=200, headers=None):
        super().__init__(content, status_code, headers, "text/html; charset=utf-8")


class RedirectResponse(Response):
    def __init__(self, url, status_code=307):
        super().__init__(b"", status_code, {"location": url})


class StreamingResponse(Response):
    def __init__(self, gen, status_code=200, headers=None, media_type=None):
        super().__init__(b"", status_code, headers, media_type)
        self.gen = gen
