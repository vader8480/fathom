"""Patch view UI (docs/ui-audit.md B.3 PV, B.8) at d, t and m.

Drag patching on the harness with real CDP input (mouse and touch), the one-row toolbar with its View,
Arrange and More popovers, URL state (``filter``, ``q``, ``status``), the context menu links, the empty
room state and read-only hiding. With ``FATHOM_UI_SHOTS`` set it saves ``patch-<d|t|m>.png`` and
``patch-menu-<d|t|m>.png``.

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_ui_pv.py``.
Skips without Chrome.
"""
from __future__ import annotations

import json
import time
import unittest
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/patchview.html"
CAMPUS = "#/campus-demo/main/patch"

PV_IDS = ["pv-add", "pv-fit", "pv-zoom-out", "pv-zoom-in", "pv-undo", "pv-redo", "pv-filter-text",
          "pv-show-unconnected", "pv-show-routes", "pv-all-rooms", "pv-snap", "pv-filter-disc",
          "pv-filter-status", "pv-arrange", "pv-save-arrangement"]
# Visible in the toolbar row itself, per layout.
ROW_WIDE = ["#pv-add", "#pv-fit", "#pv-zoom-out", "#pv-zoom-in", "#pv-undo", "#pv-redo", "#pv-filter-text",
            ".pv-menu-view", ".pv-menu-arrange", ".pv-menu-more"]  # More carries Export at every width (phase5 P5C)
ROW_SM = ["#pv-add", "#pv-fit", ".pv-search-toggle", ".pv-menu-more"]
EXPORT_IDS = ["pv-export-svg", "pv-export-png", "pv-export-pdf", "pv-print"]

VISIBLE_JS = "(function (s) { var e = document.querySelector(s); if (!e) return false; var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })(%s)"
CARDS_JS = "document.querySelectorAll('.pv-card').length > 0"

# Screen point of a port's connection dot ('l' or 'r'), or null when it is outside the canvas.
DOT_JS = """(function (sel, side) {
  var el = document.querySelector(sel); if (!el) return null;
  var d = el.querySelector('.pv-dot-' + side) || el.querySelector('.pv-dot'); if (!d) return null;
  var r = d.getBoundingClientRect(), v = document.querySelector('.pv-viewport').getBoundingClientRect();
  var x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < v.left + 2 || x > v.right - 2 || y < v.top + 2 || y > v.bottom - 2) return null;
  return {x: x, y: y};
})(%s, %s)"""

# A free output port on an editable card whose dot is on screen.
SOURCE_JS = """(function () {
  var v = document.querySelector('.pv-viewport').getBoundingClientRect();
  var ps = document.querySelectorAll('.pv-card:not(.pv-auto):not(.pv-ext) .pv-port.pv-right:not(.pv-conn)');
  for (var i = 0; i < ps.length; i++) {
    var d = ps[i].querySelector('.pv-dot-r'); if (!d) continue;
    var r = d.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x > v.left + 4 && x < v.right - 4 && y > v.top + 4 && y < v.bottom - 4) {
      return {device: ps[i].closest('.pv-card').getAttribute('data-device'), port: ps[i].getAttribute('data-port'), x: x, y: y};
    }
  }
  return null;
})()"""

# While a wire drag is in progress: a highlighted (compatible) free input on screen, nearest first.
TARGET_JS = """(function (sx, sy, src) {
  var v = document.querySelector('.pv-viewport').getBoundingClientRect(), best = null;
  document.querySelectorAll('.pv-port.pv-ok.pv-left:not(.pv-conn)').forEach(function (p) {
    var card = p.closest('.pv-card'); if (!card || card.getAttribute('data-device') === src) return;
    var d = p.querySelector('.pv-dot-l'); if (!d) return;
    var r = d.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < v.left + 4 || x > v.right - 4 || y < v.top + 4 || y > v.bottom - 4) return;
    var el = document.elementFromPoint(x, y);
    if (el && el.closest('.pv-menu, .pv-toolbar')) return;
    var dd = Math.hypot(x - sx, y - sy);
    if (!best || dd < best.d) best = {x: x, y: y, d: dd, device: card.getAttribute('data-device'), port: p.getAttribute('data-port')};
  });
  return best;
})(%s, %s, %s)"""

COUNTS_JS = """({dom: document.querySelectorAll('.pv-wires path[data-cable]').length,
  store: window.__pv.store.doc.cables.length})"""


class PatchViewDrag(UiCase):
    """A.4 #1: port-to-port drag patching (mouse at d, touch at m) creates exactly one cable."""

    def _drag(self, pg, touch):
        pg.wait_for("window.__pv && document.querySelectorAll('.pv-card').length > 0")
        before = pg.js(COUNTS_JS)
        self.assertEqual(before["dom"], before["store"])
        src = pg.wait_for(SOURCE_JS)
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
        tgt = pg.wait_for(TARGET_JS % (json.dumps(sx), json.dumps(sy), json.dumps(src["device"])), 5)
        tx, ty = tgt["x"], tgt["y"]
        cx, cy = sx + 20, sy + 15
        for i in range(1, 9):
            send("move", cx + (tx - cx) * i / 8.0, cy + (ty - cy) * i / 8.0)
        time.sleep(0.05)
        send("up", tx, ty)
        pg.wait_for("(%s).store === %d" % (COUNTS_JS, before["store"] + 1), 5)
        after = pg.wait_for("(function (c) { return c.dom === c.store ? c : null; })(%s)" % COUNTS_JS, 5)
        self.assertEqual(after["store"], before["store"] + 1)
        self.assertEqual(after["dom"], before["dom"] + 1)
        cable = pg.js("window.__pv.store.doc.cables[window.__pv.store.doc.cables.length - 1]")
        ends = {(cable["from"]["device"], cable["from"]["port"]), (cable["to"]["device"], cable["to"]["port"])}
        self.assertEqual(ends, {(src["device"], src["port"]), (tgt["device"], tgt["port"])})
        self.assertFalse(pg.js("document.querySelector('.pv-root').classList.contains('pv-connecting')"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_mouse_drag_patch_at_d(self):
        with self.open(HARNESS, "d") as pg:
            self._drag(pg, touch=False)

    def test_touch_drag_patch_at_m(self):
        with self.open(HARNESS, "m") as pg:
            self._drag(pg, touch=True)


def _post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Fathom": "1"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())


class PatchViewUi(UiCase):
    @classmethod
    def setUpClass(cls):
        super(PatchViewUi, cls).setUpClass()
        doc = json.loads(urllib.request.urlopen(cls.base + "/api/v2/projects/sunday-demo", timeout=10).read().decode())
        room = {"id": "empty-hall", "name": "Empty Hall", "venue": doc["doc"]["rooms"][0].get("venue")}
        _post_json(cls.base + "/api/v2/projects/sunday-demo/changes", {
            "base_revision": doc.get("revision", 0), "summary": "empty room for test_ui_pv",
            "ops": [{"op": "put", "coll": "rooms", "id": "empty-hall", "value": room}]})

    def visible(self, pg, sel):
        return pg.js(VISIBLE_JS % json.dumps(sel))

    def assert_aria(self, pg):
        self.assertEqual(pg.js("document.querySelector('.pv-viewport').getAttribute('role')"), "application")
        self.assertTrue(pg.js("!!document.querySelector('.pv-viewport').getAttribute('aria-label')"))
        self.assertEqual(pg.js("document.querySelector('.pv-toolbar').getAttribute('role')"), "toolbar")
        self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('.pv-card[data-device]'), function (c) { return c.getAttribute('role') === 'group' && !!c.getAttribute('aria-label'); })"))
        self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('.pv-toolbar [aria-haspopup]'), function (b) { return !!document.getElementById(b.getAttribute('aria-controls')); })"))

    def test_toolbar_at_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(CAMPUS, size) as pg:
                pg.wait_for(CARDS_JS)
                if size == "d":
                    self.assert_aria(pg)
                for ident in PV_IDS:
                    self.assertEqual(pg.js("document.querySelectorAll('#%s').length" % ident), 1, "#%s at %s" % (ident, size))
                bar = pg.rect(".pv-toolbar")
                self.assertLessEqual(bar["height"], 56, "toolbar is one row at %s" % size)
                self.assertLessEqual(pg.js("(function (t) { return t.scrollWidth - t.clientWidth; })(document.querySelector('.pv-toolbar'))"), 0)
                self.assertLessEqual(pg.page_hscroll(), 0, "page scrolls horizontally at %s" % size)
                row = ROW_SM if size == "m" else ROW_WIDE
                for sel in row:
                    self.assertTrue(self.visible(pg, sel), "%s visible at %s" % (sel, size))
                    self.assertEqual(pg.offscreen(sel), 0, "%s off-screen at %s" % (sel, size))
                    r = pg.rect(sel)
                    if sel != "#pv-filter-text":
                        floor = 44 if size != "d" else 40
                        self.assertGreaterEqual(r["height"], floor - 0.5, "%s target height at %s" % (sel, size))
                hidden = [".pv-menu-view", ".pv-menu-arrange", "#pv-filter-text", "#pv-zoom-in"] if size == "m" else [".pv-search-toggle"]
                for sel in hidden:
                    self.assertFalse(self.visible(pg, sel), "%s hidden at %s" % (sel, size))
                pg.shot("patch-" + size)

                trigger = ".pv-menu-more" if size == "m" else ".pv-menu-view"
                pop_id = pg.js("document.querySelector(%s).getAttribute('aria-controls')" % json.dumps(trigger))
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-haspopup')" % json.dumps(trigger)), "true")
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-expanded')" % json.dumps(trigger)), "false")
                pg.click(trigger)
                pg.wait_for("document.querySelector(%s).getAttribute('aria-expanded') === 'true'" % json.dumps(trigger))
                self.assertFalse(pg.js("document.getElementById(%s).hidden" % json.dumps(pop_id)))
                inside = ["#pv-show-unconnected", "#pv-show-routes", "#pv-all-rooms", "#pv-snap", "#pv-filter-disc [data-disc]",
                          "#pv-filter-status [data-status]"]
                if size == "m":
                    inside += ["#pv-zoom-out", "#pv-zoom-in", "#pv-undo", "#pv-redo", "#pv-arrange"]
                for sel in inside:
                    self.assertTrue(self.visible(pg, sel), "%s visible in the popover at %s" % (sel, size))
                    self.assertEqual(pg.offscreen(sel), 0, "%s off-screen in the popover at %s" % (sel, size))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pressed = pg.js("document.getElementById('pv-show-routes').getAttribute('aria-pressed')")
                pg.click("#pv-show-routes")
                self.assertNotEqual(pg.js("document.getElementById('pv-show-routes').getAttribute('aria-pressed')"), pressed)
                pg.shot("patch-menu-" + size)
                pg.press("Escape")
                pg.wait_for("document.querySelector(%s).getAttribute('aria-expanded') === 'false'" % json.dumps(trigger))
                self.assertTrue(pg.js("document.getElementById(%s).hidden" % json.dumps(pop_id)))
                self.assertTrue(pg.js("document.activeElement === document.querySelector(%s)" % json.dumps(trigger)),
                                "focus returns to the trigger at %s" % size)
                if size != "m":
                    pg.click(".pv-menu-arrange")
                    self.assertTrue(self.visible(pg, "#pv-arrange"))
                    pg.click(".pv-menu-view")
                    self.assertFalse(self.visible(pg, "#pv-arrange"), "opening View closes Arrange")
                    pg.js("document.querySelector('.pv-viewport').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))")
                    self.assertFalse(pg.js("!!document.querySelector('.pv-pop-wrap.pv-open')"), "outside press closes the popover")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_url_filter_state(self):
        with self.open(CAMPUS + "?q=cl5", "d") as pg:
            pg.wait_for(CARDS_JS)
            self.assertEqual(pg.js("document.getElementById('pv-filter-text').value"), "cl5")
            pg.wait_for("!document.querySelector('.pv-card[data-device=foh-cl5]').classList.contains('pv-dim')")
            self.assertTrue(pg.js("document.querySelector('.pv-card[data-device=vox-1]').classList.contains('pv-dim')"))
            pg.reload()
            pg.wait_for(CARDS_JS)
            self.assertEqual(pg.js("document.getElementById('pv-filter-text').value"), "cl5", "?q survives a reload")
            hl = pg.js("history.length")
            pg.js("(function (i) { i.focus(); i.value = 'ulxd'; i.dispatchEvent(new Event('input', {bubbles: true})); })(document.getElementById('pv-filter-text'))")
            pg.wait_for("location.hash.indexOf('q=ulxd') > 0", 5)
            pg.click(".pv-menu-view")
            pg.click("#pv-filter-disc [data-disc=audio]")
            pg.wait_for("location.hash.indexOf('filter=audio') > 0", 5)
            pg.click("#pv-filter-status [data-status=installed]")
            pg.wait_for("location.hash.indexOf('status=installed') > 0", 5)
            self.assertEqual(pg.js("history.length"), hl, "filter changes use replaceState")
            self.assertEqual(pg.js("document.querySelector('.pv-menu-view .pv-menu-n').textContent"), "2")
            pg.press("Escape")
            pg.reload()
            pg.wait_for(CARDS_JS)
            self.assertEqual(pg.js("document.querySelector('#pv-filter-disc [data-disc=audio]').getAttribute('aria-pressed')"), "true")
            self.assertEqual(pg.js("document.querySelector('#pv-filter-status [data-status=installed]').getAttribute('aria-pressed')"), "true")
            # same-view hash change: route(r) applies the query
            pg.goto(CAMPUS + "?q=vox")
            pg.wait_for("document.getElementById('pv-filter-text').value === 'vox'", 5)
            self.assertEqual(pg.js("document.querySelector('#pv-filter-disc [data-disc=audio]').getAttribute('aria-pressed')"), "false")
            self.assertFalse(pg.js("document.querySelector('.pv-card[data-device=vox-1]').classList.contains('pv-dim')"))
            self.assertEqual(pg.js("window.__fathomErrors"), [])
        with self.open(CAMPUS + "?q=cl5", "m") as pg:
            pg.wait_for(CARDS_JS)
            self.assertTrue(self.visible(pg, "#pv-filter-text"), "a restored filter keeps the phone search box open")
            self.assertEqual(pg.js("document.getElementById('pv-filter-text').value"), "cl5")
            self.assertEqual(pg.js("(function (t) { return t.scrollWidth - t.clientWidth; })(document.querySelector('.pv-toolbar'))"), 0)
            pg.js("(function (i) { i.focus(); i.value = ''; i.dispatchEvent(new Event('input', {bubbles: true})); i.blur(); })(document.getElementById('pv-filter-text'))")
            pg.wait_for("location.hash.indexOf('q=') < 0", 5)
            self.assertFalse(self.visible(pg, "#pv-filter-text"))
            pg.click(".pv-search-toggle")
            pg.wait_for("document.activeElement === document.getElementById('pv-filter-text')", 5)
            self.assertLessEqual(pg.page_hscroll(), 0)

    def _context(self, pg, device):
        r = pg.rect(".pv-card[data-device=%s] .pv-title" % device)
        x, y = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
        pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "buttons": 2, "clickCount": 1})
        pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "buttons": 0, "clickCount": 1})
        return pg.wait_for("(function () { var m = document.querySelector('.pv-menu'); return m && !m.hidden && Array.prototype.map.call(m.querySelectorAll('.pv-mi'), function (b) { return b.textContent; }); })()", 5)

    def _pick(self, pg, label):
        pg.js("Array.prototype.filter.call(document.querySelectorAll('.pv-menu .pv-mi'), function (b) { return b.textContent === %s; })[0].click()" % json.dumps(label))

    def test_context_menu_links(self):
        with self.open(CAMPUS + "?q=ulxd", "d") as pg:
            pg.wait_for(CARDS_JS)
            items = self._context(pg, "ulxd-main")
            for label in ("Open details", "Open device page", "Show in rack", "Show on plan", "Trace from here"):
                self.assertIn(label, items)
            self._pick(pg, "Show in rack")
            pg.wait_for("location.hash.indexOf('/racks/rk-foh/elevation') > 0", 5)
            self.assertIn("sel=device:ulxd-main", pg.hash)
            pg.goto(CAMPUS + "?q=cl5")
            pg.wait_for("!!document.querySelector('.pv-card[data-device=foh-cl5]')")
            self._context(pg, "foh-cl5")
            # The plan view may canonicalise `sel` once mounted; check the hash this view navigated to.
            pg.js("window.__pvHashes = []; addEventListener('hashchange', function () { window.__pvHashes.push(location.hash); }); 1")
            self._pick(pg, "Show on plan")
            first = pg.wait_for("window.__pvHashes[0]", 5)
            self.assertIn("/plan/fp-main-floor?", first)
            self.assertIn("sel=marker:fp-main-floor:foh-cl5", first)
            pg.goto(CAMPUS + "?q=cl5")
            pg.wait_for("!!document.querySelector('.pv-card[data-device=foh-cl5]')")
            self._context(pg, "foh-cl5")
            self._pick(pg, "Open device page")
            pg.wait_for("location.hash.indexOf('/devices/foh-cl5') > 0", 5)
        with self.open(CAMPUS + "?q=cl5", "t") as pg:
            pg.wait_for(CARDS_JS)
            self._context(pg, "foh-cl5")
            self._pick(pg, "Open details")
            pg.wait_for("/sel=(device|port):foh-cl5/.test(location.hash)", 5)
            self.assertNotIn("drawer=0", pg.hash, "Open details opens the drawer below lg")
            pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('CL5') >= 0", 5)
            self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_empty_room_and_no_match(self):
        with self.open("#/sunday-demo/empty-hall/patch", "d") as pg:
            pg.wait_for("!!document.querySelector('.pv-empty:not([hidden]) .fb-empty')")
            self.assertEqual(pg.js("document.querySelector('.pv-empty .fb-empty-title').textContent"), "No devices in Empty Hall yet.")
            self.assertEqual(pg.js("document.querySelector('.pv-empty button').textContent"), "Add gear")
            pg.shot("patch-empty-d")
            pg.click(".pv-empty button")
            pg.wait_for("!!document.querySelector('.app-dialog-backdrop')", 5)
            pg.press("Escape")
        with self.open(CAMPUS + "?status=retired", "m") as pg:
            pg.wait_for("!!document.querySelector('.pv-empty:not([hidden]) .fb-empty')")
            self.assertEqual(pg.js("document.querySelector('.pv-empty .fb-empty-title').textContent"), "No devices match the filters.")
            self.assertEqual(pg.js("document.querySelector('.pv-menu-more .pv-menu-n').textContent"), "1")
            self.assertGreaterEqual(pg.rect(".pv-empty button")["height"], 44 - 0.5)
            pg.click(".pv-empty button")
            pg.wait_for(CARDS_JS, 5)
            pg.wait_for("location.hash.indexOf('status=') < 0", 5)
            self.assertTrue(pg.js("document.querySelector('.pv-empty').hidden"))

    def test_read_only_hides_write_actions(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS + "?readonly=1", size) as pg:
                pg.wait_for("window.__pv && document.querySelectorAll('.pv-card').length > 0")
                for ident in PV_IDS:
                    self.assertEqual(pg.js("document.querySelectorAll('#%s').length" % ident), 1, "#%s stays in the DOM" % ident)
                for sel in ("#pv-add", ".pv-menu-arrange", "#pv-undo", "#pv-redo", "#pv-arrange"):
                    self.assertFalse(self.visible(pg, sel), "%s is not shown read-only at %s" % (sel, size))
                hint = pg.js("document.querySelector('.pv-hint').textContent")
                self.assertNotRegex(hint, r"(?i)drag|re-patch|rename", "the canvas hint offers no edits read-only")
                if size == "m":
                    pg.click(".pv-menu-more")
                    self.assertFalse(self.visible(pg, "#pv-arrange"))
                    self.assertTrue(self.visible(pg, "#pv-zoom-in"))
                else:
                    self.assertTrue(self.visible(pg, "#pv-fit"))
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ---- Export group in the More menu (phase5 P5C, FR-EXP-06, §5.9)

    EXPORT_JS = """Array.prototype.map.call(document.querySelectorAll('.pv-pane-export .pv-export'), function (a) {
      return {id: a.id, href: a.getAttribute('href'), download: a.getAttribute('download'), disabled: a.getAttribute('aria-disabled') === 'true', title: a.title};
    })"""

    def _open_more(self, pg):
        pg.click(".pv-menu-more")
        pg.wait_for("document.querySelector('.pv-menu-more').getAttribute('aria-expanded') === 'true'")
        pg.js("document.getElementById('pv-print').scrollIntoView({block: 'end'}); 1")

    def test_export_menu(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(CAMPUS, size) as pg:
                pg.wait_for(CARDS_JS)
                for ident in EXPORT_IDS:
                    self.assertEqual(pg.js("document.querySelectorAll('#%s').length" % ident), 1, "#%s once at %s" % (ident, size))
                self._open_more(pg)
                pg.wait_for("sessionStorage.getItem('fathom.pv.raster') === 'ok'", 10)
                items = pg.js(self.EXPORT_JS)
                self.assertEqual([i["id"] for i in items], ["pv-export-svg", "pv-export-png", "pv-export-pdf"])
                for i in items:
                    ext = i["id"].split("-")[-1]
                    self.assertTrue(i["href"].endswith("/api/v2/projects/campus-demo/rooms/main/patch." + ext), (size, i))
                    self.assertEqual(i["download"], "campus-demo-main-patch." + ext)
                    self.assertFalse(i["disabled"], "Chrome is on this server: %s stays live" % i["id"])
                    self.assertEqual(pg.js("document.getElementById(%s).tagName" % json.dumps(i["id"])), "A", "plain anchors so iOS downloads work")
                self.assertEqual(pg.js("document.getElementById('pv-print').tagName"), "BUTTON")
                floor = 44 if size != "d" else 40
                for ident in EXPORT_IDS:
                    self.assertTrue(self.visible(pg, "#" + ident), "#%s visible in the More popover at %s" % (ident, size))
                    self.assertEqual(pg.offscreen("#" + ident), 0, "#%s off-screen at %s" % (ident, size))
                    self.assertGreaterEqual(pg.rect("#" + ident)["height"], floor - 0.5, "#%s target height at %s" % (ident, size))
                self.assertLessEqual(pg.page_hscroll(), 0)
                # the SVG link really answers
                status = pg.js("fetch(document.getElementById('pv-export-svg').href, {credentials: 'same-origin'}).then(function (r) { return r.status + ' ' + r.headers.get('Content-Type'); })")
                self.assertTrue(status.startswith("200 image/svg+xml"), status)
                pg.shot("patch-export-" + size)
                pg.press("Escape")
                self.assertEqual(pg.js("window.__fathomErrors"), [])
        # a scene active in the shell -> ?scene= on every href (Phase 3 scenes API)
        r = _post_json(self.base + "/api/v2/projects/campus-demo/scenes", {"name": "Export scene", "activate": True})
        sid = r["scene"]["id"]
        try:
            with self.open(CAMPUS, "d") as pg:
                pg.wait_for(CARDS_JS)
                self._open_more(pg)
                for i in pg.js(self.EXPORT_JS):
                    self.assertTrue(i["href"].endswith("?scene=" + sid), i)
        finally:
            _post_json(self.base + "/api/v2/projects/campus-demo/scenes/base/activate", {})

    def test_export_menu_without_chrome(self):
        # the HEAD probe answers 400 chrome_missing: PNG and PDF grey out with the hint, SVG stays live
        with self.open(CAMPUS, "d", intercepts=[("/api/v2/projects/campus-demo/rooms/main/patch.png*", 400,
                                                   {"error": "chrome_missing", "message": "PNG/PDF export needs Google Chrome on the server (SVG export always works)"}, "HEAD")]) as pg:
            pg.wait_for(CARDS_JS)
            self._open_more(pg)
            pg.wait_for("sessionStorage.getItem('fathom.pv.raster') === 'missing'", 10)
            items = dict((i["id"], i) for i in pg.js(self.EXPORT_JS))
            self.assertFalse(items["pv-export-svg"]["disabled"])
            self.assertTrue(items["pv-export-svg"]["href"].endswith("/rooms/main/patch.svg"))
            for ident in ("pv-export-png", "pv-export-pdf"):
                self.assertTrue(items[ident]["disabled"], ident)
                self.assertIsNone(items[ident]["href"], "a greyed-out export is not a link")
                self.assertEqual(items[ident]["title"], "Needs Chrome on the server")
            self.assertEqual(pg.js("document.querySelectorAll('[aria-disabled=true]').length"), 2)
            pg.shot("patch-export-nochrome-d")
            # one probe per session: with the stub gone (this server has Chrome) a remount still reads the cached answer
            pg.clear_intercepts()
            pg.goto("#/campus-demo/main/table")
            pg.goto(CAMPUS)
            pg.wait_for(CARDS_JS)
            self._open_more(pg)
            time.sleep(0.5)
            self.assertTrue(pg.js("document.getElementById('pv-export-pdf').getAttribute('aria-disabled') === 'true'"), "cached answer applied on remount")
            self.assertEqual(pg.js("sessionStorage.getItem('fathom.pv.raster')"), "missing")
            # Print… fits the canvas to the page while the dialog is up and restores the view afterwards
            before = pg.js("document.querySelector('.pv-world').style.transform")
            pg.js("window.print = function () { window.__printed = (window.__printed || 0) + 1; }; 1")
            pg.click("#pv-print")
            self.assertEqual(pg.js("window.__printed"), 1)
            self.assertTrue(pg.js("document.querySelector('.pv-root').classList.contains('pv-printing')"))
            self.assertFalse(pg.js("!!document.querySelector('.pv-pop-wrap.pv-open')"), "Print… closes the popover")
            pg.js("window.dispatchEvent(new Event('afterprint')); 1")
            self.assertFalse(pg.js("document.querySelector('.pv-root').classList.contains('pv-printing')"))
            self.assertEqual(pg.js("document.querySelector('.pv-world').style.transform"), before, "the view is restored after printing")
            self.assertEqual(pg.js("window.__fathomErrors"), [])


if __name__ == "__main__":
    unittest.main()
