"""INS: the inspector as drawer content (docs/ui-audit.md B.3 INS, D1, D4, D8).

Runs the real app on a ``tests/_ui.py`` server (``campus-demo`` sample). Covers ``sec=`` focusing and its
URL round trip, the section index, persisted collapse state (``fathom.ui.inspector``), the header (glyph,
status, "Open page", close), the device, port and cable drawers in the three drawer modes (docked at d,
sheet at t, full at m), the read-only rendering for a viewer, and no horizontal page scroll at t and m.
Skips without Chrome; set ``FATHOM_CHROME=/usr/bin/google-chrome-stable``. With ``FATHOM_UI_SHOTS`` set it
writes ``ins-device``, ``ins-port``, ``ins-cable`` and ``ins-inventory`` at d, t and m.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/"
MODES = {"d": "dr-docked", "t": "dr-sheet", "m": "dr-full"}

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

# Is details[data-section=<key>] open, and is its summary inside the drawer's visible box (below the index)?
SECTION_IN_VIEW = """(function (key) {
  var host = document.getElementById('app-inspector');
  var d = host.querySelector('.ins > details[data-section="' + key + '"]');
  if (!d || !d.open) return false;
  var s = d.querySelector('summary').getBoundingClientRect(), hr = host.getBoundingClientRect();
  var nav = host.querySelector('.ins-index'), top = nav ? nav.getBoundingClientRect().bottom : hr.top;
  return s.top >= top - 2 && s.bottom <= Math.min(hr.bottom, innerHeight) + 1;
})(%s)"""

SECTIONS = ("Array.prototype.map.call(document.querySelectorAll('#app-inspector .ins > details[data-section]'),"
            " function (d) { return d.getAttribute('data-section'); })")
CHIPS = ("Array.prototype.map.call(document.querySelectorAll('#app-inspector nav.ins-index a.ins-index-chip'),"
         " function (a) { return a.getAttribute('data-sec'); })")


def q(s: str) -> str:
    return json.dumps(s)


class InspectorUi(UiCase):
    def ready(self, pg, text=None):
        pg.wait_for(DRAWER_OPEN)
        pg.wait_for("!!document.querySelector('#app-inspector .ins-head')")
        if text:
            pg.wait_for("document.querySelector('#app-inspector .ins-head h3').textContent.indexOf(%s) >= 0" % q(text))

    def layout_checks(self, pg, size):
        cls = pg.js("document.getElementById('app-inspector').className").split()
        self.assertIn(MODES[size], cls, "drawer mode at %s" % size)
        self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at %s" % size)
        # The drawer scrolls vertically; nothing may be clipped sideways.
        self.assertEqual(pg.offscreen("#app-inspector button", "x"), 0, "buttons clipped sideways at %s" % size)
        scroll = pg.js("document.getElementById('app-inspector').scrollTop")
        pg.js("document.getElementById('app-inspector').scrollTop = 0; 1")
        self.assertEqual(pg.offscreen("#app-inspector .ins-head a, #app-inspector .ins-head button"), 0, "header controls visible")
        pg.js("document.getElementById('app-inspector').scrollTop = %d; 1" % scroll)

    def test_sec_opens_section_in_view_at_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "inventory?sel=device:foh-cl5&sec=inventory", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.ready(pg, "FOH CL5")
                pg.wait_for(SECTION_IN_VIEW % q("inventory"))
                self.assertEqual(pg.js("document.querySelector('#app-inspector .ins-index-chip[aria-current=true]').getAttribute('data-sec')"), "inventory")
                self.assertIn("sec=inventory", pg.hash)
                self.assertIn("/inventory?", pg.hash, "the view segment is unchanged")
                self.layout_checks(pg, size)
                pg.shot("ins-inventory-" + size)

    def test_section_index_and_sec_round_trip(self):
        with self.open(CAMPUS + "patch?sel=device:foh-cl5", "d") as pg:
            self.ready(pg, "FOH CL5")
            secs = pg.js(SECTIONS)
            for key in ("identity", "ports", "inventory", "net", "dmx", "procedures", "problems", "qr", "notes"):
                self.assertIn(key, secs)
            self.assertEqual(pg.js(CHIPS), secs, "one index chip per section, in order")
            self.assertTrue(pg.js("getComputedStyle(document.querySelector('#app-inspector .ins-index')).position") == "sticky")
            href = pg.js("document.querySelector('#app-inspector .ins-index-chip[data-sec=net]').getAttribute('href')")
            self.assertIn("sel=device:foh-cl5", href)
            self.assertIn("sec=net", href, "chips are deep links")

            pg.click("#app-inspector .ins-index-chip[data-sec=net]")
            pg.wait_for("location.hash.indexOf('sec=net') > 0")
            pg.wait_for(SECTION_IN_VIEW % q("net"))
            self.assertIn("sel=device:foh-cl5", pg.hash)
            self.assertEqual(pg.js("document.activeElement.parentElement.getAttribute('data-section')"), "net", "focus on the summary")

            # the index stays put while the drawer scrolls
            pg.js("document.getElementById('app-inspector').scrollTop = 2500; 1")
            nav = pg.rect("#app-inspector .ins-index")
            host = pg.rect("#app-inspector")
            self.assertLessEqual(abs(nav["top"] - host["top"]), 2, "sticky index at the top of the drawer")

            pg.reload()
            self.ready(pg, "FOH CL5")
            pg.wait_for(SECTION_IN_VIEW % q("net"))

            # opening a section by hand writes sec; closing it removes sec
            pg.js("document.getElementById('app-inspector').scrollTop = 0; 1")
            pg.click("#app-inspector details[data-section=dmx] > summary")
            pg.wait_for("location.hash.indexOf('sec=dmx') > 0")
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=dmx]').open"))
            pg.click("#app-inspector details[data-section=dmx] > summary")
            pg.wait_for("location.hash.indexOf('sec=') < 0")
            self.assertIn("sel=device:foh-cl5", pg.hash)

    def test_collapse_state_persists_per_kind(self):
        with self.open(CAMPUS + "patch?sel=device:foh-cl5", "d") as pg:
            self.ready(pg, "FOH CL5")
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=identity]').open"))
            self.assertFalse(pg.js("document.querySelector('#app-inspector details[data-section=rack]').open"))
            pg.click("#app-inspector details[data-section=identity] > summary")
            pg.click("#app-inspector details[data-section=rack] > summary")
            pg.wait_for("!document.querySelector('#app-inspector details[data-section=identity]').open")
            pg.wait_for("(localStorage.getItem('fathom.ui.inspector') || '').indexOf('\"rack\":true') > 0")
            stored = json.loads(pg.js("localStorage.getItem('fathom.ui.inspector')"))
            self.assertEqual(stored["open"]["device"], {"identity": False, "rack": True})
            pg.js("location.hash = %s; 1" % q(CAMPUS + "patch?sel=device:rio-sl"))
            self.ready(pg, "Stage Rack SL")
            self.assertFalse(pg.js("document.querySelector('#app-inspector details[data-section=identity]').open"), "kept across devices")
            pg.reload()
            self.ready(pg, "Stage Rack SL")
            self.assertFalse(pg.js("document.querySelector('#app-inspector details[data-section=identity]').open"), "kept across reload")
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=rack]').open"))
            pg.js("location.hash = %s; 1" % q(CAMPUS + "patch?sel=port:rio-sl:analog-in-9"))
            self.ready(pg, "Kick In")
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=fields]').open"), "ports have their own state")
            pg.js("localStorage.setItem('fathom.ui.inspector', '{not json'); 1")
            pg.reload()
            self.ready(pg, "Kick In")
            self.assertEqual(pg.smoke["errors"], [], "corrupt state falls back to defaults")

    def test_device_header_and_actions(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "patch?sel=device:foh-cl5", size) as pg:
                self.ready(pg, "FOH CL5")
                headinfo = pg.js("""(function () {
                  var h = document.querySelector('#app-inspector .ins-head');
                  return {kind: h.getAttribute('data-kind'), glyph: h.querySelector('.ins-glyph').textContent,
                    status: h.querySelector('.ins-status').textContent, open: h.querySelector('a.ins-open-page').getAttribute('href'),
                    close: !!h.querySelector('button.ins-close[aria-label="Close details"]')};
                })()""")
                self.assertEqual(headinfo["kind"], "device")
                self.assertEqual(headinfo["glyph"], "\u25EB")
                self.assertEqual(headinfo["status"], "installed")
                self.assertEqual(headinfo["open"], CAMPUS + "devices/foh-cl5")
                self.assertTrue(headinfo["close"])
                labels = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-inspector .ins-actions > *'), function (b) { return b.textContent; })")
                for want in ("Show in patch view", "Trace path", "Device page", "Duplicate", "Merge\u2026", "Delete"):
                    self.assertIn(want, labels)
                self.layout_checks(pg, size)
                if size != "d":
                    for sel in ("#app-inspector .ins-close", "#app-inspector .ins-open-page", "#app-inspector .ins-index-chip"):
                        r = pg.rect(sel)
                        self.assertGreaterEqual(r["height"], 44, sel)
                pg.shot("ins-device-" + size)
                if size == "m":
                    pg.click("#app-inspector .ins-close")
                    pg.wait_for("!document.getElementById('app-inspector').classList.contains('dr-open')")
                    self.assertNotIn("sel=", pg.hash)
                    self.assertTrue(pg.js("document.getElementById('app-selbar').hidden"), "closing deselects")
                if size == "d":
                    pg.click("#app-inspector a.ins-open-page")
                    pg.wait_for("location.hash === %s" % q(CAMPUS + "devices/foh-cl5"))
                    pg.wait_for("!document.getElementById('app-inspector').classList.contains('dr-open')")

    def test_show_in_patch_view_keeps_canvas_clear_below_lg(self):
        with self.open(CAMPUS + "inventory?sel=device:foh-cl5", "t") as pg:
            self.ready(pg, "FOH CL5")
            pg.click("#app-inspector .ins-actions button:first-child")
            pg.wait_for("location.hash.indexOf('/patch?') > 0")
            self.assertIn("sel=device:foh-cl5", pg.hash)
            self.assertIn("drawer=0", pg.hash)
            pg.wait_for("!document.getElementById('app-selbar').hidden")

    def test_port_drawer_leads_with_far_end(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "patch?sel=port:rio-sl:analog-in-9", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.ready(pg, "Kick In")
                first = pg.js("document.querySelector('#app-inspector .ins > details[data-section]').getAttribute('data-section')")
                self.assertEqual(first, "cables", "Now connected is the first section")
                now = pg.js("""(function () {
                  var s = document.querySelector('#app-inspector details[data-section=cables]');
                  return {open: s.open, title: s.querySelector('summary').textContent, peer: s.querySelector('a.ins-now-peer').textContent,
                    peerSel: s.querySelector('a.ins-now-peer').getAttribute('data-peer'), cable: !!s.querySelector('a.ins-now-cable'),
                    trace: !!s.querySelector('[data-action=trace]'), status: document.querySelector('#app-inspector .ins-head .ins-status').textContent};
                })()""")
                self.assertTrue(now["open"])
                self.assertTrue(now["title"].startswith("Now connected"))
                self.assertIn("Drum mics", now["peer"])
                self.assertTrue(now["peerSel"].startswith("port:"))
                self.assertTrue(now["cable"])
                self.assertTrue(now["trace"], "Trace sits in the Now connected block")
                self.assertEqual(now["status"], "patched")
                self.assertEqual(pg.js("document.querySelectorAll('#app-inspector [data-action=trace]').length"), 1)
                self.layout_checks(pg, size)
                pg.shot("ins-port-" + size)
                if size == "m":
                    pg.click("#app-inspector a.ins-now-peer")
                    pg.wait_for("location.hash.indexOf(%s) > 0" % q("sel=" + now["peerSel"]))
                    pg.wait_for("document.querySelector('#app-inspector .ins-head').getAttribute('data-kind') === 'port'")
                    self.assertTrue(pg.js(DRAWER_OPEN), "the far end opens in the same drawer")
                    pg.click("#app-inspector a.ins-now-cable")
                    pg.wait_for("location.hash.indexOf('sel=cable:') > 0")
                    pg.wait_for("document.querySelector('#app-inspector .ins-head').getAttribute('data-kind') === 'cable'")
                    self.assertIn("/patch?", pg.hash)

    def test_cable_drawer_endpoints_first(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "schedules?sel=cable:c-0001", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.ready(pg, "c-0001")
                self.assertEqual(pg.js(SECTIONS)[:2], ["endpoints", "fields"])
                ends = pg.js("""Array.prototype.map.call(document.querySelectorAll('#app-inspector [data-section=endpoints] .ins-ep-row'), function (r) {
                  var dev = r.querySelector('.ins-ep-dev'), port = r.querySelector('.ins-ep-port');
                  return {dev: dev && dev.getAttribute('href'), port: port && port.getAttribute('data-peer')};
                })""")
                self.assertEqual(len(ends), 2)
                self.assertTrue(all(e["dev"] and "/devices/" in e["dev"] for e in ends), ends)
                self.assertTrue(all(e["port"] and e["port"].startswith("port:") for e in ends), ends)
                labels = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-inspector [data-section=fields] .field > label'), function (l) { return l.textContent; })")
                self.assertEqual(labels[:5], ["Tag", "Signal", "Medium", "Length", "Status"])
                self.assertEqual(pg.js("document.querySelectorAll('#app-inspector [data-action=schedules]').length"), 0, "already in schedules")
                self.layout_checks(pg, size)
                pg.shot("ins-cable-" + size)
        with self.open(CAMPUS + "patch?sel=cable:c-0001", "d") as pg:
            self.ready(pg, "c-0001")
            pg.click("#app-inspector .ins-ep-row[data-end=to] .ins-ep-port")
            pg.wait_for("location.hash.indexOf('sel=port:') > 0")
            pg.wait_for("document.querySelector('#app-inspector .ins-head').getAttribute('data-kind') === 'port'")
            pg.js("history.replaceState(null, '', location.pathname + location.search + %s); dispatchEvent(new HashChangeEvent('hashchange')); 1" % q(CAMPUS + "patch?sel=cable:c-0001"))
            pg.wait_for("document.querySelector('#app-inspector .ins-head').getAttribute('data-kind') === 'cable'")
            pg.click("#app-inspector [data-action=schedules]")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables?sel=cable:c-0001"))
            pg.wait_for(DRAWER_OPEN)

    def test_viewer_sees_read_only_drawer(self):
        url = self.base + "/api/v2/projects/campus-demo"
        body = json.loads(urllib.request.urlopen(url, timeout=10).read().decode())
        body["role"] = "viewer"
        with self.open(CAMPUS + "patch?sel=device:foh-cl5", "m", intercepts=[("/api/v2/projects/campus-demo", 200, body, "GET")]) as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.ready(pg, "FOH CL5")
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-inspector .ins-actions > *'), function (b) { return b.textContent; })")
            for gone in ("Duplicate", "Merge\u2026", "Delete"):
                self.assertNotIn(gone, labels)
            for kept in ("Show in patch view", "Device page"):
                self.assertIn(kept, labels)
            self.assertTrue(pg.js("document.querySelector('#app-inspector [data-section=identity] input').disabled"))
            self.assertTrue(pg.js("!!document.querySelector('#app-inspector a.ins-open-page')"))
            self.assertTrue(pg.js("!!document.querySelector('#app-inspector nav.ins-index')"))
            self.layout_checks(pg, "m")
            pg.js("location.hash = %s; 1" % q(CAMPUS + "patch?sel=port:rio-sl:analog-in-9"))
            self.ready(pg, "Kick In")
            self.assertEqual(pg.js("document.querySelectorAll('#app-inspector [aria-label=Disconnect]').length"), 0)
            self.assertTrue(pg.js("!!document.querySelector('#app-inspector a.ins-now-peer')"))

    def test_unknown_selection_says_not_found(self):
        with self.open(CAMPUS + "patch?sel=device:no-such-device", "d") as pg:
            pg.wait_for(DRAWER_OPEN)
            pg.wait_for("!!document.querySelector('#app-inspector .ins-missing')")
            self.assertIn("no-such-device", pg.js("document.querySelector('#app-inspector .ins-missing').textContent"))
            pg.click("#app-inspector .ins-close")
            pg.wait_for("location.hash.indexOf('sel=') < 0")
