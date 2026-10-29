"""PAGE (docs/SPEC.md §6.7.3): the rack entity page ``racks/<id>/<tab>[/front|rear|both]``.

Overview cards carry the rack totals (U used/free, weight against the max load, power against the
circuit limit, devices, accessories) and warn when a limit is exceeded; library template weights
arrive through ``loadTemplateInfo``. The ``accessories`` tab is a DataTable of ``rack.items`` with
inline label and U edits, delete and Add accessory. The elevation takes ``/both`` plus the display
and annotation controls (``fathom.ui.rack.display`` / ``.annotate``). The header ⋯ menu links the
public viewer page, opens the QR dialog (and explains a 409 ``no_public_url``), exports and
duplicates the rack. Viewers get no edit controls, and at d no ⋯ (export, viewer page and QR sit in
the header bar). Runs at d (widened to 1440×900) and m (390×844).

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_ui_rk_page.py -v``.
Skips without Chrome; ``$FATHOM_UI_SHOTS`` collects ``page-*.png``.
"""
from __future__ import annotations

import json
import time
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

PROJECT = "campus-demo"
CAMPUS = "#/campus-demo/main/"
PAGE = CAMPUS + "racks/rk-foh"
SIZES = ("d", "m")
QR_PATH = "/api/v2/projects/campus-demo/qr/rack/rk-foh.svg"

# rk-foh: 40 kg empty, 45 kg max, 200 W circuit; two accessories (a blank at U3 and a 1.5 kg
# shelf at U4). With 3 + 4 kg of devices it weighs 48.5 kg (over) and draws 230 W (over).
SEED = [
    {"op": "merge", "coll": "racks", "id": "rk-foh", "value": {
        "weight_kg": 40, "max_load_kg": 45, "power_limit_w": 200, "width_in": 19, "form_factor": "four_post", "row": "FOH row",
        "items": [{"id": "ri-1", "type": "blank", "u": 3}, {"id": "ri-2", "type": "shelf", "u": 4, "slots": 2, "weight_kg": 1.5}]}},
    {"op": "merge", "coll": "devices", "id": "ulxd-main", "value": {"weight_kg": 3}},
    {"op": "merge", "coll": "devices", "id": "switcher", "value": {"weight_kg": 4, "power_w": 150}},
    {"op": "merge", "coll": "devices", "id": "ctrl-main", "value": {"power_w": 80}},
]


def q(s: str) -> str:
    return json.dumps(s)


def api(base: str, method: str, path: str, body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Fathom": "1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def seed(base: str, ops: list) -> None:
    rev = api(base, "GET", "/api/v2/projects/" + PROJECT)["revision"]
    api(base, "POST", "/api/v2/projects/%s/changes" % PROJECT, {"base_revision": rev, "summary": "PAGE test seed", "ops": ops})


def wide(pg) -> None:
    """Widen the d page to 1440×900 (lg layout); m stays 390×844."""
    if pg.size == "d":
        pg.command("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        pg.wait_for("window.innerWidth === 1440")


def page_ready(pg, tab: str) -> None:
    pg.wait_for("!!document.querySelector('header.eh .eh-tab[aria-selected=true][data-tab=%s]')" % tab)
    pg.wait_for("!!document.querySelector('.rp-panel[data-tab=%s]')" % tab)


def card(pg, key: str) -> dict:
    return pg.js("""(function (c) { return c ? {n: c.querySelector('.rp-card-n').textContent, text: c.textContent, level: c.getAttribute('data-level'),
      tag: c.tagName.toLowerCase(), href: c.getAttribute('href') || ''} : null; })(document.querySelector('.rp-card[data-card=%s]'))""" % key)


def open_menu(pg) -> None:
    pg.click(".eh-more")
    pg.wait_for("!document.querySelector('.eh-menu').hidden")


class RackPageUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(RackPageUi, cls).setUpClass()
        seed(cls.base, SEED)

    def ready(self, pg, what: str) -> None:
        self.assertEqual(pg.smoke["errors"], [], "errors on %s" % what)

    def test_overview_cards_show_totals_and_the_over_limit_warning(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(PAGE + "/overview", size) as pg:
                self.ready(pg, "rack overview at " + size)
                wide(pg)
                page_ready(pg, "overview")
                keys = pg.js("Array.prototype.map.call(document.querySelectorAll('.rp-card'), function (c) { return c.getAttribute('data-card'); })")
                self.assertEqual(keys, ["used", "free", "weight", "power", "devices", "accessories", "cables", "problems"])
                self.assertEqual(card(pg, "used")["n"], "7", "5 devices on U1, U6, U8, U10, U12 + the blank and the shelf")
                self.assertIn("of 12 U", card(pg, "used")["text"])
                self.assertEqual(card(pg, "free")["n"], "5")
                w = card(pg, "weight")
                self.assertEqual((w["n"], w["level"]), ("48.5", "warn"), "40 + 3 + 4 + 1.5 kg against a 45 kg max")
                self.assertIn("3.5 kg over the max", w["text"])
                p = card(pg, "power")
                self.assertEqual((p["n"], p["level"]), ("230", "warn"))
                self.assertIn("W of 200 limit", p["text"])
                self.assertIn("30 W over the limit", p["text"])
                self.assertEqual(card(pg, "devices")["n"], "5")
                acc = card(pg, "accessories")
                self.assertEqual(acc["n"], "2")
                self.assertTrue(acc["href"].endswith("/racks/rk-foh/accessories"), acc["href"])
                self.assertTrue(pg.js("getComputedStyle(document.querySelector('.rp-card[data-card=weight]')).borderTopColor !== "
                                      "getComputedStyle(document.querySelector('.rp-card[data-card=devices]')).borderTopColor"),
                                "the over-limit cards are styled (page-rack.css loaded)")
                badges = pg.js("Array.prototype.map.call(document.querySelectorAll('header.eh .eh-badge'), function (b) { return b.textContent; })")
                self.assertIn("Over max load", " ".join(badges))
                self.assertIn("Over power limit", " ".join(badges))
                facts = pg.js("""(function () { var o = {}; Array.prototype.forEach.call(document.querySelectorAll('.eh-fact[data-fact]'),
                  function (f) { o[f.getAttribute('data-fact')] = f.querySelector('dd').textContent; }); return o; })()""")
                self.assertEqual(facts.get("width"), "19\u2033")
                self.assertEqual(facts.get("form"), "4-post")
                self.assertEqual(facts.get("row"), "FOH row")
                self.assertEqual(pg.js("document.querySelector('.eh-tab[data-tab=accessories] .eh-count').textContent"), "2")
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll at " + size)
                pg.shot("page-overview-" + size)
                pg.click(".rp-card[data-card=accessories]")
                pg.wait_for("location.hash === %r" % (PAGE + "/accessories"))
                page_ready(pg, "accessories")

    def test_template_weights_come_from_the_library(self):
        with self.open(CAMPUS + "racks/rk-amp/overview", "d") as pg:
            self.ready(pg, "rk-amp overview")
            page_ready(pg, "overview")
            pg.wait_for("document.querySelector('.rp-card[data-card=weight] .rp-card-n').textContent === '13.5'")
            self.assertEqual(card(pg, "power")["n"], "120", "power_w of the catalog/library templates")
            self.assertEqual(card(pg, "weight")["level"], None, "no max load set: no warning")

    def test_elevation_both_route_and_display_controls(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(PAGE + "/elevation/both", size) as pg:
                self.ready(pg, "elevation/both at " + size)
                wide(pg)
                page_ready(pg, "elevation")
                pg.js("new Promise(function (r) { setTimeout(r, 300); })")
                self.assertTrue(pg.hash.endswith("/racks/rk-foh/elevation/both"), "both is a canonical sub: " + pg.hash)
                self.assertTrue(pg.js("!!document.querySelector('.rp-face[data-face=both][aria-current]')"))
                self.assertTrue(pg.js("!!document.querySelector('.rp-elev[data-face=both] .rk-slots[data-rack=rk-foh]')"))
                faces = pg.js("Array.prototype.map.call(document.querySelectorAll('.rp-face'), function (a) { return [a.getAttribute('data-face'), a.hash]; })")
                self.assertEqual([f[0] for f in faces], ["front", "rear", "both"])
                self.assertTrue(faces[0][1].endswith("/racks/rk-foh/elevation"), faces[0][1])
                self.assertTrue(faces[2][1].endswith("/racks/rk-foh/elevation/both"), faces[2][1])
                self.assertTrue(pg.js("document.querySelector('.eh-tab[data-tab=elevation]').hash.endsWith('/elevation/both')"),
                                "the tab link keeps the face")
                pg.click(".rp-display-opt[data-display=image]")
                pg.wait_for("document.querySelector('.rp-display-opt[data-display=image]').getAttribute('aria-pressed') === 'true'")
                self.assertEqual(pg.js("localStorage.getItem('fathom.ui.rack.display')"), "image")
                self.assertFalse(pg.js("!!document.querySelector('.rp-bar select')"), "no form field for a view option")
                pg.click(".rp-ann-btn")
                pg.wait_for("!document.getElementById('rp-ann-menu').hidden")
                self.assertEqual(pg.js("document.activeElement.getAttribute('data-annotate')"), "", "focus starts on the current option")
                pg.press("Escape")
                pg.wait_for("document.getElementById('rp-ann-menu').hidden")
                self.assertTrue(pg.js("document.activeElement.classList.contains('rp-ann-btn')"))
                pg.click(".rp-ann-btn")
                pg.wait_for("!document.getElementById('rp-ann-menu').hidden")
                if size == "m":
                    self.assertGreaterEqual(pg.rect(".rp-ann-opt[data-annotate=model]")["height"], 44)
                    self.assertGreaterEqual(pg.rect(".rp-ann-btn")["height"], 44)
                pg.click(".rp-ann-opt[data-annotate=model]")
                pg.wait_for("document.getElementById('rp-ann-menu').hidden")
                self.assertEqual(pg.js("localStorage.getItem('fathom.ui.rack.annotate')"), "model")
                self.assertEqual(pg.js("document.querySelector('.rp-ann-value').textContent"), "Model")
                if size == "d":
                    opts = pg.js("""(function () { var s = document.querySelector('.rp-elev .rk-slots'); return !!s; })()""")
                    self.assertTrue(opts)
                pg.shot("page-elevation-both-" + size)
                pg.reload()
                self.ready(pg, "reload")
                page_ready(pg, "elevation")
                self.assertEqual(pg.js("document.querySelector('.rp-display-opt[data-display=image]').getAttribute('aria-pressed')"), "true")
                self.assertEqual(pg.js("document.querySelector('.rp-ann-value').textContent"), "Model")
                self.assertEqual(pg.js("document.querySelector('.rp-ann-opt[aria-checked=true]').getAttribute('data-annotate')"), "model")
                pg.click(".rp-face[data-face=rear]")
                pg.wait_for("/\\/racks\\/rk-foh\\/elevation\\/rear$/.test(location.hash)")
                pg.wait_for("!!document.querySelector('.rp-elev[data-face=rear] .rk-slots[data-face=rear]')")
                pg.click(".rp-face[data-face=front]")
                pg.wait_for("/\\/racks\\/rk-foh\\/elevation$/.test(location.hash)")
                self.assertLessEqual(pg.page_hscroll(), 0)

    def test_viewer_link_and_qr_dialog(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(PAGE + "/overview", size) as pg:
                self.ready(pg, "rack overview at " + size)
                wide(pg)
                page_ready(pg, "overview")
                open_menu(pg)
                items = pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-menu .eh-menu-item'), function (a) { return a.getAttribute('data-action'); })")
                for k in ("export", "viewer", "qr", "duplicate", "delete"):
                    self.assertIn(k, items)
                viewer = pg.js("document.querySelector('.eh-menu [data-action=viewer]').href")
                self.assertEqual(viewer, self.base + "/p/campus-demo/rk/rk-foh")
                self.assertEqual(pg.js("document.querySelector('.eh-menu [data-action=viewer]').target"), "_blank")
                pg.click(".eh-menu [data-action=qr]")
                pg.wait_for("!!document.querySelector('.app-dialog .rp-qr-img[src]')")
                self.assertEqual(pg.js("document.querySelector('.rp-qr-img').getAttribute('src')"), self.base + QR_PATH)
                pg.wait_for("document.querySelector('.rp-qr-img').naturalWidth > 0")
                pg.wait_for("!document.querySelector('.rp-qr-print').disabled")
                self.assertEqual(pg.js("document.querySelector('.rp-qr-url a').href"), viewer)
                self.assertEqual(pg.offscreen(".app-dialog", "x"), 0, "the QR dialog fits at " + size)
                pg.shot("page-qr-" + size)
                pg.js("window.__printed = 0; window.print = function () { window.__printed++; }; 1")
                pg.click(".rp-qr-print")
                self.assertEqual(pg.js("window.__printed"), 1)
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.app-dialog')")
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def test_qr_without_a_public_url_explains_it(self):
        with self.open(PAGE + "/overview", "m", intercepts=[(QR_PATH, 409, {
                "error": "no public URL is known (set settings.public_url or FATHOM_PUBLIC_URL)", "code": "no_public_url"})]) as pg:
            page_ready(pg, "overview")
            open_menu(pg)
            pg.click(".eh-menu [data-action=qr]")
            pg.wait_for("!!document.querySelector('.app-dialog .rp-qr-err')")
            self.assertIn("public URL", pg.js("document.querySelector('.rp-qr-err').textContent"))
            self.assertTrue(pg.js("document.querySelector('.rp-qr-img').hidden"))
            self.assertTrue(pg.js("document.querySelector('.rp-qr-print').disabled"))
            pg.shot("page-qr-409-m")

    def test_unknown_face_is_replaced(self):
        with self.open(PAGE + "/elevation/side", "d") as pg:
            pg.wait_for("location.hash === %r" % (PAGE + "/elevation"))
            page_ready(pg, "elevation")


class RackPageEdits(UiCase):
    """Accessory edits and duplicate change the doc, so they run on their own server."""

    @classmethod
    def setUpClass(cls) -> None:
        super(RackPageEdits, cls).setUpClass()
        seed(cls.base, SEED)

    def server_rack(self, rack_id: str) -> dict:
        doc = api(self.base, "GET", "/api/v2/projects/" + PROJECT)["doc"]
        return next(r for r in doc["racks"] if r["id"] == rack_id)

    def wait_server(self, fn, what: str, timeout: float = 15.0):
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            last = fn()
            if last:
                return last
            time.sleep(0.2)
        self.fail("timed out waiting for the server: %s (last %r)" % (what, last))

    def items_of(self, rack_id: str) -> dict:
        return {it["id"]: it for it in self.server_rack(rack_id).get("items") or []}

    def test_accessories_tab_edit_at_desktop(self):
        with self.open(PAGE + "/accessories", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            wide(pg)
            page_ready(pg, "accessories")
            pg.wait_for("document.querySelectorAll('.rp-accessories tr.dt-row').length === 2")
            rows = pg.js("""Array.prototype.map.call(document.querySelectorAll('.rp-accessories tr.dt-row'), function (r) {
              return [r.getAttribute('data-id'), r.textContent]; })""")
            self.assertEqual([r[0] for r in rows], ["ri-2", "ri-1"], "top of the rack first")
            self.assertIn("Shelf", rows[0][1])
            self.assertIn("0 / 2 used", rows[0][1])
            self.assertIn("1.5 kg", rows[0][1])
            headers = pg.js("Array.prototype.map.call(document.querySelectorAll('.rp-accessories th'), function (t) { return t.textContent.trim(); })")
            for col in ("U", "Type", "Label", "Face", "Depth", "Slots", "Weight"):
                self.assertTrue(any(hd.startswith(col) for hd in headers), (col, headers))
            pg.shot("page-accessories-d")

            lab = "tr.dt-row[data-id=ri-1] input.rp-acc-label"
            pg.js("var i = document.querySelector(%s); i.value = 'Top blank'; i.dispatchEvent(new Event('change', {bubbles: true})); 1" % q(lab))
            self.wait_server(lambda: self.items_of("rk-foh")["ri-1"].get("label") == "Top blank", "label saved")
            pg.wait_for("document.querySelector(%s).value === 'Top blank'" % q(lab))

            u = "tr.dt-row[data-id=ri-1] input.rp-acc-u"
            pg.js("var i = document.querySelector(%s); i.value = '10'; i.dispatchEvent(new Event('change', {bubbles: true})); 1" % q(u))
            pg.wait_for("document.querySelector(%s).value === '3'" % q(u))
            pg.wait_for("Array.prototype.some.call(document.querySelectorAll('.app-toast, [role=status], [role=alert]'), function (t) { return /does not fit at U10/.test(t.textContent); })")
            pg.js("var i = document.querySelector(%s); i.value = '2'; i.dispatchEvent(new Event('change', {bubbles: true})); 1" % q(u))
            self.wait_server(lambda: self.items_of("rk-foh")["ri-1"].get("u") == 2, "blank moved to U2")

            pg.js("var s = document.getElementById('rp-acc-type'); s.value = 'vent'; s.dispatchEvent(new Event('change')); 1")
            pg.click(".rp-acc-add")
            pg.wait_for("document.querySelectorAll('.rp-accessories tr.dt-row').length === 3")
            pg.wait_for("document.querySelector('.eh-tab[data-tab=accessories] .eh-count').textContent === '3'")
            added = self.wait_server(lambda: self.items_of("rk-foh").get("ri-3"), "vent added")
            self.assertEqual((added["type"], added["u"]), ("vent", 11), "first fit from the top (U12 holds the full-depth switch)")
            pg.click("tr.dt-row[data-id=ri-3] .rp-acc-del")
            pg.wait_for("document.querySelectorAll('.rp-accessories tr.dt-row').length === 2")
            self.wait_server(lambda: "ri-3" not in self.items_of("rk-foh"), "vent deleted")
            self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def test_accessories_tab_at_phone(self):
        with self.open(CAMPUS + "racks/rk-bcast/accessories", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            page_ready(pg, "accessories")
            self.assertTrue(pg.js("!!document.querySelector('.rp-accessories .dt-empty, .rp-accessories .fb-empty, .rp-accessories [class*=empty]')"),
                            "an empty rack shows the empty state")
            pg.js("var s = document.getElementById('rp-acc-type'); s.value = 'shelf'; s.dispatchEvent(new Event('change')); 1")
            pg.click(".rp-acc-add")
            pg.wait_for("document.querySelectorAll('.rp-accessories tr.dt-row, .rp-accessories .dt-card').length >= 1")
            item = self.wait_server(lambda: self.items_of("rk-bcast").get("ri-1"), "shelf added")
            self.assertEqual(item["type"], "shelf")
            lab = ".rp-accessories input.rp-acc-label[data-item=ri-1]"
            pg.wait_for("!!document.querySelector(%s)" % q(lab))
            h = pg.js("document.querySelector(%s).getBoundingClientRect().height" % q(lab))
            self.assertGreaterEqual(h, 44, "44 px inputs under a coarse pointer")
            self.assertGreaterEqual(pg.js("document.querySelector('.rp-acc-add').getBoundingClientRect().height"), 44)
            pg.js("var i = document.querySelector(%s); i.value = 'Laptop shelf'; i.dispatchEvent(new Event('change', {bubbles: true})); 1" % q(lab))
            self.wait_server(lambda: self.items_of("rk-bcast")["ri-1"].get("label") == "Laptop shelf", "label saved")
            self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll at 390 px")
            pg.shot("page-accessories-m")

    def test_duplicate_rack_with_devices(self):
        with self.open(CAMPUS + "racks/rk-amp/overview", "d") as pg:
            page_ready(pg, "overview")
            open_menu(pg)
            pg.click(".eh-menu [data-action=duplicate]")
            pg.wait_for("!!document.querySelector('.app-dialog #rp-dup-devices')")
            pg.click(".app-dialog #rp-dup-devices")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("location.hash.indexOf('/racks/rk-amp-room-rack-copy/overview') > 0")
            pg.wait_for("document.querySelector('.eh-title').textContent === 'Amp room rack (copy)'")
            pg.wait_for("document.querySelector('.rp-card[data-card=devices] .rp-card-n').textContent === '5'")
            doc = self.wait_server(lambda: (lambda d: d if any(r["id"] == "rk-amp-room-rack-copy" for r in d["racks"]) else None)(
                api(self.base, "GET", "/api/v2/projects/" + PROJECT)["doc"]), "rack duplicated")
            copies = [d for d in doc["devices"] if (d.get("rack") or {}).get("id") == "rk-amp-room-rack-copy"]
            self.assertEqual(len(copies), 5)
            self.assertEqual(pg.js("window.__fathomErrors || []"), [])


class RackPageViewer(UiCase):
    """A login-on server: a viewer gets the read-only accessories table and no duplicate/delete."""

    PASSWORD = "viewer1-password-1"

    @classmethod
    def setUpClass(cls) -> None:
        super(RackPageViewer, cls).setUpClass()
        from fathom import users

        users.add_user("admin1", "admin1-password-1", role="admin")
        users.add_user("viewer1", cls.PASSWORD, role="viewer")

    def test_viewer_accessories_and_menu(self):
        import base64
        from fathom import users

        auth = "Basic " + base64.b64encode(b"admin1:admin1-password-1").decode()
        rev = json.loads(urllib.request.urlopen(urllib.request.Request(
            self.base + "/api/v2/projects/" + PROJECT, headers={"Authorization": auth}), timeout=10).read().decode())["revision"]
        urllib.request.urlopen(urllib.request.Request(
            self.base + "/api/v2/projects/%s/changes" % PROJECT, method="POST",
            data=json.dumps({"base_revision": rev, "summary": "seed", "ops": SEED}).encode(),
            headers={"Authorization": auth, "Content-Type": "application/json", "X-Fathom": "1"}), timeout=10).read()
        cookie = users.make_session(users.get_user("viewer1"))
        for size in SIZES:
            with self.subTest(size=size):
                cm = self.open("/login", size, ready=False)
                pg = cm.__enter__()
                self.addCleanup(cm.__exit__, None, None, None)
                pg.command("Network.enable")
                pg.command("Network.setCookie", {"name": "fathom_session", "value": cookie, "url": self.base + "/", "httpOnly": True, "sameSite": "Lax"})
                pg.goto("/" + PAGE + "/accessories")
                page_ready(pg, "accessories")
                pg.wait_for("document.querySelectorAll('.rp-accessories tr.dt-row, .rp-accessories .dt-card').length >= 2")
                st = pg.js("""({inputs: document.querySelectorAll('.rp-accessories input.rp-acc-label, .rp-accessories input.rp-acc-u').length,
                  add: !!document.querySelector('.rp-acc-add'), del: document.querySelectorAll('.rp-acc-del').length})""")
                self.assertEqual(st, {"inputs": 0, "add": False, "del": 0})
                if size == "d":
                    self.assertFalse(pg.js("!!document.querySelector('.eh-more')"), "no ⋯ for viewers at lg")
                    items = pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-actions .eh-action'), function (a) { return a.getAttribute('data-action'); })")
                    self.assertEqual(items, ["edit", "print", "export", "viewer", "qr"])
                    self.assertEqual(pg.js("document.querySelector('.eh-action[data-action=viewer]').href"), self.base + "/p/campus-demo/rk/rk-foh")
                else:
                    open_menu(pg)
                    items = pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-menu .eh-menu-item'), function (a) { return a.getAttribute('data-action'); })")
                self.assertIn("viewer", items)
                self.assertIn("qr", items)
                self.assertIn("export", items)
                self.assertNotIn("duplicate", items)
                self.assertNotIn("delete", items)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])


if __name__ == "__main__":
    import unittest
    unittest.main()
