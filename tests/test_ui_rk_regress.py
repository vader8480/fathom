"""REG: regression suite for the Rackula work, at d and m.

Things the rack features must not break: drag patching port to port in the patch view and tracing
from the patched port; the public device page (the QR target) and its rack link, which carries a
share token; racks stay read-only for a viewer; the service worker registers and every precache
entry is served (200) and cached, rack images go to their own runtime cache; a CSV import places a
racked device and a build then writes the rack files; History lists a rack edit and Restore undoes
it; the rack harness walkthrough (``dev/rack.html?walk=1``) runs clean.

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_ui_rk_regress.py -v``.
Skips without Chrome; ``$FATHOM_UI_SHOTS`` collects ``reg-*.png``.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from urllib.parse import urljoin, urlparse

try:
    from _ui import UiCase, ROOT
    import test_ui_pv as pvt
except ImportError:  # pragma: no cover
    from tests._ui import UiCase, ROOT
    from tests import test_ui_pv as pvt

PROJECT = "campus-demo"
CAMPUS = "#/campus-demo/main/"
SIZES = ("d", "m")
SW = ROOT / "fathom" / "static" / "sw.js"

# Created in parallel by LAND (rack-toolbar.css) and PAGE (page-rack.css); every other entry is strict.
PENDING = {
    "static/css/rack-toolbar.css": "LAND creates rack-toolbar.css; skipped until it merges",
    "static/css/page-rack.css": "PAGE creates page-rack.css; skipped until it merges",
}

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); if (!el) return false; var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")


def q(s: str) -> str:
    return json.dumps(s)


def sw_source() -> str:
    return SW.read_text(encoding="utf-8")


def sw_version() -> str:
    m = re.search(r"const VERSION = '([^']+)'", sw_source())
    return m.group(1) if m else ""


def precache_entries() -> list:
    block = re.search(r"const PRECACHE = \[(.*?)\];", sw_source(), re.S).group(1)
    block = re.sub(r"//[^\n]*", "", block)
    return re.findall(r"'([^']*)'", block)


def api(base: str, method: str, path: str, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hd = {"X-Fathom": "1"}
    if body is not None:
        hd["Content-Type"] = "application/json"
    hd.update(headers or {})
    req = urllib.request.Request(base + path, data=data, method=method, headers=hd)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode() or "{}"
        return json.loads(raw) if raw.lstrip()[:1] in "{[" else raw


def doc_of(base: str) -> dict:
    return api(base, "GET", "/api/v2/projects/" + PROJECT)


def device(base: str, dev_id: str) -> dict:
    return next((d for d in doc_of(base)["doc"].get("devices") or [] if d.get("id") == dev_id), {})


def wait_until(fn, timeout: float = 20.0, what: str = "condition"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("timed out after %.0fs waiting for %s" % (timeout, what))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading, .fb-skeleton, [aria-busy=true]');
    })(%s)""" % q(view), timeout)


class RackRegression(UiCase):
    # ------------------------------------------------------------ patching

    def test_drag_patch_then_trace_from_the_port(self):
        """Port-to-port drag in the app's patch view (mouse at d, touch at m) saves one cable; the trace from it reaches the target."""
        for size in SIZES:
            with self.subTest(size=size), self.open(CAMPUS + "patch", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for(pvt.CARDS_JS, 20)
                before = len(doc_of(self.base)["doc"]["cables"])
                src, tgt = self._drag(pg, touch=(size == "m"))
                cable = wait_until(lambda: next((c for c in doc_of(self.base)["doc"]["cables"]
                                                 if {(c["from"].get("device"), c["from"].get("port")), (c["to"].get("device"), c["to"].get("port"))}
                                                 == {(src["device"], src["port"]), (tgt["device"], tgt["port"])}), None), what="the cable on the server")
                self.assertEqual(len(doc_of(self.base)["doc"]["cables"]), before + 1, "exactly one cable is saved")
                self.assertTrue(cable.get("id"))
                pg.shot("reg-patch-" + size)
            with self.subTest(size=size, step="trace"), self.open(CAMPUS + "patch?sel=port:%s:%s" % (src["device"], src["port"]), size) as pg:
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("!!document.querySelector('#app-inspector [data-action=trace]')")
                pg.click("#app-inspector [data-action=trace]")
                pg.wait_for("!!document.querySelector('.trace-backdrop .trace-sheet .trace-hop')")
                devs = pg.js("Array.prototype.map.call(document.querySelectorAll('.trace-sheet .trace-dev'), function (d) { return d.getAttribute('data-device'); })")
                self.assertEqual(devs[0], src["device"], "the trace starts at the patched port's device")
                self.assertIn(tgt["device"], devs, "the new cable is traced to its target")
                pg.shot("reg-trace-" + size)
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.trace-backdrop')")
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def _drag(self, pg, touch: bool):
        src = pg.wait_for(pvt.SOURCE_JS)
        sx, sy = src["x"], src["y"]

        def send(kind, x, y):
            if touch:
                if kind == "up":
                    pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                else:
                    pg.command("Input.dispatchTouchEvent", {"type": "touchStart" if kind == "down" else "touchMove",
                                                            "touchPoints": [{"x": x, "y": y, "id": 1}]})
            else:
                typ = {"down": "mousePressed", "move": "mouseMoved", "up": "mouseReleased"}[kind]
                p = {"type": typ, "x": x, "y": y, "button": "left", "buttons": 0 if kind == "up" else 1}
                if kind != "move":
                    p["clickCount"] = 1
                pg.command("Input.dispatchMouseEvent", p)

        if not touch:
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx, "y": sy})
        send("down", sx, sy)
        for i in range(1, 6):
            send("move", sx + 4 * i, sy + 3 * i)
        pg.wait_for("document.querySelector('.pv-root').classList.contains('pv-connecting')", 5)
        tgt = pg.wait_for(pvt.TARGET_JS % (q(sx), q(sy), q(src["device"])), 5)
        cx, cy = sx + 20, sy + 15
        for i in range(1, 9):
            send("move", cx + (tgt["x"] - cx) * i / 8.0, cy + (tgt["y"] - cy) * i / 8.0)
        time.sleep(0.05)
        send("up", tgt["x"], tgt["y"])
        pg.wait_for("!document.querySelector('.pv-root').classList.contains('pv-connecting')", 5)
        return src, tgt

    # ------------------------------------------------------------ public device page (QR target)

    def test_qr_device_page_and_share_token_on_the_rack_link(self):
        token = api(self.base, "POST", "/api/v2/projects/%s/shares" % PROJECT, {"label": "reg"})["share"]["token"]
        cases = [("/p/%s/d/ulxd-main" % PROJECT, ""), ("/p/%s/d/ulxd-main?share=%s" % (PROJECT, token), token),
                 ("/p/%s/d/ulxd-main?share=sh-not-a-token" % PROJECT, ""), ("/s/%s/d/ulxd-main" % token, token)]
        for size in SIZES:
            for path, want in cases:
                with self.subTest(size=size, path=path), self.open(path, size) as pg:
                    self.assertEqual(pg.smoke["errors"], [])
                    self.assertEqual(pg.js("document.querySelector('h1').textContent.trim()"), "Wireless RX 1-4")
                    self.assertTrue(pg.js("!!document.querySelector('svg')"), "the QR code is drawn")
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    href = pg.js("document.querySelector('a[data-rack=rk-foh]').getAttribute('href')")
                    self.assertEqual(href, "../rk/rk-foh" + ("?share=" + want if want else ""), "the rack link carries only a valid share token")
                    if path.startswith("/s/") or not want:
                        pg.shot("reg-qr-device-%s%s" % (size, "-share" if want else ""))
                        pg.click("a[data-rack=rk-foh]")
                        pg.wait_for("/\\/rk\\/rk-foh/.test(location.pathname) && document.readyState === 'complete' && !!document.querySelector('h1')")
                        self.assertEqual(pg.js("document.querySelector('h1').textContent.trim()"), "FOH rack")
                        self.assertTrue(pg.js("!!document.querySelector('a[href*=\"/d/ulxd-main\"]')"), "the rack page lists the device")
                        if want:
                            self.assertTrue(pg.js("location.pathname.indexOf('/s/%s/') === 0" % token), "the share link stays inside /s/<token>/")

    # ------------------------------------------------------------ service worker

    def test_service_worker_precache_entries_are_served_and_cached(self):
        version = sw_version()
        entries = precache_entries()
        self.assertTrue(version and len(entries) > 70)
        self.assertEqual(len(entries), len(set(entries)), "no duplicate precache entries")
        for mod in ("rack-elevation.js", "rack-display.js", "rack-display-core.js", "rack-palette.js", "rack-palette-core.js",
                    "rack-export.js", "rack-export-core.js"):
            self.assertIn("static/js/" + mod, entries)
        for css in ("rack-toolbar.css", "rack-palette.css", "rack-export.css", "page-rack.css"):
            self.assertIn("static/css/" + css, entries)
        self.assertFalse([e for e in entries if "rack-images" in e], "rack images are not precached")
        for entry in entries:
            with self.subTest(entry=entry):
                if entry in PENDING and not (ROOT / "fathom" / entry).is_file():
                    self.skipTest(PENDING[entry])
                with urllib.request.urlopen(urljoin(self.base + "/", entry), timeout=30) as r:
                    self.assertEqual(r.status, 200, entry)
        img_path = next("/" + rel for rel in (p.relative_to(ROOT / "fathom").as_posix()
                                              for p in sorted((ROOT / "fathom" / "static" / "rack-images").rglob("*.webp")))
                        if "/_" not in rel)
        for size in SIZES:
            with self.subTest(size=size), self.open(CAMPUS + "racks", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                got = pg.js("""navigator.serviceWorker.ready.then(function (reg) {
                  return new Promise(function (r) { setTimeout(r, 1000); }).then(function () { return caches.keys(); }).then(function (keys) {
                    return {active: !!reg.active, scope: reg.scope, keys: keys};
                  });
                })""")
                self.assertTrue(got["active"], got)
                self.assertEqual(got["scope"], self.base + "/")
                self.assertIn("fathom-shell-" + version, got["keys"])
                cached = pg.js("caches.open(%s).then(function (c) { return c.keys(); }).then(function (k) { return k.map(function (r) { return new URL(r.url).pathname; }); })"
                               % q("fathom-shell-" + version))
                missing = [e for e in entries if urlparse(urljoin(self.base + "/", e)).path not in cached
                           and not (e in PENDING and not (ROOT / "fathom" / e).is_file())]
                self.assertEqual(missing, [], "every precache entry is in the shell cache after install")
                status = pg.js("fetch(%s).then(function (r) { return r.status; })" % q(img_path))
                self.assertEqual(status, 200)
                pg.wait_for("caches.open('fathom-images-1').then(function (c) { return c.match(%s); }).then(function (m) { return !!m; })" % q(self.base + img_path))
                in_shell = pg.js("caches.open(%s).then(function (c) { return c.match(%s); }).then(function (m) { return !!m; })"
                                 % (q("fathom-shell-" + version), q(self.base + img_path)))
                self.assertFalse(in_shell, "rack images use their own runtime cache")

    # ------------------------------------------------------------ CSV import + build

    def test_csv_import_places_a_racked_device_and_the_build_writes_rack_files(self):
        for size, u in (("d", 3), ("m", 4)):
            name = "REG CSV player %s" % size
            csv_text = "name,kind,manufacturer,model,rack,ru\r\n%s,other,Acme,P1,rk-foh,%d\r\n" % (name, u)
            with self.subTest(size=size, step="import"), self.open(CAMPUS + "imports", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg, "imports")
                card = ".adm-card[data-importer=csv]"
                pg.wait_for("!!document.querySelector(%s)" % q(card + " input[type=file]"))
                pg.js("""(function (sel, text) {
                  var inp = document.querySelector(sel), dt = new DataTransfer();
                  dt.items.add(new File([text], 'reg-devices.csv', {type: 'text/csv'}));
                  inp.files = dt.files; inp.dispatchEvent(new Event('change', {bubbles: true})); return inp.files.length;
                })(%s, %s)""" % (q(card + " input[type=file]"), q(csv_text)))
                pg.js("Array.prototype.filter.call(document.querySelectorAll(%s), function (b) { return /^(Preview|Import)$/.test(b.textContent); })[0].click()"
                      % q(card + " button"))
                pg.wait_for("!!document.querySelector(%s)" % q(card + " .adm-apply"), 20)
                chips = pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (c) { return c.textContent; })" % q(card + " .imp-sum .chip"))
                self.assertIn("create 1", chips)
                pg.shot("reg-csv-preview-" + size)
                pg.click(card + " .adm-apply")
                dev = wait_until(lambda: next((d for d in doc_of(self.base)["doc"]["devices"] if d.get("name") == name), None), what="the imported device")
                self.assertEqual((dev.get("rack") or {}).get("id"), "rk-foh")
                self.assertEqual((dev.get("rack") or {}).get("u"), u)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])
            with self.subTest(size=size, step="build"), self.open(CAMPUS + "builds", size) as pg:
                view_ready(pg, "builds")
                pg.wait_for("!!document.getElementById('bld-go')")
                pg.js("['bld-pdf', 'bld-png'].forEach(function (id) { var b = document.getElementById(id); if (b) b.checked = false; }); 1")
                known = {b["name"] for b in api(self.base, "GET", "/api/v2/projects/%s/builds" % PROJECT).get("builds") or []}
                pg.click("#bld-go")
                build = wait_until(lambda: next((b for b in api(self.base, "GET", "/api/v2/projects/%s/builds" % PROJECT).get("builds") or []
                                                 if b["name"] not in known), None), 120, "the new build")
                pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=%s]')" % q(build["name"]), 120)
                build = next(b for b in api(self.base, "GET", "/api/v2/projects/%s/builds" % PROJECT)["builds"] if b["name"] == build["name"])
                files = set(build.get("files") or [])
                for rk in ("rk-foh", "rk-amp", "rk-bcast"):
                    for suffix in ("-front.svg", "-rear.svg", ".svg", ".html"):
                        self.assertIn("racks/" + rk + suffix, files)
                html = urllib.request.urlopen("%s/builds/%s/%s/racks/rk-foh.html" % (self.base, PROJECT, build["name"]), timeout=30).read().decode("utf-8")
                self.assertIn(name, html, "the rack page of the build lists the CSV-imported device")
                pg.shot("reg-build-" + size)

    # ------------------------------------------------------------ history

    def test_history_lists_a_rack_edit_and_restore_undoes_it(self):
        for size in SIZES:
            with self.subTest(size=size):
                start = doc_of(self.base)["revision"]
                self.assertEqual(device(self.base, "ulxd-main")["rack"]["u"], 10)
                with self.open(CAMPUS + "racks", size) as pg:
                    self.assertEqual(pg.smoke["errors"], [])
                    blk = ".rk-block[data-device=ulxd-main]"
                    pg.wait_for("!!document.querySelector(%s)" % q(blk))
                    pg.js("document.querySelector(%s).focus(); 1" % q(blk))
                    pg.press("ArrowUp")
                    wait_until(lambda: device(self.base, "ulxd-main")["rack"]["u"] == 11, what="the rack move on the server")
                edit = doc_of(self.base)["revision"]
                self.assertGreater(edit, start)
                with self.open(CAMPUS + "history", size) as pg:
                    view_ready(pg, "history")
                    row = "tr.dt-row[data-id=\"%d\"]" % edit
                    pg.wait_for("!!document.querySelector(%s)" % q(row), 20)
                    summary = pg.js("document.querySelector(%s).textContent" % q(row + " td[data-col=summary]"))
                    self.assertTrue(summary.strip(), "the rack edit has a summary")
                    pg.shot("reg-history-" + size)
                    restore = ("Array.prototype.filter.call(document.querySelectorAll(%s), function (b) { return b.textContent === 'Restore'; })[0]"
                               % q("tr.dt-row[data-id=\"%d\"] .adm-acts button" % start))
                    pg.wait_for("!!(%s)" % restore)
                    pg.js(restore + ".click()")
                    pg.wait_for("!!document.querySelector('.app-dialog footer button.primary')")
                    self.assertIn("Restore revision %d?" % start, pg.js("document.querySelector('.app-dialog').textContent"))
                    pg.click(".app-dialog footer button.primary")
                    wait_until(lambda: device(self.base, "ulxd-main")["rack"]["u"] == 10, what="the restored placement")
                    restored = doc_of(self.base)["revision"]
                    self.assertGreater(restored, edit, "restore creates a new revision")
                    pg.wait_for("!!document.querySelector(%s)" % q("tr.dt-row[data-id=\"%d\"]" % restored), 20)
                    self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    # ------------------------------------------------------------ harness

    def test_rack_harness_walkthrough(self):
        for size in SIZES:
            with self.subTest(size=size), self.open("/static/dev/rack.html?walk=1", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                walk = json.loads(pg.wait_for("document.documentElement.getAttribute('data-walk')", 30))
                self.assertTrue(walk.get("ok"), "rack harness walkthrough: %s" % walk)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])
                pg.shot("reg-harness-" + size)


class RackRegressionViewer(UiCase):
    """A login-on server: a viewer sees racks read-only and the server refuses the viewer's rack writes."""

    PASSWORD = "viewer1-password-1"

    @classmethod
    def setUpClass(cls) -> None:
        super(RackRegressionViewer, cls).setUpClass()
        from fathom import users

        users.add_user("admin1", "admin1-password-1", role="admin")
        users.add_user("viewer1", cls.PASSWORD, role="viewer")

    def signed_in(self, path: str, size: str):
        from fathom import users

        cookie = users.make_session(users.get_user("viewer1"))
        cm = self.open("/login", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        pg.command("Network.enable")
        pg.command("Network.setCookie", {"name": "fathom_session", "value": cookie, "url": self.base + "/", "httpOnly": True, "sameSite": "Lax"})
        pg.goto(path)
        return pg

    def server_rack_u(self, dev_id: str) -> int:
        import base64

        auth = "Basic " + base64.b64encode(("viewer1:" + self.PASSWORD).encode()).decode()
        body = api(self.base, "GET", "/api/v2/projects/" + PROJECT, headers={"Authorization": auth})
        return next(d for d in body["doc"]["devices"] if d["id"] == dev_id)["rack"]["u"]

    def test_racks_are_read_only_for_a_viewer(self):
        for size in SIZES:
            with self.subTest(size=size, view="landing"):
                pg = self.signed_in("/" + CAMPUS + "racks", size)
                view_ready(pg, "racks")
                blk = ".rk-block[data-device=ulxd-main]"
                pg.wait_for("!!document.querySelector(%s)" % q(blk))
                st = pg.js("""({add: (function (b) { return !b || b.disabled || b.hidden; })(document.getElementById('rk-add')),
                  grips: document.querySelectorAll('#rk-unracked .rk-grip').length,
                  addbtns: Array.prototype.filter.call(document.querySelectorAll('#rk-unracked .rk-addbtn'), function (b) { return !b.disabled; }).length})""")
                self.assertEqual(st, {"add": True, "grips": 0, "addbtns": 0})
                y0 = pg.rect(blk)["top"]
                pg.js("document.querySelector(%s).focus(); 1" % q(blk))
                pg.press("ArrowUp")
                pg.press("Delete")
                pg.js("new Promise(function (r) { setTimeout(r, 600); })")
                self.assertTrue(pg.js("!!document.querySelector(%s)" % q(blk)), "Delete does not unrack for a viewer")
                self.assertEqual(pg.rect(blk)["top"], y0, "ArrowUp does not move a block for a viewer")
                self.assertEqual(self.server_rack_u("ulxd-main"), 10)
                rev = pg.js("fetch('api/v2/projects/%s').then(function (r) { return r.json(); }).then(function (j) { return j.revision; })" % PROJECT)
                status = pg.js("""fetch('api/v2/projects/%s/changes', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Fathom': '1'},
                  body: JSON.stringify({base_revision: %d, summary: 'viewer rack edit', ops: [{op: 'merge', coll: 'racks', id: 'rk-foh', value: {name: 'Hacked'}}]})
                }).then(function (r) { return r.status; })""" % (PROJECT, rev))
                self.assertEqual(status, 403)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])
                pg.shot("reg-viewer-racks-" + size)
            with self.subTest(size=size, view="rack page"):
                pg.goto(CAMPUS + "racks/rk-foh/elevation")
                pg.wait_for("!!document.querySelector('header.eh .eh-tab[aria-selected=true][data-tab=elevation]')")
                pg.wait_for("!!document.querySelector('.rk-block[data-device=ulxd-main]')")
                self.assertFalse(pg.js("!!document.querySelector('.rp-add')"), "no Add device for a viewer")
                self.assertFalse(pg.js("!!document.querySelector('.eh-more [data-action=delete], .eh-menu [data-action=delete]')"))
                self.assertEqual(pg.js("(document.querySelector('.eh-action[data-action=edit]') || {}).textContent || 'Details'"), "Details",
                                 "the header offers Details, not Edit")
            with self.subTest(size=size, view="public rack page"):
                pg.goto("/p/%s/rk/rk-foh" % PROJECT)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.querySelectorAll('form, input, textarea, select').length"), 0)
                self.assertLessEqual(pg.page_hscroll(), 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
