"""States and feedback on the canvas views (docs/ui-audit.md B.2 FEEDBACK, B.3 PV/PT/FP/RK; unit ST-CANVAS).

Each state is reached on ``campus-demo`` (plus an empty ``Empty Hall`` room seeded in ``setUpClass``):
the empty patch view, the import-overlay stale badge and the delete confirmation in the patch view; the
patch table's filtered and unfiltered empty states; the floor plan's no-plan state, image skeleton and
image error with Retry; the racks empty room, rack delete confirmation and unracked discipline chips;
and the ``sel=marker:`` deep link. Viewers (faked by answering the project GET with ``role: viewer``)
get the text without the write action. Every state is checked for page-level horizontal scroll at m and
for runtime errors. With ``FATHOM_UI_SHOTS`` set it saves ``<state>-<d|t|m>.png``.

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_ui_states_canvas.py``.
Skips without Chrome.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

PROJECT = "campus-demo"
API = "/api/v2/projects/" + PROJECT
EMPTY = "#/campus-demo/empty-hall/"
MAIN = "#/campus-demo/main/"
IMAGE = API + "/floorplans/*/image*"
SIZES = ("d", "t", "m")

TEXT_JS = "(function (s) { var e = document.querySelector(s); return e ? e.textContent.trim() : null; })(%s)"
VISIBLE_JS = ("(function (s) { var e = document.querySelector(s); if (!e) return false; var r = e.getBoundingClientRect();"
              " return r.width > 0 && r.height > 0; })(%s)")
DIALOG_JS = "(document.getElementById('app-dialog') || {}).textContent || ''"


def _get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=10).read().decode("utf-8"))


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Fathom": "1"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))


class CanvasStatesUi(UiCase):

    @classmethod
    def setUpClass(cls):
        super(CanvasStatesUi, cls).setUpClass()
        proj = _get(cls.base, API)
        venue = proj["doc"]["rooms"][0].get("venue")
        _post(cls.base, API + "/changes", {
            "base_revision": proj.get("revision", 0), "summary": "empty room for test_ui_states_canvas",
            "ops": [{"op": "put", "coll": "rooms", "id": "empty-hall",
                     "value": {"id": "empty-hall", "name": "Empty Hall", "venue": venue}}]})

    # ------------------------------------------------------------ helpers

    def viewer(self):
        body = _get(self.base, API)
        body["role"] = "viewer"
        return [(API, 200, body, "GET")]

    def text(self, pg, sel):
        return pg.js(TEXT_JS % json.dumps(sel))

    def visible(self, pg, sel):
        return pg.js(VISIBLE_JS % json.dumps(sel))

    def settle(self, pg, name):
        """Common checks for a reached state: no runtime errors, no page h-scroll at m, a screenshot."""
        self.assertEqual(pg.smoke["errors"], [], name)
        self.assertEqual(pg.js("(window.__fathomErrors || []).slice()"), [], name)
        if pg.size == "m":
            self.assertLessEqual(pg.page_hscroll(), 0, name + " scrolls the page sideways at m")
        pg.shot(name + "-" + pg.size)

    # --------------------------------------------------------- patch view

    def test_patch_view_empty_room(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY + "patch", size) as pg:
                pg.wait_for("!!document.querySelector('.pv-empty:not([hidden]) .fb-empty')")
                self.assertEqual(self.text(pg, ".pv-empty .fb-empty-title"), "No devices in Empty Hall yet.")
                self.assertEqual(self.text(pg, ".pv-empty .fb-empty-action"), "Add gear")
                self.assertTrue(self.visible(pg, ".pv-empty .fb-empty-action"))
                self.settle(pg, "pv-empty")
        with self.open(EMPTY + "patch", "m", intercepts=self.viewer()) as pg:
            pg.wait_for("!!document.querySelector('.pv-empty:not([hidden]) .fb-empty')")
            self.assertEqual(self.text(pg, ".pv-empty .fb-empty-title"), "No devices in Empty Hall yet.")
            self.assertFalse(pg.js("!!document.querySelector('.pv-empty .fb-empty-action')"), "viewers get no Add gear")
            self.settle(pg, "pv-empty-viewer")

    def test_patch_view_overlay_stale_badge(self):
        with self.open(MAIN + "patch", "d") as pg:
            pg.wait_for("!!document.querySelector('.pv-card.pv-auto')")
            self.assertTrue(pg.js("!document.querySelector('.pv-stale-host').hidden"), "imported cards are on screen")
            self.assertTrue(pg.js("document.querySelector('.pv-stale-host .fb-stale').hidden"), "fresh overlay: no badge")
        overlay = _get(self.base, API + "/overlay")
        old = dict(overlay, revision=int(overlay.get("revision") or 0) - 1)
        for size in SIZES:
            with self.subTest(size=size), \
                    self.open(MAIN + "patch", size, intercepts=[(API + "/overlay*", 200, old, "GET")]) as pg:
                rule = pg.rules[0]
                pg.wait_for("!!document.querySelector('.pv-stale-host:not([hidden]) .fb-stale.fb-is-stale:not([hidden])')")
                self.assertTrue(self.visible(pg, ".pv-stale-host .fb-stale-refresh"))
                self.assertEqual(self.text(pg, ".pv-stale-host .fb-stale-refresh"), "Refresh")
                self.assertEqual(pg.js("document.querySelector('.pv-stale-host .fb-stale').getAttribute('data-reason')"), "revision")
                self.settle(pg, "pv-stale")
                if size != "d":
                    continue
                hits = rule["hits"]
                pg.click(".pv-stale-host .fb-stale-refresh")
                pg.wait_for("document.querySelector('.pv-stale-host .fb-stale-refresh').getAttribute('aria-busy') !== 'true'")
                pg.js("new Promise(function (r) { setTimeout(r, 200); })")
                self.assertGreater(rule["hits"], hits, "Refresh re-requests the overlay")
                self.assertTrue(pg.js("document.querySelector('.fb-stale').classList.contains('fb-is-stale')"),
                                "still stale: the server answered with the old revision again")
                pg.clear_intercepts()
                pg.click(".pv-stale-host .fb-stale-refresh")
                pg.wait_for("document.querySelector('.pv-stale-host .fb-stale').hidden")
                self.assertTrue(pg.js("!!document.querySelector('.pv-card.pv-auto')"))
        with self.open(MAIN + "patch", "m", intercepts=self.viewer() + [(API + "/overlay*", 200, old, "GET")]) as pg:
            pg.wait_for("!!document.querySelector('.pv-stale-host:not([hidden]) .fb-stale.fb-is-stale')")
            self.settle(pg, "pv-stale-viewer")

    def test_patch_view_delete_confirms_cable_count(self):
        doc = _get(self.base, API)["doc"]
        dev = "foh-cl5"
        n = sum(1 for c in doc.get("cables") or []
                if (c.get("from") or {}).get("device") == dev or (c.get("to") or {}).get("device") == dev)
        self.assertGreater(n, 1)
        name = [d for d in doc["devices"] if d["id"] == dev][0]["name"]
        for size in SIZES:
            with self.subTest(size=size), self.open(MAIN + "patch?sel=device:" + dev + "&drawer=0", size) as pg:
                pg.wait_for("!!document.querySelector('.pv-card.pv-selected[data-device=\"%s\"]')" % dev)
                pg.js("document.querySelector('.pv-card[data-device=\"%s\"]').focus()" % dev)
                pg.press("Delete")
                pg.wait_for("(%s).indexOf('Delete %s?') >= 0" % (DIALOG_JS, name))
                self.assertIn("%d cables are deleted with it." % n, pg.js(DIALOG_JS))
                self.settle(pg, "pv-delete-confirm")
                pg.press("Escape")
                pg.wait_for("(%s).indexOf('Delete %s?') < 0" % (DIALOG_JS, name))
                self.assertEqual(pg.js("window.__fathomErrors && window.__fathomErrors.length || 0"), 0)
                self.assertTrue(pg.js("!!document.querySelector('.pv-card[data-device=\"%s\"]')" % dev), "cancel keeps the device")

    # -------------------------------------------------------- patch table

    def test_patch_table_clear_filters(self):
        for mode in ("rows", "blocks"):
            for size in SIZES:
                with self.subTest(mode=mode, size=size), self.open(MAIN + "table?mode=%s&q=zzzqqq" % mode, size) as pg:
                    pg.wait_for("!!document.querySelector('.pt-root .fb-empty')")
                    self.assertEqual(self.text(pg, ".pt-root .fb-empty-title"), "No ports match these filters.")
                    self.assertEqual(self.text(pg, ".pt-root .fb-empty-action"), "Clear filters")
                    self.settle(pg, "pt-filtered-" + mode)
                    pg.click(".pt-root .fb-empty-action")
                    pg.wait_for("!document.querySelector('.pt-root .fb-empty')")
                    pg.wait_for("location.hash.indexOf('q=') < 0")
                    sel = ".pt-rows .dt-row" if mode == "rows" else ".pt-scroll .pt-table"
                    self.assertTrue(pg.js("document.querySelectorAll(%s).length > 0" % json.dumps(sel)))
                    self.assertEqual(pg.js("document.getElementById('pt-filter-text') ? document.getElementById('pt-filter-text').value : ''"), "")
        with self.open(MAIN + "table?mode=rows&q=zzzqqq", "m", intercepts=self.viewer()) as pg:
            pg.wait_for("!!document.querySelector('.pt-root .fb-empty-action')")
            self.assertEqual(self.text(pg, ".pt-root .fb-empty-action"), "Clear filters", "clearing filters is not a write")
            self.settle(pg, "pt-filtered-viewer")

    def test_patch_table_empty_room(self):
        with self.open(EMPTY + "table?mode=rows", "d") as pg:
            pg.wait_for("!!document.querySelector('.pt-root .fb-empty')")
            self.assertEqual(self.text(pg, ".pt-root .fb-empty-title"), "No ports in Empty Hall yet.")
            self.assertEqual(self.text(pg, ".pt-root .fb-empty-action"), "Open patch view")
            self.settle(pg, "pt-empty")
        with self.open(EMPTY + "table?mode=rows", "m", intercepts=self.viewer()) as pg:
            pg.wait_for("!!document.querySelector('.pt-root .fb-empty')")
            self.assertFalse(pg.js("!!document.querySelector('.pt-root .fb-empty-action')"))
            self.settle(pg, "pt-empty-viewer")

    # ---------------------------------------------------------- floor plan

    def test_floor_plan_no_plan(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY + "plan", size) as pg:
                pg.wait_for("!!document.querySelector('.fp-empty:not([hidden]) .fb-empty')")
                self.assertEqual(self.text(pg, ".fp-empty .fb-empty-title"), "No floor plan for Empty Hall.")
                self.assertIn("PDF, SVG or image", self.text(pg, ".fp-empty .fb-empty-text"))
                self.assertEqual(self.text(pg, ".fp-empty .fb-empty-action"), "Upload")
                self.settle(pg, "fp-empty")
                if size == "d":
                    pg.js("window.__fpPicked = 0; document.getElementById('fp-upload').addEventListener('click',"
                          " function (e) { window.__fpPicked++; e.preventDefault(); })")
                    pg.click(".fp-empty .fb-empty-action")
                    pg.wait_for("window.__fpPicked === 1")
        with self.open(EMPTY + "plan", "m", intercepts=self.viewer()) as pg:
            pg.wait_for("!!document.querySelector('.fp-empty:not([hidden]) .fb-empty')")
            self.assertEqual(self.text(pg, ".fp-empty .fb-empty-title"), "No floor plan for Empty Hall.")
            self.assertFalse(pg.js("!!document.querySelector('.fp-empty .fb-empty-action')"), "viewers get no Upload")
            self.assertFalse(pg.js("!!document.querySelector('.fp-empty .fb-empty-text')"))
            self.assertFalse(self.visible(pg, ".fp-exhint"), "viewers get no drag-to-place hint")
            self.settle(pg, "fp-empty-viewer")

    def test_floor_plan_image_error_and_retry(self):
        for size in SIZES:
            with self.subTest(size=size), \
                    self.open(MAIN + "plan/fp-main-floor", size, intercepts=[(IMAGE, 500, "boom", "GET")]) as pg:
                rule = pg.rules[0]
                pg.wait_for("!!document.querySelector('.fp-imgerror:not([hidden]) .fb-error')")
                self.assertGreaterEqual(rule["hits"], 1)
                self.assertIn("did not load", self.text(pg, ".fp-imgerror .fb-error-msg"))
                self.assertTrue(self.visible(pg, ".fp-imgerror .fb-retry"))
                self.assertTrue(pg.js("document.querySelector('.fp-img').classList.contains('fp-img-pending')"))
                self.settle(pg, "fp-image-error")
                if size != "d":
                    continue
                hits = rule["hits"]
                pg.click(".fp-imgerror .fb-retry")
                pg.wait_for("!!document.querySelector('.fp-imgerror:not([hidden]) .fb-retry')")
                self.assertGreater(rule["hits"], hits, "Retry re-requests the image")
                pg.clear_intercepts()
                pg.click(".fp-imgerror .fb-retry")
                pg.wait_for("document.querySelector('.fp-imgerror').hidden && document.querySelector('.fp-img').naturalWidth > 0")
                self.assertFalse(pg.js("document.querySelector('.fp-img').classList.contains('fp-img-pending')"))
                self.assertTrue(pg.js("document.querySelector('.fp-imgload').hidden"))

    def test_floor_plan_image_skeleton(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY + "plan", size) as pg:
                held = []
                plain = pg._event

                def hold(msg, plain=plain, held=held):
                    if msg.get("method") == "Fetch.requestPaused":
                        pg.events.append(msg)
                        held.append(msg["params"]["requestId"])
                        return
                    plain(msg)

                pg._event = hold
                pg.command("Network.enable")
                pg.command("Network.setBypassServiceWorker", {"bypass": True})
                pg.command("Fetch.enable", {"patterns": [{"urlPattern": "*" + IMAGE, "requestStage": "Request"}]})
                pg.goto(MAIN + "plan/fp-main-floor")
                pg.wait_for("!!document.querySelector('.fp-imgload:not([hidden]) .fb-skeleton[aria-busy=true]')")
                self.assertTrue(held, "the image request is held")
                self.assertTrue(pg.js("document.querySelector('.fp-img').classList.contains('fp-img-pending')"))
                self.settle(pg, "fp-image-loading")
                pg._event = plain
                for rid in held:
                    pg.command("Fetch.continueRequest", {"requestId": rid})
                pg.command("Fetch.disable")
                pg.wait_for("document.querySelector('.fp-imgload').hidden && document.querySelector('.fp-img').naturalWidth > 0")
                self.assertFalse(pg.js("document.querySelector('.fp-img').classList.contains('fp-img-pending')"))

    def test_marker_deep_link_keeps_marker(self):
        link = "sel=marker:fp-main-floor:foh-cl5"
        for size in SIZES:
            with self.subTest(size=size), self.open(MAIN + "plan/fp-main-floor?" + link, size) as pg:
                pg.wait_for("!!document.querySelector('.fp-marker.fp-selected[data-device=\"foh-cl5\"]')")
                pg.js("new Promise(function (r) { setTimeout(r, 800); })")
                self.assertIn(link, pg.hash, "the marker selection is not rewritten to device:")
                pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
                pg.wait_for("(document.querySelector('#app-inspector .ins-head') || {getAttribute: function () {}})"
                            ".getAttribute('data-kind') === 'marker'")
                self.assertIn("FOH CL5", self.text(pg, "#app-inspector"))
                self.settle(pg, "fp-marker-link")
        with self.open(MAIN + "plan/fp-main-floor?" + link + "&drawer=0", "m") as pg:
            pg.wait_for("!!document.querySelector('.fp-marker.fp-selected[data-device=\"foh-cl5\"]')")
            self.assertTrue(self.visible(pg, "#app-selbar"), "canvas selection below lg uses the selection bar (D4)")
            self.assertEqual(self.text(pg, "#app-selbar .app-selbar-title"), "FOH CL5")
            self.assertIn(link, pg.hash)
            self.settle(pg, "fp-marker-selbar")

    # --------------------------------------------------------------- racks

    def test_racks_empty_room(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY + "racks", size) as pg:
                pg.wait_for("!!document.querySelector('.rk-empty .fb-empty')")
                self.assertEqual(self.text(pg, ".rk-empty .fb-empty-title"), "No racks in Empty Hall.")
                self.assertEqual(self.text(pg, ".rk-empty .fb-empty-action"), "Add rack")
                self.settle(pg, "rk-empty")
                if size == "d":
                    pg.click(".rk-empty .fb-empty-action")
                    pg.wait_for("!!document.querySelector('.rk-form:not([hidden]) #rk-f-name')")
        with self.open(EMPTY + "racks", "m", intercepts=self.viewer()) as pg:
            pg.wait_for("!!document.querySelector('.rk-empty .fb-empty')")
            self.assertEqual(self.text(pg, ".rk-empty .fb-empty-title"), "No racks in Empty Hall.")
            self.assertFalse(pg.js("!!document.querySelector('.rk-empty .fb-empty-action')"), "viewers get no Add rack")
            self.settle(pg, "rk-empty-viewer")

    def test_rack_delete_confirms_device_count(self):
        doc = _get(self.base, API)["doc"]
        n = sum(1 for d in doc["devices"] if (d.get("rack") or {}).get("id") == "rk-foh"
                or d.get("rack") == "rk-foh")
        self.assertGreater(n, 1)
        for size in SIZES:
            with self.subTest(size=size), self.open(MAIN + "racks", size) as pg:
                pg.wait_for("!!document.getElementById('rk-select')")
                pg.js("var s = document.getElementById('rk-select'); s.value = 'rk-foh'; s.dispatchEvent(new Event('change'))")
                pg.click("#rk-edit")
                pg.click(".rk-form [data-act=delete]")
                pg.wait_for("(%s).indexOf('Delete FOH rack?') >= 0" % DIALOG_JS)
                self.assertIn("%d devices become unracked." % n, pg.js(DIALOG_JS))
                self.settle(pg, "rk-delete-confirm")
                pg.press("Escape")
                pg.wait_for("(%s).indexOf('Delete FOH rack?') < 0" % DIALOG_JS)
                self.assertTrue(any(r["id"] == "rk-foh" for r in _get(self.base, API)["doc"]["racks"]), "cancel keeps the rack")

    def test_unracked_discipline_chips(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(MAIN + "racks", size) as pg:
                pg.wait_for("document.querySelectorAll('#rk-unracked .ex-item').length > 0")
                info = pg.js("""(function () {
                  var box = document.querySelector('.rk-root .ex-chips');
                  var shown = box ? Array.prototype.filter.call(box.querySelectorAll('[data-chip]'), function (b) { return !b.hidden; })
                    .map(function (b) { return b.getAttribute('data-chip'); }) : [];
                  return {box: !!box && !box.hidden, shown: shown, items: document.querySelectorAll('#rk-unracked .ex-item').length};
                })()""")
                self.assertTrue(info["box"], "the unracked list mixes disciplines, so chips show")
                self.assertGreaterEqual(len(info["shown"]), 2)
                self.settle(pg, "rk-chips")
                if size != "d":
                    continue
                chip = info["shown"][0]
                pg.click(".rk-root .ex-chips [data-chip=\"%s\"]" % chip)
                pg.wait_for("document.querySelectorAll('#rk-unracked .ex-item').length < %d" % info["items"])
                self.assertEqual(pg.js("document.querySelector('.rk-root .ex-chips [data-chip=\"%s\"]').getAttribute('aria-pressed')" % chip), "true")
                pg.click(".rk-root .ex-chips [data-chip=\"%s\"]" % chip)
                pg.wait_for("document.querySelectorAll('#rk-unracked .ex-item').length === %d" % info["items"])


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
