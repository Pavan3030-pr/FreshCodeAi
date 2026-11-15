"""MINIMAL FastAPI/Starlette stand-in used ONLY when real FastAPI is not installed (offline sandbox).
It implements just what this project uses so routes, middleware and auth flows can be exercised end to end. It is not
FastAPI: real runs (and CI) use the real package, which is the authority."""
import asyncio
import inspect
import re
import typing
import urllib.parse

from fastapi.responses import JSONResponse, Response, StreamingResponse


class _Headers(dict):
    def __init__(self, items=()):
        super().__init__({k.lower(): v for k, v in dict(items).items()})

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _State:
    pass


class _URL:
    def __init__(self, path):
        self.path = path


class Request:
    def __init__(self, method, path, headers, cookies, client, query):
        self.method, self.url, self.headers, self.cookies = method, _URL(path), _Headers(headers), cookies
        self.client = type("C", (), {"host": client})()
        self.state, self.query_params = _State(), query


def _compile(path):
    names = re.findall(r"{(\w+)}", path)
    return re.compile("^" + re.sub(r"{\w+}", r"([^/]+)", path) + "$"), names


class _Routes:
    def __init__(self):
        self.routes = []

    def _reg(self, method):
        def outer(path, **_kw):
            def deco(fn):
                self.routes.append((method, path, fn))
                return fn
            return deco
        return outer

    def get(self, p, **k): return self._reg("GET")(p, **k)
    def post(self, p, **k): return self._reg("POST")(p, **k)
    def patch(self, p, **k): return self._reg("PATCH")(p, **k)
    def delete(self, p, **k): return self._reg("DELETE")(p, **k)
    def put(self, p, **k): return self._reg("PUT")(p, **k)


class APIRouter(_Routes):
    def __init__(self, prefix=""):
        super().__init__()
        self.prefix = prefix

    def _reg(self, method):
        inner = super()._reg(method)
        return lambda path, **k: inner(self.prefix + path, **k)


class FastAPI(_Routes):
    def __init__(self, **_kw):
        super().__init__()
        self.mw = None
        self.handlers = {}
        self.mounts = {}

    def mount(self, path, app, name=None):
        self.mounts[path] = app

    def include_router(self, router):
        self.routes.extend(router.routes)

    def middleware(self, kind):
        def deco(fn):
            self.mw = fn
            return fn
        return deco

    def exception_handler(self, cls):
        def deco(fn):
            self.handlers[cls] = fn
            return fn
        return deco

    # ---- dispatch ----
    async def _route(self, request, body):
        path = request.url.path
        for prefix, static in self.mounts.items():
            if path.startswith(prefix + "/"):
                return static.serve(path[len(prefix) + 1:])
        for method, pattern, fn in self.routes:
            rx, names = _compile(pattern)
            m = rx.match(path)
            if m and method == request.method:
                return await self._call(fn, request, dict(zip(names, m.groups())), body)
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    async def _call(self, fn, request, pathvars, body):
        from pydantic import BaseModel, ValidationError
        sig = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
        kwargs = {}
        try:
            for name, param in sig.parameters.items():
                hint = hints.get(name)
                if hint is Request:
                    kwargs[name] = request
                elif inspect.isclass(hint) and issubclass(hint, BaseModel):
                    kwargs[name] = hint(**(body if isinstance(body, dict) else {}))
                elif name in pathvars:
                    kwargs[name] = hint(pathvars[name]) if hint in (int, float) else pathvars[name]
                elif name in request.query_params:
                    raw = request.query_params[name]
                    kwargs[name] = (raw.lower() in ("1", "true", "yes")) if hint is bool else (hint(raw) if hint in (int, float) else raw)
                elif param.default is not inspect.Parameter.empty:
                    kwargs[name] = param.default
        except (ValidationError, ValueError) as exc:
            errs = exc.errors() if hasattr(exc, "errors") else [{"loc": [], "msg": str(exc)}]
            return JSONResponse({"detail": [{"loc": ["body"] + e["loc"], "msg": e["msg"]} for e in errs]}, status_code=422)
        try:
            result = await fn(**kwargs)
        except Exception as exc:
            for cls, handler in self.handlers.items():
                if isinstance(exc, cls):
                    return await handler(request, exc)
            raise
        return result if isinstance(result, Response) else JSONResponse(result)

    async def handle(self, method, target, headers=None, body=b"", client="127.0.0.1"):
        parsed = urllib.parse.urlparse(target)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        headers = headers or {}
        cookies = {}
        for part in (headers.get("cookie") or headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        import json as _json
        try:
            parsed_body = _json.loads(body) if body else {}
        except ValueError:
            parsed_body = {}
        request = Request(method, parsed.path, headers, cookies, client, query)

        async def call_next(req):
            return await self._route(req, parsed_body)

        if self.mw:
            return await self.mw(request, call_next)
        return await call_next(request)


class _Static:
    def __init__(self, directory):
        self.directory = directory

    def serve(self, rel):
        import mimetypes
        f = (self.directory / rel).resolve()
        if not str(f).startswith(str(self.directory.resolve())) or not f.is_file():
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return Response(f.read_bytes(), media_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream")
