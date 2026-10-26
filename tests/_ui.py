"""Shared headless-Chrome helpers for ``tests/test_ui_*.py`` (docs/ui-audit.md B.2 SHELL item 10, D10).

Not collected by ``unittest discover`` (the name starts with ``_``). One ``UiServer`` per TestCase class
serves ``fathom.server.app`` on a free loopback port from a temp ``FATHOM_DATA`` holding ``sunday-demo``
(``fathom/static/dev/fixture-v2.json``) and ``campus-demo`` (``fathom/samples/campus-demo``), exactly as
``FrontendSmoke.setUpClass`` does. ``open(path, size)`` gives a real-time page in its own browser context
(fresh cookies and storage) of one shared headless Chrome, sized per ``SIZES``; it returns once
``data-smoke`` is set on ``<html>``. Every helper raises ``AssertionError`` on timeouts, so failures read
like assertions. Suites skip when Chrome is absent (``CHROME`` is None); set ``FATHOM_CHROME``.

    try:
        from _ui import UiCase
    except ImportError:  # pragma: no cover
        from tests._ui import UiCase

    class ShellUi(UiCase):                      # skips without Chrome; one server per class
        def test_patch_at_three_sizes(self):
            for size in ("d", "t", "m"):
                with self.open("#/campus-demo/main/patch", size) as pg:
                    self.assertEqual(pg.smoke["errors"], [])
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    pg.click("[data-view=table]")
                    pg.wait_for("location.hash.indexOf('/table') > 0")
                    pg.press("Escape")
                    pg.shot("table-" + size)    # $FATHOM_UI_SHOTS/table-<size>.png when set
            with self.open("#/campus-demo/main/patch", "m",
                           intercepts=[("/api/v2/projects/campus-demo/overlay", 500, {"error": "boom"})]) as pg:
                self.assertTrue(pg.js("!!document.querySelector('#app-main')"))

Without ``UiCase``: ``with UiServer() as srv, srv.open(path, size) as pg: ...``. Session methods:
``js``, ``wait_for``, ``click``, ``press``, ``rect``, ``page_hscroll``, ``offscreen``, ``reload``, ``goto``,
``shot``, ``intercept``, ``clear_intercepts`` (plus ``call``/``eval`` from ``CDP``).
"""
from __future__ import annotations

import atexit
import base64
import contextlib
import fnmatch
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from wsgiref.simple_server import make_server

try:
    from test_frontend_smoke import CDP, CHROME, ROOT, smoke_url, _QuietHandler, _ThreadingWSGIServer
except ImportError:  # pragma: no cover
    from tests.test_frontend_smoke import CDP, CHROME, ROOT, smoke_url, _QuietHandler, _ThreadingWSGIServer

__all__ = ["CHROME", "SIZES", "UiServer", "UiPage", "UiCase", "open", "skip_without_chrome"]

SIZES = {"d": (1280, 900, False), "t": (820, 1180, True), "m": (390, 844, True)}

skip_without_chrome = unittest.skipUnless(CHROME, "Chrome not found (set FATHOM_CHROME): UI test skipped")

READY_TIMEOUT = 60.0

_KEYS = {
    "Enter": (13, "Enter", "\r"), "Escape": (27, "Escape", ""), "Tab": (9, "Tab", ""),
    "Backspace": (8, "Backspace", ""), "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "Space": (32, "Space", " "), "ArrowDown": (40, "ArrowDown", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowRight": (39, "ArrowRight", ""), "Home": (36, "Home", ""),
    "End": (35, "End", ""), "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
}
_MODS = {"Alt": 1, "Control": 2, "Ctrl": 2, "Meta": 4, "Cmd": 4, "Shift": 8}


def _q(s: str) -> str:
    return json.dumps(s)


def _resolve(base: str, path: str, smoke: bool = True) -> str:
    if path.startswith(("http://", "https://")):
        url = path
    else:
        if path.startswith(("#", "?")):
            path = "/" + path
        url = base + path
    return smoke_url(url) if smoke else url


# ---------------------------------------------------------------- shared Chrome

class _Chrome(object):
    """One headless Chrome with a browser-level DevTools connection; pages live in throwaway contexts."""

    def __init__(self) -> None:
        self.ud = tempfile.mkdtemp(prefix="ui-chrome-")
        cmd = [CHROME or "chrome", "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-extensions", "--disable-dev-shm-usage", "--user-data-dir=" + self.ud,
               "--remote-debugging-port=0", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.lock = threading.Lock()
        try:
            port_file = Path(self.ud) / "DevToolsActivePort"
            t0 = time.time()
            while not port_file.exists() or not port_file.read_text().strip():
                if time.time() - t0 > 30 or self.proc.poll() is not None:
                    raise RuntimeError("Chrome did not open a DevTools port")
                time.sleep(0.05)
            self.port = int(port_file.read_text().split()[0])
            info = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=10).read().decode())
            self.browser = CDP(info["webSocketDebuggerUrl"])
        except Exception:
            self.close()
            raise

    def alive(self) -> bool:
        return self.proc.poll() is None

    def command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self.lock:
            msg = self.browser.call(method, params)
        if "error" in msg:
            raise RuntimeError("%s failed: %s" % (method, msg["error"]))
        return msg.get("result") or {}

    def new_page(self) -> Tuple[str, str]:
        """(browserContextId, page websocket url) of a fresh isolated tab."""
        ctx = self.command("Target.createBrowserContext")["browserContextId"]
        tid = self.command("Target.createTarget", {"url": "about:blank", "browserContextId": ctx})["targetId"]
        return ctx, "ws://127.0.0.1:%d/devtools/page/%s" % (self.port, tid)

    def dispose(self, ctx: str) -> None:
        try:
            self.command("Target.disposeBrowserContext", {"browserContextId": ctx})
        except Exception:
            pass

    def close(self) -> None:
        b = getattr(self, "browser", None)
        if b is not None:
            b.close()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.ud, ignore_errors=True)


_chrome = None  # type: Optional[_Chrome]
_chrome_lock = threading.Lock()


def _get_chrome() -> _Chrome:
    global _chrome
    with _chrome_lock:
        if _chrome is None or not _chrome.alive():
            if _chrome is not None:
                _chrome.close()
            _chrome = _Chrome()
        return _chrome


def _close_chrome() -> None:
    global _chrome
    with _chrome_lock:
        if _chrome is not None:
            _chrome.close()
            _chrome = None


atexit.register(_close_chrome)


# ---------------------------------------------------------------- page session

class UiPage(CDP):
    """A CDP page session with UI helpers. Events are handled while any command waits for its reply."""

    def __init__(self, ws_url: str, size: str, base: str) -> None:
        CDP.__init__(self, ws_url)
        self.size = size
        self.base = base
        self.smoke = None  # type: Optional[Dict[str, Any]]
        self.events = deque(maxlen=500)  # type: deque
        self.rules = []  # type: List[Dict[str, Any]]
        self.touch = SIZES[size][2]

    # -------------------------------------------------------- protocol plumbing

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.next_id += 1
        mid = self.next_id
        self._send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._recv())
            if msg.get("id") == mid:
                return msg
            if "method" in msg:
                self._event(msg)

    def command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        msg = self.call(method, params)
        if "error" in msg:
            raise RuntimeError("%s failed: %s" % (method, msg["error"]))
        return msg.get("result") or {}

    def _fire(self, method: str, params: Dict[str, Any]) -> None:
        """Send without waiting (used from inside the event loop; the reply is skipped later)."""
        self.next_id += 1
        self._send(json.dumps({"id": self.next_id, "method": method, "params": params}))

    def _event(self, msg: Dict[str, Any]) -> None:
        self.events.append(msg)
        if msg["method"] != "Fetch.requestPaused":
            return
        p = msg["params"]
        req = p.get("request") or {}
        for rule in self.rules:
            if (rule["method"] is None or rule["method"] == req.get("method")) and fnmatch.fnmatchcase(req.get("url", ""), rule["glob"]):
                rule["hits"] += 1
                self._fire("Fetch.fulfillRequest", {
                    "requestId": p["requestId"], "responseCode": rule["status"], "body": rule["body"],
                    "responseHeaders": [{"name": "Content-Type", "value": rule["type"]}, {"name": "Cache-Control", "value": "no-store"}],
                })
                return
        self._fire("Fetch.continueRequest", {"requestId": p["requestId"]})

    def setup(self) -> None:
        w, hgt, touch = SIZES[self.size]
        self.command("Page.enable")
        self.command("Page.bringToFront")
        self.command("Emulation.setFocusEmulationEnabled", {"enabled": True})
        self.command("Emulation.setDeviceMetricsOverride", {"width": w, "height": hgt, "deviceScaleFactor": 2 if touch else 1, "mobile": touch})
        if touch:
            self.command("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            self.command("Emulation.setEmulatedMedia", {"features": [{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}]})

    # -------------------------------------------------------------- basics

    def js(self, expr: str) -> Any:
        """Evaluate JS (promises awaited) and return its JSON value; raises RuntimeError on a JS exception."""
        return self.eval(expr)

    def wait_for(self, expr: str, timeout: float = 15.0) -> Any:
        """Poll ``expr`` until truthy and return its value."""
        t0 = time.time()
        last_err = None
        while time.time() - t0 < timeout:
            try:
                v = self.eval(expr)
                if v:
                    return v
            except RuntimeError as e:  # e.g. document swapped mid-navigation
                last_err = e
            time.sleep(0.1)
        raise AssertionError("timed out after %.0fs waiting for %s (location=%r%s)"
                             % (timeout, expr, self._location(), "; last error: %s" % last_err if last_err else ""))

    def _location(self) -> str:
        try:
            return self.eval("location.href")
        except Exception:
            return "?"

    @property
    def hash(self) -> str:
        return self.eval("location.hash")

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> Dict[str, Any]:
        """Wait for ``data-smoke`` on <html> (set ~1 s after the first render) and keep it in ``self.smoke``."""
        raw = self.wait_for("document.documentElement && document.documentElement.getAttribute('data-smoke')", timeout)
        self.smoke = json.loads(raw)
        return self.smoke

    def navigate(self, url: str, ready: bool = True) -> None:
        self.command("Page.navigate", {"url": url})
        if ready:
            self.wait_ready()
        else:
            self.wait_for("document.readyState === 'complete' && location.href !== 'about:blank'")

    def goto(self, path: str, ready: bool = True) -> None:
        """A '#…' path only changes the hash (waits for hashchange); anything else loads a new document."""
        if path.startswith("#"):
            self.eval("""new Promise(function (res) {
              var done = false;
              function fin() { if (done) return; done = true; removeEventListener('hashchange', fin); setTimeout(res, 50); }
              addEventListener('hashchange', fin); setTimeout(fin, 1000); location.hash = %s;
            })""" % _q(path))
        else:
            self.navigate(_resolve(self.base, path, smoke=ready), ready)

    def reload(self, ready: bool = True) -> None:
        """Reload the document (same URL and hash) and wait for the new one to be ready."""
        self.eval("window.__uiBeforeReload = 1")
        self.command("Page.reload")
        self.wait_for("document.readyState !== 'loading' && !window.__uiBeforeReload")
        if ready:
            self.wait_ready()
        else:
            self.wait_for("document.readyState === 'complete'")

    # --------------------------------------------------------------- geometry

    def rect(self, selector: str) -> Optional[Dict[str, float]]:
        """Bounding client rect of the first match, or None when nothing matches."""
        return self.eval("""(function () {
          var el = document.querySelector(%s); if (!el) return null;
          var r = el.getBoundingClientRect();
          return {x: r.x, y: r.y, left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height};
        })()""" % _q(selector))

    def page_hscroll(self) -> int:
        """Horizontal page overflow in px (``scrollWidth - innerWidth``); <= 0 means no horizontal page scroll."""
        return int(round(self.eval("document.documentElement.scrollWidth - window.innerWidth")))

    def offscreen(self, selector: str, axis: str = "xy") -> int:
        """Number of rendered matches that are not fully visible without scrolling.

        A match counts when its rect sticks out (by more than 1px) of the viewport or of the visible box of
        any ancestor scroll/clip container (overflow other than ``visible``), along ``axis`` ('x', 'y' or
        'xy'). Elements with an empty rect or ``visibility: hidden`` are not counted.
        """
        return int(self.eval("""(function (sel, axis) {
          var W = window.innerWidth, H = window.innerHeight, n = 0;
          Array.prototype.forEach.call(document.querySelectorAll(sel), function (el) {
            var r = el.getBoundingClientRect();
            if (!r.width && !r.height) return;
            var cs = getComputedStyle(el);
            if (cs.visibility === 'hidden') return;
            var l = 0, t = 0, rt = W, b = H;
            if (cs.position !== 'fixed') {
              for (var p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
                var s = getComputedStyle(p), pr;
                if (s.overflowX !== 'visible') { pr = p.getBoundingClientRect(); l = Math.max(l, pr.left); rt = Math.min(rt, pr.right); }
                if (s.overflowY !== 'visible') { pr = p.getBoundingClientRect(); t = Math.max(t, pr.top); b = Math.min(b, pr.bottom); }
                if (s.position === 'fixed') break;
              }
            }
            var out = false;
            if (axis.indexOf('x') >= 0 && (r.left < l - 1 || r.right > rt + 1)) out = true;
            if (axis.indexOf('y') >= 0 && (r.top < t - 1 || r.bottom > b + 1)) out = true;
            if (out) n++;
          });
          return n;
        })(%s, %s)""" % (_q(selector), _q(axis))))

    # ----------------------------------------------------------------- input

    def click(self, selector: str, timeout: float = 5.0, force: bool = False) -> None:
        """Real pointer click (a tap at t/m) on the centre of the first visible match.

        Scrolls it into view and fails when another element covers that point; ``force=True`` skips the
        hit test and calls ``el.click()`` instead (for hidden or covered controls).
        """
        if force:
            self.wait_for("!!document.querySelector(%s)" % _q(selector), timeout)
            self.eval("document.querySelector(%s).click()" % _q(selector))
            return
        probe = """(function (sel) {
          var all = document.querySelectorAll(sel), el = null;
          for (var i = 0; i < all.length; i++) { var q = all[i].getBoundingClientRect(); if (q.width > 0 && q.height > 0) { el = all[i]; break; } }
          if (!el) return null;
          el.scrollIntoView({block: 'center', inline: 'center'});
          var r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
          var hit = document.elementFromPoint(x, y);
          function name(n) { return n ? n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\\s+/).join('.') : '') : 'nothing'; }
          return {x: x, y: y, ok: !!hit && (hit === el || el.contains(hit)), hit: name(hit)};
        })(%s)""" % _q(selector)
        pt = self.wait_for(probe, timeout)
        if not pt["ok"]:
            raise AssertionError("click(%s): point (%d, %d) is covered by %s" % (selector, pt["x"], pt["y"], pt["hit"]))
        x, y = pt["x"], pt["y"]
        if self.touch:
            self.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            self.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        else:
            self.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            self.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
            self.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})

    def press(self, key: str) -> None:
        """Key press to the focused element: 'Escape', 'Enter', 'ArrowDown', 'a', 'Meta+k', 'Control+Shift+P'…"""
        parts = key.split("+") if len(key) > 1 else [key]
        if parts[-1] == "" and len(parts) > 1:  # "Control++"
            parts = parts[:-2] + ["+"]
        name = parts[-1]
        mods = 0
        for m in parts[:-1]:
            if m not in _MODS:
                raise ValueError("press(%r): unknown modifier %r" % (key, m))
            mods |= _MODS[m]
        if name in _KEYS:
            vk, code, text = _KEYS[name]
            name = " " if name == "Space" else name
        elif len(name) == 1:
            ch = name.upper() if mods & 8 else name
            name, text, vk = ch, ch, ord(ch.upper())
            code = ("Key" + ch.upper()) if ch.isalpha() else ("Digit" + ch) if ch.isdigit() else ""
        else:
            raise ValueError("press(%r): unknown key" % key)
        if mods & (2 | 4):
            text = ""
        down = {"type": "keyDown" if text else "rawKeyDown", "key": name, "code": code, "modifiers": mods,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if text:
            down["text"] = text
            down["unmodifiedText"] = text
        self.command("Input.dispatchKeyEvent", down)
        self.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": code, "modifiers": mods,
                                                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})

    # ------------------------------------------------------- screenshots, network

    def shot(self, name: str) -> Optional[str]:
        """Write ``$FATHOM_UI_SHOTS/<name>.png`` when that variable is set; returns the path or None."""
        d = os.environ.get("FATHOM_UI_SHOTS")
        if not d:
            return None
        Path(d).mkdir(parents=True, exist_ok=True)
        data = self.command("Page.captureScreenshot", {"format": "png"})["data"]
        p = Path(d) / (name + ".png")
        p.write_bytes(base64.b64decode(data))
        return str(p)

    def intercept(self, pattern: str, status: int = 500, body: Any = "", method: Optional[str] = None) -> Dict[str, Any]:
        """Answer matching requests with ``status`` and ``body`` instead of the server.

        ``pattern`` is a CDP URL glob (``*`` and ``?``); a pattern starting with ``/`` matches that path on
        any origin (add ``*`` for query strings). ``body`` may be str, bytes or a JSON-able dict/list.
        ``method`` limits the rule to one HTTP method. The service worker is bypassed so cached routes are
        interceptable too. Applies to requests made from now on (``reload()`` to re-fetch); the returned
        rule's ``hits`` counts fulfilled requests.
        """
        glob = "*" + pattern if pattern.startswith("/") else pattern
        if isinstance(body, (dict, list)):
            raw, ctype = json.dumps(body).encode(), "application/json"
        elif isinstance(body, bytes):
            raw, ctype = body, "application/octet-stream"
        else:
            raw = str(body).encode()
            ctype = "application/json" if str(body)[:1] in ("{", "[") else "text/plain; charset=utf-8"
        rule = {"glob": glob, "status": int(status), "body": base64.b64encode(raw).decode(), "type": ctype,
                "method": method.upper() if method else None, "hits": 0}
        self.rules.append(rule)
        self.command("Network.enable")
        self.command("Network.setBypassServiceWorker", {"bypass": True})
        self.command("Fetch.enable", {"patterns": [{"urlPattern": r["glob"], "requestStage": "Request"} for r in self.rules]})
        return rule

    def clear_intercepts(self) -> None:
        self.rules = []
        self.command("Fetch.disable")


@contextlib.contextmanager
def open(path: str, size: str = "d", base: Optional[str] = None, ready: bool = True,
         intercepts: Optional[List[Tuple[Any, ...]]] = None) -> Iterator[UiPage]:  # noqa: A001
    """Open ``path`` (``#/…``, ``/…`` or a full URL; ``?smoke=1`` is added when ``ready``) at ``size``.

    ``base`` defaults to the most recently started ``UiServer``. ``intercepts`` is a list of
    ``(pattern, status, body[, method])`` installed before the first request.
    """
    if size not in SIZES:
        raise ValueError("size must be one of %s" % sorted(SIZES))
    if base is None:
        if UiServer.current is None:
            raise RuntimeError("no UiServer running; start one or pass base=")
        base = UiServer.current.base
    chrome = _get_chrome()
    ctx, ws = chrome.new_page()
    page = None
    try:
        page = UiPage(ws, size, base)
        page.setup()
        for rule in intercepts or []:
            page.intercept(*rule)
        page.navigate(_resolve(base, path, smoke=ready), ready)
        yield page
    finally:
        if page is not None:
            page.close()
        chrome.dispose(ctx)


# ---------------------------------------------------------------------- server

class UiServer(object):
    """Threaded WSGI server on a temp FATHOM_DATA with sunday-demo and campus-demo; ``.base`` is its URL."""

    current = None  # type: Optional[UiServer]

    def __init__(self) -> None:
        self.base = ""
        self.data = ""
        self.campus_rooms = []  # type: List[str]
        self._old_env = {}  # type: Dict[str, Optional[str]]
        self.server = None  # type: Any

    def start(self) -> "UiServer":
        self._old_env = {k: os.environ.get(k) for k in ("FATHOM_DATA", "FATHOM_DEV", "FATHOM_AUTH")}
        self.data = tempfile.mkdtemp(prefix="ui-data-")
        os.environ["FATHOM_DATA"] = self.data
        os.environ.pop("FATHOM_AUTH", None)
        projects = Path(self.data) / "projects"
        (projects / "sunday-demo").mkdir(parents=True)
        shutil.copy(str(ROOT / "fathom" / "static" / "dev" / "fixture-v2.json"), str(projects / "sunday-demo" / "project.json"))
        campus = ROOT / "fathom" / "samples" / "campus-demo"
        if (campus / "project.json").exists():
            shutil.copytree(str(campus), str(projects / "campus-demo"))
            try:
                doc = json.loads((campus / "project.json").read_text(encoding="utf-8"))
                self.campus_rooms = [r["id"] for r in doc.get("rooms", [])]
            except Exception:
                self.campus_rooms = []
        from fathom.server import app
        self.server = make_server("127.0.0.1", 0, app, server_class=_ThreadingWSGIServer, handler_class=_QuietHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        UiServer.current = self
        return self

    def stop(self) -> None:
        try:
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
        finally:
            for k, v in self._old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            if UiServer.current is self:
                UiServer.current = None
            shutil.rmtree(self.data, ignore_errors=True)

    def url(self, path: str, smoke: bool = True) -> str:
        return _resolve(self.base, path, smoke)

    def open(self, path: str, size: str = "d", **kw: Any) -> Any:
        kw.setdefault("base", self.base)
        return open(path, size, **kw)

    def __enter__(self) -> "UiServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


@skip_without_chrome
class UiCase(unittest.TestCase):
    """Base class: one ``UiServer`` per subclass (``cls.server``, ``cls.base``); ``self.open(path, size)``."""

    server = None  # type: Optional[UiServer]
    base = ""

    @classmethod
    def setUpClass(cls) -> None:
        super(UiCase, cls).setUpClass()
        cls.server = UiServer().start()
        cls.base = cls.server.base

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            if cls.server is not None:
                cls.server.stop()
        finally:
            super(UiCase, cls).tearDownClass()

    def open(self, path: str, size: str = "d", **kw: Any) -> Any:
        assert self.server is not None
        return self.server.open(path, size, **kw)
