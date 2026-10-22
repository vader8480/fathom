"""T2 gate G7 (SPEC §8.1, §6.12, §8.2): headless-Chrome smoke test of the app, harnesses and viewer pages.

Serves ``fathom.server.app`` with wsgiref on a free loopback port and a temp ``FATHOM_DATA`` holding
``sunday-demo`` (Appendix B fixture) and ``campus-demo`` (copied when present). Every page is loaded
with ``chrome --headless=new --disable-gpu --virtual-time-budget=8000 --dump-dom <url>?smoke=1`` and the
``data-smoke`` attribute on ``<html>`` is checked for ``ready: true`` and ``errors: []``.

The 150/600 performance budget is measured in real time through the Chrome DevTools protocol, because
``--virtual-time-budget`` virtualises ``performance.now()`` (the harness reports ``renderMs: 0`` there).

Skipped (not failed) when Chrome is absent.
"""
from __future__ import annotations

import base64
import concurrent.futures
import html
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Optional, Tuple
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIEWS = ["map", "patch", "table", "plan", "racks", "inventory", "schedules", "imports", "discovery", "history", "builds", "settings", "sop", "json"]
HARNESSES = ["patchview", "floorplan", "rack", "schedules", "patchtable"]
VIEWER_PAGES = ["/p/sunday-demo", "/p/sunday-demo/rooms", "/p/sunday-demo/d/atem-mini", "/p/sunday-demo/r/main/patch"]
SHELL_IDS = ["app", "app-top", "app-project", "app-room", "app-views", "app-search", "app-assistant-btn", "app-save", "app-user",
             "app-main", "app-inspector", "app-assistant", "fathom-live", "app-toasts", "app-dialog"]
PERF_PATH = "/static/dev/patchview.html?devices=150&cables=600"
PERF_BUDGET_MS = 1500
CHROME_TIMEOUT = 120
PARALLEL = 4


def _find_chrome() -> Optional[str]:
    try:
        from fathom.export import find_chrome
        return find_chrome()
    except Exception:
        return None


CHROME = _find_chrome()


def smoke_url(path: str) -> str:
    """Add smoke=1 to the query; hash routes keep ?smoke=1 before the #."""
    frag = ""
    if "#" in path:
        path, frag = path.split("#", 1)
        frag = "#" + frag
    return path + ("&" if "?" in path else "?") + "smoke=1" + frag


# ------------------------------------------------------------------ DOM parsing

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node(object):
    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional["Node"]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children = []  # type: List[Any]

    def text(self) -> str:
        out = []  # type: List[str]
        for c in self.children:
            out.append(c.text() if isinstance(c, Node) else c)
        return "".join(out)

    def classes(self) -> List[str]:
        return (self.attrs.get("class") or "").split()


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root
        self.all = []  # type: List[Node]

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        self.all.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        self.all.append(n)

    def handle_endtag(self, tag: str) -> None:
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data: str) -> None:
        self.cur.children.append(data)


class Page(object):
    def __init__(self, url: str, dom: str, stderr: str, returncode: int) -> None:
        self.url = url
        self.dom = dom
        self.stderr = stderr
        self.returncode = returncode
        tb = TreeBuilder()
        try:
            tb.feed(dom)
        except Exception:
            pass
        self.nodes = tb.all
        self.smoke = None  # type: Optional[Dict[str, Any]]
        self.smoke_raw = None  # type: Optional[str]
        for n in self.nodes:
            if n.tag == "html" and "data-smoke" in n.attrs:
                self.smoke_raw = n.attrs["data-smoke"]
                try:
                    self.smoke = json.loads(self.smoke_raw)
                except ValueError:
                    self.smoke = None
                break

    def by_id(self, ident: str) -> Optional[Node]:
        for n in self.nodes:
            if n.attrs.get("id") == ident:
                return n
        return None

    def select(self, tag: Optional[str] = None, cls: Optional[str] = None, **attrs: str) -> List[Node]:
        out = []
        for n in self.nodes:
            if tag and n.tag != tag:
                continue
            if cls and cls not in n.classes():
                continue
            ok = True
            for k, v in attrs.items():
                key = k.replace("_", "-")
                if key not in n.attrs or (v is not None and v != "*" and n.attrs[key] != v):
                    ok = False
                    break
            if ok:
                out.append(n)
        return out

    def uncaught(self, origin: str) -> List[str]:
        lines = []
        for ln in self.stderr.splitlines():
            if ":CONSOLE" in ln and "Uncaught" in ln and origin in ln:
                lines.append(ln.split("] ", 1)[-1][:300])
        return lines


def run_chrome_dump(url: str) -> Page:
    ud = tempfile.mkdtemp(prefix="t2-chrome-")
    try:
        cmd = [CHROME or "chrome", "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-extensions", "--user-data-dir=" + ud, "--enable-logging=stderr", "--v=0",
               "--virtual-time-budget=8000", "--dump-dom", url]
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=CHROME_TIMEOUT)
            return Page(url, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"), r.returncode)
        except subprocess.TimeoutExpired:
            return Page(url, "", "chrome timed out after %ds" % CHROME_TIMEOUT, -1)
    finally:
        shutil.rmtree(ud, ignore_errors=True)


# ------------------------------------------------------------ minimal CDP client

class CDP(object):
    """Just enough of the Chrome DevTools protocol (RFC 6455 client frames over a raw socket)."""

    def __init__(self, ws_url: str) -> None:
        m = re.match(r"ws://([^/:]+):(\d+)(/.*)", ws_url)
        if not m:
            raise RuntimeError("bad websocket url " + ws_url)
        self.sock = socket.create_connection((m.group(1), int(m.group(2))), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (m.group(3), m.group(1), m.group(2), key)
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket handshake failed: %r" % resp[:200])
        self.buf = resp.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, text: str) -> None:
        data = text.encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        self.sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self) -> str:
        parts = []  # type: List[bytes]
        while True:
            b0, b1 = self._recv_exact(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(n)
            op = b0 & 0x0F
            if op in (0, 1, 2):
                parts.append(payload)
                if b0 & 0x80:
                    return b"".join(parts).decode("utf-8", "replace")
            elif op == 8:
                raise RuntimeError("websocket closed by peer")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.next_id += 1
        mid = self.next_id
        self._send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._recv())
            if msg.get("id") == mid:
                return msg

    def eval(self, expression: str) -> Any:
        """Evaluate JS (promises awaited) and return the JSON value; raises on a JS exception."""
        r = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        res = r.get("result") or {}
        if res.get("exceptionDetails"):
            raise RuntimeError("JS error: %s" % json.dumps(res["exceptionDetails"])[:500])
        return (res.get("result") or {}).get("value")

    def wait(self, expression: str, timeout: float = 15.0) -> Any:
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.eval(expression)
            if v:
                return v
            time.sleep(0.15)
        raise RuntimeError("timed out waiting for %s" % expression)

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def cdp_session(url: str, timeout: float = 60.0, mobile: Optional[Tuple[int, int]] = None):
    """Context manager: real-time headless Chrome on ``url`` (optionally emulating a phone), yielding a CDP client once data-smoke is set."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        ud = tempfile.mkdtemp(prefix="t2-cdp-")
        proc = subprocess.Popen([CHROME or "chrome", "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                 "--disable-extensions", "--user-data-dir=" + ud, "--remote-debugging-port=0", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cdp = None
        try:
            port_file = Path(ud) / "DevToolsActivePort"
            t0 = time.time()
            while not port_file.exists() or not port_file.read_text().strip():
                if time.time() - t0 > 30:
                    raise RuntimeError("Chrome did not open a DevTools port")
                time.sleep(0.1)
            port = int(port_file.read_text().split()[0])
            targets = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=10).read().decode())
            page = [t for t in targets if t.get("type") == "page"][0]
            cdp = CDP(page["webSocketDebuggerUrl"])
            cdp.call("Page.enable")
            if mobile:
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": mobile[0], "height": mobile[1], "deviceScaleFactor": 2, "mobile": True})
                cdp.call("Emulation.setTouchEmulationEnabled", {"enabled": True})
                cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}]})
            cdp.call("Page.navigate", {"url": url})
            t0 = time.time()
            while time.time() - t0 < timeout:
                # documentElement can be null for an instant while the navigation swaps documents
                val = cdp.eval("document.documentElement ? document.documentElement.getAttribute('data-smoke') : null")
                if val:
                    cdp.smoke = json.loads(val)
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("data-smoke not set within %ds (real time)" % timeout)
            yield cdp
        finally:
            if cdp is not None:
                cdp.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            shutil.rmtree(ud, ignore_errors=True)

    return _cm()


def measure_realtime(url: str, timeout: float = 60.0) -> Dict[str, Any]:
    """Load url in real time (no virtual time) and return the parsed data-smoke JSON."""
    with cdp_session(url, timeout) as cdp:
        return cdp.smoke


# ---------------------------------------------------------------------- server

class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


@unittest.skipUnless(CHROME, "Chrome not found (fathom.export.find_chrome() returned None): frontend smoke skipped")
class FrontendSmoke(unittest.TestCase):
    pages = {}  # type: Dict[str, Page]

    @classmethod
    def setUpClass(cls) -> None:
        cls._old_env = {k: os.environ.get(k) for k in ("FATHOM_DATA", "FATHOM_DEV", "FATHOM_AUTH")}
        cls.data = tempfile.mkdtemp(prefix="t2-smoke-data-")
        os.environ["FATHOM_DATA"] = cls.data
        os.environ.pop("FATHOM_AUTH", None)
        projects = Path(cls.data) / "projects"
        (projects / "sunday-demo").mkdir(parents=True)
        shutil.copy(str(ROOT / "fathom" / "static" / "dev" / "fixture-v2.json"), str(projects / "sunday-demo" / "project.json"))
        cls.campus_rooms = []  # type: List[str]
        campus = ROOT / "fathom" / "samples" / "campus-demo"
        if (campus / "project.json").exists():
            shutil.copytree(str(campus), str(projects / "campus-demo"))
            try:
                doc = json.loads((campus / "project.json").read_text(encoding="utf-8"))
                cls.campus_rooms = [r["id"] for r in doc.get("rooms", [])]
            except Exception:
                cls.campus_rooms = []
        from fathom.server import app
        cls.server = make_server("127.0.0.1", 0, app, server_class=_ThreadingWSGIServer, handler_class=_QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        urls = cls.all_paths()
        with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            futs = {ex.submit(run_chrome_dump, cls.base + smoke_url(p)): p for p in urls}
            for f in concurrent.futures.as_completed(futs):
                cls.pages[futs[f]] = f.result()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.shutdown()
            cls.server.server_close()
        finally:
            for k, v in cls._old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(cls.data, ignore_errors=True)

    @classmethod
    def app_path(cls, view: str, project: str = "sunday-demo", room: str = "main", query: str = "") -> str:
        return "/#/%s/%s/%s%s" % (project, room, view, query)

    @classmethod
    def all_paths(cls) -> List[str]:
        paths = [cls.app_path(v) for v in VIEWS]
        paths += ["/static/dev/%s.html" % h for h in HARNESSES]
        paths += VIEWER_PAGES + ["/login", PERF_PATH]
        paths.append(cls.app_path("patch", query="?sel=device:atem-mini"))
        paths.append("/?debug_missing_view=racks#/sunday-demo/main/racks")
        if cls.campus_rooms:
            paths.append(cls.app_path("patch", project="campus-demo", room=cls.campus_rooms[0]))
            paths.append("/p/campus-demo/rooms")
        return paths

    # ---------------------------------------------------------------- helpers

    def page(self, path: str) -> Page:
        if path not in self.pages:
            self.pages[path] = run_chrome_dump(self.base + smoke_url(path))
        return self.pages[path]

    def assert_smoke(self, path: str, fr: str, require_attr: bool = True) -> Page:
        p = self.page(path)
        self.assertTrue(p.dom, "%s: Chrome produced no DOM for %s (rc=%s): %s" % (fr, path, p.returncode, p.stderr[-400:]))
        if p.smoke is None:
            if require_attr:
                self.fail("%s (§6.12): %s has no parsable data-smoke attribute on <html> (raw=%r); uncaught: %s"
                          % (fr, path, p.smoke_raw, p.uncaught(self.base)))
            self.assert_no_console_errors(p, path, fr)
            return p
        self.assertIs(p.smoke.get("ready"), True, "%s (§6.12): %s data-smoke.ready is not true: %s" % (fr, path, p.smoke_raw))
        self.assertEqual(p.smoke.get("errors"), [], "%s (§6.12): %s reported errors: %s" % (fr, path, json.dumps(p.smoke.get("errors"))[:1500]))
        return p

    def assert_no_console_errors(self, p: Page, path: str, fr: str) -> None:
        """Fallback for pages without data-smoke: no uncaught JS errors and no broken same-origin subresources."""
        self.assertEqual(p.uncaught(self.base), [], "%s: uncaught JS errors on %s" % (fr, path))
        body = [n for n in p.nodes if n.tag == "body"]
        self.assertTrue(body and body[0].text().strip(), "%s: %s rendered an empty body" % (fr, path))
        broken = []
        for n in p.nodes:
            ref = n.attrs.get("src") if n.tag in ("script", "img", "iframe") else n.attrs.get("href") if n.tag == "link" else None
            if not ref or ref.startswith(("data:", "blob:", "#", "javascript:")):
                continue
            full = urllib.request.urljoin(p.url, ref)
            if not full.startswith(self.base):
                continue
            try:
                code = urllib.request.urlopen(full, timeout=10).getcode()
            except Exception as e:  # HTTPError has .code
                code = getattr(e, "code", str(e))
            if code != 200:
                broken.append("%s -> %s" % (ref, code))
        self.assertEqual(broken, [], "%s: broken same-origin subresources on %s" % (fr, path))

    # ------------------------------------------------------------------ tests

    def test_app_views(self) -> None:
        """Every view of the §6.4 registry mounts in the app with no errors."""
        for v in VIEWS:
            with self.subTest(view=v):
                self.assert_smoke(self.app_path(v), "FR-UX-03")
        if self.campus_rooms:
            with self.subTest(view="campus-demo patch"):
                self.assert_smoke(self.app_path("patch", project="campus-demo", room=self.campus_rooms[0]), "FR-ROOM-07")

    def test_app_shell_dom_ids(self) -> None:
        p = self.page(self.app_path("patch"))
        for ident in SHELL_IDS:
            with self.subTest(id=ident):
                self.assertIsNotNone(p.by_id(ident), "§6.4: shell element #%s missing" % ident)
        tabs = {n.attrs.get("data-view") for n in p.nodes if n.attrs.get("data-view")}
        for v in VIEWS:
            with self.subTest(tab=v):
                self.assertIn(v, tabs, "§6.4: #app-views has no [data-view=%s] tab" % v)

    def test_harnesses(self) -> None:
        for h in HARNESSES:
            with self.subTest(harness=h):
                self.assert_smoke("/static/dev/%s.html" % h, "§6.12")

    def test_viewer_pages(self) -> None:
        """Server-rendered viewer pages (FR-MAP-01/06, FR-PT-08) render with no console errors."""
        pages = list(VIEWER_PAGES)
        if self.campus_rooms:
            pages.append("/p/campus-demo/rooms")
        for path in pages:
            with self.subTest(page=path):
                self.assert_smoke(path, "FR-PT-08" if path.endswith("/patch") else "FR-MAP-06", require_attr=False)

    def test_login_page(self) -> None:
        p = self.assert_smoke("/login", "FR-USER-03", require_attr=False)
        self.assertTrue(p.select("input"), "FR-USER-03: /login has no inputs")

    def test_patchview_harness(self) -> None:
        p = self.assert_smoke("/static/dev/patchview.html", "FR-PV-02")
        wires = p.select("path", data_cable="*")
        self.assertEqual(len(wires), 15, "FR-PV-02: harness on fixture must show 15 path[data-cable], got %d" % len(wires))
        self.assertEqual(len({w.attrs["data-cable"] for w in wires}), 15, "FR-PV-02: one wire per cable")
        stats = (p.smoke or {}).get("stats") or {}
        self.assertEqual(stats.get("wires"), 15, "FR-PV-15 (§6.5): __pvStats.wires")

    def test_patchview_perf_150_600(self) -> None:
        p = self.assert_smoke(PERF_PATH, "FR-PV-15")
        stats = (p.smoke or {}).get("stats") or {}
        self.assertEqual(stats.get("cards"), 150, "FR-PV-15: __pvStats.cards for devices=150")
        self.assertEqual(stats.get("wires"), 600, "FR-PV-15: __pvStats.wires for cables=600")
        self.assertEqual(len(p.select("path", data_cable="*")), 600, "FR-PV-15: 600 wires in the DOM")
        real = measure_realtime(self.base + smoke_url(PERF_PATH))
        self.assertTrue(real.get("ready"), "FR-PV-15: harness not ready in real time: %r" % real)
        rs = (real.get("stats") or {}).get("renderMs")
        self.assertIsInstance(rs, (int, float), "FR-PV-15 (§6.5): __pvStats.renderMs missing: %r" % real.get("stats"))
        sys.stderr.write("\n[T2] patchview 150/600 renderMs (real time) = %s ms\n" % rs)
        self.assertGreater(rs, 0, "FR-PV-15: renderMs must be a real measurement (> 0)")
        self.assertLessEqual(rs, PERF_BUDGET_MS, "FR-PV-15 / §8.2: renderMs %s > %d ms for devices=150&cables=600" % (rs, PERF_BUDGET_MS))

    def test_rack_harness(self) -> None:
        p = self.assert_smoke("/static/dev/rack.html", "FR-RACK-03")
        blocks = p.select("div", cls="rk-block", data_device="*")
        devs = {b.attrs["data-device"] for b in blocks}
        self.assertIn("shure-wireless", devs, "FR-RACK-03: 12U FOH rack shows shure-wireless")
        self.assertEqual(devs, {"shure-wireless"}, "FR-RACK-03: FOH rack holds exactly one device")

    def test_aria_landmarks(self) -> None:
        app = self.page(self.app_path("patch"))
        vp = app.select(cls="pv-viewport")
        self.assertTrue(vp, "FR-A11Y-02: .pv-viewport missing in the app patch view")
        self.assertEqual(vp[0].attrs.get("role"), "application", "FR-A11Y-02: patch canvas role=application")
        self.assertTrue(vp[0].attrs.get("aria-label"), "FR-A11Y-02: patch canvas aria-label")
        cards = app.select(cls="pv-card", data_device="*")
        self.assertTrue(cards, "FR-A11Y-02: no .pv-card[data-device]")
        for c in cards:
            self.assertEqual(c.attrs.get("role"), "group", "FR-A11Y-02: card role=group (%s)" % c.attrs.get("data-device"))
            self.assertTrue(c.attrs.get("aria-label"), "FR-A11Y-02: card aria-label (%s)" % c.attrs.get("data-device"))
        live = app.by_id("fathom-live")
        self.assertIsNotNone(live, "FR-A11Y-02: #fathom-live missing")
        self.assertEqual(live.attrs.get("aria-live"), "polite", "FR-A11Y-02: #fathom-live aria-live=polite")
        fp = self.page("/static/dev/floorplan.html").select(cls="fp-viewport")
        self.assertTrue(fp and fp[0].attrs.get("role") == "application", "FR-A11Y-02: .fp-viewport role=application")
        ths = self.page("/static/dev/patchtable.html").select("th")
        self.assertTrue(ths, "FR-A11Y-02: patch table has <th> cells")
        self.assertTrue(all(t.attrs.get("scope") for t in ths), "FR-A11Y-02: tables use <th scope>")

    def test_deep_link_selection(self) -> None:
        path = self.app_path("patch", query="?sel=device:atem-mini")
        p = self.assert_smoke(path, "FR-UX-02")
        ins = p.by_id("app-inspector")
        self.assertIsNotNone(ins, "FR-UX-02: #app-inspector missing")
        self.assertIn("ATEM Mini", ins.text(), "FR-UX-02: deep link ?sel=device:atem-mini must show ATEM Mini in the inspector")

    def test_sop_viewer_on_a_phone(self) -> None:
        """SOP wiki (§6.4 sop view) at 390×844: drill-down tree, rendered page with tappable checklist, no horizontal scroll."""
        if not self.campus_rooms:
            self.skipTest("campus-demo sample not present")
        url = self.base + smoke_url(self.app_path("sop", project="campus-demo", room="main"))
        with cdp_session(url, mobile=(390, 844)) as cdp:
            self.assertIs(cdp.smoke.get("ready"), True, "SOP view ready on a phone: %r" % cdp.smoke)
            self.assertEqual(cdp.smoke.get("errors"), [])
            cdp.wait("document.querySelectorAll('.sop-item').length")
            tree = cdp.eval("""({
              items: document.querySelectorAll('.sop-item').length,
              hscroll: document.documentElement.scrollWidth > window.innerWidth,
              tab: !!document.querySelector('#app-tabbar [data-tab=sop]'),
              search: !!document.querySelector('.sop-search'),
              searchSticky: getComputedStyle(document.querySelector('.sop-tree-head')).position,
              minTap: Math.min.apply(null, Array.from(document.querySelectorAll('.sop-item-main')).map(function (b) { return b.getBoundingClientRect().height; })),
            })""")
            self.assertGreaterEqual(tree["items"], 1, "SOP-UI-01: page tree lists the sample sections")
            self.assertFalse(tree["hscroll"], "SOP-UI-01: no horizontal scrolling at 390px")
            self.assertTrue(tree["tab"], "SOP-UI-01: SOPs is a bottom tab, not under More")
            self.assertTrue(tree["search"], "SOP-UI-01: search field present")
            self.assertEqual(tree["searchSticky"], "sticky", "SOP-UI-01: tree header (with search) is sticky")
            self.assertGreaterEqual(tree["minTap"], 44, "SOP-UI-01: list rows are ≥44px tap targets")
            # drill into the first section, then open the power-up page
            cdp.eval("document.querySelector('.sop-item.has-kids .sop-item-main').click()")
            self.assertTrue(cdp.wait("!!document.querySelector('.sop-tree-list > .sop-back')"), "SOP-UI-02: drill-down shows a back button")
            cdp.eval("document.querySelector('.sop-item[data-page=power-up] .sop-item-main').click()")
            cdp.wait("document.querySelectorAll('.sop-page input[data-task]').length")
            cdp.eval("var b = document.querySelectorAll('.sop-page input[data-task]'); b[0].click(); b[1].click(); 1")
            page = cdp.eval("""({
              title: document.querySelector('.sop-page h1').textContent,
              font: parseFloat(getComputedStyle(document.querySelector('.sop-body')).fontSize),
              tasks: document.querySelectorAll('.sop-page input[data-task]').length,
              checked: document.querySelectorAll('.sop-page input[data-task]:checked').length,
              stored: sessionStorage.getItem('fathom.sop.tasks.campus-demo.power-up'),
              taskTap: Math.min.apply(null, Array.from(document.querySelectorAll('.md-task-label')).map(function (b) { return b.getBoundingClientRect().height; })),
              applies: document.querySelectorAll('.sop-applies .chip').length,
              appliesSticky: getComputedStyle(document.querySelector('.sop-applies')).position,
              toc: !!document.querySelector('details.sop-toc'),
              hscroll: document.querySelector('.sop-main').scrollWidth > document.querySelector('.sop-main').clientWidth + 1,
              next: !!document.querySelector('.sop-prevnext .sop-next'),
              errors: window.__fathomErrors,
            })""")
            self.assertIn("Power-up", page["title"])
            self.assertGreaterEqual(page["font"], 17, "SOP-UI-03: body text ≥17px")
            self.assertGreater(page["tasks"], 5)
            self.assertEqual(page["checked"], 2, "SOP-UI-04: checkboxes toggle by tap")
            self.assertEqual(json.loads(page["stored"] or "[]"), [0, 1], "SOP-UI-04: checklist state kept in sessionStorage")
            self.assertGreaterEqual(page["taskTap"], 44, "SOP-UI-04: task rows ≥44px")
            self.assertGreater(page["applies"], 0, "SOP-UI-03: Applies-to chips")
            self.assertEqual(page["appliesSticky"], "sticky", "SOP-UI-03: Applies-to strip is sticky")
            self.assertTrue(page["toc"], "SOP-UI-03: collapsible TOC")
            self.assertFalse(page["hscroll"], "SOP-UI-03: no horizontal scrolling in the rendered page")
            self.assertTrue(page["next"], "SOP-UI-03: next sibling at the bottom")
            self.assertEqual(page["errors"], [])
            # troubleshooting page: the table scrolls inside its container, the page does not
            cdp.eval("location.hash = '#/campus-demo/main/sop?page=no-audio'; 1")
            cdp.wait("!!document.querySelector('.sop-page .md-table')")
            tbl = cdp.eval("({wrap: getComputedStyle(document.querySelector('.md-table')).overflowX, hscroll: document.querySelector('.sop-main').scrollWidth > document.querySelector('.sop-main').clientWidth + 1, callouts: document.querySelectorAll('.md-callout').length, errors: window.__fathomErrors})")
            self.assertEqual(tbl["wrap"], "auto", "SOP-UI-03: tables scroll inside their container")
            self.assertFalse(tbl["hscroll"])
            self.assertGreater(tbl["callouts"], 0)
            self.assertEqual(tbl["errors"], [])
            # device inspector shows the Procedures section with backlinks
            cdp.eval("document.querySelector('.sop-applies .chip[data-device]').click(); 1")
            cdp.wait("document.querySelectorAll('#app-inspector .ins-procs li').length")
            procs = cdp.eval("document.querySelectorAll('#app-inspector [data-section=procedures] .ins-procs li').length")
            self.assertGreaterEqual(procs, 1, "SOP-UI-05: device inspector lists the procedures that reference the device")

    def test_view_error_card(self) -> None:
        path = "/?debug_missing_view=racks#/sunday-demo/main/racks"
        p = self.page(path)
        self.assertIsNotNone(p.smoke, "FR-UX-03 (§6.12): no data-smoke on %s" % path)
        self.assertIs(p.smoke.get("ready"), True, "FR-UX-03: app still becomes ready when a view module fails")
        main = p.by_id("app-main")
        self.assertIsNotNone(main, "FR-UX-03: #app-main missing")
        self.assertRegex(main.text().lower(), r"error|fail|could not|couldn't|unable", "FR-UX-03: inline error card with the message in #app-main")
        self.assertIsNotNone(p.by_id("app-views"), "FR-UX-03: the rest of the app keeps working")


if __name__ == "__main__":
    unittest.main()
