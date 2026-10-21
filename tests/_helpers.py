"""Shared helpers for the Fathom 0.3 backend suites (T1).

Stdlib only, Python 3.9 syntax. Nothing here imports a v0.3 module at import time,
so every suite imports cleanly while implementation units are still landing.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union
from wsgiref.util import setup_testing_defaults

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FIXTURES = HERE / "fixtures"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PKG = REPO / "fathom"
SAMPLES = PKG / "samples"
RRC_DIR = SAMPLES / "rrc-littleton"
CAMPUS_DIR = SAMPLES / "campus-demo"
FIXTURE_V2 = PKG / "static" / "dev" / "fixture-v2.json"

# Owner of each module (SPEC §7.2) — used in skip messages.
OWNERS = {
    "schema": "W1", "project": "W1", "history": "W1", "users": "W1", "openapi": "W1", "server": "W1", "model": "W1",
    "vocab": "W2", "plugins": "W2", "parsers": "W2", "library": "W2", "floorplan": "W2", "cables": "W2",
    "network": "W2", "bom": "W2", "qr": "W2", "merge": "W2", "export": "W2", "cli": "W2", "selftest": "W2",
    "assistant": "W6", "llm": "W6", "trace": "W6", "patch": "W6", "search": "W6", "racks": "W6", "dmx": "W6",
    "render_html": "W5", "render_svg": "W5", "layout": "W5",
}

# Env vars that change behavior; cleared for every temp data dir unless given.
_ISOLATED_ENV = (
    "FATHOM_DATA", "FATHOM_AUTH", "FATHOM_PUBLIC_VIEW", "FATHOM_PUBLIC_URL", "FATHOM_LLM_URL", "FATHOM_LLM_MODEL",
    "FATHOM_LLM_API_KEY", "FATHOM_LLM_TIMEOUT", "FATHOM_LLM_MAX_CONTEXT", "FATHOM_PLUGINS", "FATHOM_LIBRARY",
    "FATHOM_CHECKLISTS", "FATHOM_ODA", "FATHOM_ODA_XVFB", "FATHOM_PDF_RASTERIZER", "FATHOM_DEV",
    "FATHOM_MAX_UPLOAD_MB", "FATHOM_MAX_JSON_MB",
)


# --------------------------------------------------------------------------- modules


def _owner(name: str) -> str:
    leaf = name.split(".")[1] if name.startswith("fathom.") and "." in name else name
    return OWNERS.get(leaf, "?")


def requires(module_or_attr: str) -> Any:
    """Import ``fathom.x`` (or ``fathom.x:attr``) or raise SkipTest naming the owning unit.

    Only a *missing* module/attribute skips. A module that exists but raises while
    importing is a real failure and is re-raised.
    """
    mod_name, _, attr = module_or_attr.partition(":")
    if not mod_name.startswith("fathom"):
        mod_name = "fathom." + mod_name
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", "") or ""
        if missing and (missing == mod_name or mod_name.startswith(missing + ".")):
            raise unittest.SkipTest("%s module %s not present yet" % (_owner(mod_name), mod_name))
        raise
    if not attr:
        return mod
    obj: Any = mod
    for part in attr.split("."):
        if not hasattr(obj, part):
            raise unittest.SkipTest("%s attribute %s:%s not present yet" % (_owner(mod_name), mod_name, attr))
        obj = getattr(obj, part)
    return obj


def has(module_or_attr: str) -> bool:
    try:
        requires(module_or_attr)
        return True
    except unittest.SkipTest:
        return False


# --------------------------------------------------------------------------- data dirs


@contextlib.contextmanager
def temp_env(**env: Optional[str]) -> Iterator[None]:
    """Set (value) or unset (None) env vars; restore on exit."""
    saved = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def temp_data_dir(**env: Optional[str]) -> Iterator[Path]:
    """Fresh ``$FATHOM_DATA`` (``projects/`` and ``builds/`` created); restores the env.

    Behavior-changing ``FATHOM_*`` variables are cleared unless passed in ``env``.
    """
    tmp = Path(tempfile.mkdtemp(prefix="fathom-t1-"))
    (tmp / "projects").mkdir()
    (tmp / "builds").mkdir()
    values: Dict[str, Optional[str]] = {k: None for k in _ISOLATED_ENV}
    values.update(env)
    values["FATHOM_DATA"] = str(tmp)
    try:
        with temp_env(**values):
            _reset_caches()
            yield tmp
    finally:
        _reset_caches()
        shutil.rmtree(tmp, ignore_errors=True)


def _reset_caches() -> None:
    """Best effort: drop module-level caches that are keyed without the data dir."""
    for name, fn in (("fathom.library", "load_library"), ("fathom.assistant", "load_checklists")):
        mod = sys.modules.get(name)
        f = getattr(mod, fn, None) if mod else None
        if f is not None:
            try:
                f(refresh=True)
            except Exception:
                pass


def uniq(prefix: str = "p") -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:8])


# --------------------------------------------------------------------------- fixtures


def read_json(path: Union[str, Path]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fixture_path(*parts: str) -> Path:
    return FIXTURES.joinpath(*parts)


def load_fixture(name: str) -> Any:
    """Load ``tests/fixtures/<name>`` (JSON)."""
    return read_json(FIXTURES / name)


def sunday_doc() -> Dict[str, Any]:
    """Appendix B (extracted verbatim from SPEC.md into tests/fixtures/sunday-demo.json)."""
    return load_fixture("sunday-demo.json")


def rrc_dict() -> Dict[str, Any]:
    return read_json(RRC_DIR / "project.json")


def install_project(data_dir: Path, name: str, doc: Optional[Dict[str, Any]] = None, src_dir: Optional[Path] = None) -> Path:
    """Create ``projects/<name>`` from a doc (written as project.json) and/or a copied folder."""
    pdir = data_dir / "projects" / name
    if src_dir is not None:
        shutil.copytree(str(src_dir), str(pdir), symlinks=False)
    else:
        pdir.mkdir(parents=True)
    if doc is not None:
        (pdir / "project.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return pdir


def install_rrc(data_dir: Path, name: str = "rrc") -> Path:
    """Copy RRC into the data dir; rewrite relative import paths are already relative to the folder."""
    return install_project(data_dir, name, src_dir=RRC_DIR)


def install_campus(data_dir: Path, name: str = "campus") -> Path:
    if not (CAMPUS_DIR / "project.json").exists():
        raise unittest.SkipTest("W2 sample fathom/samples/campus-demo not present yet")
    return install_project(data_dir, name, src_dir=CAMPUS_DIR)


def install_sunday(data_dir: Path, name: str = "sunday-demo") -> Path:
    return install_project(data_dir, name, doc=sunday_doc())


# --------------------------------------------------------------------------- WSGI


class Headers(dict):
    """Response headers keyed by lowercase name (last value wins); ``.all(name)`` lists every value."""

    def __init__(self, pairs: Sequence[Tuple[str, str]]):
        super().__init__()
        self.pairs = list(pairs)
        for k, v in self.pairs:
            dict.__setitem__(self, k.lower(), v)

    def __getitem__(self, k: str) -> str:
        return dict.__getitem__(self, k.lower())

    def get(self, k: str, default: Any = None) -> Any:  # type: ignore[override]
        return dict.get(self, k.lower(), default)

    def __contains__(self, k: object) -> bool:
        return dict.__contains__(self, str(k).lower())

    def all(self, k: str) -> List[str]:
        return [v for kk, v in self.pairs if kk.lower() == k.lower()]


def _environ(method: str, path: str, body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    env: Dict[str, Any] = {}
    setup_testing_defaults(env)
    raw_path, _, query = path.partition("?")
    env["REQUEST_METHOD"] = method.upper()
    env["SCRIPT_NAME"] = headers.pop("__script_name__", "")
    env["PATH_INFO"] = headers.pop("__path_info__", None) or _unquote_path(raw_path)
    env["RAW_URI"] = env["REQUEST_URI"] = path
    env["QUERY_STRING"] = query
    env["REMOTE_ADDR"] = headers.pop("__remote_addr__", "127.0.0.1")
    if headers.pop("__https__", None):
        env["wsgi.url_scheme"] = "https"
        env["HTTPS"] = "on"
    env["wsgi.input"] = io.BytesIO(body)
    env["wsgi.errors"] = io.StringIO()
    env["CONTENT_LENGTH"] = str(len(body)) if body else ""
    for k, v in headers.items():
        key = k.upper().replace("-", "_")
        if key == "CONTENT_TYPE":
            env["CONTENT_TYPE"] = v
        elif key == "CONTENT_LENGTH":
            env["CONTENT_LENGTH"] = v
        else:
            env["HTTP_" + key] = v
    return env


def _unquote_path(p: str) -> str:
    """WSGI servers decode PATH_INFO (latin-1 str of the decoded bytes)."""
    from urllib.parse import unquote_to_bytes

    return unquote_to_bytes(p).decode("latin-1")


def call(app: Any, method: str, path: str, body: Any = None, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Headers, bytes]:
    """Drive the WSGI ``app`` in-process. ``body``: dict/list → JSON, str → UTF-8, bytes → raw.

    Special header keys (not sent): ``__path_info__`` (raw PATH_INFO override),
    ``__remote_addr__``, ``__https__``, ``__script_name__``.
    """
    hdrs = dict(headers or {})
    data = b""
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            if not any(k.lower() == "content-type" for k in hdrs):
                hdrs["Content-Type"] = "application/json"
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = bytes(body)
    env = _environ(method, path, data, hdrs)
    captured: Dict[str, Any] = {}

    def start_response(status: str, response_headers: List[Tuple[str, str]], exc_info: Any = None) -> Any:
        captured["status"] = status
        captured["headers"] = response_headers
        return lambda chunk: captured.setdefault("written", []).append(chunk)

    result = app(env, start_response)
    try:
        chunks = list(result)
    finally:
        close = getattr(result, "close", None)
        if close:
            close()
    out = b"".join(captured.get("written", [])) + b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    status = int(str(captured["status"]).split()[0])
    return status, Headers(captured["headers"]), out


def jbody(body: bytes) -> Any:
    return json.loads(body.decode("utf-8"))


def basic(user: str, password: str) -> Dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()}


def multipart(files: Sequence[Tuple[str, str, bytes, str]], fields: Optional[Dict[str, str]] = None) -> Tuple[bytes, str]:
    """Build a multipart/form-data body. ``files`` = [(field, filename, data, content_type)]."""
    boundary = "----fathomT1" + uuid.uuid4().hex
    parts: List[bytes] = []
    for k, v in (fields or {}).items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode("utf-8"))
    for field, filename, data, ctype in files:
        head = "--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (
            boundary, field, filename, ctype or "application/octet-stream")
        parts.append(head.encode("utf-8") + data + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def upload(app: Any, path: str, files: Sequence[Tuple[str, bytes, str]], headers: Optional[Dict[str, str]] = None, csrf: bool = True) -> Tuple[int, Headers, bytes]:
    """POST files (filename, data, ctype) as multipart; adds ``X-Fathom: 1`` unless csrf=False."""
    body, ctype = multipart([("file", fn, data, ct) for fn, data, ct in files])
    h = {"Content-Type": ctype}
    if csrf:
        h["X-Fathom"] = "1"
    h.update(headers or {})
    return call(app, "POST", path, body, h)


def get_app() -> Any:
    server = requires("server")
    return server.app


def png_bytes(w: int = 4, h: int = 3) -> bytes:
    """A tiny valid RGB PNG (stdlib zlib + struct)."""
    import struct
    import zlib

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x20\x40\x60" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpg_bytes() -> bytes:
    """Minimal JPEG header bytes (SOI + APP0 JFIF + EOI) — enough for type detection."""
    return bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def deep(o: Any) -> Any:
    return copy.deepcopy(o)


def fr(fr_id: str, section: str, msg: str = "") -> str:
    """Assertion message naming the requirement and spec section."""
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    return "%s (SPEC %s)%s" % (fr_id, section, (": " + msg) if msg else "")
