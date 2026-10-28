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
    from test_ui_inv import seed_campus
except ImportError:  # pragma: no cover
    from tests._ui import UiCase
    from tests.test_ui_inv import seed_campus

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


class _InspectorBase(UiCase):
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


class InspectorUi(_InspectorBase):
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
            self.assertTrue(pg.js("document.querySelector('#app-inspector [data-section=notes] textarea').disabled"), "Notes is read-only for a viewer")
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


INV = "#app-inspector details[data-section=inventory] "


class InspectorKnoxUi(_InspectorBase):
    """Inventory section extras (FR-INV-10..13) on a campus-demo copy seeded by ``test_ui_inv.knox_seed``."""

    @classmethod
    def setUpClass(cls) -> None:
        super(InspectorKnoxUi, cls).setUpClass()
        seed_campus(cls.server)

    def _doc_device(self, dev_id):
        url = self.base + "/api/v2/projects/campus-demo"
        body = json.loads(urllib.request.urlopen(url, timeout=10).read().decode())
        return next(d for d in body["doc"]["devices"] if d["id"] == dev_id)

    def _wait_device(self, pg, dev_id, js_pred, timeout=15.0):
        pg.wait_for("fetch('/api/v2/projects/campus-demo', {headers: {Accept: 'application/json'}}).then(function (r) { return r.json(); })"
                    " .then(function (p) { var d = p.doc.devices.filter(function (x) { return x.id === %s; })[0]; return !!(d && (%s)); })" % (q(dev_id), js_pred), timeout)

    def _fields_rows(self, pg):
        return pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (r) {"
                     " return [r.querySelector('.ins-field-key').value, r.querySelector('.ins-field-val').value]; })" % q(INV + ".ins-field-row"))

    def _set(self, pg, selector, value):
        pg.js("(function (el) { el.value = %s; el.dispatchEvent(new Event('change', {bubbles: true})); })(document.querySelector(%s))" % (q(value), q(selector)))

    def test_knox_condition_stored_in_code_and_holds(self):
        for size in ("d", "m"):
            with self.open(CAMPUS + "inventory?sel=device:foh-cl5&sec=inventory", size) as pg:
                self.ready(pg, "FOH CL5")
                pg.wait_for(SECTION_IN_VIEW % q("inventory"))
                labels = pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (l) { return l.textContent; })" % q(INV + ".field > label"))
                self.assertEqual(labels[:3], ["Condition", "Stored in", "Code"], "the Knox rows lead the Inventory section")
                cond = INV + ".field:nth-of-type(1) select"
                self.assertEqual(pg.js("document.querySelector(%s).value" % q(cond)), "good")
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelector(%s).options, function (o) { return o.value; })" % q(cond)),
                                 ["", "new", "good", "fair", "poor", "broken"], "an empty option plus the five conditions")
                stored = INV + ".field:nth-of-type(2) select"
                self.assertEqual(pg.js("document.querySelector(%s).value" % q(stored)), "case-foh")
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelector(%s).options, function (o) { return o.textContent; })" % q(stored)),
                                 ["\u2014", "FOH road case"], "the project's containers")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % q(INV + ".ins-code-text")), "ABCD-2345")
                copy = pg.js("document.querySelector(%s).getAttribute('data-copy')" % q(INV + ".ins-copy-link"))
                self.assertTrue(copy.endswith("/c/ABCD-2345"), copy)
                self.assertTrue(pg.js("!!document.querySelector(%s)" % q(INV + "img.ins-qr-thumb")), "the QR thumbnail reuses the device QR image")
                if size == "m":
                    self.assertGreaterEqual(pg.rect(INV + ".ins-copy-link")["height"], 44 - 0.5, "Copy link is a 44px target")
                    self.assertGreaterEqual(pg.rect(INV + ".ins-field-add")["height"], 44 - 0.5)
                self.layout_checks(pg, size)
                pg.shot("ins-knox-%s" % size)

                # condition and stored-in write through ops; undo reverts
                self._set(pg, cond, "poor")
                self._wait_device(pg, "foh-cl5", "d.inventory.condition === 'poor'")
                self._set(pg, stored, "")
                self._wait_device(pg, "foh-cl5", "!d.container")
                pg.press("Control+z")
                self._wait_device(pg, "foh-cl5", "d.container === 'case-foh'")
                pg.press("Control+z")
                self._wait_device(pg, "foh-cl5", "d.inventory.condition === 'good'")

                # a container shows what it holds and has no Stored in row; each entry selects that device
                pg.js("location.hash = %s; 1" % q(CAMPUS + "inventory?sel=device:case-foh&sec=inventory"))
                self.ready(pg, "FOH road case")
                labels = pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (l) { return l.textContent; })" % q(INV + ".field > label"))
                self.assertEqual(labels[:3], ["Condition", "Holds (2)", "Code"])
                self.assertNotIn("Stored in", labels)
                held = pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (a) { return a.getAttribute('data-device'); })" % q(INV + ".ins-holds-link"))
                self.assertEqual(held, ["di-kit", "foh-cl5"])
                pg.click(INV + ".ins-holds-link[data-device=di-kit]")
                self.ready(pg, "DI box kit")
                self.assertTrue(pg.js("location.hash.indexOf('sel=device:di-kit') > 0 || location.hash.indexOf('sel=device%3Adi-kit') > 0"))
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % q(INV + ".ins-code")).strip(), "\u2014", "no code yet shows an em dash")

    def test_knox_custom_fields_add_edit_remove_and_duplicate_error(self):
        with self.open(CAMPUS + "inventory?sel=device:foh-cl5&sec=inventory", "d") as pg:
            self.ready(pg, "FOH CL5")
            pg.wait_for("document.querySelectorAll(%s).length === 4" % q(INV + ".ins-field-row"))
            self.assertEqual(self._fields_rows(pg), [["owner", "AV office"], ["insured", "yes"], ["bin", "B-01"], ["lease", "2027-01"]])

            # edit a value: the whole object is written, other keys untouched
            self._set(pg, INV + ".ins-field-row:nth-child(3) .ins-field-val", "B-02")
            self._wait_device(pg, "foh-cl5", "d.inventory.fields.bin === 'B-02' && d.inventory.fields.owner === 'AV office' && Object.keys(d.inventory.fields).length === 4")

            # add a field; the key is trimmed
            pg.click(INV + ".ins-field-add")
            pg.wait_for("document.querySelectorAll(%s).length === 5 && document.activeElement.classList.contains('ins-field-key')" % q(INV + ".ins-field-row"))
            self._set(pg, INV + ".ins-field-row:nth-child(5) .ins-field-key", "  rfid ")
            self._set(pg, INV + ".ins-field-row:nth-child(5) .ins-field-val", "E200-1")
            self._wait_device(pg, "foh-cl5", "d.inventory.fields.rfid === 'E200-1' && Object.keys(d.inventory.fields).length === 5")

            # a duplicate key is refused inline and nothing is written
            self._set(pg, INV + ".ins-field-row:nth-child(5) .ins-field-key", "owner")
            pg.wait_for("!!document.querySelector(%s)" % q(INV + ".ins-fields-err .fb-error"))
            self.assertIn("Duplicate field name", pg.js("document.querySelector(%s).textContent" % q(INV + ".ins-fields-err")))
            self.assertTrue(pg.js("document.querySelector(%s).classList.contains('ins-field-dup')" % q(INV + ".ins-field-row:nth-child(5) .ins-field-key")))
            self.assertEqual(self._doc_device("foh-cl5")["inventory"]["fields"]["rfid"], "E200-1", "the duplicate is not written")
            self._set(pg, INV + ".ins-field-row:nth-child(5) .ins-field-key", "rfid")
            pg.wait_for("!document.querySelector(%s)" % q(INV + ".ins-fields-err .fb-error"))

            # remove a field: the key is deleted from the document; undo brings it back
            pg.click(INV + ".ins-field-row:nth-child(5) .ins-field-rm")
            self._wait_device(pg, "foh-cl5", "!('rfid' in d.inventory.fields) && Object.keys(d.inventory.fields).length === 4")
            pg.wait_for("document.querySelectorAll(%s).length === 4" % q(INV + ".ins-field-row"))
            pg.press("Control+z")
            self._wait_device(pg, "foh-cl5", "d.inventory.fields.rfid === 'E200-1'")
            pg.wait_for("document.querySelectorAll(%s).length === 5" % q(INV + ".ins-field-row"))
            self.assertEqual(self._fields_rows(pg)[4], ["rfid", "E200-1"], "the editor re-renders from the document after undo")

    def test_knox_viewer_sees_read_only_fields(self):
        url = self.base + "/api/v2/projects/campus-demo"
        body = json.loads(urllib.request.urlopen(url, timeout=10).read().decode())
        body["role"] = "viewer"
        with self.open(CAMPUS + "inventory?sel=device:foh-cl5&sec=inventory", "d", intercepts=[("/api/v2/projects/campus-demo", 200, body, "GET")]) as pg:
            self.ready(pg, "FOH CL5")
            self.assertTrue(pg.js("document.querySelector(%s).disabled" % q(INV + ".field:nth-of-type(1) select")), "condition is read-only")
            self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll(%s), function (i) { return i.disabled; })" % q(INV + ".ins-field-row input")))
            self.assertFalse(pg.js("!!document.querySelector(%s)" % q(INV + ".ins-field-add")), "no Add field for viewers")
            self.assertTrue(pg.js("!!document.querySelector(%s)" % q(INV + ".ins-copy-link")), "the code link can still be copied")
