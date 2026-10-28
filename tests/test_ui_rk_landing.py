"""LAND: the racks landing toolbar and workflows (docs/notes/rackula.md, wave 2).

The face / display / annotate controls persist across a reload; the Library panel adds a catalog
device at the first free RU in one commit; the accessory menu adds an item; "New rack from
template" and "Import from Rackula" run against the real server; racks sharing a row sit in titled
strips (md/lg) and the phone shows one rack at a time with prev/next and a swipe. Each class gets its
own server, so the mutations stay apart. Skips without Chrome (set ``FATHOM_CHROME``);
``$FATHOM_UI_SHOTS`` collects screenshots (the desktop ones at 1440x900).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

ROOT = Path(__file__).resolve().parent.parent
LANDING = "#/campus-demo/main/racks"
MEDIA_SERVER = ROOT / "tests" / "fixtures" / "rackula" / "media-server.rackula.yaml"

TWO_RACKS = "document.querySelectorAll('.rk-rack').length === 2"
SOME_RACKS = "document.querySelectorAll('.rk-rack').length >= 2"
DIALOG_OPEN = "!!document.querySelector('#app-dialog .app-dialog')"
DIALOG_CLOSED = "!document.querySelector('#app-dialog .app-dialog')"
VISIBLE_RACKS = """Array.prototype.filter.call(document.querySelectorAll('.rk-rack'), function (s) {
  return !s.hidden && s.getBoundingClientRect().width > 0; }).map(function (s) { return s.getAttribute('data-rack'); })"""


def pressed(box: str) -> str:
    return "(document.querySelector('#%s [aria-pressed=true]') || {}).getAttribute ? " \
           "document.querySelector('#%s [aria-pressed=true]').getAttribute('data-value') : null" % (box, box)


class LandingCase(UiCase):
    def project(self) -> dict:
        raw = urllib.request.urlopen(self.base + "/api/v2/projects/campus-demo").read().decode("utf-8")
        return json.loads(raw)

    def doc(self) -> dict:
        return self.project()["doc"]

    def poll(self, fn, what: str, timeout: float = 15.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = fn(self.doc())
            if v:
                return v
            time.sleep(0.2)
        self.fail("timed out waiting for the server to have " + what)

    def rack(self, d: dict, rid: str):
        return next((r for r in d.get("racks") or [] if r.get("id") == rid), None)

    def landing(self, size: str, **kw):
        pg = self.open(LANDING, size, **kw)
        return pg

    def ready(self, pg, what: str) -> None:
        self.assertEqual(pg.smoke["errors"], [], "errors on " + what)
        pg.wait_for("document.querySelectorAll('.rk-rack').length >= 1")

    def pick_rack(self, pg, rid: str) -> None:
        pg.js("var s = document.getElementById('rk-select'); s.value = %s; s.dispatchEvent(new Event('change'))" % json.dumps(rid))
        if rid == "*":
            pg.wait_for("document.querySelectorAll('.rk-rack').length > 1")
        else:
            pg.wait_for("document.querySelectorAll('.rk-rack').length === 1 && !!document.querySelector('.rk-rack[data-rack=%s]')" % rid)

    def blur(self, pg) -> None:
        pg.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()")

    def menu_pick(self, pg, anchor: str, act: str) -> None:
        pg.click(anchor)
        pg.wait_for("!!document.querySelector('.rkt-menu [data-act=%s]')" % act)
        pg.click(".rkt-menu [data-act=%s]" % act)
        pg.wait_for("!document.querySelector('.rkt-menu')")

    def footer(self, pg, label: str) -> None:
        sel = "#app-dialog footer button"
        idx = pg.wait_for("""(function () {
          var bs = document.querySelectorAll(%s);
          for (var i = 0; i < bs.length; i++) if (!bs[i].hidden && bs[i].textContent === %s) return String(i);
          return '';
        })()""" % (json.dumps(sel), json.dumps(label)))
        pg.click("#app-dialog footer button:nth-child(%d)" % (int(idx) + 1))

    def snap(self, pg, name: str) -> None:
        """Screenshot at 1440x900 (desktop) or 390x844 (phone) when $FATHOM_UI_SHOTS is set."""
        if pg.size == "m":
            time.sleep(0.3)
            pg.shot(name + "-390")
            return
        if pg.size != "d" or not os.environ.get("FATHOM_UI_SHOTS"):
            return
        pg.command("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        try:
            pg.wait_for("window.innerWidth === 1440")
            time.sleep(0.4)
            pg.shot(name + "-1440")
        finally:
            pg.command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            pg.wait_for("window.innerWidth === 1280")


# ---------------------------------------------------------------- controls

class LandingControls(LandingCase):
    def test_controls_persist_across_reload(self):
        for size in ("d", "m"):
            with self.landing(size) as pg:
                self.ready(pg, "racks landing at " + size)
                pg.wait_for(TWO_RACKS)
                self.assertEqual(pg.js(pressed("rk-face")), "front")
                self.assertEqual(pg.js(pressed("rk-display")), "label")
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll at " + size)
                self.assertEqual(pg.offscreen(".rkt-bar button:not([hidden])", "x"), 0, "toolbar controls fit at " + size)
                if size == "m":
                    h = pg.js("Math.min.apply(null, Array.prototype.map.call(document.querySelectorAll("
                              "'.rkt-bar button'), function (b) { var r = b.getBoundingClientRect(); return r.width ? r.height : 99; }))")
                    self.assertGreaterEqual(h, 44, "44 px targets under a coarse pointer")

                pg.click("#rk-face [data-value=rear]")
                pg.wait_for("document.querySelectorAll('.rk-slots[data-face=rear]').length === 2")
                pg.click("#rk-display [data-value=image]")
                pg.wait_for(pressed("rk-display") + " === 'image'")
                pg.click("#rk-annotate")
                pg.wait_for("!!document.querySelector('.rkt-menu [data-act=annotate-ip]')")
                self.snap(pg, "toolbar-annotate")
                pg.click(".rkt-menu [data-act=annotate-ip]")
                pg.wait_for("document.getElementById('rk-annotate').getAttribute('data-value') === 'ip'")
                self.assertIn("IP address", pg.js("document.getElementById('rk-annotate').textContent"))
                store = pg.js("[localStorage.getItem('fathom.ui.rack.face'), localStorage.getItem('fathom.ui.rack.display'),"
                              " localStorage.getItem('fathom.ui.rack.annotate')]")
                self.assertEqual(store, ["rear", "image", "ip"])

                pg.reload()
                self.ready(pg, "reload at " + size)
                pg.wait_for(TWO_RACKS)
                self.assertEqual(pg.js(pressed("rk-face")), "rear")
                self.assertEqual(pg.js(pressed("rk-display")), "image")
                self.assertEqual(pg.js("document.getElementById('rk-annotate').getAttribute('data-value')"), "ip")
                pg.wait_for("document.querySelectorAll('.rk-slots[data-face=rear]').length === 2")

                pg.click("#rk-face [data-value=both]")
                pg.wait_for(pressed("rk-face") + " === 'both'")
                self.assertEqual(pg.js("localStorage.getItem('fathom.ui.rack.face')"), "both")
                pg.click("#rk-face [data-value=front]")
                pg.wait_for("document.querySelectorAll('.rk-slots[data-face=front]').length === 2")
                self.snap(pg, "toolbar")

    def test_keyboard_shortcuts(self):
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            pg.wait_for(TWO_RACKS)
            self.blur(pg)
            pg.press("i")
            pg.wait_for(pressed("rk-display") + " === 'image'")
            pg.press("i")
            pg.wait_for(pressed("rk-display") + " === 'both'")
            pg.press("i")
            pg.wait_for(pressed("rk-display") + " === 'label'")
            pg.press("a")
            pg.wait_for("document.getElementById('rk-annotate').getAttribute('data-value') === 'name'")
            self.assertEqual(pg.js("localStorage.getItem('fathom.ui.rack.annotate')"), "name")
            pg.press("?")
            pg.wait_for("!!document.querySelector('.rkt-menu.rkt-help .rkt-keys')")
            keys = pg.js("Array.prototype.map.call(document.querySelectorAll('.rkt-keys kbd'), function (k) { return k.textContent; })")
            for k in ("i", "a", "?"):
                self.assertIn(k, keys)
            self.assertEqual(pg.js("document.getElementById('rk-help').getAttribute('aria-expanded')"), "true")
            self.snap(pg, "shortcuts")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.rkt-menu')")
            pg.click("#rk-add")
            pg.wait_for("!document.querySelector('.rk-form').hidden")
            pg.press("i")
            self.assertEqual(pg.js(pressed("rk-display")), "label", "shortcuts are off while typing")

    def test_viewer_hides_write_tools(self):
        body = self.project()
        body["role"] = "viewer"
        viewer = [("/api/v2/projects/campus-demo", 200, body, "GET")]
        for size in ("d", "m"):
            with self.landing(size, intercepts=viewer) as pg:
                self.ready(pg, "racks landing as viewer at " + size)
                for i in ("rk-library", "rk-accessory"):
                    self.assertTrue(pg.js("document.getElementById(%s).hidden" % json.dumps(i)), i + " is hidden for viewers")
                self.assertFalse(pg.js("document.getElementById('rk-export').hidden"))
                self.assertFalse(pg.js("document.getElementById('rk-export').disabled"))
                pg.click("#rk-more")
                pg.wait_for("!!document.querySelector('.rkt-menu [data-act=export]')")
                acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.rkt-menu [data-act]'), function (b) { return b.getAttribute('data-act'); })")
                for a in ("template", "import", "duplicate"):
                    self.assertNotIn(a, acts, a + " is hidden for viewers")
                self.assertIn("print", acts)
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.rkt-menu')")


# ---------------------------------------------------------------- library and accessories

class LandingLibrary(LandingCase):
    def search_catalog(self, pg, q: str) -> str:
        pg.wait_for("!!document.querySelector('#rk-library-panel .rpal-search')")
        pg.wait_for("!!document.querySelector('#rk-library-panel .rpal-row')", timeout=20)
        pg.js("var s = document.querySelector('#rk-library-panel .rpal-search'); s.value = %s; s.dispatchEvent(new Event('input'))" % json.dumps(q))
        return pg.wait_for("(document.querySelector('#rk-library-panel .rpal-row[data-source=catalog]') || {getAttribute: function () { return ''; }})"
                           ".getAttribute('data-id')")

    def placed(self, tid: str, rid: str, before: int):
        def check(d):
            hits = [x for x in d.get("devices") or [] if x.get("template") == tid and (x.get("rack") or {}).get("id") == rid]
            return hits if len(hits) > before else None
        return check

    def count(self, tid: str, rid: str) -> int:
        return len([x for x in self.doc().get("devices") or [] if x.get("template") == tid and (x.get("rack") or {}).get("id") == rid])

    def test_library_add_places_a_catalog_device(self):
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            self.pick_rack(pg, "rk-foh")
            pg.click("#rk-library")
            pg.wait_for("!document.getElementById('rk-library-panel').hidden")
            self.assertEqual(pg.js("document.getElementById('rk-library').getAttribute('aria-pressed')"), "true")
            tid = self.search_catalog(pg, "AP4421A")
            self.assertTrue(tid)
            lib = pg.rect("#rk-library-panel")
            vp = pg.rect(".rk-viewport")
            self.assertGreater(lib["left"], vp["left"], "lg: the library is a right-hand panel")
            self.assertAlmostEqual(lib["right"], pg.js("document.querySelector('.rk-body').getBoundingClientRect().right"), delta=2)
            self.assertLessEqual(vp["right"], lib["left"] + 1, "the panel sits beside the elevation, not over it")
            self.snap(pg, "library")
            before = self.count(tid, "rk-foh")
            n_blocks = pg.js("document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-block').length")
            pg.click("#rk-library-panel .rpal-row[data-source=catalog] .rpal-add")
            hits = self.poll(self.placed(tid, "rk-foh", before), "the catalog device in rk-foh")
            dev = hits[-1]
            self.assertGreaterEqual(dev["rack"].get("u") or 0, 1)
            self.assertEqual(dev.get("room"), "main")
            pg.wait_for("document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-block').length > %d" % n_blocks)
            self.assertTrue(pg.js("!!document.querySelector('.rk-rack[data-rack=rk-foh] .rk-block[data-device=%s]')" % json.dumps(dev["id"])))
            pg.click(".rkt-lib-close")
            pg.wait_for("document.getElementById('rk-library-panel').hidden")
            self.assertEqual(pg.js("document.getElementById('rk-library').getAttribute('aria-pressed')"), "false")

    def test_library_asks_which_rack_when_all_are_shown(self):
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            pg.wait_for(TWO_RACKS)
            pg.click("#rk-library")
            tid = self.search_catalog(pg, "AP4421A")
            before = self.count(tid, "rk-amp")
            pg.click("#rk-library-panel .rpal-row[data-source=catalog] .rpal-add")
            pg.wait_for("!!document.querySelector('#app-dialog .rkt-pick[data-rack=rk-amp]')")
            self.assertTrue(pg.js("!!document.querySelector('#app-dialog .rkt-pick[data-rack=rk-foh]')"))
            pg.click("#app-dialog .rkt-pick[data-rack=rk-amp]")
            pg.wait_for(DIALOG_CLOSED)
            self.poll(self.placed(tid, "rk-amp", before), "the catalog device in rk-amp")
            pg.press("Escape")
            pg.wait_for("document.getElementById('rk-library-panel').hidden")

    def test_library_bottom_sheet_at_m(self):
        with self.landing("m") as pg:
            self.ready(pg, "racks landing at m")
            pg.wait_for("!!document.querySelector('.rkt-pager:not([hidden])')")
            shown = pg.js(VISIBLE_RACKS)
            self.assertEqual(len(shown), 1)
            pg.click("#rk-library")
            pg.wait_for("!document.getElementById('rk-library-panel').hidden")
            tid = self.search_catalog(pg, "AP4421A")
            r = pg.rect("#rk-library-panel")
            self.assertAlmostEqual(r["bottom"], 844, delta=2, msg="sm: the library is a bottom sheet")
            self.assertAlmostEqual(r["width"], 390, delta=2)
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.snap(pg, "library-sheet")
            before = self.count(tid, shown[0])
            pg.click("#rk-library-panel .rpal-row[data-source=catalog] .rpal-add")
            self.poll(self.placed(tid, shown[0], before), "the catalog device in the paged rack " + shown[0])

    def test_accessory_menu_adds_an_item(self):
        for size in ("d", "m"):
            with self.landing(size) as pg:
                self.ready(pg, "racks landing at " + size)
                self.pick_rack(pg, "rk-foh")
                before = len(self.rack(self.doc(), "rk-foh").get("items") or [])
                pg.click("#rk-accessory")
                pg.wait_for("!!document.querySelector('.rkt-menu [data-act=item-blank]')")
                acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.rkt-menu [data-act]'), function (b) { return b.getAttribute('data-act'); })")
                self.assertIn("item-vent", acts)
                self.assertIn("item-shelf", acts)
                if size == "m":
                    self.assertAlmostEqual(pg.rect(".rkt-menu")["bottom"], 844, delta=2, msg="sm: menus are bottom sheets")
                self.snap(pg, "accessory-menu")
                pg.click(".rkt-menu [data-act=item-blank]")
                items = self.poll(lambda d: len(self.rack(d, "rk-foh").get("items") or []) > before and self.rack(d, "rk-foh")["items"],
                                  "a new item in rk-foh")
                self.assertEqual(items[-1]["type"], "blank")
                pg.wait_for("/^Added .* to FOH rack at U\\d+$/.test(document.querySelector('.rk-readout').textContent)")


# ---------------------------------------------------------------- server workflows

class LandingServerWorkflows(LandingCase):
    def test_new_rack_from_template(self):
        with self.landing("m") as pg:
            self.ready(pg, "racks landing at m")
            self.menu_pick(pg, "#rk-more", "template")
            pg.wait_for("!!document.querySelector('#app-dialog .rkt-tpl[data-template=church-audio-12u]')")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.snap(pg, "template-dialog")
            pg.press("Escape")
            pg.wait_for(DIALOG_CLOSED)
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            pg.wait_for(SOME_RACKS)
            self.menu_pick(pg, "#rk-more", "template")
            pg.wait_for("!!document.querySelector('#app-dialog .rkt-tpl[data-template=church-audio-12u]')")
            n = pg.js("document.querySelectorAll('#app-dialog .rkt-tpl').length")
            self.assertGreaterEqual(n, 5)
            pg.click("#app-dialog .rkt-tpl[data-template=church-audio-12u]")
            self.assertTrue(pg.js("document.querySelector('#app-dialog .rkt-tpl[data-template=church-audio-12u] input').checked"))
            pg.js("var n = document.getElementById('rkt-tpl-name'); n.value = 'Chapel rack'; n.dispatchEvent(new Event('input'))")
            self.snap(pg, "template-dialog")
            before = self.project()["revision"]
            self.footer(pg, "Create rack")
            pg.wait_for(DIALOG_CLOSED)
            rack = self.poll(lambda d: next((r for r in d.get("racks") or [] if r.get("name") == "Chapel rack"), None), "the Chapel rack")
            self.assertGreater(self.project()["revision"], before)
            self.assertEqual(rack.get("room"), "main")
            self.assertEqual(rack.get("units"), 12)
            self.assertTrue(any((x.get("rack") or {}).get("id") == rack["id"] for x in self.doc().get("devices") or []),
                            "the template brings placeholder devices")
            pg.wait_for("!!document.querySelector('.rk-rack[data-rack=%s]')" % json.dumps(rack["id"]), timeout=20)
            pg.wait_for("document.getElementById('rk-select').value === %s" % json.dumps(rack["id"]))

    def import_preview(self, pg) -> None:
        self.menu_pick(pg, "#rk-more", "import")
        pg.wait_for("!!document.getElementById('rkt-imp-file')")
        self.assertTrue(pg.js("Array.prototype.filter.call(document.querySelectorAll('#app-dialog footer button'), "
                              "function (b) { return b.textContent === 'Apply'; })[0].hidden"), "Apply waits for a preview")
        root = pg.command("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = pg.command("DOM.querySelector", {"nodeId": root, "selector": "#rkt-imp-file"})["nodeId"]
        pg.command("DOM.setFileInputFiles", {"nodeId": node, "files": [str(MEDIA_SERVER)]})
        pg.wait_for("document.getElementById('rkt-imp-file').files.length === 1")
        self.footer(pg, "Preview")
        pg.wait_for("document.querySelectorAll('#app-dialog .rkt-imp-table[data-table=devices] tr.dt-row').length === 6", timeout=20)
        self.assertEqual(pg.js("document.querySelectorAll('#app-dialog .rkt-imp-table[data-table=racks] tr.dt-row').length"), 1)
        status = pg.js("document.querySelector('#app-dialog .rkt-imp-status').textContent")
        self.assertIn("1 rack, 6 devices", status)
        self.assertIn("whole-U", pg.js("document.querySelector('#app-dialog .rkt-warns').textContent"))
        self.assertIn("Media Server", pg.js("document.querySelector('#app-dialog .rkt-imp-table[data-table=racks]').textContent"))
        self.assertFalse(pg.js("Array.prototype.filter.call(document.querySelectorAll('#app-dialog footer button'), "
                               "function (b) { return b.textContent === 'Apply'; })[0].hidden"))
        self.assertIsNone(self.rack(self.doc(), "rk-media-server"), "a preview writes nothing")

    def test_rackula_import_preview_and_apply(self):
        with self.landing("m") as pg:
            self.ready(pg, "racks landing at m")
            self.import_preview(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.snap(pg, "import-preview")
            pg.press("Escape")
            pg.wait_for(DIALOG_CLOSED)
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            pg.wait_for(SOME_RACKS)
            self.import_preview(pg)
            self.snap(pg, "import-preview")
            self.footer(pg, "Apply")
            pg.wait_for(DIALOG_CLOSED)
            rack = self.poll(lambda d: (self.rack(d, "rk-media-server") or {}).get("room") == "main" and self.rack(d, "rk-media-server"),
                             "the imported rack in room main")
            self.assertEqual(rack.get("units"), 18)
            devs = [x for x in self.doc().get("devices") or [] if (x.get("rack") or {}).get("id") == "rk-media-server"]
            self.assertEqual(len(devs), 6)
            self.assertTrue(all(x.get("room") == "main" for x in devs))
            pg.wait_for("!!document.querySelector('.rk-rack[data-rack=rk-media-server]')", timeout=20)
            self.assertEqual(pg.js("document.querySelectorAll('.rk-rack[data-rack=rk-media-server] .rk-block').length"), 6)
            self.assertEqual(pg.js("document.getElementById('rk-select').value"), "rk-media-server")

    def test_duplicate_rack(self):
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            self.pick_rack(pg, "rk-foh")
            n = len(self.doc().get("racks") or [])
            self.menu_pick(pg, "#rk-more", "duplicate")
            pg.wait_for("document.getElementById('rkt-dup-rack') && document.getElementById('rkt-dup-rack').value === 'rk-foh'")
            self.assertTrue(pg.js("document.getElementById('rkt-dup-devices').checked"))
            self.footer(pg, "Duplicate")
            pg.wait_for(DIALOG_CLOSED)
            d = self.poll(lambda d: len(d.get("racks") or []) > n and d, "a duplicated rack")
            new = [r for r in d["racks"] if r["id"] not in ("rk-foh", "rk-amp", "rk-bcast") and r.get("room") == "main"
                   and (r.get("name") or "").startswith("FOH rack")]
            self.assertTrue(new, [r.get("name") for r in d["racks"]])
            copies = [x for x in d.get("devices") or [] if (x.get("rack") or {}).get("id") == new[-1]["id"]]
            self.assertGreater(len(copies), 0, "devices are copied by default")
            pg.wait_for("document.getElementById('rk-select').value === %s" % json.dumps(new[-1]["id"]))


# ---------------------------------------------------------------- rows and the phone pager

class LandingRows(LandingCase):
    def edit_rack(self, pg, rid: str, fields: dict) -> None:
        self.pick_rack(pg, rid)
        pg.click("#rk-edit")
        pg.wait_for("!document.querySelector('.rk-form').hidden && !!document.getElementById('rk-f-row')")
        for fid, val in fields.items():
            pg.js("var n = document.getElementById(%s); n.value = %s; n.dispatchEvent(new Event('input')); n.dispatchEvent(new Event('change'))"
                  % (json.dumps(fid), json.dumps(val)))
        pg.click(".rk-form button[type=submit]")
        pg.wait_for("document.querySelector('.rk-form').hidden")

    def test_1_rows_group_into_bays(self):
        with self.landing("d") as pg:
            self.ready(pg, "racks landing")
            pg.wait_for(TWO_RACKS)
            self.assertFalse(pg.js("!!document.querySelector('.rkt-row')"), "no strips while no rack has a row")
            self.assertEqual(pg.js("document.querySelectorAll('.rkt-totals').length"), 2, "every rack gets a totals chip")
            self.assertIn("7 U free", pg.js("document.querySelector('.rkt-totals[data-rack=rk-foh]').textContent"))
            self.edit_rack(pg, "rk-foh", {"rk-f-row": "Bay A", "rk-f-maxload": "100"})
            pg.click("#rk-edit")
            pg.wait_for("document.getElementById('rk-f-rows').options.length === 1")
            self.assertEqual(pg.js("document.getElementById('rk-f-row').value"), "Bay A")
            self.assertEqual(pg.js("document.getElementById('rk-f-maxload').value"), "100")
            pg.click(".rk-form [data-act=cancel]")
            pg.wait_for("document.querySelector('.rk-form').hidden")
            self.edit_rack(pg, "rk-amp", {"rk-f-row": "Bay A", "rk-f-power": "100", "rk-f-form": "open_frame", "rk-f-width": "19"})
            d = self.poll(lambda d: (self.rack(d, "rk-amp") or {}).get("row") == "Bay A" and d, "rk-amp in Bay A")
            amp = self.rack(d, "rk-amp")
            self.assertEqual(amp.get("power_limit_w"), 100)
            self.assertEqual(amp.get("form_factor"), "open_frame")
            self.assertNotIn("width_in", {k: v for k, v in amp.items() if v is not None}, "the 19-inch default is left out")
            self.assertEqual(self.rack(d, "rk-foh").get("max_load_kg"), 100)
            self.pick_rack(pg, "*")
            pg.wait_for("document.querySelectorAll('.rkt-row[data-row=\"Bay A\"] .rkt-strip > .rk-rack').length === 2")
            self.assertIn("Bay A", pg.js("document.querySelector('.rkt-row[data-row=\"Bay A\"] .rkt-row-title').textContent"))
            chip = pg.js("document.querySelector('.rkt-totals[data-rack=rk-amp]').className")
            self.assertIn("rkt-warn", chip, "120 W over a 100 W limit warns")
            self.assertTrue(pg.js("!!document.querySelector('.rkt-totals[data-rack=rk-amp] [data-k=power].rkt-over')"))
            self.assertIn("/ 100 W", pg.js("document.querySelector('.rkt-totals[data-rack=rk-amp] [data-k=power]').textContent"))
            self.assertIn("/ 100 kg", pg.js("document.querySelector('.rkt-totals[data-rack=rk-foh]').textContent"))

            self.menu_pick(pg, "#rk-more", "duplicate")
            pg.wait_for("!!document.getElementById('rkt-dup-rack')")
            pg.js("var s = document.getElementById('rkt-dup-rack'); s.value = 'rk-foh'; s.dispatchEvent(new Event('change'))")
            self.footer(pg, "Duplicate")
            pg.wait_for(DIALOG_CLOSED)
            copy = self.poll(lambda d: next((r for r in d["racks"] if r["id"] not in ("rk-foh", "rk-amp", "rk-bcast")), None), "the copy")
            self.edit_rack(pg, copy["id"], {"rk-f-row": "Bay B", "rk-f-name": "FOH spare"})
            self.poll(lambda d: (self.rack(d, copy["id"]) or {}).get("row") == "Bay B", "the copy in Bay B")
            self.pick_rack(pg, "*")
            pg.wait_for("document.querySelectorAll('.rkt-row[data-row=\"Bay B\"] .rk-rack').length === 1")
            self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.rkt-row'), function (r) { return r.getAttribute('data-row'); })"),
                             ["Bay A", "Bay B"])
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.wait_for("!document.querySelector('.app-toast')", timeout=10)
            self.snap(pg, "rows-bays")
            pg.js("document.querySelector('.rkt-row[data-row=\"Bay B\"]').scrollIntoView({block: 'end'})")
            self.snap(pg, "rows-bays-b")

    def test_2_pager_at_m(self):
        with self.landing("m") as pg:
            self.ready(pg, "racks landing at m")
            pg.wait_for("!!document.querySelector('.rkt-pager:not([hidden])')")
            n = pg.js("document.querySelectorAll('.rk-rack').length")
            self.assertGreaterEqual(n, 2)
            self.assertFalse(pg.js("!!document.querySelector('.rkt-row')"), "sm shows one rack at a time, not strips")
            first = pg.js(VISIBLE_RACKS)
            self.assertEqual(len(first), 1)
            label = pg.js("document.querySelector('.rkt-pager-label').textContent")
            self.assertIn("1 of %d" % n, label)
            self.assertTrue(pg.js("document.getElementById('rk-prev').disabled"))
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.offscreen(".rk-rack:not([hidden]) .rk-slots", "x"), 0)
            self.snap(pg, "pager")
            pg.click("#rk-next")
            pg.wait_for("document.querySelector('.rkt-pager-label').textContent.indexOf('2 of %d') >= 0" % n)
            second = pg.js(VISIBLE_RACKS)
            self.assertEqual(len(second), 1)
            self.assertNotEqual(second, first)
            pg.click("#rk-prev")
            pg.wait_for("document.querySelector('.rkt-pager-label').textContent.indexOf('1 of %d') >= 0" % n)
            self.assertEqual(pg.js(VISIBLE_RACKS), first)
            pg.js("""(function () {
              var v = document.querySelector('.rk-viewport'), r = v.getBoundingClientRect();
              var x = r.left + r.width / 2, y = r.top + 20;
              v.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 7, pointerType: 'touch', clientX: x, clientY: y}));
              document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 7, pointerType: 'touch', clientX: x - 90, clientY: y + 10}));
            })()""")
            pg.wait_for("document.querySelector('.rkt-pager-label').textContent.indexOf('2 of %d') >= 0" % n)
            pg.js("""(function () {
              var v = document.querySelector('.rk-viewport'), r = v.getBoundingClientRect();
              var x = r.left + r.width / 2, y = r.top + 20;
              v.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 8, pointerType: 'touch', clientX: x, clientY: y}));
              document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 8, pointerType: 'touch', clientX: x + 30, clientY: y}));
            })()""")
            time.sleep(0.3)
            self.assertIn("2 of %d" % n, pg.js("document.querySelector('.rkt-pager-label').textContent"), "a 30 px swipe does not page")
            self.snap(pg, "pager-2")
            self.pick_rack(pg, "rk-foh")
            self.assertTrue(pg.js("document.querySelector('.rkt-pager').hidden"), "one chosen rack needs no pager")
