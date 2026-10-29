"""Fathom web app: a WSGI application (``fathom.server:app``) plus a threaded
development server (``fathom serve``). Production runs it under gunicorn or
any WSGI host; see the Dockerfile.

Routes are registered with :func:`route` (method, regex pattern, role, OpenAPI
metadata); the full contract is docs/SPEC.md §5 and ``GET /api/openapi.json``.
Engine modules owned by other units (merge overlay, library, floor plans,
schedules, trace, search, assistant, renderers, builds) are imported lazily
inside their handlers, so a missing or broken module only breaks its own
endpoints.

Environment
-----------
FATHOM_DATA            data dir (default ~/.fathom)
FATHOM_HOST/PORT       dev server bind (default 127.0.0.1:8080)
FATHOM_AUTH            "user:pass[,user2:pass2]" in-memory admins (enables auth)
FATHOM_PUBLIC_VIEW=1   viewer (/p/*) and builds stay public when auth is on
FATHOM_MAX_UPLOAD_MB   multipart cap (default 50)
FATHOM_MAX_JSON_MB     JSON body cap (default 20)
FATHOM_MAX_BACKUP_MB   backup upload cap (default 4096)
FATHOM_PUBLIC_URL      base URL for QR codes when settings.public_url is empty
FATHOM_DEV=1           serve /static/dev/* harnesses to non-loopback clients
FATHOM_CHROME          Chrome / Chromium binary for server-side PDF / PNG
"""

from __future__ import annotations

import base64
import hashlib
import html as html_mod
import inspect
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import traceback
import webbrowser
from email import message_from_bytes
from email.policy import default as email_default_policy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple
from urllib.parse import parse_qs, quote

from . import __version__
from .project import (
    SAMPLES_DIR,
    STATIC_DIR,
    ConflictError,
    PreconditionError,
    ValidationError,
    builds_root,
    delete_project,
    ensure_data_dirs,
    find_project_file,
    list_builds,
    list_projects,
    new_build_dir,
    new_project,
    project_info,
    project_info_v2,
    projects_root,
    safe_name,
)

_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SEG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_UPLOAD = int(os.environ.get("FATHOM_MAX_UPLOAD_MB") or 50) * 1024 * 1024
MAX_OPS = 2000
_NAME = r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,63})"
_EID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"

APP_CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
           "connect-src 'self'; frame-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
VIEWER_CSP = APP_CSP.replace("script-src 'self';", "script-src 'self' 'unsafe-inline';")
FILE_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
STATIC_EXT = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8",
}
SHELL_ASSETS = [
    "./", "static/app.html", "static/login.html", "static/css/app.css", "static/css/patchview.css", "static/css/plan.css",
    "static/js/app.js", "static/js/api.js", "static/js/model-core.js", "static/js/inspector.js", "static/js/assistant-ui.js",
    "static/js/patchtable.js", "static/js/patchtable-core.js", "static/js/patchview.js", "static/js/patchview-core.js",
    "static/js/floorplan.js", "static/js/floorplan-core.js", "static/js/rack.js", "static/js/rack-core.js",
    "static/js/schedules.js", "static/js/inventory.js", "static/js/views-admin.js", "static/js/merge-ui.js", "static/js/views-discovery.js", "static/js/suggest-ui.js",
    "static/js/views-sop.js", "static/css/sop.css", "static/icons/icon-192.png", "manifest.webmanifest",
]
SCHEDULE_KINDS = ("patch", "cables", "ip", "dmx", "bom", "inventory", "racks", "labels")
_STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content", 302: "Found", 304: "Not Modified", 400: "Bad Request", 401: "Unauthorized",
    403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
    415: "Unsupported Media Type", 422: "Unprocessable Entity", 428: "Precondition Required", 429: "Too Many Requests",
    500: "Internal Server Error", 507: "Insufficient Storage",
}
_DEFAULT_CODES = {
    400: "bad_request", 401: "auth_required", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict",
    413: "too_large", 415: "unsupported_format", 422: "invalid", 428: "precondition_required", 429: "throttled", 500: "internal",
    507: "no_space",
}


def _max_upload() -> int:
    return int(float(os.environ.get("FATHOM_MAX_UPLOAD_MB") or 50) * 1024 * 1024)


def _max_json() -> int:
    return int(float(os.environ.get("FATHOM_MAX_JSON_MB") or 20) * 1024 * 1024)


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "", details: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.details = details
        self.headers = headers or {}


# ------------------------------------------------------------------ helpers


def _safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = _SAFE_FILE_RE.sub("_", base).strip(" .")
    return base or "upload"


def _project_dir(name: str) -> Path:
    if not safe_name(name):
        raise ApiError(400, "bad project name")
    pf = find_project_file(projects_root() / name)
    if pf is None:
        raise ApiError(404, f"project '{name}' not found")
    return pf.parent


def _contained(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _parse_multipart(content_type: str, body: bytes) -> List[Tuple[str, bytes]]:
    return [(n, d) for n, d, _ in _parse_multipart_full(content_type, body)]


def _parse_multipart_full(content_type: str, body: bytes) -> List[Tuple[str, bytes, str]]:
    msg = message_from_bytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body, policy=email_default_policy)
    files: List[Tuple[str, bytes, str]] = []
    if not msg.is_multipart():
        return files
    for part in msg.iter_parts():
        fname = part.get_filename()
        if not fname:
            continue
        files.append((fname, part.get_payload(decode=True) or b"", part.get_content_type() or ""))
    return files


def _auth_pairs() -> List[Tuple[str, str]]:
    from .users import env_users

    return env_users()


def _compat(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``fn`` with only the keyword arguments its signature accepts."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover
        return fn(*args, **kwargs)
    params = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def _int(v: Any, default: int, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _log_exc(label: str) -> None:
    sys.stderr.write(f"fathom: {label}\n")
    traceback.print_exc(file=sys.stderr)


class Request:
    def __init__(self, environ: Dict[str, Any]) -> None:
        self.environ = environ
        raw_method = environ.get("REQUEST_METHOD", "GET").upper()
        self.is_head = raw_method == "HEAD"
        self.method = "GET" if self.is_head else raw_method
        self.path = environ.get("PATH_INFO", "/") or "/"
        self.query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True).items()}
        self.params: Dict[str, str] = {}
        self.user: Optional[Dict[str, Any]] = None
        self.auth_via = "none"
        self.route: Optional["Route"] = None
        self._body: Optional[bytes] = None

    def header(self, name: str) -> str:
        if name.lower() == "content-type":
            return self.environ.get("CONTENT_TYPE", "") or ""
        if name.lower() == "content-length":
            return self.environ.get("CONTENT_LENGTH", "") or ""
        key = "HTTP_" + name.upper().replace("-", "_")
        return self.environ.get(key, "") or ""

    @property
    def script_root(self) -> str:
        return (self.environ.get("SCRIPT_NAME") or "").rstrip("/")

    @property
    def scheme(self) -> str:
        fwd = self.header("x-forwarded-proto").split(",")[0].strip().lower()
        return fwd or str(self.environ.get("wsgi.url_scheme") or "http")

    @property
    def host(self) -> str:
        h = self.header("host")
        if h:
            return h
        name = str(self.environ.get("SERVER_NAME") or "localhost")
        port = str(self.environ.get("SERVER_PORT") or "")
        default = "443" if self.scheme == "https" else "80"
        return name if not port or port == default else f"{name}:{port}"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"

    @property
    def root_url(self) -> str:
        return self.origin + self.script_root

    @property
    def remote_addr(self) -> str:
        return str(self.environ.get("REMOTE_ADDR") or "")

    def cookie(self, name: str) -> str:
        values = self.cookies(name)
        return values[0] if values else ""

    def cookies(self, name: str) -> List[str]:
        """Every value sent under ``name`` (browsers send one per Path/Domain scope, most specific first)."""
        out: List[str] = []
        for part in self.header("cookie").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name and v:
                out.append(v)
        return out

    def wants_html(self) -> bool:
        return "text/html" in self.header("accept")

    def is_multipart(self) -> bool:
        return "multipart/form-data" in self.header("content-type").lower()

    def body_cap(self) -> int:
        if self.route is not None and self.route.max_body is not None:
            return self.route.max_body()
        return _max_upload() if self.is_multipart() else _max_json()

    def body(self) -> bytes:
        if self._body is None:
            cap = self.body_cap()
            raw_len = self.environ.get("CONTENT_LENGTH") or ""
            stream = self.environ.get("wsgi.input")
            if raw_len:
                try:
                    n = int(raw_len)
                except ValueError:
                    raise ApiError(400, "bad Content-Length")
                if n > cap:
                    raise ApiError(413, f"body larger than {cap // (1024 * 1024)} MB", "too_large")
                self._body = stream.read(n) if n and stream is not None else b""
            elif "chunked" in self.header("transfer-encoding").lower() and stream is not None:
                buf = io.BytesIO()
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    buf.write(chunk)
                    if buf.tell() > cap:
                        raise ApiError(413, f"body larger than {cap // (1024 * 1024)} MB", "too_large")
                self._body = buf.getvalue()
            else:
                self._body = b""
        return self._body

    def json(self) -> Dict[str, Any]:
        raw = self.body()
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, f"bad JSON: {exc}")
        if not isinstance(data, dict):
            raise ApiError(400, "expected a JSON object")
        return data

    def files(self) -> List[Tuple[str, bytes, str]]:
        ctype = self.header("content-type")
        if "multipart/form-data" not in ctype.lower():
            raise ApiError(400, "expected multipart/form-data")
        files = _parse_multipart_full(ctype, self.body())
        if not files:
            raise ApiError(400, "no files in upload")
        return files

    @property
    def username(self) -> str:
        return str((self.user or {}).get("username") or "")

    def role_for(self, project: str = "") -> str:
        from .users import effective_role

        if self.user is None:
            return "viewer"
        return effective_role(self.user, project)


class Response:
    def __init__(self, body: bytes = b"", status: int = 200, content_type: str = "application/json; charset=utf-8", headers: Optional[Dict[str, str]] = None) -> None:
        self.body = body
        self.status = status
        self.headers: Dict[str, str] = {"Content-Type": content_type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        self.headers.update(headers or {})
        self.cookies: List[str] = []
        self.csp: Optional[str] = None
        self.file: Optional[Path] = None

    @classmethod
    def stream_file(cls, path: Path, content_type: str, headers: Optional[Dict[str, str]] = None) -> "Response":
        """Body read from ``path`` in chunks when sent (large downloads)."""
        r = cls(b"", 200, content_type, headers)
        r.file = path
        return r

    @classmethod
    def json(cls, obj: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> "Response":
        return cls(json.dumps(obj, ensure_ascii=False).encode("utf-8"), status, headers=headers)

    @classmethod
    def text(cls, text: str, content_type: str = "text/plain; charset=utf-8", status: int = 200, headers: Optional[Dict[str, str]] = None) -> "Response":
        return cls(text.encode("utf-8"), status, content_type, headers)

    @classmethod
    def empty(cls, status: int = 204) -> "Response":
        r = cls(b"", status)
        r.headers.pop("Content-Type", None)
        return r


def _error_response(status: int, message: str, code: str = "", details: Optional[Dict[str, Any]] = None) -> Response:
    body: Dict[str, Any] = {"error": message, "code": code or _DEFAULT_CODES.get(status, "error")}
    if details is not None:
        body["details"] = details
    return Response.json(body, status)


Handler = Callable[[Request], Response]


# ------------------------------------------------------------------- routes


class Route:
    def __init__(self, method: str, pattern: str, handler: Handler, role: str = "viewer", summary: str = "",
                 tags: Optional[List[str]] = None, body: Optional[str] = None, response: Optional[str] = None, page: str = "api",
                 max_body: Optional[Callable[[], int]] = None) -> None:
        self.method = method
        self.pattern = pattern
        self.regex: Pattern[str] = re.compile("^" + pattern + "$")
        self.handler = handler
        self.role = role
        self.summary = summary or (handler.__doc__ or "").strip().split("\n")[0]
        self.tags = list(tags or [])
        self.body = body
        self.response = response
        self.page = page  # api | app | viewer | static | file | build
        self.max_body = max_body  # body cap override; such handlers read wsgi.input themselves

    @property
    def path(self) -> str:
        from .openapi import path_of

        return path_of(self.pattern)

    def __iter__(self) -> Any:  # v0.2 tuple shape: (method, regex, handler)
        return iter((self.method, self.regex, self.handler))


ROUTES: List[Route] = []
_ROUTES = ROUTES


def route(method: str, pattern: str, role: str = "viewer", summary: str = "", tags: Optional[List[str]] = None,
          body: Optional[str] = None, response: Optional[str] = None, page: str = "api",
          max_body: Optional[Callable[[], int]] = None) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        ROUTES.append(Route(method, pattern, fn, role=role, summary=summary, tags=tags, body=body, response=response, page=page, max_body=max_body))
        return fn

    return deco


def route_table() -> List[Dict[str, Any]]:
    """Registered routes (method, regex pattern, OpenAPI path, role, summary, tags)."""
    return [{"method": r.method, "pattern": r.pattern, "path": r.path, "role": r.role, "summary": r.summary, "tags": list(r.tags)} for r in ROUTES]


# ------------------------------------------------------------- doc helpers


def _load(pdir: Path) -> Tuple[Dict[str, Any], int]:
    from .project import read_doc

    try:
        return read_doc(pdir)
    except FileNotFoundError:
        raise ApiError(404, "project not found")


def _rev(doc: Dict[str, Any]) -> int:
    try:
        return int(doc.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def _etag_rev(req: Request) -> Optional[int]:
    raw = req.header("if-match").strip()
    if not raw:
        return None
    m = re.match(r'^(?:W/)?"?r(\d+)"?$', raw)
    if not m:
        raise ApiError(400, "If-Match must look like \"r<revision>\"")
    return int(m.group(1))


def _imports_hash(doc: Dict[str, Any], pdir: Path) -> str:
    h = hashlib.sha1()
    for imp in doc.get("imports") or []:
        if not isinstance(imp, dict) or not imp.get("path"):
            continue
        p = Path(str(imp["path"]))
        p = p if p.is_absolute() else pdir / p
        items = [p] if p.is_file() else (sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [])
        for f in items:
            try:
                st = f.stat()
                h.update(f"{f}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8", "replace"))
            except OSError:
                continue
    return h.hexdigest()


_CACHE_LOCK = threading.Lock()
_OVERLAY_CACHE: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
_SEARCH_CACHE: Dict[Tuple[str, int], Any] = {}


def _overlay(doc: Dict[str, Any], pdir: Path, strict: bool = True) -> Optional[Dict[str, Any]]:
    key = (str(pdir.resolve()), _rev(doc), _imports_hash(doc, pdir))
    with _CACHE_LOCK:
        hit = _OVERLAY_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from .merge import build_overlay

        ov = build_overlay(doc, pdir)
    except Exception:
        if strict:
            raise
        _log_exc("overlay failed (continuing without)")
        return None
    with _CACHE_LOCK:
        if len(_OVERLAY_CACHE) > 32:
            _OVERLAY_CACHE.clear()
        _OVERLAY_CACHE[key] = ov
    return ov


def _changes(req: Request, pdir: Path, ops: List[Dict[str, Any]], base: int, summary: str, source: str) -> Dict[str, Any]:
    from .project import apply_changes

    return apply_changes(pdir, ops, base_revision=base, author=req.username, summary=summary, source=source)


def _server_ops(req: Request, pdir: Path, ops: List[Dict[str, Any]], summary: str, source: str) -> Dict[str, Any]:
    """Apply server-generated ops on top of the current revision."""
    from .project import current_revision

    return _changes(req, pdir, ops, current_revision(pdir), summary, source)


def _public_base(req: Request, doc: Dict[str, Any]) -> str:
    s = (doc.get("settings") or {}).get("public_url") or os.environ.get("FATHOM_PUBLIC_URL") or req.root_url
    return str(s).rstrip("/")


def _device_url(base: str, project: str, device: str) -> str:
    try:
        from .export import device_url

        return device_url(base, project, device)
    except ImportError:
        return f"{base.rstrip('/')}/p/{quote(project)}/d/{quote(device)}"


def _rel_base(req: Request) -> str:
    depth = max(0, req.path.count("/") - 1)
    return "../" * depth


def _room_ids(doc: Dict[str, Any]) -> List[str]:
    return [str(r.get("id")) for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]


def _csv(columns: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> str:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.get("label", c.get("key")) for c in columns])
    for r in rows:
        out = []
        for c in columns:
            v = r.get(c.get("key"))
            if v is None:
                v = ""
            elif isinstance(v, bool):
                v = "yes" if v else ""
            elif isinstance(v, (list, tuple)):
                v = "; ".join(str(x) for x in v)
            out.append(v)
        w.writerow(out)
    return buf.getvalue()


def _html_table(title: str, columns: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> str:
    e = html_mod.escape
    head = "".join(f'<th scope="col">{e(str(c.get("label", c.get("key"))))}</th>' for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{e('' if r.get(c.get('key')) is None else str(r.get(c.get('key'))))}</td>" for c in columns) + "</tr>" for r in rows)
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{e(title)}</title><style>body{{font:14px system-ui,sans-serif;margin:24px}}table{{border-collapse:collapse}}"
            f"td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}</style></head><body><h1>{e(title)}</h1>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>")


# =================================================================== routes
# ---- app shell, health


@route("GET", "/", role="viewer", summary="Editor (single-page app)", tags=["app"], page="app")
def r_index(req: Request) -> Response:
    html = (STATIC_DIR / "app.html").read_text(encoding="utf-8")
    return Response.text(html, "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@route("GET", "/healthz", role="public", summary="Liveness", tags=["app"])
def r_health(req: Request) -> Response:
    return Response.json({"ok": True, "version": __version__})


@route("GET", "/login", role="public", summary="Login page", tags=["session"], page="app")
def r_login_page(req: Request) -> Response:
    p = STATIC_DIR / "login.html"
    if not p.is_file():
        raise ApiError(404, "login page not installed")
    return Response.text(p.read_text(encoding="utf-8"), "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


# ---- session & users


def _user_out(u: Dict[str, Any]) -> Dict[str, Any]:
    out = {"username": u.get("username"), "role": u.get("role")}
    # Per-project overrides ride along when there are any (the plain {username, role} shape stays for everyone else).
    if u.get("projects"):
        out["projects"] = dict(u.get("projects") or {})
    return out


def _cookie(req: Request, value: str, max_age: int) -> str:
    path = (req.script_root or "") + "/"
    c = f"fathom_session={value}; Path={path}; Max-Age={max_age}; HttpOnly; SameSite=Lax"
    if req.scheme == "https":
        c += "; Secure"
    return c


@route("GET", "/api/v2/session", role="public", summary="Current session", tags=["session"])
def r_session_get(req: Request) -> Response:
    from .users import auth_enabled, public_view

    on = auth_enabled()
    return Response.json({"auth_enabled": on, "authenticated": req.user is not None,
                          "user": _user_out(req.user) if req.user else None, "public_view": public_view()})


@route("POST", "/api/v2/session", role="public", summary="Log in (sets the session cookie)", tags=["session"], body="Login")
def r_session_post(req: Request) -> Response:
    from .users import make_session, note_failure, note_success, throttled, verify

    body = req.json()
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    ip = req.remote_addr
    if throttled(ip, username):
        raise ApiError(429, "too many failed logins; try again in a few minutes", "throttled")
    user = verify(username, password)
    if user is None:
        note_failure(ip, username)
        raise ApiError(401, "wrong username or password", "bad_credentials")
    note_success(ip, username)
    resp = Response.json({"user": _user_out(user)})
    resp.cookies.append(_cookie(req, make_session(user), 1_209_600))
    return resp


@route("DELETE", "/api/v2/session", role="public", summary="Log out", tags=["session"])
def r_session_delete(req: Request) -> Response:
    resp = Response.json({"ok": True})
    resp.cookies.append(_cookie(req, "", 0))
    return resp


def _user_error(exc: Exception) -> ApiError:
    code = getattr(exc, "code", "bad_request")
    status = {"exists": 409, "not_found": 404, "last_admin": 409}.get(code, 400)
    return ApiError(status, str(exc), code)


@route("GET", "/api/v2/users", role="admin", summary="List users", tags=["users"])
def r_users(req: Request) -> Response:
    from .users import list_users

    return Response.json({"users": list_users()})


@route("POST", "/api/v2/users", role="admin", summary="Create a user", tags=["users"], body="User")
def r_users_create(req: Request) -> Response:
    from .users import UserError, add_user

    body = req.json()
    try:
        u = add_user(str(body.get("username") or ""), str(body.get("password") or ""), str(body.get("role") or "editor"), body.get("projects"))
    except UserError as exc:
        raise _user_error(exc)
    return Response.json({"user": u}, 201)


@route("PATCH", r"/api/v2/users/(?P<username>(?!me$)[A-Za-z0-9][A-Za-z0-9._@-]{0,63})", role="admin", summary="Update a user", tags=["users"], body="User")
def r_user_patch(req: Request) -> Response:
    from . import users as U

    name = req.params["username"]
    body = req.json()
    try:
        if U.get_user(name) is None or U.get_user(name).get("source") != "users":
            raise U.UserError(f"user '{name}' not found", "not_found")
        if "role" in body:
            U.set_role(name, str(body["role"]))
        if "password" in body:
            U.set_password(name, str(body["password"]))
        if "disabled" in body:
            U.set_disabled(name, bool(body["disabled"]))
        if "projects" in body:
            U.set_projects(name, body["projects"])
    except U.UserError as exc:
        raise _user_error(exc)
    u = next(x for x in U.list_users() if x["username"] == name)
    return Response.json({"user": u})


@route("DELETE", r"/api/v2/users/(?P<username>(?!me$)[A-Za-z0-9][A-Za-z0-9._@-]{0,63})", role="admin", summary="Delete a user", tags=["users"])
def r_user_delete(req: Request) -> Response:
    from .users import UserError, remove_user

    try:
        remove_user(req.params["username"])
    except UserError as exc:
        raise _user_error(exc)
    return Response.empty(204)


@route("POST", "/api/v2/users/me/password", role="any", summary="Change my password", tags=["users"], body="PasswordChange")
def r_user_password(req: Request) -> Response:
    from .users import UserError, get_user, make_session, set_password, verify

    if not req.user or req.user.get("source") != "users":
        raise ApiError(403, "only users.json accounts can change their password here")
    body = req.json()
    if verify(req.username, str(body.get("old") or "")) is None:
        raise ApiError(403, "wrong current password")
    try:
        set_password(req.username, str(body.get("new") or ""))
    except UserError as exc:
        raise _user_error(exc)
    resp = Response.json({"ok": True})
    if req.auth_via == "cookie":
        fresh = get_user(req.username)
        if fresh:
            resp.cookies.append(_cookie(req, make_session(fresh), 1_209_600))
    return resp


# ---- invites, editing lock, suggestions (phase 2 P2A: FR-USER-11..13, §5.3, §5.16)

_INVITE = r"(?P<invite>inv-[A-Za-z0-9_-]{16,64})"
_STATUS_TEXT.setdefault(423, "Locked")
#: ``settings`` keys the lock op itself may touch while a project is locked
_LOCK_KEYS = ("locked", "locked_by", "locked_at")
_SUGGEST_FORWARD_TIMEOUT = 5.0


def _invite_url(req: Request, token: str) -> str:
    base = str(os.environ.get("FATHOM_PUBLIC_URL") or req.root_url).rstrip("/")
    return f"{base}/invite/{quote(token)}"


@route("GET", "/api/v2/invites", role="admin", summary="Open invite links", tags=["users"])
def r_invites(req: Request) -> Response:
    from .users import list_invites

    return Response.json({"invites": list_invites(), "accept_url": (req.script_root or "") + "/invite/{token}"})


@route("POST", "/api/v2/invites", role="admin", summary="Create a one-time invite link ({role, projects, ttl_hours, note})", tags=["users"], body="Invite")
def r_invites_create(req: Request) -> Response:
    from .users import UserError, create_invite

    body = req.json()
    try:
        inv = create_invite(str(body.get("role") or "editor"), body.get("projects"), created_by=req.username,
                            ttl_hours=body.get("ttl_hours") if body.get("ttl_hours") is not None else 72, note=str(body.get("note") or ""))
    except UserError as exc:
        raise _user_error(exc)
    inv["url"] = _invite_url(req, inv["token"])
    return Response.json(inv, 201)


@route("DELETE", r"/api/v2/invites/" + _INVITE, role="admin", summary="Revoke an invite link", tags=["users"])
def r_invite_delete(req: Request) -> Response:
    from .users import revoke_invite

    if not revoke_invite(req.params["invite"]):
        raise ApiError(404, "invite not found")
    return Response.json({"ok": True})


@route("GET", r"/invite/" + _INVITE, role="public", summary="Invite page (asks the API whether the token is still valid)", tags=["users"], page="app")
def r_invite_page(req: Request) -> Response:
    if req.path.endswith("/"):  # keep the page's relative asset URLs (../static/…) valid
        return Response(b"", 302, "text/plain; charset=utf-8", {"Location": req.script_root + req.path.rstrip("/")})
    p = STATIC_DIR / "invite.html"
    if not p.is_file():
        raise ApiError(404, "invite page not installed")
    return Response.text(p.read_text(encoding="utf-8"), "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@route("GET", r"/api/v2/invites/" + _INVITE + "/check", role="public", summary="Is this invite still open? ({ok, role, expires, auth_enabled} or 404 invalid_invite)", tags=["users"])
def r_invite_check(req: Request) -> Response:
    from .users import auth_enabled, get_invite

    inv = get_invite(req.params["invite"])
    if inv is None:
        raise ApiError(404, "this invite link is no longer valid", "invalid_invite")
    return Response.json({"ok": True, "role": inv.get("role"), "expires": inv.get("expires"), "auth_enabled": auth_enabled()})


@route("POST", r"/api/v2/invites/" + _INVITE + "/accept", role="public", summary="Accept an invite ({username, password}): creates the user and signs them in", tags=["users"], body="Login")
def r_invite_accept(req: Request) -> Response:
    from .users import UserError, make_session, note_failure, note_success, redeem_invite, throttled

    token = req.params["invite"]
    ip = req.remote_addr
    if throttled(ip, token):
        raise ApiError(429, "too many attempts; try again in a few minutes", "throttled")
    body = req.json()
    try:
        user = redeem_invite(token, str(body.get("username") or ""), str(body.get("password") or ""))
    except UserError as exc:
        if exc.code == "not_found":
            note_failure(ip, token)
            raise ApiError(404, str(exc), "invalid_invite")
        raise _user_error(exc)
    note_success(ip, token)
    resp = Response.json({"user": _user_out(user)})
    resp.cookies.append(_cookie(req, make_session(user), 1_209_600))
    return resp


# -- editing lock (settings.locked): /changes and PUT refuse with 423 unless the batch is the unlock itself


def _lock_flags(name: str) -> Dict[str, Any]:
    """``locked`` / ``locked_by`` / ``locked_at`` of a project's settings (for the project list)."""
    from .project import load_dict

    out: Dict[str, Any] = {"locked": False, "locked_by": "", "locked_at": ""}
    pf = find_project_file(projects_root() / name)
    if pf is None:
        return out
    try:
        s = load_dict(pf).get("settings") or {}
    except Exception:
        return out
    if isinstance(s, dict) and s.get("locked") is True:
        out.update({"locked": True, "locked_by": str(s.get("locked_by") or ""), "locked_at": str(s.get("locked_at") or "")})
    return out


def _locked_error(settings: Dict[str, Any]) -> ApiError:
    return ApiError(423, "this project is locked for editing", "locked",
                    {"locked_by": str(settings.get("locked_by") or ""), "locked_at": str(settings.get("locked_at") or "")})


def _lock_only_ops(settings: Dict[str, Any], ops: List[Any]) -> bool:
    """True when every op only touches the lock keys of ``settings`` (a replace counts when nothing else differs)."""
    for op in ops:
        if not isinstance(op, dict) or op.get("op") != "root" or op.get("key") != "settings" or not isinstance(op.get("value"), dict):
            return False
        value = op["value"]
        if op.get("replace"):
            for k in set(settings) | set(value):
                if k not in _LOCK_KEYS and settings.get(k) != value.get(k):
                    return False
        elif any(k not in _LOCK_KEYS for k in value):
            return False
    return True


def _stamp_lock(req: Request, stored: Dict[str, Any], value: Dict[str, Any], replace: bool) -> None:
    """Fill ``locked_by`` / ``locked_at`` in a settings patch that flips ``locked`` (clients only send ``locked``)."""
    from .history import utc_now

    if "locked" not in value and not replace:
        return
    was = stored.get("locked") is True
    now_locked = value.get("locked") is True
    if now_locked and not was:
        value["locked_by"] = req.username or "local"
        value["locked_at"] = utc_now()
    elif now_locked:
        value["locked_by"] = str(stored.get("locked_by") or req.username or "local")
        value["locked_at"] = str(stored.get("locked_at") or utc_now())
    elif replace:
        value.pop("locked_by", None)
        value.pop("locked_at", None)
    else:
        value["locked_by"] = None
        value["locked_at"] = None


def _lock_guard_ops(req: Request, doc: Dict[str, Any], ops: List[Any]) -> List[Any]:
    """423 when the stored doc is locked and the batch is not the unlock; stamps lock ops either way."""
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    if settings.get("locked") is True and not _lock_only_ops(settings, ops):
        raise _locked_error(settings)
    out: List[Any] = []
    for op in ops:
        if isinstance(op, dict) and op.get("op") == "root" and op.get("key") == "settings" and isinstance(op.get("value"), dict):
            op = dict(op, value=dict(op["value"]))
            _stamp_lock(req, settings, op["value"], bool(op.get("replace")))
        out.append(op)
    return out


def _lock_guard_put(req: Request, stored: Dict[str, Any], doc: Dict[str, Any]) -> None:
    """PUT counterpart: 423 unless only the lock keys differ; stamps ``locked_by`` / ``locked_at`` in ``doc``."""
    import copy

    from . import schema

    s_stored = stored.get("settings") if isinstance(stored.get("settings"), dict) else {}
    if not isinstance(doc.get("settings"), dict):
        if s_stored.get("locked") is True:
            raise _locked_error(s_stored)
        return
    if s_stored.get("locked") is True:
        if schema.doc_version(doc) != 2:
            raise _locked_error(s_stored)
        a = schema.normalize(copy.deepcopy(stored))
        b = schema.normalize(copy.deepcopy(doc))
        for d in (a, b):
            d.pop("revision", None)
            for k in _LOCK_KEYS:
                (d.get("settings") or {}).pop(k, None)
        if schema.diff_docs(a, b):
            raise _locked_error(s_stored)
    if "locked" in doc["settings"] or s_stored.get("locked") is True:
        _stamp_lock(req, s_stored, doc["settings"], True)


# -- "Suggest an improvement": problem reports with kind=suggestion, optionally forwarded


def _suggest_url(doc: Dict[str, Any]) -> str:
    s = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    url = str(s.get("suggest_url") or os.environ.get("FATHOM_SUGGEST_URL") or "").strip()
    return url if re.match(r"^https?://", url, re.I) else ""


def _forward_suggestion(url: str, payload: Dict[str, Any]) -> bool:
    """POST the suggestion as JSON to ``url``; failures are logged and never fail the report."""
    import urllib.error
    import urllib.request

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        rq = urllib.request.Request(url, data=data, method="POST",
                                    headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": f"fathom/{__version__}"})
        with urllib.request.urlopen(rq, timeout=_SUGGEST_FORWARD_TIMEOUT) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except Exception as exc:  # network / HTTP / bad URL: the report is already stored
        sys.stderr.write(f"fathom: suggestion forward to {url} failed: {exc}\n")
        return False


@route("GET", "/api/v2/suggestions", role="admin", summary="Improvement suggestions across every project (newest first)", tags=["problems"])
def r_suggestions(req: Request) -> Response:
    items: List[Dict[str, Any]] = []
    for n in list_projects():
        try:
            doc, _ = _load(_project_dir(n))
        except ApiError:
            continue
        for r in doc.get("problems") or []:
            if isinstance(r, dict) and r.get("id") and r.get("kind") == "suggestion":
                items.append(dict(_problem_view(doc, r, n), project=n))
    items.reverse()
    items.sort(key=lambda r: str(r.get("created") or ""), reverse=True)
    return Response.json({"items": items})


# ---- backups

_BACKUP = r"(?P<backup>[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip)"
_ZIP_TYPES = ("application/zip", "application/x-zip-compressed", "application/octet-stream")


def _max_backup() -> int:
    from .backup import max_upload_bytes

    return max_upload_bytes()


def _backup_error(exc: Exception) -> ApiError:
    code = getattr(exc, "code", "invalid")
    status = {"not_found": 404, "too_large": 413, "no_space": 507, "busy": 409}.get(code, 422)
    return ApiError(status, str(exc), code)


@route("GET", "/api/v2/backups", role="admin", summary="List server backups", tags=["backups"])
def r_backups(req: Request) -> Response:
    from .backup import list_backups

    return Response.json({"backups": list_backups(), "max_upload_mb": _max_backup() // (1024 * 1024)})


@route("POST", "/api/v2/backups", role="admin", summary="Back up every project, user and setting", tags=["backups"], body="BackupCreate")
def r_backups_create(req: Request) -> Response:
    from .backup import BackupError, create_backup

    body = req.json()
    try:
        info = create_backup(include_builds=bool(body.get("include_builds")), label=str(body.get("label") or ""), author=req.username)
    except BackupError as exc:
        raise _backup_error(exc)
    return Response.json({"backup": info}, 201)


@route("POST", "/api/v2/backups/upload", role="admin", summary="Upload a backup zip (raw request body)", tags=["backups"], body="BackupZip",
       max_body=_max_backup)
def r_backups_upload(req: Request) -> Response:
    from .backup import BackupError, save_upload

    if req.header("content-type").split(";")[0].strip().lower() not in _ZIP_TYPES:
        raise ApiError(415, "send the backup zip as the request body (Content-Type: application/zip)", "unsupported_format")
    raw_len = req.header("content-length")
    if not raw_len and "chunked" not in req.header("transfer-encoding").lower():
        raise ApiError(400, "Content-Length required")
    try:
        info = save_upload(req.environ["wsgi.input"], int(raw_len) if raw_len else None)
    except BackupError as exc:
        raise _backup_error(exc)
    return Response.json({"backup": info}, 201)


@route("GET", r"/api/v2/backups/" + _BACKUP, role="admin", summary="Download a backup", tags=["backups"], page="file")
def r_backup_get(req: Request) -> Response:
    from .backup import BackupError, backup_path

    try:
        path = backup_path(req.params["backup"])
    except BackupError as exc:
        raise _backup_error(exc)
    return Response.stream_file(path, "application/zip", {"Content-Disposition": f'attachment; filename="{path.name}"'})


@route("DELETE", r"/api/v2/backups/" + _BACKUP, role="admin", summary="Delete a backup", tags=["backups"])
def r_backup_delete(req: Request) -> Response:
    from .backup import BackupError, delete_backup

    try:
        delete_backup(req.params["backup"])
    except BackupError as exc:
        raise _backup_error(exc)
    return Response.empty(204)


@route("POST", r"/api/v2/backups/" + _BACKUP + "/restore", role="admin", summary="Replace all data with a backup ({\"confirm\": <backup>})",
       tags=["backups"], body="BackupRestore")
def r_backup_restore(req: Request) -> Response:
    from .backup import BackupError, restore_backup

    name = req.params["backup"]
    if req.json().get("confirm") != name:
        raise ApiError(400, "pass {\"confirm\": \"<backup name>\"} to replace all data with this backup")
    try:
        res = restore_backup(name, author=req.username)
    except BackupError as exc:
        raise _backup_error(exc)
    _sync_generation()
    return Response.json(res)


# ---- meta, schema, library


def _vocab_dict() -> Dict[str, Any]:
    try:
        from .vocab import as_dict

        return as_dict()
    except Exception:
        _log_exc("vocab.as_dict failed")
        from .model import BRANDS, KINDS, MEDIA

        return {"kinds": KINDS, "media": MEDIA, "brands": BRANDS}


def _samples() -> List[str]:
    return sorted(p.name for p in SAMPLES_DIR.iterdir() if p.is_dir() and find_project_file(p)) if SAMPLES_DIR.is_dir() else []


@route("GET", "/api/v2/meta", role="viewer", summary="Vocabulary, importers, capabilities, limits", tags=["meta"])
def r_meta_v2(req: Request) -> Response:
    from .users import auth_enabled, public_view

    out: Dict[str, Any] = {"version": __version__, "vocab": _vocab_dict(), "importers": [], "plugins_errors": [], "samples": _samples()}
    try:
        from . import plugins

        out["importers"] = [{"kind": i.kind, "label": i.label, "mode": getattr(i, "mode", "live"), "accepts": list(getattr(i, "accepts", ()) or ()),
                             "folder": bool(getattr(i, "folder", False)), "help": getattr(i, "help", ""),
                             "templates": list(getattr(i, "templates", ()) or ()) if getattr(i, "template", None) else []} for i in plugins.importers()]
        out["plugins_errors"] = [str(x) for x in plugins.plugin_errors()]
    except Exception:
        _log_exc("plugins unavailable")
    caps: Dict[str, Any] = {"chrome": False, "pdf_rasterizer": None, "oda": bool(os.environ.get("FATHOM_ODA")),
                            "llm": {"configured": False, "model": ""}, "secure_context_hint": req.scheme == "https" or req.host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]")}
    try:
        from .export import find_chrome

        caps["chrome"] = bool(find_chrome())
    except Exception:
        _log_exc("export.find_chrome failed")
    try:
        from .floorplan import rasterizer

        caps["pdf_rasterizer"] = rasterizer()
    except Exception:
        pass
    try:
        from .llm import info

        li = info() or {}
        caps["llm"] = {"configured": bool(li.get("configured")), "model": str(li.get("model") or "")}
    except Exception:
        pass
    out["capabilities"] = caps
    try:
        from .vocab import CONDITIONS

        out["conditions"] = list(CONDITIONS)
    except Exception:  # pragma: no cover
        out["conditions"] = ["new", "good", "fair", "poor", "broken"]
    out["auth"] = {"enabled": auth_enabled(), "public_view": public_view()}
    out["limits"] = {"max_upload_mb": _max_upload() // (1024 * 1024), "max_json_mb": _max_json() // (1024 * 1024),
                     "max_backup_mb": _max_backup() // (1024 * 1024)}
    try:
        from .library import load_library

        out["library_count"] = len(load_library())
    except Exception:
        out["library_count"] = 0
    return Response.json(out)


@route("GET", "/api/v2/schema.json", role="public", summary="JSON Schema of the project doc", tags=["meta"])
def r_schema(req: Request) -> Response:
    from .schema import JSON_SCHEMA

    return Response.json(JSON_SCHEMA, headers={"Content-Type": "application/schema+json"})


def _ports_summary(t: Dict[str, Any]) -> str:
    parts = []
    for g in t.get("ports") or []:
        if not isinstance(g, dict):
            continue
        n = len(g.get("names") or []) or int(g.get("count") or 1)
        parts.append(f"{n}× {g.get('group', '')}")
    return " · ".join(parts)


def _template_summary(t: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: t.get(k) for k in ("id", "manufacturer", "model", "name", "kind", "discipline", "ru")}
    out["name"] = out.get("name") or t.get("model")
    out["ports_summary"] = t.get("ports_summary") or _ports_summary(t)
    out["source"] = t.get("source") or "builtin"
    for k, v in t.items():
        if k not in out and k in ("tags", "brand"):
            out[k] = v
    return out


def _doc_for_query(req: Request) -> Optional[Dict[str, Any]]:
    name = req.query.get("project") or ""
    if not name:
        return None
    return _load(_project_dir(name))[0]


@route("GET", "/api/v2/library", role="viewer", summary="Search the equipment library", tags=["library"])
def r_library(req: Request) -> Response:
    from .library import list_templates

    doc = _doc_for_query(req)
    ts = list_templates(q=req.query.get("q", ""), discipline=req.query.get("discipline", ""), kind=req.query.get("kind", ""), doc=doc)
    return Response.json({"templates": [_template_summary(t) for t in ts]})


@route("GET", "/api/v2/library/suggest", role="viewer", summary="Suggest library models for manufacturer / model / name strings (?manufacturer=&model=&text=&kind=&project=&limit=)", tags=["library"])
def r_library_suggest(req: Request) -> Response:
    from .library.suggest import suggest_models

    limit = _int(req.query.get("limit"), 5)
    q = {k: str(req.query.get(k) or "")[:200] for k in ("manufacturer", "model", "text", "kind")}
    out = suggest_models(q["manufacturer"], q["model"], q["text"], kind=q["kind"], doc=_doc_for_query(req), limit=max(1, min(limit, 20)))
    return Response.json({"query": q, "suggestions": out})


@route("GET", r"/api/v2/library/(?P<tid>[A-Za-z0-9][A-Za-z0-9._-]{0,127})", role="viewer", summary="Get a template", tags=["library"])
def r_library_get(req: Request) -> Response:
    from .library import get_template

    t = get_template(req.params["tid"], doc=_doc_for_query(req))
    if t is None:
        raise ApiError(404, "template not found")
    return Response.json(t)


def _builtin_ids() -> set:
    try:
        from .library import load_library

        return {k for k, v in load_library().items() if (v or {}).get("source", "builtin") in ("builtin", "extension", "preset")}
    except Exception:
        return set()


@route("GET", "/api/v2/presets", role="viewer", summary="Built-in device type presets (generic gear with default ports)", tags=["library"])
def r_presets(req: Request) -> Response:
    from .presets import as_dict

    return Response.json(as_dict())


@route("POST", "/api/v2/library", role="editor", summary="Save a global custom template", tags=["library"], body="Template")
def r_library_post(req: Request) -> Response:
    from .library import save_custom_template, validate_template

    t = req.json()
    problems = validate_template(t)
    if problems:
        raise ApiError(422, "template is not valid", "invalid", {"problems": [{"level": "error", "code": "invalid", "ref": "", "path": "", "message": str(p)} for p in problems]})
    override = req.query.get("override") == "1"
    if str(t.get("id")) in _builtin_ids() and not override:
        raise ApiError(409, "a built-in template has this id; pass ?override=1 to shadow it", "exists")
    try:
        save_custom_template(t, override=override)
    except FileExistsError as exc:
        raise ApiError(409, str(exc), "exists")
    return Response.json(t, 201)


@route("DELETE", r"/api/v2/library/(?P<tid>[A-Za-z0-9][A-Za-z0-9._-]{0,127})", role="editor", summary="Delete a custom template", tags=["library"])
def r_library_delete(req: Request) -> Response:
    from .library import delete_custom_template, get_template, load_library

    tid = req.params["tid"]
    lib = load_library(refresh=True)
    t = lib.get(tid) or get_template(tid)
    if t is None:
        raise ApiError(404, "template not found")
    if (t.get("source") or "builtin") != "custom":
        raise ApiError(409, "built-in templates cannot be deleted", "conflict")
    try:
        delete_custom_template(tid)
    except FileNotFoundError:
        raise ApiError(404, "template not found")
    return Response.empty(204)


# ---- projects (v2)


@route("GET", "/api/v2/projects", role="viewer", summary="List projects", tags=["projects"])
def r_projects_v2(req: Request) -> Response:
    rows = []
    for n in list_projects():
        info = project_info_v2(n)
        info["role"] = req.role_for(n)
        info.update(_lock_flags(n))
        rows.append(info)
    return Response.json({"projects": rows})


# ---- room starters (phase3 P3C): bundled one-room church samples offered as project templates and as rooms to add


@route("GET", "/api/v2/starters", role="viewer", summary="Church room starter templates", tags=["projects"])
def r_starters(req: Request) -> Response:
    from .starters import list_starters

    return Response.json({"starters": list_starters()})


@route("POST", r"/api/v2/projects/" + _NAME + "/rooms/from-starter", role="editor", summary="Add a room from a starter", tags=["projects"], body="Starter")
def r_room_from_starter(req: Request) -> Response:
    from .schema import diff_docs
    from .starters import StarterError, get_starter, merge_room

    pdir = _project_dir(req.params["name"])
    body = req.json()
    starter_id = str(body.get("starter") or "")
    starter = get_starter(starter_id)
    if starter is None:
        raise ApiError(400, f"unknown starter '{starter_id}'", "bad_enum")
    room_name = str(body.get("name") or "").strip()[:80]
    doc, _ = _load(pdir)
    try:
        merged, info = merge_room(doc, starter_id, room_name or None)
    except StarterError as exc:
        raise ApiError(404 if exc.code == "not_found" else 400, str(exc), exc.code)
    ops = diff_docs(doc, merged)
    ops = _lock_guard_ops(req, doc, ops)
    summary = f"Added room {info['name']} from starter {starter['label']}"
    res = _server_ops(req, pdir, ops, summary, "starter")
    return Response.json({"room": info["room"], "info": info, "revision": res["revision"], "problems": res.get("problems") or []}, 201,
                         headers={"ETag": f'"r{res["revision"]}"'})


@route("POST", "/api/v2/projects", role="editor", summary="Create a project", tags=["projects"], body="ProjectCreate")
def r_projects_create_v2(req: Request) -> Response:
    body = req.json()
    name = str(body.get("name", "")).strip()
    if not safe_name(name):
        raise ApiError(400, "name must be letters, digits, . _ - (max 64)")
    if (projects_root() / name).exists():
        raise ApiError(409, f"project '{name}' already exists", "exists")
    template = str(body.get("template") or "blank")
    if template != "blank" and template not in _samples():
        raise ApiError(400, f"unknown template '{template}'")
    pdir = new_project(name, template=template, org=str(body.get("org") or ""))
    doc, _ = _load(pdir)
    return Response.json({"name": pdir.name, "revision": _rev(doc)}, 201)


@route("GET", r"/api/v2/projects/" + _NAME, role="viewer", summary="Get the project doc", tags=["projects"], response="Doc")
def r_project_get_v2(req: Request) -> Response:
    from .schema import validate_doc

    pdir = _project_dir(req.params["name"])
    doc, version = _load(pdir)
    rev = _rev(doc)
    return Response.json({"name": pdir.name, "revision": rev, "doc": doc, "problems": validate_doc(doc), "role": req.role_for(pdir.name),
                          "migrated_from": 1 if version < 2 else None}, headers={"ETag": f'"r{rev}"'})


@route("PUT", r"/api/v2/projects/" + _NAME, role="editor", summary="Replace the doc (If-Match or base_revision)", tags=["projects"], body="DocPut")
def r_project_put_v2(req: Request) -> Response:
    from .project import save_doc

    pdir = _project_dir(req.params["name"])
    body = req.json()
    base = _etag_rev(req)
    if base is None and body.get("base_revision") is not None:
        base = _int(body.get("base_revision"), -1)
    if base is None:
        raise ApiError(428, "send If-Match: \"r<revision>\" or base_revision", "precondition_required")
    doc = body.get("doc")
    if not isinstance(doc, dict):
        raise ApiError(400, "body.doc must be an object")
    _lock_guard_put(req, _load(pdir)[0], doc)
    res = save_doc(doc, pdir, base_revision=base, author=req.username, summary=str(body.get("summary") or "Saved"), source="put")
    return Response.json({"revision": res["revision"], "rebased": res["rebased"], "problems": res["problems"]}, headers={"ETag": f'"r{res["revision"]}"'})


@route("POST", r"/api/v2/projects/" + _NAME + "/changes", role="editor", summary="Apply change ops", tags=["projects"], body="Changes")
def r_project_changes(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    body = req.json()
    if body.get("base_revision") is None:
        raise ApiError(428, "base_revision is required", "precondition_required")
    ops = body.get("ops")
    if not isinstance(ops, list):
        raise ApiError(400, "ops must be a list")
    if len(ops) > MAX_OPS:
        raise ApiError(400, f"at most {MAX_OPS} ops per request")
    ops = _lock_guard_ops(req, _load(pdir)[0], ops)
    res = _changes(req, pdir, ops, _int(body.get("base_revision"), -1), str(body.get("summary") or f"{len(ops)} change{'s' if len(ops) != 1 else ''}"), "changes")
    return Response.json(res, headers={"ETag": f'"r{res["revision"]}"'})


@route("GET", r"/api/v2/projects/" + _NAME + "/devices/duplicates", role="viewer", summary="Likely duplicate devices (?device=<id>&min=<score>)", tags=["devices"])
def r_device_duplicates(req: Request) -> Response:
    from .dedupe import MergeError, find_duplicates

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    try:
        min_score = float(req.query.get("min") or 0.5)
    except ValueError:
        raise ApiError(400, "min must be a number")
    min_score = min(1.0, max(0.0, min_score))
    limit = _int(req.query.get("limit"), 50, 1, 500)
    try:
        found = find_duplicates(doc, _overlay(doc, pdir, strict=False), device_id=str(req.query.get("device") or ""), min_score=min_score)
    except MergeError as exc:
        raise ApiError(404 if exc.code == "not_found" else 400, str(exc), exc.code)
    return Response.json({"revision": _rev(doc), "min_score": min_score, "total": len(found), "duplicates": found[:limit]})


def _merge_body(req: Request, pdir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from .dedupe import MergeError, merge_plan

    body = req.json()
    survivor = str(body.get("survivor") or "")
    dups = body.get("duplicates")
    if not survivor or not isinstance(dups, list) or not dups or not all(isinstance(d, str) for d in dups):
        raise ApiError(400, "survivor (id) and duplicates (list of ids) are required")
    if len(dups) > 20:
        raise ApiError(400, "at most 20 duplicates per merge")
    choices = body.get("choices") or {}
    if not isinstance(choices, dict) or not all(isinstance(v, str) for v in choices.values()):
        raise ApiError(400, "choices must map field keys to device ids")
    doc, _ = _load(pdir)
    try:
        plan = merge_plan(doc, survivor, dups, choices=choices, overlay=_overlay(doc, pdir, strict=False), author=req.username)
    except MergeError as exc:
        raise ApiError(404 if exc.code == "not_found" else 400, str(exc), exc.code)
    plan["revision"] = _rev(doc)
    return body, plan


@route("POST", r"/api/v2/projects/" + _NAME + "/devices/merge/preview", role="editor", summary="Preview a device merge (no write)", tags=["devices"], body="MergeRequest")
def r_device_merge_preview(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    _, plan = _merge_body(req, pdir)
    return Response.json(plan)


@route("POST", r"/api/v2/projects/" + _NAME + "/devices/merge", role="editor", summary="Merge duplicate devices into one (one revision)", tags=["devices"], body="MergeRequest")
def r_device_merge(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    body, plan = _merge_body(req, pdir)
    base = body.get("base_revision")
    base_rev = plan["revision"] if base is None else _int(base, -1)
    res = _changes(req, pdir, plan["ops"], base_rev, plan["summary"], "merge")
    res.update({"survivor": plan["survivor"], "duplicates": plan["duplicates"], "summary": plan["summary"],
                "warnings": plan["warnings"], "ops": plan["ops"]})
    return Response.json(res, headers={"ETag": f'"r{res["revision"]}"'})


def _device_or_404(doc: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id") == device_id:
            return d
    raise ApiError(404, f"device '{device_id}' not found", "not_found")


@route("GET", r"/api/v2/projects/" + _NAME + r"/devices/(?P<device>" + _EID + ")/channels", role="viewer",
       summary="Console channels, buses, DCAs and links of a device (persisted, else from the imports overlay)", tags=["devices"])
def r_device_channels(req: Request) -> Response:
    from . import console as C

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    dev = _device_or_404(doc, req.params["device"])
    ov = _overlay(doc, pdir, strict=False) or {}
    eff = C.effective_channels(doc, ov, dev["id"])
    labels = (ov.get("channel_labels") or {}).get(dev["id"]) or {}
    out = dict(eff)
    out.update({"device": dev["id"], "labels": labels, "summary": C.summary(eff["channels"], eff["links"])})
    return Response.json(out)


@route("POST", r"/api/v2/projects/" + _NAME + r"/devices/(?P<device>" + _EID + ")/channels/apply", role="editor",
       summary="Apply the imported console channels to the device (user-entered channels and links are kept)", tags=["devices"])
def r_device_channels_apply(req: Request) -> Response:
    from . import console as C

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    dev = _device_or_404(doc, req.params["device"])
    ov = _overlay(doc, pdir) or {}
    if C.overlay_channels(ov, dev["id"]) is None:
        raise ApiError(404, "no imported console channels for this device", "not_found")
    ops = C.apply_ops(doc, ov, dev["id"])
    revision = _rev(doc)
    if ops:
        value = ops[0]["value"]
        res = _server_ops(req, pdir, ops, f"Apply console channels to {dev.get('name') or dev['id']}", "import")
        revision = res["revision"]
        applied = C.summary(value.get("channels") or [], value.get("channel_links") or [])
    else:
        applied = C.summary(dev.get("channels") or [], dev.get("channel_links") or [])
    return Response.json({"revision": revision, "changed": bool(ops), "summary": applied})


@route("DELETE", r"/api/v2/projects/" + _NAME, role="admin", summary="Move a project to the trash (?confirm=<name>; &purge=1 deletes it for good)", tags=["projects"])
def r_project_delete_v2(req: Request) -> Response:
    name = req.params["name"]
    _project_dir(name)
    if req.query.get("confirm") != name:
        raise ApiError(400, "pass ?confirm=<name> to delete a project and its builds")
    purge = str(req.query.get("purge") or "").lower() in ("1", "true", "yes")
    delete_project(name, purge=purge, by=req.username)
    return Response.json({"ok": True, "trashed": not purge})


# ---- trash and short codes (phase 1, FR-INV-07 / FR-INV-09)

_TNAME = r"(?P<tname>[A-Za-z0-9][A-Za-z0-9._-]{0,63})"
_CODE = r"(?P<code>[A-Za-z0-9]{4}-?[A-Za-z0-9]{4})"


@route("GET", r"/api/v2/trash", role="admin", summary="Trashed projects (purges entries past the retention period)", tags=["projects"])
def r_trash_list(req: Request) -> Response:
    from .project import TRASH_RETENTION_DAYS, list_trashed

    return Response.json({"items": list_trashed(), "retention_days": TRASH_RETENTION_DAYS})


@route("POST", r"/api/v2/trash/" + _TNAME + "/restore", role="admin", summary="Restore a trashed project", tags=["projects"])
def r_trash_restore(req: Request) -> Response:
    from .project import ProjectExists, restore_project, trash_info

    info = trash_info(req.params["tname"])
    if info is None:
        raise ApiError(404, "nothing in the trash by that name", "not_found")
    try:
        restore_project(req.params["tname"])
    except ProjectExists as exc:
        raise ApiError(409, str(exc), "exists")
    except FileNotFoundError:
        raise ApiError(404, "nothing in the trash by that name", "not_found")
    return Response.json({"ok": True, "name": info["name"]})


@route("DELETE", r"/api/v2/trash/" + _TNAME, role="admin", summary="Delete a trashed project for good", tags=["projects"])
def r_trash_purge(req: Request) -> Response:
    from .project import purge_project

    try:
        purge_project(req.params["tname"])
    except FileNotFoundError:
        raise ApiError(404, "nothing in the trash by that name", "not_found")
    return Response.json({"ok": True})


@route("GET", r"/api/v2/codes/" + _CODE, role="viewer", summary="Resolve a device short code (XXXX-XXXX) across projects", tags=["devices"])
def r_code_lookup(req: Request) -> Response:
    from .project import find_by_short_code
    from .users import role_at_least

    hit = find_by_short_code(req.params["code"])
    if hit is None or not role_at_least(req.role_for(hit["project"]), "viewer"):
        raise ApiError(404, "not_found", "not_found")
    return Response.json(hit)


# ---- scenes (phase 3 P3A, FR-SCN / §4.3.18 / §5.6 "Scenes"): named patch + placement variants

_SID = r"(?P<sid>sc-[0-9a-f]{8}|base)"


def _scene_commit(req: Request, pdir: Path, mutate: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], Any, str]]) -> Tuple[Dict[str, Any], Any, Dict[str, Any]]:
    """Load → ``mutate(doc) -> (new_doc, info, summary)`` → store as one revision (source ``scene``),
    all under the project lock so the capture and the write see the same state; 423 while the
    project is locked for editing (FR-USER-12), like ``/changes``."""
    from .project import project_lock, save_doc

    with project_lock(pdir):
        doc, _ = _load(pdir)
        settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
        if settings.get("locked") is True:
            raise _locked_error(settings)
        new_doc, info, summary = mutate(doc)
        res = save_doc(new_doc, pdir, base_revision=None, author=req.username, summary=summary, source="scene")
    return new_doc, info, res


def _scene_or_404(doc: Dict[str, Any], sid: str) -> None:
    from . import scenes as S

    if S.find(doc, sid) is None and not (sid == S.BASE):
        raise ApiError(404, f"scene '{sid}' not found", "not_found")


def _scene_view(doc: Dict[str, Any], sid: str) -> Dict[str, Any]:
    """The doc as it looks with scene ``sid`` active (nothing stored). The org eyebrow every viewer
    page renders gets a "Scene: <name>" caption so the page says which variant it shows (the only
    hook reachable from here without touching the renderers). 404 for an unknown scene."""
    from . import scenes as S

    try:
        data = S.scene_data(doc, sid)
        name = S.scene_name(doc, sid)
    except KeyError:
        raise ApiError(404, f"scene '{sid}' not found", "not_found")
    out = S.apply(doc, data)
    meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
    out["meta"] = meta
    org = str(meta.get("org") or "")
    meta["org"] = f"{org} \u00b7 Scene: {name}" if org else f"Scene: {name}"
    return out


@route("GET", r"/api/v2/projects/" + _NAME + "/scenes", role="viewer", summary="Scenes (named patch + placement variants) with their diff against Base", tags=["scenes"])
def r_scenes(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    return Response.json({"scenes": S.summarize(doc), "active": S.active_id(doc), "revision": _rev(doc)})


@route("POST", r"/api/v2/projects/" + _NAME + "/scenes", role="editor", summary="Create a scene from the current state ({name, note, copy_from, activate})", tags=["scenes"], body="Scene")
def r_scene_create(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    body = req.json()
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "name is required", "missing_field")
    if len(name) > S.MAX_NAME:
        raise ApiError(400, f"name is longer than {S.MAX_NAME} characters", "bad_enum")
    note = str(body.get("note") or "")
    copy_from = str(body.get("copy_from") or "") or None
    activate = body.get("activate") is True

    def mutate(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, str]:
        if copy_from:
            _scene_or_404(doc, copy_from)
        new, scene = S.create(doc, name, note=note, by=req.username, copy_from=copy_from)
        if activate:
            new, _ = S.activate(new, scene["id"], by=req.username)
        return new, scene["id"], f"Created scene {name}"

    new_doc, sid, res = _scene_commit(req, pdir, mutate)
    return Response.json({"scene": S.summary_for(new_doc, sid), "revision": res["revision"]}, 201)


@route("PATCH", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID, role="editor", summary="Rename a scene / edit its note ({name, note})", tags=["scenes"], body="ScenePatch")
def r_scene_patch(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    sid = req.params["sid"]
    body = req.json()
    name = body.get("name")
    note = body.get("note")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ApiError(400, "name must not be empty", "missing_field")
        if len(name) > S.MAX_NAME:
            raise ApiError(400, f"name is longer than {S.MAX_NAME} characters", "bad_enum")
    if note is not None:
        note = str(note)

    def mutate(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, str]:
        if S.find(doc, sid) is None:
            raise ApiError(404, f"scene '{sid}' not found", "not_found")
        old = S.scene_name(doc, sid)
        new = S.rename(doc, sid, name=name, note=note)
        label = f"Renamed scene {old} to {name}" if name is not None and name != old else f"Edited scene {old}"
        return new, S.find(new, sid)["id"], label  # type: ignore[index]

    new_doc, real_id, res = _scene_commit(req, pdir, mutate)
    return Response.json({"scene": S.summary_for(new_doc, real_id), "revision": res["revision"]})


@route("DELETE", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID, role="editor", summary="Delete a scene (the active one is left for Base first; Base cannot be deleted)", tags=["scenes"])
def r_scene_delete(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    sid = req.params["sid"]

    def mutate(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, str]:
        if S.is_base(doc, sid):
            raise ApiError(400, "the Base scene cannot be deleted", "bad_request")
        if S.find(doc, sid) is None:
            raise ApiError(404, f"scene '{sid}' not found", "not_found")
        name = S.scene_name(doc, sid)
        return S.delete(doc, sid), None, f"Deleted scene {name}"

    new_doc, _, res = _scene_commit(req, pdir, mutate)
    return Response.json({"ok": True, "revision": res["revision"], "active": S.active_id(new_doc)})


@route("POST", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID + "/activate", role="editor", summary="Switch to a scene (sid may be 'base'): captures the current state into the scene being left", tags=["scenes"])
def r_scene_activate(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    sid = req.params["sid"]
    doc, _ = _load(pdir)
    if sid != S.BASE and S.find(doc, sid) is None:
        raise ApiError(404, f"scene '{sid}' not found", "not_found")
    if S.active_id(doc) == (S.BASE if S.is_base(doc, sid) else sid):
        empty = S.capture(doc)
        return Response.json({"active": S.active_id(doc), "from": S.active_id(doc), "diff": S.diff(empty, empty), "revision": _rev(doc)})

    def mutate(d: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, str]:
        try:
            new, info = S.activate(d, sid, by=req.username)
        except KeyError:
            raise ApiError(404, f"scene '{sid}' not found", "not_found")
        return new, info, f"Switched to scene {S.scene_name(new, info['to'])} ({info['diff']['text']})"

    new_doc, info, res = _scene_commit(req, pdir, mutate)
    return Response.json({"active": S.active_id(new_doc), "from": info["from"], "diff": info["diff"], "revision": res["revision"]})


@route("POST", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID + "/save", role="editor", summary="Save the current state into a scene (overwrites its stored data)", tags=["scenes"])
def r_scene_save(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    sid = req.params["sid"]

    def mutate(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, str]:
        if S.find(doc, sid) is None:
            raise ApiError(404, f"scene '{sid}' not found", "not_found")
        new = S.save_current(doc, sid)
        return new, S.find(new, sid)["id"], f"Saved current state into scene {S.scene_name(new, sid)}"  # type: ignore[index]

    new_doc, real_id, res = _scene_commit(req, pdir, mutate)
    return Response.json({"scene": S.summary_for(new_doc, real_id), "revision": res["revision"]})


@route("GET", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID + "/diff", role="viewer", summary="Differences of a scene against another (?against=<sid|base>, default base)", tags=["scenes"])
def r_scene_diff(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    sid = req.params["sid"]
    against = str(req.query.get("against") or S.BASE)
    try:
        out = S.diff(S.scene_data(doc, against), S.scene_data(doc, sid))
    except KeyError as exc:
        raise ApiError(404, f"scene '{exc.args[0] if exc.args else sid}' not found", "not_found")
    out["scene"] = sid
    out["against"] = against
    out["revision"] = _rev(doc)
    return Response.json(out)


@route("GET", r"/api/v2/projects/" + _NAME + "/scenes/" + _SID + "/doc", role="viewer", summary="The project as it would look with that scene active (read-only preview, nothing changes)", tags=["scenes"])
def r_scene_doc(req: Request) -> Response:
    from . import scenes as S

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    sid = req.params["sid"]
    try:
        out = S.apply(doc, S.scene_data(doc, sid))
    except KeyError:
        raise ApiError(404, f"scene '{sid}' not found", "not_found")
    return Response.json({"doc": out, "scene": sid, "revision": _rev(doc)})


def _not_found_page(req: Request, title: str, message: str) -> Response:
    e = html_mod.escape
    home = (req.script_root or "") + "/"
    text = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{e(title)} · Fathom</title><style>body{{font:17px/1.5 system-ui,sans-serif;margin:0;padding:48px 24px;background:#0b1020;color:#e5e7eb}}"
            f"main{{max-width:32rem;margin:0 auto}}h1{{font-size:1.5rem;margin:0 0 .5rem}}p{{margin:0 0 1rem;color:#9aa3b5}}"
            f"a{{display:inline-block;min-height:44px;line-height:44px;padding:0 16px;border-radius:8px;background:#1f2937;color:#e5e7eb;text-decoration:none}}</style></head>"
            f"<body><main><h1>{e(title)}</h1><p>{e(message)}</p><a href=\"{e(home)}\">Open Fathom</a></main></body></html>")
    r = _viewer_html(text)
    r.status = 404
    return r


@route("GET", r"/c/" + _CODE, role="viewer", summary="Short link printed on device labels: redirects to the device (editor → app, viewer → device page)", tags=["viewer"], page="viewer")
def r_code_redirect(req: Request) -> Response:
    from .project import find_by_short_code
    from .users import role_at_least

    hit = find_by_short_code(req.params["code"])
    if hit is None or not role_at_least(req.role_for(hit["project"]), "viewer"):
        return _not_found_page(req, "No device has that code", "The label may belong to another Fathom server, or the device was removed.")
    root = req.script_root or ""
    if role_at_least(req.role_for(hit["project"]), "editor"):
        target = f"{root}/#/{quote(hit['project'], safe='')}//devices/{quote(hit['device'], safe='')}"
    else:
        target = f"{root}/p/{quote(hit['project'], safe='')}/d/{quote(hit['device'], safe='')}"
    return Response(b"", 302, "text/plain; charset=utf-8", {"Location": target})


@route("GET", r"/api/v2/projects/" + _NAME + r"/doc\.json", role="viewer", summary="Download the doc", tags=["projects"])
def r_project_docjson(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    return Response.text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "application/json; charset=utf-8",
                         headers={"Content-Disposition": f'attachment; filename="{pdir.name}-project.json"'})


@route("GET", r"/api/v2/projects/" + _NAME + "/history", role="viewer", summary="Revision history (newest first)", tags=["history"])
def r_history(req: Request) -> Response:
    from .history import list_revisions

    pdir = _project_dir(req.params["name"])
    before = req.query.get("before")
    revs = list_revisions(pdir, limit=_int(req.query.get("limit"), 50, 1, 1000), before=_int(before, 0) if before else None)
    return Response.json({"revisions": revs})


def _revision_doc(pdir: Path, rev: int) -> Dict[str, Any]:
    from .history import get_revision_doc

    try:
        return get_revision_doc(pdir, rev)
    except KeyError:
        raise ApiError(404, f"revision {rev} is not in the history", "history_missing")


@route("GET", r"/api/v2/projects/" + _NAME + r"/history/(?P<rev>\d+)", role="viewer", summary="Doc at a revision", tags=["history"])
def r_history_rev(req: Request) -> Response:
    from .history import get_entry

    pdir = _project_dir(req.params["name"])
    rev = int(req.params["rev"])
    doc = _revision_doc(pdir, rev)
    try:
        entry = get_entry(pdir, rev)
    except KeyError:
        entry = {}
    return Response.json({"revision": rev, "entry": entry, "doc": doc})


@route("GET", r"/api/v2/projects/" + _NAME + r"/history/(?P<rev>\d+)/diff", role="viewer", summary="Diff two revisions", tags=["history"])
def r_history_diff(req: Request) -> Response:
    from .history import diff_revisions

    pdir = _project_dir(req.params["name"])
    rev = int(req.params["rev"])
    against = _int(req.query.get("against"), rev - 1)
    _revision_doc(pdir, rev)
    _revision_doc(pdir, against)
    return Response.json(diff_revisions(pdir, against, rev))


@route("POST", r"/api/v2/projects/" + _NAME + r"/history/(?P<rev>\d+)/restore", role="editor", summary="Restore a revision as a new revision", tags=["history"], body="Restore")
def r_history_restore(req: Request) -> Response:
    from .project import restore_revision

    pdir = _project_dir(req.params["name"])
    rev = int(req.params["rev"])
    body = req.json()
    if body.get("base_revision") is None:
        raise ApiError(428, "base_revision is required", "precondition_required")
    _revision_doc(pdir, rev)
    res = restore_revision(pdir, rev, base_revision=_int(body.get("base_revision"), -1), author=req.username)
    return Response.json({"revision": res["revision"], "problems": res["problems"]})


@route("GET", r"/api/v2/projects/" + _NAME + "/overlay", role="viewer", summary="Imports overlay (computed)", tags=["imports"])
def r_overlay(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    ov = _overlay(doc, pdir)
    ih = (ov or {}).get("imports_hash") or _imports_hash(doc, pdir)
    etag = f'"r{_rev(doc)}-{ih}"'
    if req.header("if-none-match") == etag:
        r = Response.empty(304)
        r.headers["ETag"] = etag
        return r
    return Response.json(ov, headers={"ETag": etag})


@route("GET", r"/api/v2/projects/" + _NAME + "/offline-manifest", role="viewer", summary="URLs to cache for offline use", tags=["projects"])
def r_offline_manifest(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    n = pdir.name
    urls = [f"p/{n}", f"p/{n}/rooms"]
    for rid in _room_ids(doc):
        urls += [f"p/{n}/r/{rid}", f"p/{n}/r/{rid}/patch"]
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id"):
            urls.append(f"p/{n}/d/{d['id']}")
    urls += [f"api/v2/projects/{n}", "api/v2/meta"] + [a for a in SHELL_ASSETS if a not in urls]
    return Response.json({"urls": urls})


# ---- shares (P1)


def _shares_path(pdir: Path) -> Path:
    return pdir / "shares.json"


def _read_shares(pdir: Path) -> Dict[str, Dict[str, Any]]:
    p = _shares_path(pdir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_shares(pdir: Path, data: Dict[str, Dict[str, Any]]) -> None:
    tmp = pdir / ".shares.json.tmp"
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _shares_path(pdir))


@route("GET", r"/api/v2/projects/" + _NAME + "/shares", role="editor", summary="List share links", tags=["shares"])
def r_shares(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    return Response.json({"shares": [dict(v, token=k) for k, v in sorted(_read_shares(pdir).items())]})


@route("POST", r"/api/v2/projects/" + _NAME + "/shares", role="editor", summary="Create a read-only share link", tags=["shares"], body="Share")
def r_shares_create(req: Request) -> Response:
    from .history import utc_now
    from .project import project_lock

    pdir = _project_dir(req.params["name"])
    body = req.json()
    token = "sh-" + base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")[:22]
    scope = str(body.get("scope") or "all")
    if scope not in SHARE_SCOPES:
        raise ApiError(400, f"scope must be one of {', '.join(SHARE_SCOPES)}", "bad_enum")
    share = {"label": str(body.get("label") or ""), "created": utc_now(), "expires": str(body.get("expires") or ""), "by": req.username, "scope": scope}
    with project_lock(pdir):
        data = _read_shares(pdir)
        data[token] = share
        _write_shares(pdir, data)
    return Response.json({"share": dict(share, token=token), "url": f"s/{token}/"}, 201)


@route("DELETE", r"/api/v2/projects/" + _NAME + r"/shares/(?P<token>sh-[A-Za-z0-9_-]{1,64})", role="editor", summary="Revoke a share link", tags=["shares"])
def r_shares_delete(req: Request) -> Response:
    from .project import project_lock

    pdir = _project_dir(req.params["name"])
    with project_lock(pdir):
        data = _read_shares(pdir)
        if req.params["token"] not in data:
            raise ApiError(404, "share not found")
        data.pop(req.params["token"])
        _write_shares(pdir, data)
    return Response.empty(204)


# "all" mirrors the whole viewer tree; "sop" exposes only /sop/… pages and the files they embed,
# so a QR label on a rack opens the procedures without revealing the patch.
SHARE_SCOPES = ("all", "sop")
_SHARE_SOP_OK = re.compile(r"^(sop(/.*)?|files/.*)$")


def _share_lookup(token: str) -> Tuple[str, Dict[str, Any]]:
    from .history import utc_now

    for n in list_projects():
        s = _read_shares(projects_root() / n).get(token)
        if s is not None:
            exp = str(s.get("expires") or "")
            if exp and exp < utc_now():
                return "", {}
            return n, s
    return "", {}


def _share_project(token: str) -> str:
    return _share_lookup(token)[0]


def _share_allows(share: Dict[str, Any], rest: str) -> bool:
    scope = str(share.get("scope") or "all")
    if scope == "sop":
        return bool(_SHARE_SOP_OK.match(rest))
    return True


# ---- SOP pages (§4.3.15, §5.15)

_SLUG = r"(?P<slug>[a-z0-9][a-z0-9-]{0,79})"
_PAGE_FIELDS = ("slug", "title", "parent", "order", "kind", "body", "summary", "tags", "rooms", "devices", "attachments", "status",
                "owner", "review_due")


def _pages(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("id") and p.get("slug")]


def _page_by_slug(doc: Dict[str, Any], slug: str) -> Dict[str, Any]:
    p = next((x for x in _pages(doc) if x.get("slug") == slug), None)
    if p is None:
        raise ApiError(404, f"page '{slug}' not found", "page_missing")
    return p


def _page_order_key(p: Dict[str, Any]) -> Tuple[int, str]:
    o = p.get("order")
    return (int(o) if isinstance(o, int) and not isinstance(o, bool) else 10 ** 6, str(p.get("title") or "").casefold())


def _page_children(doc: Dict[str, Any], parent: Optional[str]) -> List[Dict[str, Any]]:
    return sorted([p for p in _pages(doc) if (p.get("parent") or None) == (parent or None)], key=_page_order_key)


def _page_refs(p: Dict[str, Any]) -> Dict[str, List[str]]:
    """Explicit links plus references found in the body (union, in order)."""
    from .markdown import find_refs

    found = find_refs(str(p.get("body") or ""))
    out: Dict[str, List[str]] = {}
    for key in ("devices", "rooms", "pages", "attachments"):
        seen: List[str] = []
        for v in list(p.get(key) or []) + list(found.get(key) or []):
            if isinstance(v, str) and v and v not in seen:
                seen.append(v)
        out[key] = seen
    return out


def _page_resolver(project: str, doc: Dict[str, Any]) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    devs = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    pages = {p.get("slug"): p for p in _pages(doc)}
    atts = {a.get("id"): a for a in doc.get("attachments") or [] if isinstance(a, dict)}
    proj = quote(project)

    def resolve(kind: str, ref: str) -> Optional[Dict[str, Any]]:
        if kind == "device" and ref in devs:
            return {"href": f"p/{proj}/d/{quote(ref)}", "label": str(devs[ref].get("name") or ref)}
        if kind == "room" and ref in rooms:
            return {"href": f"p/{proj}/r/{quote(ref)}", "label": str(rooms[ref].get("name") or ref)}
        if kind == "page" and ref in pages:
            return {"href": f"#/{proj}/*/sop?page={quote(ref)}", "label": str(pages[ref].get("title") or ref)}
        if kind == "attachment" and ref in atts:
            a = atts[ref]
            return {"href": f"api/v2/projects/{proj}/files/{quote(ref)}/{quote(Path(str(a.get('file') or a.get('name') or 'file')).name)}",
                    "label": str(a.get("name") or ref)}
        return None

    return resolve


def _page_summary(doc: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
    from .markdown import plain_text

    kids = sum(1 for x in _pages(doc) if (x.get("parent") or None) == p["id"])
    return {k: p.get(k) for k in ("id", "slug", "title", "parent", "order", "kind", "status", "tags", "rooms", "devices", "updated",
                                   "updated_by", "review_due")} | {
        "summary": str(p.get("summary") or plain_text(str(p.get("body") or ""), 160)), "children": kids}


def _page_payload(project: str, doc: Dict[str, Any], page: Dict[str, Any], revision: int,
                  resolver: Optional[Callable[[str, str], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    from .markdown import render

    rendered = render(str(page.get("body") or ""), resolver or _page_resolver(project, doc))
    refs = _page_refs(page)
    devs = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    by_slug = {p.get("slug"): p for p in _pages(doc)}
    by_id = {p["id"]: p for p in _pages(doc)}
    me = page["id"]
    backlinks = [{"slug": p["slug"], "title": p.get("title") or p["slug"]} for p in _pages(doc)
                 if p["id"] != me and page["slug"] in _page_refs(p)["pages"]]
    sibs = _page_children(doc, page.get("parent") or None)
    pos = next((i for i, s in enumerate(sibs) if s["id"] == me), -1)
    nav = lambda s: {"slug": s["slug"], "title": s.get("title") or s["slug"]} if s is not None else None  # noqa: E731
    crumbs: List[Dict[str, Any]] = []
    cur = by_id.get(page.get("parent") or "")
    guard = 0
    while cur is not None and guard < 50:
        crumbs.insert(0, nav(cur))
        cur = by_id.get(cur.get("parent") or "")
        guard += 1
    return {
        "page": page,
        "html": rendered["html"], "toc": rendered["toc"], "tasks": rendered["tasks"], "missing": rendered["missing"],
        "links": {
            "devices": [{"id": d, "name": str(devs[d].get("name") or d), "room": devs[d].get("room") or "", "kind": devs[d].get("kind") or ""}
                        for d in refs["devices"] if d in devs],
            "rooms": [{"id": r, "name": str(rooms[r].get("name") or r)} for r in refs["rooms"] if r in rooms],
            "pages": [nav(by_slug[s]) for s in refs["pages"] if s in by_slug],
        },
        "backlinks": backlinks,
        "breadcrumbs": crumbs,
        "children": [nav(c) for c in _page_children(doc, me)],
        "prev": nav(sibs[pos - 1]) if pos > 0 else None,
        "next": nav(sibs[pos + 1]) if 0 <= pos < len(sibs) - 1 else None,
        "revision": revision,
    }


def _clean_page_input(body: Dict[str, Any], cur: Optional[Dict[str, Any]], doc: Dict[str, Any], slug: str) -> Dict[str, Any]:
    from .schema import PAGE_KINDS, PAGE_STATUSES, SLUG_RE

    page: Dict[str, Any] = dict(cur or {})
    for k in _PAGE_FIELDS:
        if k in body:
            page[k] = body[k]
    page["slug"] = str(page.get("slug") or slug).strip().lower()
    if not SLUG_RE.match(page["slug"]):
        raise ApiError(400, "slug must be lowercase letters, digits and dashes", "bad_slug")
    title = str(page.get("title") or "").strip()
    if not title:
        raise ApiError(400, "title is required", "missing_field")
    page["title"] = title
    if page.get("kind") not in (None, "", *PAGE_KINDS):
        raise ApiError(400, f"kind must be one of {', '.join(PAGE_KINDS)}", "bad_enum")
    if page.get("status") not in (None, "", *PAGE_STATUSES):
        raise ApiError(400, f"status must be one of {', '.join(PAGE_STATUSES)}", "bad_enum")
    if page.get("body") is not None and not isinstance(page.get("body"), str):
        raise ApiError(400, "body must be a string", "bad_type")
    for k in ("tags", "rooms", "devices", "attachments"):
        v = page.get(k)
        if v is None or v == "":
            page.pop(k, None)
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            page[k] = [x.strip() for x in v if x.strip()]
        elif isinstance(v, str):
            page[k] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            raise ApiError(400, f"{k} must be a list of ids", "bad_type")
    if page.get("parent") in ("", None):
        page.pop("parent", None)
    elif page.get("parent") == page.get("id"):
        raise ApiError(400, "a page cannot be its own parent", "page_cycle")
    else:
        by_id = {p["id"]: p for p in _pages(doc)}
        if page["parent"] not in by_id:
            raise ApiError(400, f"parent page '{page['parent']}' does not exist", "dangling_ref")
        node, seen = by_id.get(page["parent"]), set()
        while node is not None:
            if node["id"] == page.get("id") or node["id"] in seen:
                raise ApiError(400, "moving the page under its own descendant would make a loop", "page_cycle")
            seen.add(node["id"])
            node = by_id.get(node.get("parent") or "")
    taken = next((p for p in _pages(doc) if p.get("slug") == page["slug"] and p["id"] != page.get("id")), None)
    if taken is not None:
        raise ApiError(409, f"slug '{page['slug']}' is already used by '{taken.get('title')}'", "duplicate_slug")
    for k in ("order",):
        if page.get(k) in ("", None):
            page.pop(k, None)
        else:
            page[k] = _int(page.get(k), 0)
    for k in ("summary", "owner", "review_due", "kind", "status"):
        if page.get(k) in ("", None):
            page.pop(k, None)
        else:
            page[k] = str(page[k]).strip()
    return page


@route("GET", r"/api/v2/projects/" + _NAME + "/pages", role="viewer", summary="SOP pages (tree summaries; ?device= / ?room= list backlinks)", tags=["pages"])
def r_pages(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    dev, room, status, kind = (req.query.get(k) or "" for k in ("device", "room", "status", "kind"))
    out = []
    for p in sorted(_pages(doc), key=lambda x: (str(x.get("parent") or ""),) + _page_order_key(x)):
        if status and (p.get("status") or "published") != status:
            continue
        if kind and (p.get("kind") or "sop") != kind:
            continue
        if dev or room:
            refs = _page_refs(p)
            if dev and dev not in refs["devices"]:
                continue
            if room and room not in refs["rooms"]:
                continue
        out.append(_page_summary(doc, p))
    return Response.json({"pages": out, "revision": _rev(doc)})


@route("POST", r"/api/v2/projects/" + _NAME + "/pages/preview", role="editor", summary="Render Markdown without saving", tags=["pages"], body="PagePreview")
def r_pages_preview(req: Request) -> Response:
    from .markdown import render

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    text = body.get("body")
    if not isinstance(text, str):
        raise ApiError(400, "body must be a string")
    if len(text) > 1_000_000:
        raise ApiError(413, "page body larger than 1 MB", "too_large")
    return Response.json(render(text, _page_resolver(pdir.name, doc)))


@route("GET", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG, role="viewer", summary="A page with rendered HTML, TOC, links and backlinks", tags=["pages"])
def r_page_get(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    return Response.json(_page_payload(pdir.name, doc, page, _rev(doc)))


@route("PUT", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG, role="editor", summary="Create or update a page", tags=["pages"], body="Page")
def r_page_put(req: Request) -> Response:
    from .history import utc_now

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    slug = req.params["slug"]
    cur = next((p for p in _pages(doc) if p.get("slug") == slug), None)
    page = _clean_page_input(body, cur, doc, slug)
    now = utc_now()
    if cur is None:
        page["id"] = "pg-" + secrets.token_hex(4)
        page["created"] = now
        if req.username and not page.get("owner"):
            page["owner"] = req.username
        if not page.get("status"):
            page["status"] = "draft"
        if not page.get("kind"):
            page["kind"] = "sop"
        if page.get("order") is None:
            sibs = _page_children(doc, page.get("parent") or None)
            page["order"] = (max([int(s.get("order") or 0) for s in sibs] or [0]) + 1)
    page["updated"] = now
    if req.username:
        page["updated_by"] = req.username
    ops = [{"op": "put", "coll": "pages", "id": page["id"], "value": page}]
    label = ("New SOP " if cur is None else "Edit SOP ") + page["title"]
    base = body.get("base_revision")
    res = _changes(req, pdir, ops, _int(base, -1), label, "pages") if base is not None else _server_ops(req, pdir, ops, label, "pages")
    doc, _ = _load(pdir)
    out = _page_payload(pdir.name, doc, _page_by_slug(doc, page["slug"]), res["revision"])
    out["problems"] = res.get("problems") or []
    return Response.json(out, 201 if cur is None else 200, headers={"ETag": f'"r{res["revision"]}"'})


@route("DELETE", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG, role="editor", summary="Delete a page (archived instead when it has children)", tags=["pages"])
def r_page_delete(req: Request) -> Response:
    from .history import utc_now

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    kids = _page_children(doc, page["id"])
    if kids and page.get("status") != "archived":
        ops = [{"op": "merge", "coll": "pages", "id": page["id"], "value": {"status": "archived", "updated": utc_now(), "updated_by": req.username or None}}]
        res = _server_ops(req, pdir, ops, f"Archive SOP {page.get('title')}", "pages")
        return Response.json({"archived": True, "children": [k["slug"] for k in kids], "revision": res["revision"]})
    ops = [{"op": "del", "coll": "pages", "id": page["id"]}]
    res = _server_ops(req, pdir, ops, f"Delete SOP {page.get('title')}", "pages")
    return Response.json({"archived": False, "revision": res["revision"]})


@route("POST", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG + "/move", role="editor", summary="Reparent / reorder a page ({parent, before})", tags=["pages"], body="PageMove")
def r_page_move(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    body = req.json()
    parent = body.get("parent", page.get("parent")) or None
    if parent == page["id"]:
        raise ApiError(400, "a page cannot be its own parent", "page_cycle")
    by_id = {p["id"]: p for p in _pages(doc)}
    if parent is not None:
        if parent not in by_id:
            raise ApiError(400, f"parent page '{parent}' does not exist", "dangling_ref")
        node, seen = by_id[parent], set()
        while node is not None:
            if node["id"] == page["id"] or node["id"] in seen:
                raise ApiError(400, "moving the page under its own descendant would make a loop", "page_cycle")
            seen.add(node["id"])
            node = by_id.get(node.get("parent") or "")
    sibs = [s for s in _page_children(doc, parent) if s["id"] != page["id"]]
    before = body.get("before")
    idx = next((i for i, s in enumerate(sibs) if s.get("slug") == before or s.get("id") == before), len(sibs)) if before else len(sibs)
    if body.get("order") is not None and not before:
        idx = max(0, min(len(sibs), _int(body.get("order"), len(sibs) + 1) - 1))
    sibs.insert(idx, page)
    ops: List[Dict[str, Any]] = []
    for i, s in enumerate(sibs, start=1):
        patch: Dict[str, Any] = {}
        if s.get("order") != i:
            patch["order"] = i
        if s["id"] == page["id"] and (page.get("parent") or None) != parent:
            patch["parent"] = parent
        if patch:
            ops.append({"op": "merge", "coll": "pages", "id": s["id"], "value": patch})
    if not ops:
        return Response.json({"revision": _rev(doc), "moved": False})
    res = _server_ops(req, pdir, ops, f"Move SOP {page.get('title')}", "pages")
    return Response.json({"revision": res["revision"], "moved": True})


def _page_versions(pdir: Path, page_id: str) -> List[Dict[str, Any]]:
    from .history import list_revisions

    ref = f"pages/{page_id}"
    return [{"revision": e["revision"], "time": e.get("time"), "author": e.get("author") or "", "summary": e.get("summary") or "",
             "source": e.get("source") or ""} for e in list_revisions(pdir, limit=None) if ref in (e.get("touched") or [])]


@route("GET", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG + "/versions", role="viewer", summary="Revisions that changed this page (newest first)", tags=["pages"])
def r_page_versions(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    limit = _int(req.query.get("limit"), 50, 1, 500)
    return Response.json({"versions": _page_versions(pdir, page["id"])[:limit], "revision": _rev(doc)})


def _page_at(pdir: Path, page: Dict[str, Any], rev: int) -> Dict[str, Any]:
    old = _revision_doc(pdir, rev)
    hit = next((p for p in old.get("pages") or [] if isinstance(p, dict) and p.get("id") == page["id"]), None)
    if hit is None:
        raise ApiError(404, f"the page did not exist at revision {rev}", "history_missing")
    return hit


@route("GET", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG + r"/versions/(?P<rev>\d+)", role="viewer", summary="The page as it was at a revision, rendered", tags=["pages"])
def r_page_version(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    rev = int(req.params["rev"])
    old = _page_at(pdir, page, rev)
    out = _page_payload(pdir.name, doc, old, rev)
    out["current_revision"] = _rev(doc)
    return Response.json(out)


@route("POST", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG + r"/restore/(?P<rev>\d+)", role="editor", summary="Restore this page's content from a revision (new revision)", tags=["pages"], body="Restore")
def r_page_restore(req: Request) -> Response:
    from .history import utc_now

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    rev = int(req.params["rev"])
    old = dict(_page_at(pdir, page, rev))
    # Restore the content; keep the page where it lives in the tree today.
    for k in ("id", "slug", "parent", "order", "created"):
        if page.get(k) is not None:
            old[k] = page[k]
        else:
            old.pop(k, None)
    old["updated"] = utc_now()
    if req.username:
        old["updated_by"] = req.username
    ops = [{"op": "put", "coll": "pages", "id": page["id"], "value": old}]
    body = req.json() if req.body().strip() else {}
    base = body.get("base_revision")
    label = f"Restore SOP {old.get('title')} from r{rev}"
    res = _changes(req, pdir, ops, _int(base, -1), label, "pages") if base is not None else _server_ops(req, pdir, ops, label, "pages")
    return Response.json({"page": old, "revision": res["revision"], "problems": res.get("problems") or []})


_COMPLETIONS_KEEP = 20


@route("POST", r"/api/v2/projects/" + _NAME + "/pages/" + _SLUG + "/complete", role="editor", summary="Record that this checklist was completed (who / when)", tags=["pages"])
def r_page_complete(req: Request) -> Response:
    from .history import utc_now

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    entry = {"at": utc_now(), "by": req.username or "local"}
    done = [c for c in page.get("completions") or [] if isinstance(c, dict)] + [entry]
    ops = [{"op": "merge", "coll": "pages", "id": page["id"], "value": {"completions": done[-_COMPLETIONS_KEEP:]}}]
    res = _server_ops(req, pdir, ops, f"Completed SOP {page.get('title') or page['slug']}", "pages")
    return Response.json({"completion": entry, "completions": done[-_COMPLETIONS_KEEP:], "revision": res["revision"]})


@route("GET", r"/api/v2/projects/" + _NAME + r"/sop/bundle\.zip", role="editor", summary="Offline HTML bundle of the published procedures (zip)", tags=["pages"], page="file")
def r_sop_bundle(req: Request) -> Response:
    from .export import sop_bundle_zip

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    data = sop_bundle_zip(pdir, doc)
    r = Response(data, 200, "application/zip", {"Content-Disposition": f'attachment; filename="{pdir.name}-procedures.zip"', "Cache-Control": "no-cache"})
    r.csp = FILE_CSP
    return r


# ---- problem reports (§4.3.16, §5.16): "Report a problem" from any SOP page

_PROBLEM_TEXT_MAX = 2000
PROBLEM_KINDS = ("problem", "suggestion")


def _multipart_form(req: Request) -> Tuple[Dict[str, str], List[Tuple[str, bytes, str]]]:
    """Text fields and files of a multipart/form-data body."""
    msg = message_from_bytes(f"Content-Type: {req.header('content-type')}\r\nMIME-Version: 1.0\r\n\r\n".encode() + req.body(), policy=email_default_policy)
    fields: Dict[str, str] = {}
    files: List[Tuple[str, bytes, str]] = []
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        fname = part.get_filename()
        if fname:
            files.append((fname, part.get_payload(decode=True) or b"", part.get_content_type() or ""))
            continue
        name = part.get_param("name", header="content-disposition")
        if name:
            fields[str(name)] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    return fields, files


def _problem_view(doc: Dict[str, Any], r: Dict[str, Any], project: str) -> Dict[str, Any]:
    devs = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    pages = {p.get("slug"): p for p in _pages(doc)}
    atts = {a.get("id"): a for a in doc.get("attachments") or [] if isinstance(a, dict)}
    out = dict(r)
    if r.get("device") in devs:
        out["device_name"] = str(devs[r["device"]].get("name") or r["device"])
    if r.get("page") in pages:
        out["page_title"] = str(pages[r["page"]].get("title") or r["page"])
    a = atts.get(r.get("attachment") or "")
    if a is not None:
        out["photo"] = f"api/v2/projects/{quote(project)}/files/{quote(a['id'])}/{quote(Path(str(a.get('file') or a.get('name') or 'file')).name)}"
    return out


def _create_problem(req: Request, pdir: Path, via: str) -> Dict[str, Any]:
    from .history import utc_now
    from .project import add_attachment
    from .schema import STATUSES
    from .users import role_at_least

    doc, _ = _load(pdir)
    photo: Optional[Tuple[str, bytes, str]] = None
    if req.is_multipart():
        fields, files = _multipart_form(req)
        body: Dict[str, Any] = dict(fields)
        photo = next((f for f in files if f[1]), None)
    else:
        body = req.json()
    kind = str(body.get("kind") or "problem").strip().lower()
    if kind not in PROBLEM_KINDS:
        raise ApiError(400, f"kind must be one of {', '.join(PROBLEM_KINDS)}", "bad_enum")
    text = str(body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "describe the problem" if kind == "problem" else "describe the suggestion", "missing_field")
    text = text[:_PROBLEM_TEXT_MAX]
    devs = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    device = str(body.get("device") or "").strip()
    if device and device not in devs:
        raise ApiError(400, f"unknown device '{device}'", "dangling_ref")
    page = str(body.get("page") or "").strip()
    if page and not any(p.get("slug") == page for p in _pages(doc)):
        raise ApiError(400, f"unknown page '{page}'", "dangling_ref")
    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:80]
    now = utc_now()
    # App users are identified by their login; public / share reporters by the name they typed (a real login still
    # counts, the implicit "local" admin of a login-less server does not).
    login = req.username if req.auth_via != "local" else ""
    by = (req.username if via == "app" else (name or login)) or name or "anonymous"
    ent: Dict[str, Any] = {"id": "pr-" + secrets.token_hex(4), "kind": kind, "text": text, "status": "open", "created": now, "by": by, "via": via}
    if device:
        ent["device"] = device
        if devs[device].get("room"):
            ent["room"] = str(devs[device]["room"])
    if page:
        ent["page"] = page
    ops: List[Dict[str, Any]] = []
    if photo is not None:
        fname, data, ctype = photo
        mime = mimetypes.guess_type(fname)[0] or (ctype if ctype and ctype != "application/octet-stream" else "") or ""
        if not mime.startswith("image/"):
            raise ApiError(400, "the photo must be an image", "bad_type")
        att = add_attachment(pdir, fname, data, mime=mime, device=device, kind="photo", author=by)
        att["note"] = f"Problem report {ent['id']}"
        ops.append({"op": "put", "coll": "attachments", "id": att["id"], "value": att})
        ent["attachment"] = att["id"]
    ops.append({"op": "put", "coll": "problems", "id": ent["id"], "value": ent})
    noted = False
    # Editors reporting from the app: the device carries the note straight away (and optionally a new status).
    # Reports through public pages / share links only create the problem entry, whoever is logged in.
    if device and via == "app" and req.user is not None and role_at_least(req.role_for(pdir.name), "editor"):
        stamp = now[:16].replace("T", " ")
        line = f"[{stamp} {by}] {'Suggestion' if kind == 'suggestion' else 'Problem'}: {text}"
        note = str(devs[device].get("note") or "").rstrip()
        merge: Dict[str, Any] = {"note": (note + "\n" if note else "") + line}
        status = str(body.get("device_status") or "").strip()
        if status and kind == "problem":  # a suggestion never changes the device status
            if status not in STATUSES:
                raise ApiError(400, f"device_status must be one of {', '.join(STATUSES)}", "bad_enum")
            merge["status"] = status
        ops.append({"op": "merge", "coll": "devices", "id": device, "value": merge})
        noted = True
    res = _server_ops(req, pdir, ops, f"{'Suggestion' if kind == 'suggestion' else 'Problem reported'}: {text[:60]}", "problems")
    out: Dict[str, Any] = {"problem": ent, "noted": noted, "revision": res["revision"]}
    if kind == "suggestion":
        target = _suggest_url(doc)
        base = _public_base(req, doc)
        link = (_device_url(base, pdir.name, device) if device
                else f"{base}/p/{quote(pdir.name)}/sop/{quote(page)}" if page else f"{base}/p/{quote(pdir.name)}")
        out["forwarded"] = bool(target) and _forward_suggestion(target, {
            "project": pdir.name, "kind": kind, "text": text, "name": by, "device": device or None, "page": page or None, "url": link})
    return out


@route("POST", r"/api/v2/projects/" + _NAME + "/problems", role="viewer", summary="Report a problem or suggest an improvement (kind=problem|suggestion; JSON or multipart with a photo)", tags=["problems"], body="ProblemReport")
def r_problems_create(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    return Response.json(_create_problem(req, pdir, "app"), 201)


@route("GET", r"/api/v2/projects/" + _NAME + "/problems", role="viewer", summary="Problem reports (?status=, ?device=, ?page=, ?kind=problem|suggestion)", tags=["problems"])
def r_problems(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    status = req.query.get("status") or ""
    device = req.query.get("device") or ""
    page = req.query.get("page") or ""
    kind = req.query.get("kind") or ""
    items = [r for r in doc.get("problems") or [] if isinstance(r, dict) and r.get("id")
             and (not status or (r.get("status") or "open") == status)
             and (not device or r.get("device") == device) and (not page or r.get("page") == page)
             and (not kind or (r.get("kind") or "problem") == kind)]
    # newest first; reports filed within the same second keep their insertion order (later entries first)
    items.reverse()
    items.sort(key=lambda r: str(r.get("created") or ""), reverse=True)
    is_open = [r for r in doc.get("problems") or [] if isinstance(r, dict) and (r.get("status") or "open") == "open"]
    return Response.json({"problems": [_problem_view(doc, r, pdir.name) for r in items],
                          "open": sum(1 for r in is_open if (r.get("kind") or "problem") == "problem"),
                          "open_suggestions": sum(1 for r in is_open if r.get("kind") == "suggestion"),
                          "revision": _rev(doc)})


@route("PATCH", r"/api/v2/projects/" + _NAME + r"/problems/(?P<pid>pr-[0-9a-f]{8})", role="editor", summary="Resolve / reopen a problem report", tags=["problems"], body="ProblemPatch")
def r_problem_patch(req: Request) -> Response:
    from .history import utc_now
    from .schema import PROBLEM_STATUSES

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    cur = next((r for r in doc.get("problems") or [] if isinstance(r, dict) and r.get("id") == req.params["pid"]), None)
    if cur is None:
        raise ApiError(404, "problem report not found")
    body = req.json()
    status = str(body.get("status") or cur.get("status") or "open")
    if status not in PROBLEM_STATUSES:
        raise ApiError(400, f"status must be one of {', '.join(PROBLEM_STATUSES)}", "bad_enum")
    value: Dict[str, Any] = {"status": status}
    if "note" in body:
        value["note"] = str(body.get("note") or "")[:_PROBLEM_TEXT_MAX] or None
    if status == "resolved":
        value["resolved"] = utc_now()
        value["resolved_by"] = req.username or "local"
    else:
        value["resolved"] = None
        value["resolved_by"] = None
    res = _server_ops(req, pdir, [{"op": "merge", "coll": "problems", "id": cur["id"], "value": value}],
                      f"Problem {status}: {str(cur.get('text') or '')[:50]}", "problems")
    return Response.json({"problem": dict(cur, **{k: v for k, v in value.items() if v is not None}), "revision": res["revision"]})


# ---- imports


def _importer(kind: str) -> Any:
    try:
        from .plugins import get_importer

        return get_importer(kind)
    except Exception:
        return None


def _detect(target: Path) -> str:
    try:
        from .plugins import detect

        return detect(target)
    except Exception:
        from .parsers import detect_kind

        return detect_kind(target)


def _known_kind(kind: str) -> bool:
    if _importer(kind) is not None:
        return True
    try:
        from .parsers import KINDS as IMPORT_KINDS

        return kind in IMPORT_KINDS
    except Exception:
        return False


def _parse(target: Path, kind: str, options: Optional[Dict[str, Any]] = None) -> Any:
    imp = _importer(kind)
    if imp is not None:
        return imp.parse(target, **(options or {}))
    from .parsers import parse_any

    return parse_any(target, kind)


def _summary(result: Any) -> Dict[str, Any]:
    fn = getattr(result, "summary", None)
    if callable(fn):
        try:
            s = fn()
            return s if isinstance(s, dict) else {"summary": s}
        except Exception:
            _log_exc("summary failed")
    return result if isinstance(result, dict) else {}


def _save_upload(req: Request, pdir: Path, kind: str, folder: str) -> Tuple[Path, str, List[Path]]:
    files = req.files()
    kind_dir = kind if kind not in ("", "auto") else "incoming"
    if not _SEG_RE.match(kind_dir):
        raise ApiError(400, "bad import kind")
    dest_dir = pdir / "exports" / kind_dir
    if folder:
        dest_dir = dest_dir / _safe_filename(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    for fname, data, _ in files:
        dest = dest_dir / _safe_filename(fname)
        dest.write_bytes(data)
        saved.append(dest)
    target = saved[0].parent if (folder or len(saved) > 1) else saved[0]
    detected = kind if kind not in ("", "auto") else _detect(target)
    if not detected or detected == "unknown" or not _known_kind(detected):
        for f in saved:
            f.unlink(missing_ok=True)
        if folder and target.is_dir() and not any(target.iterdir()):
            target.rmdir()
        raise ApiError(400, f"could not tell what {target.name} is; choose the kind explicitly")
    if kind in ("", "auto"):
        final_dir = pdir / "exports" / detected
        final_dir.mkdir(parents=True, exist_ok=True)
        moved = final_dir / target.name
        if target.is_dir() and moved.exists():
            shutil.rmtree(moved)
        shutil.move(str(target), str(moved))
        target = moved
        incoming = pdir / "exports" / "incoming"
        if incoming.is_dir() and not any(incoming.iterdir()):
            incoming.rmdir()
    return target, detected, saved


def _register_import(req: Request, pdir: Path, target: Path, kind: str, device: str, room: str) -> Tuple[Dict[str, Any], int]:
    from .history import utc_now
    from .schema import default_room_id

    doc, _ = _load(pdir)
    rel = target.relative_to(pdir).as_posix()
    existing = next((i for i in doc.get("imports") or [] if isinstance(i, dict) and i.get("path") == rel), None)
    if existing is not None:
        ent = dict(existing, kind=kind)
        if device:
            ent["device"] = device
        if room:
            ent["room"] = room
    else:
        taken = {i.get("id") for i in doc.get("imports") or [] if isinstance(i, dict)}
        n = 1
        while "imp-%04d" % n in taken:
            n += 1
        ent = {"id": "imp-%04d" % n, "kind": kind, "path": rel, "room": room or default_room_id(doc) or "main", "added": utc_now()}
        if device:
            ent["device"] = device
        if req.username:
            ent["by"] = req.username
    res = _server_ops(req, pdir, [{"op": "put", "coll": "imports", "id": ent["id"], "value": ent}], f"Import {target.name}", "import")
    return ent, res["revision"]


@route("POST", r"/api/v2/projects/" + _NAME + "/imports", role="editor", summary="Upload and register an import", tags=["imports"], body="Multipart")
def r_import_v2(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    device = req.query.get("device", "")
    if device and not _ID_RE.match(device):
        raise ApiError(400, "bad device id")
    target, kind, _ = _save_upload(req, pdir, req.query.get("kind", "auto"), req.query.get("folder", ""))
    result = _parse(target, kind)
    fatal = str(getattr(result, "fatal", "") or "")
    if fatal:
        if target.is_file():
            target.unlink(missing_ok=True)
        raise ApiError(422, fatal)
    summary = _summary(result)
    ent, rev = _register_import(req, pdir, target, kind, device, req.query.get("room", ""))
    return Response.json({"import": ent, "summary": summary, "revision": rev}, 201)


def _import_ent(doc: Dict[str, Any], import_id: str) -> Dict[str, Any]:
    ent = next((i for i in doc.get("imports") or [] if isinstance(i, dict) and i.get("id") == import_id), None)
    if ent is None:
        raise ApiError(404, "import not found")
    return ent


def _import_target(pdir: Path, ent: Dict[str, Any]) -> Path:
    p = Path(str(ent.get("path") or ""))
    return p if p.is_absolute() else pdir / p


@route("DELETE", r"/api/v2/projects/" + _NAME + r"/imports/(?P<iid>" + _EID + ")", role="editor", summary="Remove an import", tags=["imports"])
def r_import_delete_v2(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    ent = _import_ent(doc, req.params["iid"])
    if req.query.get("delete_files") == "1":
        target = _import_target(pdir, ent)
        if _contained(target, pdir / "exports") and target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
    res = _server_ops(req, pdir, [{"op": "del", "coll": "imports", "id": ent["id"]}], f"Removed import {ent.get('path')}", "import")
    return Response.json({"revision": res["revision"]})


@route("GET", r"/api/v2/projects/" + _NAME + r"/imports/(?P<iid>" + _EID + ")/inspect", role="viewer", summary="Parse summary of an import", tags=["imports"])
def r_import_inspect_v2(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    ent = _import_ent(doc, req.params["iid"])
    target = _import_target(pdir, ent)
    if not target.exists():
        raise ApiError(404, "import files not found")
    return Response.json({"kind": ent.get("kind"), "summary": _summary(_parse(target, str(ent.get("kind")), ent.get("options") or None))})


@route("POST", r"/api/v2/projects/" + _NAME + "/imports/preview", role="editor", summary="Preview a one-shot import as ops (no write)", tags=["imports"], body="Multipart")
def r_import_preview(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    files = req.files()
    tmp = Path(tempfile.mkdtemp(prefix="fathom-preview-"))
    try:
        for fname, data, _ in files:
            (tmp / _safe_filename(fname)).write_bytes(data)
        target = tmp if len(files) > 1 else tmp / _safe_filename(files[0][0])
        kind = req.query.get("kind") or _detect(target)
        imp = _importer(kind)
        if imp is None or getattr(imp, "preview", None) is None:
            raise ApiError(400, f"no one-shot importer for kind '{kind}'")
        result = imp.parse(target)
        room = req.query.get("room") or ""
        out = imp.preview(result, doc, {"room": room, "device": req.query.get("device", ""), "import": None, "project_dir": pdir}) or {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response.json({"kind": kind, "ops": out.get("ops") or [], "summary": out.get("summary") or {}, "warnings": out.get("warnings") or [],
                          "errors": out.get("errors") or [], "base_revision": _rev(doc), "suggestions": _op_suggestions(out.get("ops") or [], doc)})


def _op_suggestions(ops: List[Dict[str, Any]], doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Model suggestions for the devices a one-shot import would create without a template (device id → suggestions)."""
    from .library.suggest import suggest_for_device

    out: Dict[str, List[Dict[str, Any]]] = {}
    for op in ops:
        if not isinstance(op, dict) or op.get("coll") != "devices" or op.get("op") != "put" or not isinstance(op.get("value"), dict):
            continue
        sug = suggest_for_device(op["value"], doc)
        if sug:
            out[str(op.get("id") or op["value"].get("id"))] = sug
    return out


@route("GET", r"/api/v2/projects/" + _NAME + r"/imports/templates/(?P<kind>" + _EID + r")/(?P<table>[a-z0-9_-]{1,32})\.csv", role="viewer",
       summary="Example file for an importer (edit, then upload)", tags=["imports"])
def r_import_template(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    imp = _importer(req.params["kind"])
    table = req.params["table"]
    names = [str(t.get("name")) for t in getattr(imp, "templates", ()) or ()] if imp is not None else []
    if imp is None or getattr(imp, "template", None) is None or table not in names:
        raise ApiError(404, "no such import template")
    text = imp.template(table, doc)
    fname = f"fathom-{table}-template.csv"
    return Response.text("\ufeff" + text, "text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---- network discovery (ad hoc runs — nothing here runs unless a request starts it; active probes are opt-in per project)

_RUN_ID = r"(?P<rid>run-\d{8}-\d{6}-[0-9a-f]{4})"


def _discovery_error(exc: Exception) -> ApiError:
    from . import discovery

    if isinstance(exc, discovery.RunBusy):
        return ApiError(409, str(exc), code="run_active", details={"run": exc.run_id})
    if isinstance(exc, discovery.RunNotFound):
        return ApiError(404, "discovery run not found")
    if isinstance(exc, ValueError):
        return ApiError(400, str(exc))
    raise exc


@route("GET", r"/api/v2/projects/" + _NAME + "/discovery/runs", role="viewer", summary="Discovery runs for the project (latest first) and the active one", tags=["discovery"])
def r_discovery_runs(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    return Response.json({"runs": discovery.list_runs(pdir), "active": discovery.active_run_id(pdir) or None, "sources": discovery.sources(doc, pdir),
                          "capabilities": discovery.extra_installed(), "mode": discovery.MODE})


@route("POST", r"/api/v2/projects/" + _NAME + "/discovery/runs", role="editor", summary="Start a discovery run (409 while one is active); active probes only when enabled for the project", tags=["discovery"], body="DiscoveryRun")
def r_discovery_run_start(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    window = body.get("window")
    if window is not None and not isinstance(window, (int, float)):
        raise ApiError(400, "window must be a number of seconds")
    probes = body.get("probes")
    if probes is not None and not (isinstance(probes, list) and all(isinstance(p, str) for p in probes)):
        raise ApiError(400, "probes must be a list of probe ids")
    try:
        run = discovery.start_run(pdir, doc, by=req.username, window=int(window) if window is not None else None, probes=probes)
    except Exception as exc:
        raise _discovery_error(exc)
    return Response.json({"run": run}, 202)


@route("GET", r"/api/v2/projects/" + _NAME + "/discovery/runs/" + _RUN_ID, role="viewer", summary="Status, progress and log of a discovery run", tags=["discovery"])
def r_discovery_run(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    try:
        return Response.json({"run": discovery.get_run(pdir, req.params["rid"])})
    except Exception as exc:
        raise _discovery_error(exc)


@route("DELETE", r"/api/v2/projects/" + _NAME + "/discovery/runs/" + _RUN_ID, role="editor", summary="Cancel a discovery run", tags=["discovery"])
def r_discovery_run_cancel(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    try:
        return Response.json({"run": discovery.cancel_run(pdir, req.params["rid"])})
    except Exception as exc:
        raise _discovery_error(exc)


@route("GET", r"/api/v2/projects/" + _NAME + "/discovery/runs/" + _RUN_ID + "/findings", role="viewer",
       summary="Findings of a run, correlated against the current document", tags=["discovery"])
def r_discovery_findings(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    try:
        return Response.json(discovery.findings(pdir, doc, req.params["rid"]))
    except Exception as exc:
        raise _discovery_error(exc)


@route("GET", r"/api/v2/projects/" + _NAME + "/discovery/runs/" + _RUN_ID + "/diff", role="viewer",
       summary="What changed since a previous completed run (?against=<run id>; default: the one before)", tags=["discovery"])
def r_discovery_diff(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    against = str(req.query.get("against") or "")
    if against and not discovery.RUN_ID_RE.match(against):
        raise ApiError(400, "against must be a run id")
    try:
        return Response.json(discovery.run_diff(pdir, doc, req.params["rid"], against=against))
    except Exception as exc:
        raise _discovery_error(exc)


@route("POST", r"/api/v2/projects/" + _NAME + "/discovery/runs/" + _RUN_ID + "/findings/promote", role="editor",
       summary="Promote findings: create devices, merge into existing, add cables / networks, ignore", tags=["discovery"], body="DiscoveryPromote")
def r_discovery_promote(req: Request) -> Response:
    from . import discovery

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    try:
        ops, summary = discovery.promote_ops(pdir, doc, req.params["rid"], body)
    except Exception as exc:
        raise _discovery_error(exc)
    if len(ops) > MAX_OPS:
        raise ApiError(413, f"too many changes in one promote ({len(ops)} > {MAX_OPS})")
    revision = _rev(doc)
    if ops:
        parts = [f"{n} {k}" for k, n in summary.items() if n and k != "ignored"]
        res = _server_ops(req, pdir, ops, "Discovery: " + (", ".join(parts) or "promote"), "discovery")
        revision = res["revision"]
    return Response.json({"ops": len(ops), "summary": summary, "revision": revision})


@route("GET", r"/api/v2/projects/" + _NAME + "/discovery/settings", role="viewer", summary="Discovery settings (secrets reported as *_set flags only)", tags=["discovery"])
def r_discovery_settings(req: Request) -> Response:
    from . import discovery
    from .discovery import settings as dsettings

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    return Response.json({"settings": dsettings.public(doc, pdir), "sources": discovery.sources(doc, pdir), "limits": {"min_window": dsettings.MIN_WINDOW, "max_window": dsettings.MAX_WINDOW}})


@route("PUT", r"/api/v2/projects/" + _NAME + "/discovery/settings", role="editor", summary="Update discovery settings (secrets go to a side file, never into the document)",
       tags=["discovery"], body="DiscoverySettings")
def r_discovery_settings_put(req: Request) -> Response:
    from .discovery import settings as dsettings
    from .project import project_lock

    pdir = _project_dir(req.params["name"])
    body = req.json()
    with project_lock(pdir):
        doc, _ = _load(pdir)
        try:
            value = dsettings.apply_update(doc, pdir, body)
        except ValueError as exc:
            raise ApiError(400, str(exc))
        res = _server_ops(req, pdir, [{"op": "root", "key": "settings", "value": {"discovery": value}}], "Discovery settings", "discovery")
    doc, _ = _load(pdir)
    return Response.json({"settings": dsettings.public(doc, pdir), "revision": res["revision"]})


@route("POST", r"/api/v2/projects/" + _NAME + "/discovery/test", role="editor", summary="Test one source (reachability / capability; never starts a listen window)",
       tags=["discovery"], body="DiscoveryTest")
def r_discovery_test(req: Request) -> Response:
    from .discovery import settings as dsettings
    from .discovery.probes import all_probes, probe_by_id

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    mod = probe_by_id(str(body.get("probe") or ""))
    if mod is None:
        raise ApiError(400, "probe must be one of " + ", ".join(m.INFO.id for m in all_probes()))
    cfg = dsettings.effective(doc, pdir)["probes"].get(mod.INFO.id) or {}
    if isinstance(body.get("settings"), dict):  # unsaved form values; secrets only when typed
        for k, v in body["settings"].items():
            if isinstance(v, (str, bool, int, float)) and (v != "" or k not in dsettings.secret_keys(mod.INFO.id)):
                cfg[k] = v
    try:
        result = mod.test(cfg)
    except Exception as exc:
        result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    result["message"] = dsettings.redact(str(result.get("message") or ""), pdir)
    return Response.json({"probe": mod.INFO.id, "result": result})


# ---- files (attachments)


_INLINE_IMAGES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@route("POST", r"/api/v2/projects/" + _NAME + "/files", role="editor", summary="Upload photos / documents", tags=["files"], body="Multipart")
def r_files_post(req: Request) -> Response:
    from .project import add_attachment

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    device = req.query.get("device", "")
    if device and not any(isinstance(d, dict) and d.get("id") == device for d in doc.get("devices") or []):
        raise ApiError(400, f"unknown device '{device}'")
    atts = []
    for fname, data, ctype in req.files():
        mime = mimetypes.guess_type(fname)[0] or (ctype if ctype and ctype != "application/octet-stream" else "") or "application/octet-stream"
        kind = req.query.get("kind") or ("photo" if mime.startswith("image/") else "document")
        if kind not in ("photo", "document", "floorplan", "floorplan-source", "other"):
            raise ApiError(400, "bad attachment kind")
        atts.append(add_attachment(pdir, fname, data, mime=mime, device=device, kind=kind, author=req.username))
    ops = [{"op": "put", "coll": "attachments", "id": a["id"], "value": a} for a in atts]
    res = _server_ops(req, pdir, ops, f"Uploaded {len(atts)} file{'s' if len(atts) != 1 else ''}", "files")
    return Response.json({"attachments": atts, "revision": res["revision"]}, 201)


def _attachment(doc: Dict[str, Any], att_id: str) -> Dict[str, Any]:
    a = next((x for x in doc.get("attachments") or [] if isinstance(x, dict) and x.get("id") == att_id), None)
    if a is None:
        raise ApiError(404, "file not found")
    return a


def _attachment_path(pdir: Path, att: Dict[str, Any]) -> Path:
    root = pdir / "files"
    target = pdir / str(att.get("file") or "")
    if not str(att.get("file") or "").startswith("files/") or not _contained(target, root) or not target.is_file():
        raise ApiError(404, "file not found")
    return target


def _serve_user_file(path: Path, mime: str, name: str) -> Response:
    data = path.read_bytes()
    headers = {"Cache-Control": "no-cache"}
    ctype = mime or "application/octet-stream"
    if ctype == "image/svg+xml":
        try:
            from .floorplan import sanitize_svg

            data = sanitize_svg(data.decode("utf-8", "replace")).encode("utf-8")
        except Exception:
            headers["Content-Disposition"] = f'attachment; filename="{quote(name)}"'
    elif ctype not in _INLINE_IMAGES:
        headers["Content-Disposition"] = f'attachment; filename="{quote(name)}"'
    r = Response(data, 200, ctype, headers)
    r.csp = FILE_CSP
    return r


@route("GET", r"/api/v2/projects/" + _NAME + r"/files/(?P<att>att-[0-9a-f]{12})/(?P<filename>[^/]+)", role="viewer", summary="Download an attachment", tags=["files"], page="file")
def r_files_get(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    att = _attachment(doc, req.params["att"])
    path = _attachment_path(pdir, att)
    return _serve_user_file(path, str(att.get("mime") or ""), path.name)


@route("DELETE", r"/api/v2/projects/" + _NAME + r"/files/(?P<att>att-[0-9a-f]{12})", role="editor", summary="Delete an attachment", tags=["files"])
def r_files_delete(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    att = _attachment(doc, req.params["att"])
    users = [f.get("id") for f in doc.get("floorplans") or [] if isinstance(f, dict)
             and att["id"] in ((f.get("source") or {}).get("attachment"), (f.get("image") or {}).get("attachment"))]
    if users:
        raise ApiError(409, f"used by floor plan {', '.join(str(u) for u in users)}", "in_use", {"floorplans": users})
    res = _server_ops(req, pdir, [{"op": "del", "coll": "attachments", "id": att["id"]}], f"Deleted {att.get('name')}", "files")
    folder = pdir / "files" / att["id"]
    if _contained(folder, pdir / "files") and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    return Response.json({"revision": res["revision"]})


# ---- floor plans


_PLAN_MIME = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg"}


def _plan_error(exc: Exception) -> ApiError:
    code = str(getattr(exc, "code", "unsupported_format") or "unsupported_format")
    msg = str(getattr(exc, "message", "") or exc)
    if code == "pdf_unsupported":
        return ApiError(422, msg, code)
    if code == "binary_dxf":
        return ApiError(415, msg, "unsupported_format")
    return ApiError(415, msg, code if code in ("dwg_unsupported", "unsupported_format") else "unsupported_format")


@route("POST", r"/api/v2/projects/" + _NAME + "/floorplans", role="editor", summary="Upload a floor plan", tags=["floorplans"], body="Multipart")
def r_floorplan_post(req: Request) -> Response:
    from . import floorplan as FP
    from .model import slug
    from .project import add_attachment
    from .schema import default_room_id

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    files = req.files()
    fname, data, _ = files[0]
    room = req.query.get("room") or default_room_id(doc)
    if room not in _room_ids(doc):
        raise ApiError(400, f"unknown room '{room}'")
    page = _int(req.query.get("page"), 0, 0)
    name = req.query.get("name") or Path(fname).stem or "Floor plan"
    src_kind = FP.detect_plan_kind(fname, data[:4096])
    tmp = Path(tempfile.mkdtemp(prefix="fathom-plan-"))
    try:
        src_path = tmp / _safe_filename(fname)
        src_path.write_bytes(data)
        try:
            res = FP.convert(src_path, page=page)
        except FP.UnsupportedPlan as exc:
            raise _plan_error(exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    src_mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    src_att = add_attachment(pdir, fname, data, mime=src_mime, kind="floorplan-source", author=req.username)
    image_kind = res.image_kind
    if image_kind == src_kind and res.data == data:
        img_att = src_att
        img_att["kind"] = "floorplan"
    else:
        stem = Path(_safe_filename(fname)).stem
        img_att = add_attachment(pdir, f"{stem}.{image_kind}", res.data, mime=_PLAN_MIME.get(image_kind, "application/octet-stream"), kind="floorplan", author=req.username)
    taken = {f.get("id") for f in doc.get("floorplans") or [] if isinstance(f, dict)}
    fid = base_id = "fp-" + slug(name)
    n = 2
    while fid in taken:
        fid = f"{base_id}-{n}"
        n += 1
    fp: Dict[str, Any] = {"id": fid, "name": name, "room": room, "source": {"attachment": src_att["id"], "kind": res.kind or src_kind, "page": page},
                          "image": {"attachment": img_att["id"], "kind": image_kind, "width": res.width, "height": res.height}}
    if res.layers:
        fp["layers"] = res.layers
    if res.units:
        fp["units"] = res.units
    ops = [{"op": "put", "coll": "attachments", "id": src_att["id"], "value": src_att}]
    if img_att is not src_att:
        ops.append({"op": "put", "coll": "attachments", "id": img_att["id"], "value": img_att})
    ops.append({"op": "put", "coll": "floorplans", "id": fid, "value": fp})
    out = _server_ops(req, pdir, ops, f"Added floor plan {name}", "files")
    return Response.json({"floorplan": fp, "warnings": list(res.warnings or []), "revision": out["revision"]}, 201)


def _floorplan(doc: Dict[str, Any], fid: str) -> Dict[str, Any]:
    f = next((x for x in doc.get("floorplans") or [] if isinstance(x, dict) and x.get("id") == fid), None)
    if f is None:
        raise ApiError(404, "floor plan not found")
    return f


@route("POST", r"/api/v2/projects/" + _NAME + r"/floorplans/(?P<fp>" + _EID + ")/reconvert", role="editor", summary="Re-render a floor plan (page / hidden layers)", tags=["floorplans"], body="Reconvert")
def r_floorplan_reconvert(req: Request) -> Response:
    from . import floorplan as FP
    from .project import add_attachment

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    fp = dict(_floorplan(doc, req.params["fp"]))
    body = req.json()
    src = _attachment(doc, str((fp.get("source") or {}).get("attachment")))
    page = _int(body.get("page", (fp.get("source") or {}).get("page", 0)), 0, 0)
    hidden = body.get("hidden_layers", fp.get("hidden_layers") or [])
    try:
        res = FP.convert(_attachment_path(pdir, src), page=page, hide_layers=[str(x) for x in hidden or []])
    except FP.UnsupportedPlan as exc:
        raise _plan_error(exc)
    img = add_attachment(pdir, f"{Path(str(src.get('name') or 'plan')).stem}.{res.image_kind}", res.data,
                         mime=_PLAN_MIME.get(res.image_kind, "application/octet-stream"), kind="floorplan", author=req.username)
    fp["source"] = dict(fp.get("source") or {}, page=page)
    fp["image"] = {"attachment": img["id"], "kind": res.image_kind, "width": res.width, "height": res.height}
    if hidden:
        fp["hidden_layers"] = list(hidden)
    if res.layers:
        fp["layers"] = res.layers
    ops = [{"op": "put", "coll": "attachments", "id": img["id"], "value": img}, {"op": "put", "coll": "floorplans", "id": fp["id"], "value": fp}]
    out = _server_ops(req, pdir, ops, f"Re-rendered floor plan {fp.get('name')}", "files")
    return Response.json({"floorplan": fp, "revision": out["revision"]})


@route("GET", r"/api/v2/projects/" + _NAME + r"/floorplans/(?P<fp>" + _EID + r")/image", role="viewer", summary="Floor plan image (?hide=L1,L2)", tags=["floorplans"], page="file")
def r_floorplan_image(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    fp = _floorplan(doc, req.params["fp"])
    img = _attachment(doc, str((fp.get("image") or {}).get("attachment")))
    hide = [x for x in (req.query.get("hide") or "").split(",") if x]
    src_kind = (fp.get("source") or {}).get("kind")
    if hide and (fp.get("image") or {}).get("kind") == "svg" and src_kind in ("dxf", "drawio"):
        from . import floorplan as FP

        src = _attachment(doc, str((fp.get("source") or {}).get("attachment")))
        key = hashlib.sha1(("|".join(sorted(hide)) + f"|{(fp.get('source') or {}).get('page', 0)}").encode("utf-8")).hexdigest()
        cache = pdir / "files" / src["id"] / "cache" / f"{key}.svg"
        if not cache.is_file():
            res = FP.convert(_attachment_path(pdir, src), page=_int((fp.get("source") or {}).get("page"), 0), hide_layers=hide)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(res.data)
        return _serve_user_file(cache, "image/svg+xml", cache.name)
    path = _attachment_path(pdir, img)
    return _serve_user_file(path, str(img.get("mime") or _PLAN_MIME.get(str((fp.get("image") or {}).get("kind")), "")), path.name)


@route("GET", r"/api/v2/projects/" + _NAME + r"/floorplans/(?P<fp>" + _EID + r")\.svg", role="viewer", summary="Floor plan export SVG with markers", tags=["floorplans"], page="file")
def r_floorplan_svg(req: Request) -> Response:
    from .floorplan import plan_svg

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    fid = req.params["fp"]
    _floorplan(doc, fid)
    r = Response.text(plan_svg(doc, fid, pdir), "image/svg+xml; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = FILE_CSP
    return r


# ---- schedules, analysis, trace, search, QR


@route("GET", r"/api/v2/projects/" + _NAME + r"/schedules/(?P<kind>[a-z]+)", role="viewer", summary="Schedules (patch, cables, ip, dmx, bom, inventory, racks, labels)", tags=["schedules"])
def r_schedule(req: Request) -> Response:
    from .schema import filter_state

    pdir = _project_dir(req.params["name"])
    kind = req.params["kind"]
    if kind not in SCHEDULE_KINDS:
        raise ApiError(404, f"unknown schedule '{kind}'")
    doc, _ = _load(pdir)
    fmt = req.query.get("format") or ("html" if kind == "labels" else "json")
    if fmt not in ("json", "csv", "html"):
        raise ApiError(400, "format must be json, csv or html")
    room = req.query.get("room") or "*"
    state = req.query.get("state") or "all"
    disc = req.query.get("discipline") or ""
    if state not in ("all", "planned", "as_built", "everything"):
        raise ApiError(400, "state must be all, planned, as_built or everything")
    fdoc = filter_state(doc, state)
    name = pdir.name
    if kind == "labels":
        if fmt != "html":
            raise ApiError(400, "labels are only available as format=html")
        from .cables import label_sheet_html

        layout = (doc.get("settings") or {}).get("labels") or None
        r = Response.text(_compat(label_sheet_html, fdoc, room=room, layout=layout, qr=req.query.get("qr") == "1", base_url=_public_base(req, doc)),
                          "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
        r.csp = VIEWER_CSP
        return r
    if kind == "patch" and fmt == "csv":
        from .patch import patch_table, patch_table_csv

        text = patch_table_csv(_compat(patch_table, fdoc, _overlay(doc, pdir, strict=False), room=room, discipline=disc))
        return Response.text(text, "text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}-{kind}.csv"'})
    if kind == "patch":
        from .patch import patch_schedule

        data = _compat(patch_schedule, fdoc, _overlay(doc, pdir, strict=False), room=room, discipline=disc)
    elif kind == "cables":
        from .cables import cable_schedule

        data = _compat(cable_schedule, doc, room=room, state=state, discipline=disc)
    elif kind == "ip":
        from .network import ip_schedule

        data = _compat(ip_schedule, fdoc, _overlay(doc, pdir, strict=False), room=room)
    elif kind == "dmx":
        from .dmx import dmx_schedule

        data = _compat(dmx_schedule, fdoc, _overlay(doc, pdir, strict=False), room=room)
    elif kind == "bom":
        from .bom import bom

        data = _compat(bom, doc, state=state, room=room)
    elif kind == "inventory":
        from .bom import inventory_schedule

        data = _compat(inventory_schedule, doc, room=room)
    else:
        from .racks import rack_schedule

        data = _compat(rack_schedule, fdoc, room=room)
    data = dict(data or {})
    data.setdefault("kind", kind)
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if fmt == "csv":
        return Response.text(_csv(columns, rows), "text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}-{kind}.csv"'})
    if fmt == "html":
        r = Response.text(_html_table(f"{name} · {kind}", columns, rows), "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
        r.csp = VIEWER_CSP
        return r
    data.setdefault("problems", [])
    return Response.json(data)


@route("GET", r"/api/v2/projects/" + _NAME + "/cables/tag-preview", role="editor", summary="Preview automatic cable tags as ops", tags=["schedules"])
def r_tag_preview(req: Request) -> Response:
    from .cables import assign_tags_ops

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    scope = req.query.get("scope") or "missing"
    if scope not in ("missing", "all"):
        raise ApiError(400, "scope must be missing or all")
    ops = assign_tags_ops(doc, scope=scope, pattern=req.query.get("pattern") or None)
    return Response.json({"ops": ops, "count": len(ops), "base_revision": _rev(doc)})


@route("GET", r"/api/v2/projects/" + _NAME + r"/racks/(?P<rack>" + _EID + r")\.svg", role="viewer", summary="Rack elevation SVG (?face=front|rear)", tags=["schedules"], page="file")
def r_rack_svg(req: Request) -> Response:
    from .racks import rack_svg

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    rid = req.params["rack"]
    if not any(isinstance(r, dict) and r.get("id") == rid for r in doc.get("racks") or []):
        raise ApiError(404, "rack not found")
    face = req.query.get("face") or "front"
    if face not in ("front", "rear"):
        raise ApiError(400, "face must be front or rear")
    r = Response.text(rack_svg(doc, rid, face=face), "image/svg+xml; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = FILE_CSP
    return r


# ---- device labels for the Brady M511 (phase 1 P1B, §3.24 FR-QR-03..05, §5.8)


@route("GET", r"/api/v2/labels/presets", role="viewer", summary="Device label presets: Brady M511 cartridge sizes (id, label, width_mm, height_mm, parts, continuous)", tags=["schedules"])
def r_label_presets(req: Request) -> Response:
    from .labels import DEFAULT_PRESET, presets

    return Response.json({"presets": presets(), "default": DEFAULT_PRESET})


@route("GET", r"/api/v2/projects/" + _NAME + r"/labels/devices", role="viewer",
       summary="Device labels at true size for the Brady M511 (?preset=, format=html|csv|zip|svg, devices=<id,id>, room=, status=, png=0)", tags=["schedules"])
def r_device_labels(req: Request) -> Response:
    from .labels import DEFAULT_PRESET, PRESETS, device_label_svg, label_sheet_html, labels_csv, labels_zip, select_devices

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    preset = req.query.get("preset") or DEFAULT_PRESET
    if preset not in PRESETS:
        raise ApiError(400, "bad_preset", "bad_preset", {"presets": sorted(PRESETS)})
    fmt = req.query.get("format") or "html"
    if fmt not in ("html", "csv", "zip", "svg"):
        raise ApiError(400, "format must be html, csv, zip or svg")
    room = req.query.get("room") or None
    if room and room != "*" and room not in _room_ids(doc):
        raise ApiError(404, f"room '{room}' not found")
    status = req.query.get("status") or None
    devices = select_devices(doc, ids=req.query.get("devices") or None, room=room, state=status)
    base = _public_base(req, doc)
    name = pdir.name
    if fmt == "svg":
        if len(devices) != 1 or len([s for s in (req.query.get("devices") or "").split(",") if s.strip()]) != 1:
            raise ApiError(400, "format=svg needs exactly one device id in ?devices=", "one_device")
        r = Response.text(device_label_svg(doc, devices[0], preset, base_url=base, project=name), "image/svg+xml; charset=utf-8",
                          headers={"Cache-Control": "no-cache", "Content-Disposition": f'inline; filename="{_safe_filename(devices[0]["id"])}-{preset}.svg"'})
        r.csp = FILE_CSP
        return r
    if fmt == "csv":
        return Response.text(labels_csv(doc, devices, base_url=base, project=name), "text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="device-labels.csv"'})
    if fmt == "zip":
        data = labels_zip(doc, devices, preset, base_url=base, project=name, png=req.query.get("png") != "0")
        r = Response(data, 200, "application/zip", {"Content-Disposition": f'attachment; filename="device-labels-{preset}.zip"', "Cache-Control": "no-cache"})
        r.csp = FILE_CSP
        return r
    title = " · ".join(s for s in ("Device labels", (doc.get("meta") or {}).get("org") or name) if s)
    r = Response.text(label_sheet_html(doc, devices, preset, base_url=base, title=title, project=name), "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = VIEWER_CSP
    return r


@route("GET", r"/api/v2/projects/" + _NAME + r"/qr/(?P<device>" + _EID + r")\.svg", role="viewer", summary="QR code SVG for a device page", tags=["schedules"], page="file")
def r_qr(req: Request) -> Response:
    from .qr import svg

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    dev = req.params["device"]
    if not any(isinstance(d, dict) and d.get("id") == dev for d in doc.get("devices") or []):
        raise ApiError(404, "device not found")
    base = _public_base(req, doc)
    if not base:
        raise ApiError(409, "no public URL is known (set settings.public_url or FATHOM_PUBLIC_URL)", "no_public_url")
    ecl = (req.query.get("ecl") or "M").upper()
    if ecl not in ("L", "M", "Q", "H"):
        raise ApiError(400, "ecl must be L, M, Q or H")
    text = svg(_device_url(base, pdir.name, dev), ecl=ecl, scale=_int(req.query.get("scale"), 4, 1, 40))
    r = Response.text(text, "image/svg+xml; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = FILE_CSP
    return r


def _sop_public_url(req: Request, pdir: Path, doc: Dict[str, Any], slug: str) -> str:
    """Absolute URL a QR code should carry: the share link when ?share= names a valid token of this project, else /p/…"""
    base = _public_base(req, doc)
    if not base:
        raise ApiError(409, "no public URL is known (set settings.public_url or FATHOM_PUBLIC_URL)", "no_public_url")
    token = req.query.get("share") or ""
    if token:
        if token not in _read_shares(pdir):
            raise ApiError(404, "share link not found", "share_missing")
        return f"{base}/s/{quote(token)}/sop/{quote(slug)}"
    return f"{base}/p/{quote(pdir.name)}/sop/{quote(slug)}"


@route("GET", r"/api/v2/projects/" + _NAME + r"/qr/page/" + _SLUG + r"\.svg", role="viewer", summary="QR code SVG for a public SOP page (?share=<token> to encode a share link)", tags=["pages"], page="file")
def r_qr_page(req: Request) -> Response:
    from .qr import svg

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    page = _page_by_slug(doc, req.params["slug"])
    if (page.get("status") or "published") != "published":
        raise ApiError(409, "only published pages have a public URL; publish the page first", "not_published")
    ecl = (req.query.get("ecl") or "M").upper()
    if ecl not in ("L", "M", "Q", "H"):
        raise ApiError(400, "ecl must be L, M, Q or H")
    text = svg(_sop_public_url(req, pdir, doc, page["slug"]), ecl=ecl, scale=_int(req.query.get("scale"), 4, 1, 40))
    r = Response.text(text, "image/svg+xml; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = FILE_CSP
    return r


@route("GET", r"/api/v2/projects/" + _NAME + r"/qr/pages\.html", role="viewer", summary="Printable QR sheet of a room's published SOPs (?room=, ?share=)", tags=["pages"], page="viewer")
def r_qr_pages_sheet(req: Request) -> Response:
    from .qr import svg
    from .render_html import render_sop_qr_sheet, sop_tree

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    room = req.query.get("room") or ""
    if room and room not in _room_ids(doc):
        raise ApiError(404, f"room '{room}' not found")
    pages = [p for p, _depth in sop_tree(doc) if not room or room in _page_refs(p)["rooms"]]
    items = []
    for p in pages:
        url = _sop_public_url(req, pdir, doc, p["slug"])
        items.append({"page": p, "url": url, "svg": svg(url, ecl="M", scale=4)})
    room_name = next((str(r.get("name") or r.get("id")) for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id") == room), "")
    return _viewer_html(render_sop_qr_sheet(doc, items, project=pdir.name, room=room_name, share=bool(req.query.get("share"))))


@route("GET", r"/api/v2/projects/" + _NAME + "/trace", role="viewer", summary="Port-level trace (from, to | direction)", tags=["analysis"])
def r_trace_v2(req: Request) -> Response:
    from . import trace as T

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    overlay = _overlay(doc, pdir, strict=False)
    src = T.resolve_ref(doc, req.query.get("from", ""), overlay)
    if src is None:
        raise ApiError(400, "unknown endpoint in 'from'")
    dst = None
    if req.query.get("to"):
        dst = T.resolve_ref(doc, req.query["to"], overlay)
        if dst is None:
            raise ApiError(400, "unknown endpoint in 'to'")
    state = req.query.get("state") or "all"
    g = _compat(T.port_graph, doc, overlay, discipline=req.query.get("discipline") or None, state=state)
    depth = _int(req.query.get("max_depth"), 24, 1, 64)
    limit = _int(req.query.get("limit"), 50, 1, 500)
    dca = str(req.query.get("dca") or "").lower() in ("1", "true", "yes")

    def node(ref: Tuple[str, Optional[str]]) -> str:
        return f"{ref[0]}:{ref[1]}" if ref[1] else f"{ref[0]}:*"

    if dst is not None:
        paths = T.port_paths(g, node(src), node(dst), max_depth=depth, limit=limit)
    elif (req.query.get("direction") or "down") == "up":
        paths = T.upstream_paths(g, node(src), max_depth=depth, limit=limit)
    else:
        paths = T.downstream_paths(g, node(src), max_depth=depth, limit=limit)
    names = {d["id"]: str(d.get("name") or d["id"]) for d in T.doc_devices(doc, overlay) if isinstance(d, dict) and d.get("id")}
    out = []
    for p in paths:
        if dca:
            p = T.with_dca_hops(p)
        labels = T.hop_labels(doc, p, overlay)
        hops = [dict(h, label=labels[i] if i < len(labels) else "", device_name=names.get(str(h.get("device")), str(h.get("device") or "")))
                for i, h in enumerate(p.get("hops") or [])]
        item = {"hops": hops, "cables": list(p.get("cables") or []), "via": list(p.get("via") or []), "text": T.path_text(doc, p, overlay)}
        if p.get("incomplete"):
            item["incomplete"] = p["incomplete"]
        out.append(item)
    return Response.json({"paths": out, "from": node(src), "to": node(dst) if dst else None})


@route("GET", r"/api/v2/projects/" + _NAME + "/search", role="viewer", summary="Search devices, ports, cables, interfaces …", tags=["analysis"])
def r_search(req: Request) -> Response:
    from .search import build_index, search

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    key = (str(pdir.resolve()), _rev(doc))
    with _CACHE_LOCK:
        idx = _SEARCH_CACHE.get(key)
    if idx is None:
        idx = build_index(doc, _overlay(doc, pdir, strict=False))
        with _CACHE_LOCK:
            if len(_SEARCH_CACHE) > 32:
                _SEARCH_CACHE.clear()
            _SEARCH_CACHE[key] = idx
    kinds = [k for k in (req.query.get("kinds") or "").split(",") if k] or None
    hits = search(idx, req.query.get("q", ""), limit=_int(req.query.get("limit"), 20, 1, 200), kinds=kinds)
    return Response.json({"hits": hits})


@route("POST", r"/api/v2/projects/" + _NAME + "/assistant", role="viewer", summary="Troubleshooting assistant", tags=["analysis"], body="Question", response="Answer")
def r_assistant(req: Request) -> Response:
    from .assistant import answer

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    q = str(body.get("question") or "").strip()
    if not q:
        raise ApiError(400, "ask a question")
    room = body.get("room") or None
    use_llm = bool(body.get("use_llm", True)) and bool(((doc.get("settings") or {}).get("assistant") or {}).get("llm", True))
    hist = body.get("history") if isinstance(body.get("history"), list) else None
    res = answer(doc, q, room=room, overlay=_overlay(doc, pdir, strict=False), use_llm=use_llm, history=hist, base_revision=_rev(doc))
    return Response.json(res)


# ---- builds


def _run_files(run_dir: Path) -> List[str]:
    return sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())


@route("POST", r"/api/v2/projects/" + _NAME + "/builds", role="editor", summary="Build the documentation package", tags=["builds"], body="BuildOptions")
def r_build_v2(req: Request) -> Response:
    from .export import find_chrome, write_build
    from .schema import flow_project

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    body = req.json()
    want_pdf, want_png = bool(body.get("pdf")), bool(body.get("png"))
    if (want_pdf or want_png) and not find_chrome():
        raise ApiError(400, "server-side PDF / PNG needs Chrome or Chromium on the host (FATHOM_CHROME)")
    state = str(body.get("state") or "all")
    if state not in ("all", "planned", "as_built", "everything"):
        raise ApiError(400, "state must be all, planned, as_built or everything")
    rooms = body.get("rooms")
    if rooms is not None:
        if not isinstance(rooms, list) or any(str(r) not in _room_ids(doc) for r in rooms):
            raise ApiError(400, "rooms must be a list of room ids")
        rooms = [str(r) for r in rooms]
    discovery = body.get("discovery", True)
    if not isinstance(discovery, bool):
        raise ApiError(400, "discovery must be a boolean (include the Discovered connections section)")
    project = flow_project(doc, state=state)
    run_dir = new_build_dir(pdir.name, (doc.get("meta") or {}).get("slug") or pdir.name)
    _compat(write_build, project, pdir, run_dir, pdf=want_pdf, png=want_png, doc=doc, state=state, rooms=rooms, base_url=_public_base(req, doc), discovery=discovery)
    n = pdir.name
    return Response.json({"build": run_dir.name, "files": _run_files(run_dir), "url": f"builds/{n}/{run_dir.name}/index.html",
                          "zip": f"builds/{n}/{run_dir.name}/{run_dir.name}.zip"}, 201)


@route("GET", r"/api/v2/projects/" + _NAME + "/builds", role="viewer", summary="List builds", tags=["builds"])
def r_builds_v2(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    return Response.json({"builds": list_builds(pdir.name, recursive=True)})


def _delete_build(pdir: Path, run: str) -> None:
    if not _RUN_RE.match(run):
        raise ApiError(400, "bad build name")
    target = builds_root() / pdir.name / run
    if not target.is_dir() or not _contained(target, builds_root()):
        raise ApiError(404, "build not found")
    shutil.rmtree(target)


@route("DELETE", r"/api/v2/projects/" + _NAME + r"/builds/(?P<run>[^/]+)", role="editor", summary="Delete a build", tags=["builds"])
def r_build_delete_v2(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    _delete_build(pdir, req.params["run"])
    return Response.json({"ok": True})


# ======================================================== v1 endpoints (kept)


@route("GET", "/api/meta", role="viewer", summary="v1 vocabularies and capabilities", tags=["v1"])
def r_meta(req: Request) -> Response:
    from .model import BRANDS, DEFAULT_COLUMNS, KINDS, MEDIA
    from .users import auth_enabled, public_view

    try:
        from .parsers import KINDS as IMPORT_KINDS

        import_kinds = list(IMPORT_KINDS)
    except Exception:
        import_kinds = []
    try:
        from .export import find_chrome

        chrome = bool(find_chrome())
    except Exception:
        chrome = False
    return Response.json({
        "version": __version__, "kinds": KINDS, "media": MEDIA, "brands": sorted(BRANDS), "import_kinds": import_kinds,
        "default_columns": DEFAULT_COLUMNS, "samples": _samples(), "chrome": chrome, "auth": auth_enabled(),
        "public_view": public_view(), "max_upload_mb": _max_upload() // (1024 * 1024),
    })


@route("GET", "/api/projects", role="viewer", summary="v1 project list", tags=["v1"])
def r_projects(req: Request) -> Response:
    return Response.json({"projects": [project_info(n) for n in list_projects()]})


@route("POST", "/api/projects", role="editor", summary="v1 create project", tags=["v1"], body="ProjectCreate")
def r_projects_create(req: Request) -> Response:
    body = req.json()
    name = str(body.get("name", "")).strip()
    if not safe_name(name):
        raise ApiError(400, "name must be letters, digits, . _ - (max 64)")
    if (projects_root() / name).exists():
        raise ApiError(400, f"project '{name}' already exists")
    template = str(body.get("template") or "blank")
    if template != "blank" and template not in _samples():
        raise ApiError(400, f"unknown template '{template}'")
    pdir = new_project(name, template=template, org=str(body.get("org") or ""))
    return Response.json({"ok": True, "name": pdir.name}, 201)


@route("GET", r"/api/projects/" + _NAME, role="viewer", summary="v1 project (flow view of the default room)", tags=["v1"])
def r_project_get(req: Request) -> Response:
    from .model import validate
    from .schema import flow_project, is_v1_expressible

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    project = flow_project(doc)
    exports = sorted(p.relative_to(pdir).as_posix() for p in (pdir / "exports").rglob("*") if p.is_file()) if (pdir / "exports").is_dir() else []
    return Response.json({"name": pdir.name, "data": project.to_dict(), "problems": validate(project), "exports": exports,
                          "builds": list_builds(pdir.name), "schema": 2, "v1_expressible": is_v1_expressible(doc)})


@route("PUT", r"/api/projects/" + _NAME, role="editor", summary="v1 save (only while the doc is v1-expressible)", tags=["v1"], body="V1Project")
def r_project_put(req: Request) -> Response:
    from .model import project_from_dict, validate
    from .project import save_doc
    from .schema import is_v1_expressible, migrate

    pdir = _project_dir(req.params["name"])
    data = req.json()
    doc, _ = _load(pdir)
    if not is_v1_expressible(doc):
        raise ApiError(409, "this project uses v2 features; save it through /api/v2", "v2_required")
    v1 = dict(data)
    v1.setdefault("fathom", 1)
    new = migrate(v1)
    if "imports" not in data:
        new["imports"] = list(doc.get("imports") or [])
    save_doc(new, pdir, base_revision=None, author=req.username, summary="Saved (v1 editor)", source="put")
    return Response.json({"ok": True, "problems": validate(project_from_dict(data))})


@route("DELETE", r"/api/projects/" + _NAME, role="admin", summary="v1 delete project", tags=["v1"])
def r_project_delete(req: Request) -> Response:
    name = req.params["name"]
    _project_dir(name)
    if req.query.get("confirm") != name:
        raise ApiError(400, "pass ?confirm=<name> to delete a project and its builds")
    delete_project(name)
    return Response.json({"ok": True})


@route("POST", r"/api/projects/" + _NAME + "/imports", role="editor", summary="v1 upload an import", tags=["v1"], body="Multipart")
def r_import(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    node = req.query.get("node", "")
    target, kind, _ = _save_upload(req, pdir, req.query.get("kind", "auto"), req.query.get("folder", ""))
    summary = _summary(_parse(target, kind))
    _register_import(req, pdir, target, kind, node, "")
    return Response.json({"ok": True, "kind": kind, "path": target.relative_to(pdir).as_posix(), "summary": summary})


@route("DELETE", r"/api/projects/" + _NAME + "/imports", role="editor", summary="v1 remove an import by path", tags=["v1"])
def r_import_delete(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    rel = req.query.get("path", "")
    hits = [i for i in doc.get("imports") or [] if isinstance(i, dict) and i.get("path") == rel]
    if req.query.get("delete") == "1" and rel:
        target = pdir / rel
        if _contained(target, pdir / "exports") and target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
    if hits:
        _server_ops(req, pdir, [{"op": "del", "coll": "imports", "id": i["id"]} for i in hits], f"Removed import {rel}", "import")
    return Response.json({"ok": True, "removed": len(hits)})


@route("GET", r"/api/projects/" + _NAME + "/inspect", role="viewer", summary="v1 parse summary of an export", tags=["v1"])
def r_inspect(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    rel = req.query.get("path", "")
    target = pdir / rel
    if not rel or not _contained(target, pdir) or not target.exists():
        raise ApiError(404, "export not found")
    kind = req.query.get("kind") or _detect(target)
    return Response.json({"kind": kind, "summary": _summary(_parse(target, kind))})


@route("GET", r"/api/projects/" + _NAME + "/trace", role="viewer", summary="v1 card-level trace", tags=["v1"])
def r_trace(req: Request) -> Response:
    from .merge import apply_imports
    from .schema import flow_project
    from .trace import describe_path, downstream, find_paths, resolve_node

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    project = flow_project(doc)
    apply_imports(project, pdir)
    src = resolve_node(project, req.query.get("from", ""))
    if src is None:
        raise ApiError(400, "unknown source card")
    dst = resolve_node(project, req.query.get("to", "")) if req.query.get("to") else None
    paths = find_paths(project, src.id, dst.id) if dst else downstream(project, src.id)
    return Response.json({"paths": [describe_path(project, p) for p in paths]})


@route("POST", r"/api/projects/" + _NAME + "/build", role="editor", summary="v1 build", tags=["v1"], body="BuildOptions")
def r_build(req: Request) -> Response:
    from .export import find_chrome, write_build
    from .schema import flow_project

    pdir = _project_dir(req.params["name"])
    body = req.json()
    doc, _ = _load(pdir)
    project = flow_project(doc)
    if not project.meta.slug:
        from .model import slug

        project.meta.slug = slug(project.meta.org or pdir.name)
    want_pdf, want_png = bool(body.get("pdf")), bool(body.get("png"))
    if (want_pdf or want_png) and not find_chrome():
        raise ApiError(400, "server-side PDF / PNG needs Chrome or Chromium on the host (FATHOM_CHROME); use the viewer's Print / PDF button instead")
    run_dir = new_build_dir(pdir.name, project.meta.slug or pdir.name)
    _compat(write_build, project, pdir, run_dir, pdf=want_pdf, png=want_png, doc=doc, base_url=_public_base(req, doc))
    files = sorted(p.name for p in run_dir.iterdir() if p.is_file())
    return Response.json({"ok": True, "build": run_dir.name, "files": files, "url": f"builds/{pdir.name}/{run_dir.name}/index.html",
                          "zip": f"builds/{pdir.name}/{run_dir.name}/{run_dir.name}.zip"}, 201)


@route("GET", r"/api/projects/" + _NAME + "/builds", role="viewer", summary="v1 list builds", tags=["v1"])
def r_builds(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    return Response.json({"builds": list_builds(pdir.name)})


@route("DELETE", r"/api/projects/" + _NAME + r"/builds/(?P<run>[^/]+)", role="editor", summary="v1 delete a build", tags=["v1"])
def r_build_delete(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    _delete_build(pdir, req.params["run"])
    return Response.json({"ok": True})


# ================================================================ viewer


def _nav(req: Request, doc: Dict[str, Any], name: str, current: str) -> Dict[str, Any]:
    base = _rel_base(req)
    prefix = base + _view_prefix(req, name)
    rooms = [{"id": str(r.get("id")), "name": str(r.get("name") or r.get("id")), "url": f"{prefix}/r/{r.get('id')}"}
             for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]
    links = [{"label": "Rooms", "url": f"{prefix}/rooms"}]
    if current:
        links.append({"label": "Patch table", "url": f"{prefix}/r/{current}/patch"})
    if not req.path.startswith("/s/"):
        links.append({"label": "Open editor", "url": f"{base}#/{name}/{current}/map" if current else f"{base}#/{name}"})
    return {"project": name, "rooms": rooms, "current": current, "links": links}


def _view_prefix(req: Request, name: str) -> str:
    m = re.match(r"^/s/(sh-[A-Za-z0-9_-]+)", req.path)
    return f"s/{m.group(1)}" if m else f"p/{name}"


def _viewer_html(text: str) -> Response:
    r = Response.text(text, "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
    r.csp = VIEWER_CSP
    return r


def _room_or_404(doc: Dict[str, Any], room: str) -> str:
    if room not in _room_ids(doc):
        raise ApiError(404, f"room '{room}' not found")
    return room


def _render_room_map(req: Request, pdir: Path, doc: Dict[str, Any], room: Optional[str]) -> Response:
    from .export import prepare
    from .layout import compute_layout
    from .model import slug
    from .render_html import render_html
    from .schema import default_room_id, flow_project

    project = flow_project(doc, room)
    if not project.meta.slug:
        project.meta.slug = slug(project.meta.org or pdir.name)
    prepare(project, pdir)
    layout = compute_layout(project)
    current = room or default_room_id(doc)
    html = _compat(render_html, project, layout, nav=_nav(req, doc, pdir.name, current), base_url=_rel_base(req), sw=True, doc=doc)
    return _viewer_html(html)


def _viewer_project(req: Request) -> Tuple[Path, Dict[str, Any]]:
    """Project folder and doc for a viewer page; ``?scene=<sid|base>`` renders that scene (§5.13, 404 unknown)."""
    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    sid = str(req.query.get("scene") or "").strip()
    if sid:
        doc = _scene_view(doc, sid)
    return pdir, doc


@route("GET", r"/p/" + _NAME, role="viewer", summary="Viewer: default room map", tags=["viewer"], page="viewer")
def r_view(req: Request) -> Response:
    pdir, doc = _viewer_project(req)
    return _render_room_map(req, pdir, doc, None)


@route("GET", r"/p/" + _NAME + r"/(?P<file>diagram\.svg|patch-sheet\.csv|project\.json)", role="viewer", summary="Viewer downloads (default room)", tags=["viewer"], page="viewer")
def r_view_file(req: Request) -> Response:
    from .export import render_project
    from .model import slug
    from .schema import flow_project

    pdir, doc = _viewer_project(req)
    file = req.params["file"]
    if file == "project.json":
        return Response.text(json.dumps(doc, indent=2, ensure_ascii=False), "application/json; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{pdir.name}-project.json"'})
    project = flow_project(doc)
    if not project.meta.slug:
        project.meta.slug = slug(project.meta.org or pdir.name)
    arts = render_project(project, pdir)
    if file == "diagram.svg":
        return Response.text(arts["svg"], "image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{pdir.name}.svg"'})
    return Response.text(arts["csv"], "text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{pdir.name}-patch-sheet.csv"'})


@route("GET", r"/p/" + _NAME + "/rooms", role="viewer", summary="Viewer: room index", tags=["viewer"], page="viewer")
def r_view_rooms(req: Request) -> Response:
    from .render_html import render_room_index

    pdir, doc = _viewer_project(req)
    return _viewer_html(_compat(render_room_index, doc, project=pdir.name, base_url=_rel_base(req), sw=True))


@route("GET", r"/p/" + _NAME + r"/r/(?P<room>" + _EID + ")", role="viewer", summary="Viewer: room map", tags=["viewer"], page="viewer")
def r_view_room(req: Request) -> Response:
    pdir, doc = _viewer_project(req)
    return _render_room_map(req, pdir, doc, _room_or_404(doc, req.params["room"]))


@route("GET", r"/p/" + _NAME + r"/r/(?P<room>" + _EID + r")/diagram\.svg", role="viewer", summary="Viewer: room map SVG", tags=["viewer"], page="viewer")
def r_view_room_svg(req: Request) -> Response:
    from .export import prepare
    from .layout import compute_layout
    from .render_svg import render_svg
    from .schema import flow_project

    pdir, doc = _viewer_project(req)
    room = _room_or_404(doc, req.params["room"])
    project = flow_project(doc, room)
    prepare(project, pdir)
    return Response.text(render_svg(project, compute_layout(project)), "image/svg+xml",
                         headers={"Content-Disposition": f'attachment; filename="{pdir.name}-{room}.svg"', "Cache-Control": "no-cache"})


@route("GET", r"/p/" + _NAME + r"/r/(?P<room>" + _EID + ")/patch", role="viewer", summary="Viewer: read-only patch table", tags=["viewer"], page="viewer")
def r_view_room_patch(req: Request) -> Response:
    from .patch import patch_table
    from .render_html import render_patch_page

    pdir, doc = _viewer_project(req)
    room = _room_or_404(doc, req.params["room"])
    blocks = _compat(patch_table, doc, _overlay(doc, pdir, strict=False), room=room)
    return _viewer_html(_compat(render_patch_page, doc, room, blocks, project=pdir.name, base_url=_rel_base(req), sw=True))


@route("GET", r"/p/" + _NAME + r"/d/(?P<device>" + _EID + ")", role="viewer", summary="Viewer: device page", tags=["viewer"], page="viewer")
def r_view_device(req: Request) -> Response:
    from .render_html import render_device_page

    pdir, doc = _viewer_project(req)
    dev = req.params["device"]
    if not any(isinstance(d, dict) and d.get("id") == dev for d in doc.get("devices") or []):
        raise ApiError(404, "device not found")
    qr_svg = ""
    try:
        from .qr import svg

        base = _public_base(req, doc)
        if base:
            qr_svg = svg(_device_url(base, pdir.name, dev))
    except Exception:
        _log_exc("qr for device page failed")
    return _viewer_html(_compat(render_device_page, doc, dev, project=pdir.name, overlay=_overlay(doc, pdir, strict=False),
                                base_url=_rel_base(req), qr_svg=qr_svg, sw=True))


# ---- public SOP pages (§5.15): chrome-free, phone-first, published pages only


def _share_scope(req: Request) -> str:
    """Scope of the share link this request came through ("" when it is a plain /p/ URL)."""
    m = re.match(r"^/s/(sh-[A-Za-z0-9_-]+)", req.path)
    if not m:
        return ""
    return str(_share_lookup(m.group(1))[1].get("scope") or "all")


def _published_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["pages"] = [p for p in _pages(doc) if (p.get("status") or "published") == "published"]
    return out


def _public_page_resolver(doc: Dict[str, Any], rel: str, sop_only: bool) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    from .render_html import attachment_filename, sop_link_resolver

    return sop_link_resolver(
        doc,
        device=lambda i, _d: "" if sop_only else f"{rel}d/{quote(i, safe='')}",
        room=lambda i, _r: "" if sop_only else f"{rel}r/{quote(i, safe='')}",
        page=lambda s, p: f"{rel}sop/{quote(s, safe='')}" if (p.get("status") or "published") == "published" else None,
        attachment=lambda i, a: f"{rel}files/{quote(i, safe='')}/{quote(attachment_filename(a), safe='')}",
    )


@route("GET", r"/p/" + _NAME + "/sop", role="viewer", summary="Viewer: published procedures (SOP index)", tags=["pages"], page="viewer")
def r_view_sop_index(req: Request) -> Response:
    from .render_html import render_sop_index

    pdir, doc = _viewer_project(req)
    return _viewer_html(render_sop_index(_published_doc(doc), project=pdir.name, base_url=_rel_base(req), sw=True, rel="",
                                         sop_only=_share_scope(req) == "sop"))


@route("GET", r"/p/" + _NAME + "/sop/" + _SLUG, role="viewer", summary="Viewer: a published SOP page (phone-first, no chrome)", tags=["pages"], page="viewer")
def r_view_sop_page(req: Request) -> Response:
    from .render_html import render_sop_page

    pdir = _project_dir(req.params["name"])
    doc, _ = _load(pdir)
    pub = _published_doc(doc)
    page = next((p for p in pub["pages"] if p["slug"] == req.params["slug"]), None)
    if page is None:
        raise ApiError(404, f"page '{req.params['slug']}' not found", "page_missing")
    sop_only = _share_scope(req) == "sop"
    data = _page_payload(pdir.name, pub, page, _rev(doc), resolver=_public_page_resolver(pub, "../", sop_only))
    report = {"action": "../problems", "email": str((doc.get("settings") or {}).get("problem_email") or "")}
    return _viewer_html(render_sop_page(pub, data, project=pdir.name, base_url=_rel_base(req), sw=True, rel="../", sop_only=sop_only, report=report))


@route("POST", r"/p/" + _NAME + "/problems", role="viewer", summary="Viewer: report a problem from a public SOP page", tags=["problems"], body="ProblemReport")
def r_view_problem(req: Request) -> Response:
    pdir = _project_dir(req.params["name"])
    return Response.json(_create_problem(req, pdir, "public"), 201)


@route("POST", r"/s/(?P<token>sh-[A-Za-z0-9_-]{1,64})/problems", role="public", summary="Share link: report a problem", tags=["problems"], body="ProblemReport")
def r_share_problem(req: Request) -> Response:
    name, share = _share_lookup(req.params["token"])
    if not name:
        raise ApiError(404, "share link not found")
    return Response.json(_create_problem(req, _project_dir(name), "share"), 201)


@route("GET", r"/p/" + _NAME + r"/files/(?P<att>att-[0-9a-f]{12})/(?P<filename>[^/]+)", role="viewer", summary="Viewer: attachment (images embedded in SOP pages; mirrored by share links)", tags=["pages"], page="viewer")
def r_view_attachment(req: Request) -> Response:
    pdir, doc = _viewer_project(req)
    att = _attachment(doc, req.params["att"])
    path = _attachment_path(pdir, att)
    return _serve_user_file(path, str(att.get("mime") or ""), path.name)


@route("GET", r"/s/(?P<token>sh-[A-Za-z0-9_-]{1,64})(?:/(?P<rest>.*))?", role="public", summary="Share link: read-only mirror of /p/<project>/…", tags=["viewer"], page="viewer")
def r_share(req: Request) -> Response:
    name, share = _share_lookup(req.params["token"])
    if not name:
        raise ApiError(404, "share link not found")
    rest = (req.params.get("rest") or "").strip("/")
    if not _share_allows(share, rest):
        if str(share.get("scope") or "all") == "sop" and not rest:
            rest = "sop"
        else:
            raise ApiError(403, "this share link only opens procedures", "share_scope")
    inner = f"/p/{name}" + (f"/{rest}" if rest else "")
    for rt in ROUTES:
        if rt.method == "GET" and rt.page == "viewer" and rt.pattern.startswith("/p/"):
            m = rt.regex.match(inner)
            if m:
                req.params = m.groupdict()
                return rt.handler(req)
    raise ApiError(404, "not found")


@route("GET", r"/builds/" + _NAME + r"/(?P<run>[^/]+)/(?P<file>.+)", role="viewer", summary="Build artifacts", tags=["builds"], page="build")
def r_build_file(req: Request) -> Response:
    name, run, file = req.params["name"], req.params["run"], req.params["file"]
    segs = file.split("/")
    if not (safe_name(name) and _RUN_RE.match(run) and all(_RUN_RE.match(s) for s in segs)):
        raise ApiError(404, "not found")
    root = builds_root() / name / run
    target = root.joinpath(*segs)
    if not _contained(target, root) or not target.is_file():
        raise ApiError(404, "not found")
    leaf = segs[-1]
    ctype = mimetypes.guess_type(leaf)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("image/svg+xml", "application/json"):
        ctype += "; charset=utf-8"
    headers = {"Cache-Control": "no-cache"}
    if leaf.endswith((".zip", ".csv", ".pdf")):
        headers["Content-Disposition"] = f'attachment; filename="{leaf}"'
    r = Response(target.read_bytes(), 200, ctype, headers)
    if ctype.startswith("text/html"):
        r.csp = VIEWER_CSP
    return r


# ============================================================ static & PWA


def _static_etag(path: Path, extra: str = "") -> str:
    st = path.stat()
    return '"' + hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}|{extra}".encode("utf-8")).hexdigest()[:20] + '"'


def _static_response(req: Request, path: Path, ctype: str, extra_headers: Optional[Dict[str, str]] = None, transform: Optional[Callable[[bytes], bytes]] = None, etag_extra: str = "") -> Response:
    etag = _static_etag(path, etag_extra)
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    headers.update(extra_headers or {})
    if req.header("if-none-match") == etag:
        r = Response.empty(304)
        r.headers.update(headers)
        return r
    data = path.read_bytes()
    if transform is not None:
        data = transform(data)
    return Response(data, 200, ctype, headers)


def _is_loopback(req: Request) -> bool:
    return req.remote_addr in ("127.0.0.1", "::1", "localhost") or req.remote_addr.startswith("127.")


@route("GET", r"/static/(?P<path>.+)", role="public", summary="Static app files", tags=["static"], page="static")
def r_static(req: Request) -> Response:
    rel = req.params["path"]
    segs = rel.split("/")
    if "\x00" in rel or not all(_SEG_RE.match(s) for s in segs):
        raise ApiError(404, "not found")
    ext = Path(segs[-1]).suffix.lower()
    if ext not in STATIC_EXT:
        raise ApiError(404, "not found")
    if segs[0] == "dev" and not (os.environ.get("FATHOM_DEV") == "1" or _is_loopback(req)):
        raise ApiError(404, "not found")
    target = STATIC_DIR.joinpath(*segs)
    if not _contained(target, STATIC_DIR) or not target.is_file():
        raise ApiError(404, "not found")
    if rel == "app.html":
        from .users import auth_enabled

        if auth_enabled() and req.user is None and req.wants_html():
            nxt = quote(req.script_root + "/static/app.html", safe="")
            return Response(b"", 302, "text/plain; charset=utf-8", {"Location": f"{req.script_root}/login?next={nxt}"})
    r = _static_response(req, target, STATIC_EXT[ext])
    if ext == ".html":
        r.csp = APP_CSP
    return r


@route("GET", r"/sw\.js", role="public", summary="Service worker", tags=["static"], page="static")
def r_sw(req: Request) -> Response:
    path = STATIC_DIR / "sw.js"
    if not path.is_file():
        raise ApiError(404, "not found")
    return _static_response(req, path, "text/javascript; charset=utf-8", {"Service-Worker-Allowed": (req.script_root or "") + "/"},
                            transform=lambda b: b.replace(b"__FATHOM_VERSION__", __version__.encode("ascii")), etag_extra=__version__)


@route("GET", r"/manifest\.webmanifest", role="public", summary="Web app manifest", tags=["static"], page="static")
def r_manifest(req: Request) -> Response:
    path = STATIC_DIR / "manifest.webmanifest"
    if not path.is_file():
        raise ApiError(404, "not found")
    return _static_response(req, path, "application/manifest+json")


@route("GET", r"/favicon\.ico", role="public", summary="Favicon", tags=["static"], page="static")
def r_favicon(req: Request) -> Response:
    path = STATIC_DIR / "icons" / "favicon.ico"
    if not path.is_file():
        raise ApiError(404, "not found")
    return _static_response(req, path, "image/x-icon")


@route("GET", r"/apple-touch-icon\.png", role="public", summary="Apple touch icon", tags=["static"], page="static")
def r_apple_icon(req: Request) -> Response:
    path = STATIC_DIR / "icons" / "apple-touch-icon.png"
    if not path.is_file():
        raise ApiError(404, "not found")
    return _static_response(req, path, "image/png")


@route("GET", r"/api/openapi\.json", role="public", summary="OpenAPI 3.1 description of this API", tags=["meta"])
def r_openapi(req: Request) -> Response:
    from .openapi import build_spec

    return Response.json(build_spec(ROUTES, __version__))


@route("GET", r"/api/docs", role="public", summary="HTML endpoint reference", tags=["meta"], page="app")
def r_api_docs(req: Request) -> Response:
    from .openapi import build_spec, render_docs

    r = Response.text(render_docs(build_spec(ROUTES, __version__)), "text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
    return r


# ================================================================ WSGI app


_MUTATING = ("POST", "PUT", "PATCH", "DELETE")
_PUBLIC_VIEW_PREFIXES = ("/p/", "/builds/", "/c/")


def _authenticate(req: Request) -> None:
    from .users import auth_enabled, read_session, verify

    if not auth_enabled():
        req.user = {"username": "local", "role": "admin", "projects": {}, "source": "local"}
        req.auth_via = "local"
        return
    header = req.header("authorization")
    if header.lower().startswith("basic "):
        try:
            user, _, pw = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
        except Exception:
            user, pw = "", ""
        u = verify(user, pw)
        if u is None:
            raise ApiError(401, "wrong username or password", "auth_required", headers={"WWW-Authenticate": 'Basic realm="Fathom"'})
        req.user, req.auth_via = u, "basic"
        return
    # A stale duplicate (another Path/Domain scope, an older secret, a second Fathom on the same host) must
    # not shadow the live session, or /api/v2/session and the app pages disagree and the client loops.
    for cookie in req.cookies("fathom_session"):
        u = read_session(cookie)
        if u is not None:
            req.user, req.auth_via = u, "cookie"
            break


def _csrf_ok(req: Request) -> bool:
    if req.method not in _MUTATING:
        return True
    if req.header("x-fathom") == "1":
        return True
    if req.method in ("PUT", "PATCH", "DELETE"):
        return True
    ctype = req.header("content-type").split(";")[0].strip().lower()
    return ctype == "application/json" or ctype.endswith("+json")


def _match(req: Request) -> Tuple[Optional[Route], List[str]]:
    path = req.path.rstrip("/") or "/"
    allowed: List[str] = []
    for rt in ROUTES:
        m = rt.regex.match(path)
        if not m:
            continue
        if rt.method != req.method:
            allowed.append(rt.method)
            continue
        req.params = {k: v for k, v in m.groupdict().items() if v is not None}
        return rt, allowed
    return None, allowed


def dispatch(req: Request) -> Response:
    if "\x00" in req.path:
        raise ApiError(400, "bad path")
    rt, allowed = _match(req)
    if rt is None:
        if allowed:
            raise ApiError(405, f"method not allowed (try {', '.join(sorted(set(allowed)))})", headers={"Allow": ", ".join(sorted(set(allowed)))})
        raise ApiError(404, "not found")
    req.route = rt
    if req.method in _MUTATING:
        if not _csrf_ok(req):
            raise ApiError(403, "send X-Fathom: 1 with form / multipart / text requests", "csrf")
        raw_len = req.header("content-length")
        if raw_len:
            try:
                if int(raw_len) > req.body_cap():
                    raise ApiError(413, f"body larger than {req.body_cap() // (1024 * 1024)} MB", "too_large")
            except ValueError:
                raise ApiError(400, "bad Content-Length")
    _authenticate(req)
    if req.method in _MUTATING and req.auth_via == "cookie":
        origin = req.header("origin")
        if origin and origin != req.origin:
            raise ApiError(403, "cross-origin request refused", "csrf")
    from .users import public_view, role_at_least

    needed = rt.role
    if needed != "public":
        anonymous_ok = needed == "viewer" and public_view() and req.path.startswith(_PUBLIC_VIEW_PREFIXES)
        if req.user is None and not anonymous_ok:
            if req.method == "GET" and rt.page == "app" and req.wants_html():
                nxt = quote(req.script_root + req.path, safe="")
                return Response(b"", 302, "text/plain; charset=utf-8", {"Location": f"{req.script_root}/login?next={nxt}"})
            hdrs = {}
            if req.header("authorization").lower().startswith("basic ") or not req.wants_html():
                hdrs["WWW-Authenticate"] = 'Basic realm="Fathom"'
            raise ApiError(401, "authentication required", "auth_required", headers=hdrs)
        if req.user is not None and needed in ("viewer", "editor", "admin"):
            if not role_at_least(req.role_for(req.params.get("name", "")), needed):
                raise ApiError(403, f"needs the {needed} role", "forbidden")
    return rt.handler(req)


def _finish(req: Request, resp: Response) -> Response:
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    page = req.route.page if req.route is not None else "api"
    csp = resp.csp
    if csp is None:
        ctype = h.get("Content-Type", "")
        if page == "app" or (page == "static" and ctype.startswith("text/html")):
            csp = APP_CSP
        elif page in ("viewer", "build") and ctype.startswith("text/html"):
            csp = VIEWER_CSP
        elif page == "file":
            csp = FILE_CSP
    if csp:
        h["Content-Security-Policy"] = csp
    return resp


def _handle_exception(exc: BaseException) -> Response:
    from .schema import SchemaError
    from .users import UserError

    if isinstance(exc, ApiError):
        r = _error_response(exc.status, exc.message, exc.code, exc.details)
        r.headers.update(exc.headers)
        return r
    if isinstance(exc, ConflictError):
        return _error_response(409, str(exc), "missing_entity" if exc.code == "missing_entity" else "conflict",
                               {"revision": exc.revision, "conflicts": exc.conflicts, "by": exc.by})
    if isinstance(exc, ValidationError):
        return _error_response(422, str(exc), "invalid", {"problems": exc.problems})
    if isinstance(exc, PreconditionError):
        return _error_response(428, str(exc) or "base revision required", "precondition_required")
    if isinstance(exc, SchemaError):
        status = 409 if exc.code == "newer_schema" else 400
        return _error_response(status, str(exc), exc.code if exc.code not in ("invalid",) else "bad_request", {"ref": exc.ref} if exc.ref else None)
    if isinstance(exc, UserError):
        e = _user_error(exc)
        return _error_response(e.status, e.message, e.code)
    if isinstance(exc, PermissionError) and "read-only" in str(exc):
        return _error_response(403, str(exc), "forbidden")
    if isinstance(exc, SystemExit):  # library-level errors
        return _error_response(400, str(exc.code if exc.code is not None else exc), "bad_request")
    err_id = secrets.token_hex(4)
    sys.stderr.write(f"fathom: internal error {err_id}\n")
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return Response.json({"error": "internal error", "code": "internal", "id": err_id}, 500)


_GENERATION: Dict[str, int] = {}


def _sync_generation() -> None:
    """Drop in-memory caches once a backup restore (in any worker) has swapped the data dir."""
    try:
        from .backup import generation

        g = generation()
    except Exception:
        return
    key = str(projects_root())
    if _GENERATION.get(key, g) == g:
        _GENERATION[key] = g
        return
    _GENERATION[key] = g
    with _CACHE_LOCK:
        _OVERLAY_CACHE.clear()
        _SEARCH_CACHE.clear()
    try:
        from . import users

        users._VERIFY_CACHE.clear()
        from .library import load_library

        load_library(refresh=True)
    except Exception:
        _log_exc("cache reset after restore failed")


def _file_chunks(fh: Any) -> Any:
    try:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        fh.close()


def app(environ: Dict[str, Any], start_response: Callable) -> List[bytes]:
    """WSGI entry point."""
    req = Request(environ)
    try:
        ensure_data_dirs()
        _sync_generation()
        resp = dispatch(req)
        if resp.file is not None:
            try:
                fh = open(resp.file, "rb")
            except OSError:
                raise ApiError(404, "file not found")
            resp.headers["Content-Length"] = str(os.fstat(fh.fileno()).st_size)
            resp = _finish(req, resp)
            start_response(f"{resp.status} {_STATUS_TEXT.get(resp.status, 'OK')}",
                           list(resp.headers.items()) + [("Set-Cookie", c) for c in resp.cookies])
            if req.is_head:
                fh.close()
                return [b""]
            wrapper = environ.get("wsgi.file_wrapper")
            return wrapper(fh, 1024 * 1024) if wrapper else _file_chunks(fh)
    except BaseException as exc:  # noqa: B036 - we re-raise interpreter exits below
        if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
            raise
        resp = _handle_exception(exc)
    resp = _finish(req, resp)
    status = f"{resp.status} {_STATUS_TEXT.get(resp.status, 'OK')}"
    body = b"" if resp.status in (204, 304) else resp.body
    headers = [(k, v) for k, v in resp.headers.items()] + [("Set-Cookie", c) for c in resp.cookies]
    if resp.status not in (204, 304):
        headers.append(("Content-Length", str(len(body))))
    start_response(status, headers)
    if req.is_head:
        return [b""]
    return [body]


# --------------------------------------------------------- dev server


def serve(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False) -> None:
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    from .users import auth_enabled, public_view

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
        allow_reuse_address = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
            sys.stderr.write("  %s\n" % (fmt % args))

    ensure_data_dirs()
    httpd = make_server(host, port, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"fathom {__version__} · {url}")
    print(f"  data: {projects_root().parent}")
    if auth_enabled():
        print("  auth: on (users.json / FATHOM_AUTH)" + (" · viewer public" if public_view() else ""))
    print("  Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
