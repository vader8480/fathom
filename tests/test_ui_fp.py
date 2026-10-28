"""FP: headless-Chrome tests of the floor plan view (docs/ui-audit.md B.3 FP, B.8).

Covers the ``plan/<fp>`` route (reload, fallback with replace, ``#fp-select`` pushes, marker deep links),
the one-row toolbar (height <= 56px, ``⋯`` menu holding ``#fp-upload``, ``#fp-calibrate``, ``#fp-measure``
and ``#fp-layers`` below lg, Esc closes it), the devices explorer (``#fp-unplaced`` on ``ul.ex-list``; a
drawer opened by ``.ex-open`` at m; drag from the list onto the canvas with mouse at d and touch at m;
tap places a device), ``.fp-viewport[role=application]``, no page horizontal scroll, coarse-pointer target
sizes, read-only hiding of write actions, and the ``dev/floorplan.html`` walkthrough. Skips without Chrome.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

BASE = "#/campus-demo/main/plan"
HARNESS = "/static/dev/floorplan.html"
TOOLS = ("#fp-upload", "#fp-calibrate", "#fp-measure", "#fp-layers")
PRIMARY = ("#fp-select", "#fp-fit", "#fp-zoom-out", "#fp-zoom-in")

READY = "document.querySelector('.fp-root') && document.querySelector('.fp-viewport') && document.querySelector('#fp-select').value"
DRAWER_SETTLED = ("document.querySelector('.ex-root.ex-is-open') && getComputedStyle(document.querySelector('.ex-side')).transform === 'none'"
                  " && document.querySelector('.ex-side').getBoundingClientRect().left >= 0")
DRAWER_CLOSED = ("!document.querySelector('.ex-root.ex-is-open')"
                 " && getComputedStyle(document.querySelector('.ex-side')).visibility === 'hidden'")


def q(s):
    return json.dumps(s)


def ready(pg):
    pg.wait_for(READY)
    return pg


def visible(pg, sel):
    return pg.js("(function(){var e=document.querySelector(%s);if(!e)return false;var r=e.getBoundingClientRect();"
                 "return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden';})()" % q(sel))


def center(pg, sel):
    r = pg.rect(sel)
    assert r is not None, "no element %s" % sel
    return r["left"] + r["width"] / 2, r["top"] + r["height"] / 2


def first_unplaced(pg):
    return pg.js("(function(){var g=document.querySelector('#fp-unplaced li.fp-exitem:not(.fp-placed) .fp-grip');"
                 "return g?g.getAttribute('data-device'):null;})()")


def has_marker(pg, dev):
    return pg.js("!!document.querySelector('.fp-marker[data-device=%s]')" % q(dev))


def mouse_drag(pg, x0, y0, x1, y1, steps=8):
    pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x0, "y": y0})
    pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x0, "y": y0, "button": "left", "buttons": 1, "clickCount": 1})
    for i in range(1, steps + 1):
        pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x0 + (x1 - x0) * i / steps,
                                                "y": y0 + (y1 - y0) * i / steps, "button": "left", "buttons": 1})
    pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x1, "y": y1, "button": "left", "buttons": 0, "clickCount": 1})


def touch_drag(pg, x0, y0, x1, y1, steps=8):
    pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    for i in range(1, steps + 1):
        pg.command("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + (x1 - x0) * i / steps,
                                                                                    "y": y0 + (y1 - y0) * i / steps}]})
    pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


class FloorPlanUi(UiCase):
    def test_route_reload_and_layout_at_three_sizes(self) -> None:
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(BASE + "/fp-main-stage", size) as pg:
                ready(pg)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.querySelector('#fp-select').value"), "fp-main-stage")
                pg.reload()
                ready(pg)
                self.assertEqual(pg.js("document.querySelector('#fp-select').value"), "fp-main-stage", "plan id survives reload")
                self.assertIn("/plan/fp-main-stage", pg.hash)
                self.assertTrue(pg.js("!!document.querySelector('.fp-viewport[role=application]')"))
                self.assertEqual(pg.js("document.querySelector('#fp-unplaced').tagName + '.' + document.querySelector('#fp-unplaced').className"),
                                 "UL.ex-list")
                tb = pg.rect(".fp-toolbar")
                self.assertLessEqual(tb["height"], 56, "toolbar is one row (%s)" % tb["height"])
                self.assertLessEqual(pg.js("(function(t){return t.scrollWidth-t.clientWidth})(document.querySelector('.fp-toolbar'))"), 1,
                                     "no inner horizontal overflow in the toolbar")
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll")
                for sel in PRIMARY:
                    self.assertTrue(visible(pg, sel), "%s visible" % sel)
                    self.assertEqual(pg.offscreen(sel), 0, "%s on screen" % sel)
                if size == "d":
                    self.assertFalse(visible(pg, ".fp-menu-more"), "tools inline at lg")
                    for sel in TOOLS[1:]:
                        self.assertTrue(visible(pg, sel), "%s inline at lg" % sel)
                    self.assertTrue(visible(pg, "label[for=fp-upload]"))
                    self.assertTrue(visible(pg, ".ex-side"), "explorer is a sidebar at lg")
                else:
                    for sel in PRIMARY + (".fp-menu-more",):
                        r = pg.rect(sel)
                        self.assertGreaterEqual(min(r["width"], r["height"]), 44, "%s is a 44px target under a coarse pointer" % sel)
                    self.assertTrue(visible(pg, ".fp-menu-more"))
                    for sel in TOOLS:
                        self.assertTrue(pg.js("!!document.querySelector('#fp-menu %s')" % sel), "%s lives in the ⋯ menu" % sel)
                    self.assertFalse(visible(pg, "#fp-calibrate"))
                    self.assertEqual(pg.js("document.querySelector('.fp-menu-more').getAttribute('aria-expanded')"), "false")
                if size == "m":
                    self.assertFalse(visible(pg, ".ex-side"), "explorer is a closed drawer at sm")
                    self.assertTrue(visible(pg, ".ex-open"))
                elif size == "t":
                    self.assertTrue(visible(pg, ".ex-side"), "explorer is a sidebar at md")
                pg.shot("plan-" + size)

    def test_overflow_menu_at_tablet(self) -> None:
        with self.open(BASE + "/fp-main-floor", "t") as pg:
            ready(pg)
            pg.click(".fp-menu-more")
            pg.wait_for("!document.querySelector('#fp-menu').hidden")
            self.assertEqual(pg.js("document.querySelector('.fp-menu-more').getAttribute('aria-expanded')"), "true")
            for sel in ("#fp-calibrate", "#fp-measure", "#fp-layers", "label[for=fp-upload]"):
                self.assertTrue(visible(pg, sel), "%s visible in the open menu" % sel)
                self.assertEqual(pg.offscreen(sel), 0, "%s on screen" % sel)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("plan-menu-t")
            pg.press("Escape")
            pg.wait_for("document.querySelector('#fp-menu').hidden")
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.fp-menu-more')"), "focus returns to ⋯")
            pg.click(".fp-menu-more")
            pg.wait_for("!document.querySelector('#fp-menu').hidden")
            pg.click("#fp-measure")
            pg.wait_for("document.querySelector('#fp-menu').hidden")
            self.assertEqual(pg.js("document.querySelector('#fp-measure').getAttribute('aria-pressed')"), "true", "menu item runs")

    def test_route_fallback_push_and_back(self) -> None:
        with self.open(BASE, "d") as pg:
            ready(pg)
            pg.wait_for("location.hash.indexOf('/plan/fp-main-floor') > 0")
            n = pg.js("history.length")
            pg.goto(BASE + "/no-such-plan")
            pg.wait_for("location.hash.indexOf('/plan/fp-main-floor') > 0")
            self.assertEqual(pg.js("document.querySelector('#fp-select').value"), "fp-main-floor", "unknown id falls back")
            pg.js("(function(s){s.value='fp-main-stage';s.dispatchEvent(new Event('change',{bubbles:true}));return 1})(document.querySelector('#fp-select'))")
            pg.wait_for("location.hash.indexOf('/plan/fp-main-stage') > 0")
            self.assertEqual(pg.js("history.length"), n + 2, "the bad id and the plan change are entries; the fallback replaced")
            pg.js("history.back(); 1")
            pg.wait_for("document.querySelector('#fp-select').value === 'fp-main-floor'")
            self.assertIn("/plan/fp-main-floor", pg.hash)

    def test_marker_deep_links(self) -> None:
        with self.open(BASE + "/fp-main-stage?sel=marker:fp-main-stage:vox-1&drawer=0", "m") as pg:
            ready(pg)
            self.assertEqual(pg.js("document.querySelector('#fp-select').value"), "fp-main-stage")
            pg.wait_for("!!document.querySelector('.fp-marker.fp-selected[data-device=\"vox-1\"]')")
            self.assertTrue(visible(pg, "#app-selbar"), "canvas selection below lg uses the selection bar (D4)")
        with self.open(BASE + "?sel=device:vox-1", "d") as pg:
            ready(pg)
            pg.wait_for("document.querySelector('#fp-select').value === 'fp-main-stage'")
            pg.wait_for("location.hash.indexOf('/plan/fp-main-stage?') > 0 && location.hash.indexOf('sel=device:vox-1') > 0")

    def test_drag_from_list_with_mouse_at_desktop(self) -> None:
        with self.open(BASE + "/fp-main-floor", "d") as pg:
            ready(pg)
            dev = first_unplaced(pg)
            self.assertTrue(dev, "an unplaced device with a grip")
            self.assertFalse(has_marker(pg, dev))
            x0, y0 = center(pg, ".fp-grip[data-device=%s]" % q(dev))
            x1, y1 = center(pg, ".fp-viewport")
            mouse_drag(pg, x0, y0, x1, y1)
            pg.wait_for("!!document.querySelector('.fp-marker[data-device=%s]')" % q(dev))
            self.assertTrue(pg.js("document.querySelector('#fp-unplaced li[data-id=%s]').classList.contains('fp-placed')" % q(dev)),
                            "the device moves to the Placed group")
            self.assertEqual(pg.smoke["errors"], [])

    def test_phone_explorer_drawer_tap_and_touch_drag(self) -> None:
        with self.open(BASE + "/fp-main-floor", "m") as pg:
            ready(pg)
            pg.wait_for(DRAWER_CLOSED)
            pg.click(".ex-open")
            pg.wait_for(DRAWER_SETTLED)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("plan-explorer-m")
            pg.press("Escape")
            pg.wait_for(DRAWER_CLOSED)
            # tap an unplaced device: it is dropped in the middle and the drawer closes
            pg.click(".ex-open")
            pg.wait_for(DRAWER_SETTLED)
            dev = first_unplaced(pg)
            pg.click("#fp-unplaced li[data-id=%s] .ex-item-label" % q(dev))
            pg.wait_for("!!document.querySelector('.fp-marker[data-device=%s]')" % q(dev))
            pg.wait_for(DRAWER_CLOSED)
            # touch-drag the next one by its grip: the drawer closes as the drag starts, the drop lands on the canvas
            pg.click(".ex-open")
            pg.wait_for(DRAWER_SETTLED)
            dev2 = first_unplaced(pg)
            self.assertNotEqual(dev, dev2)
            x0, y0 = center(pg, ".fp-grip[data-device=%s]" % q(dev2))
            r = pg.rect(".fp-viewport")
            touch_drag(pg, x0, y0, r["left"] + r["width"] * 0.6, r["top"] + r["height"] * 0.5)
            pg.wait_for("!!document.querySelector('.fp-marker[data-device=%s]')" % q(dev2))
            pg.wait_for(DRAWER_CLOSED)
            self.assertLessEqual(pg.page_hscroll(), 0)

    def test_harness_walkthrough_and_read_only(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS + "?walk=1", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                walk = json.loads(pg.wait_for("document.documentElement.getAttribute('data-walk')"))
                self.assertTrue(walk.get("ok"), "floor plan harness walkthrough: %s" % walk)
                self.assertEqual(walk.get("zoomIn"), 1.25)
                self.assertTrue(pg.js("!!document.querySelector('link[href*=\"explorer.css\"]')"), "harness gets explorer.css")
                self.assertLessEqual(pg.page_hscroll(), 0)
        with self.open(HARNESS + "?readonly=1", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            for sel in ("#fp-calibrate", "label[for=fp-upload]", ".fp-grip"):
                self.assertFalse(visible(pg, sel), "%s is not rendered for read-only" % sel)
            for sel in ("#fp-measure", "#fp-layers", "#fp-select", "#fp-fit"):
                self.assertTrue(visible(pg, sel), "%s stays for read-only" % sel)


CHAPEL = "#/campus-demo/chapel/plan/fp-chapel"
RUNS_URL = "/api/v2/projects/campus-demo/floorplans/fp-chapel/runs"
RUNS_OK = {"plan": "fp-chapel", "unit": "m", "calibrated": True, "paths": [], "runs": [], "totals": {}, "unplaced": []}
RUNS_READY = READY + " && document.querySelector('#fp-runs') && !document.querySelector('#fp-runs').hidden"
TOAST = "(function(){var t=document.querySelector('#app-toasts .app-toast.ok');return t?t.textContent:''})()"


def mouse_click(pg, x, y, count=1):
    pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for i in range(count):
        pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": i + 1})
        pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": i + 1})


def labels(pg):
    return pg.js("Array.prototype.map.call(document.querySelectorAll('.fp-runlabel'), function (e) { return e.textContent; })")


def click_tool(pg, sel):
    """Click a toolbar tool, opening the ⋯ menu first when the tools have collapsed into it."""
    if not visible(pg, sel) and visible(pg, ".fp-menu-more"):
        pg.click(".fp-menu-more")
        pg.wait_for("!document.querySelector('#fp-menu').hidden")
    pg.click(sel)


class CableRunsUi(UiCase):
    """P5B: paths, cable runs and length estimates on the plan (SPEC §6.7)."""

    def test_runs_layer_labels_panel_and_use_estimate(self) -> None:
        est = {"revision": 2, "updated": [{"cable": "c-0086", "from_m": 15.0, "to_m": 16.5}], "skipped": []}
        with self.open(CHAPEL, "d", intercepts=[(RUNS_URL + "*", 200, RUNS_OK, "GET"), (RUNS_URL + "/estimate", 200, est, "POST")]) as pg:
            pg.wait_for(RUNS_READY)
            self.assertEqual(pg.smoke["errors"], [])
            self.assertEqual(pg.js("document.querySelector('#fp-runs').getAttribute('aria-pressed')"), "true", "Runs is on by default")
            self.assertTrue(visible(pg, "#fp-paths"), "Paths tool shows when the server has /runs")
            # 5 cables of the chapel have both ends placed: one dashed (auto) polyline + one label each
            pg.wait_for("document.querySelectorAll('.fp-run').length === 5")
            self.assertEqual(pg.js("document.querySelectorAll('.fp-run.fp-auto').length"), 5)
            txt = labels(pg)
            self.assertEqual(len(txt), 5)
            self.assertRegex([t for t in txt if t.startswith("A-026")][0], r"^A-026 \u00b7 \d+\.\d m$", "label = tag · length in metres")
            self.assertTrue(all(" m" in t for t in txt), "calibrated plan: every label has a length: %s" % txt)
            self.assertIn("5 runs", pg.js("document.querySelector('.fp-runs-total').textContent"))
            self.assertTrue(visible(pg, "#fp-estimate-all"))
            # select a run by its label: the panel shows plan vs entered length and the estimate
            pg.click(".fp-runlabel[data-run=\"c-0086\"]")
            pg.wait_for("!document.querySelector('#fp-runpanel').hidden")
            self.assertIn("A-026", pg.js("document.querySelector('#fp-runpanel .fp-runtitle').textContent"))
            self.assertIn("Chapel mixer", pg.js("document.querySelector('#fp-runpanel .fp-runends').textContent"))
            self.assertRegex(pg.js("document.querySelector('#fp-runpanel .fp-runlen').textContent"), r"\d+\.\d m")
            self.assertIn("15.0 m", pg.js("document.querySelector('#fp-runpanel .fp-runentered').textContent"))
            self.assertRegex(pg.js("document.querySelector('#fp-runpanel .fp-runest').textContent"), r"\d+\.\d m")
            self.assertTrue(pg.js("document.querySelector('.fp-run.fp-selected[data-run=\"c-0086\"]') !== null"), "the run is highlighted")
            rule = [r for r in pg.rules if r["method"] == "POST"][0]
            pg.click("#fp-use-estimate")
            pg.wait_for("document.querySelector('#fp-runpanel .fp-runentered').textContent.indexOf('16.5 m') >= 0")
            self.assertEqual(rule["hits"], 1, "one POST to /runs/estimate")
            self.assertIn("Length set to 16.5 m", pg.js(TOAST))
            self.assertTrue(pg.js("!!document.querySelector('#app-toasts .fp-toast-undo')"), "the toast offers Undo")
            self.assertEqual(pg.js("window.__fathomErrors.length"), 0)
            # Runs toggle: off hides the layer and is remembered per browser
            click_tool(pg, "#fp-runs")
            pg.wait_for("document.querySelectorAll('.fp-run').length === 0")
            self.assertEqual(pg.js("document.querySelector('#fp-runs').getAttribute('aria-pressed')"), "false")
            self.assertEqual(pg.js("localStorage.getItem('fathom.ui.plan.runs')"), "0")
            pg.reload()
            pg.wait_for(RUNS_READY)
            self.assertEqual(pg.js("document.querySelector('#fp-runs').getAttribute('aria-pressed')"), "false", "preference survives a reload")
            self.assertEqual(pg.js("document.querySelectorAll('.fp-run').length"), 0)
            pg.shot("plan-runs-d")

    def test_runs_404_hides_layer_and_tool(self) -> None:
        with self.open(CHAPEL, "d", intercepts=[(RUNS_URL + "*", 404, {"error": "not_found"}, "GET")]) as pg:  # an older server without the /runs route
            ready(pg)
            pg.wait_for("document.querySelector('#fp-runs').hidden")
            self.assertTrue(pg.js("document.querySelector('#fp-paths').hidden"), "Paths tool hidden")
            self.assertEqual(pg.js("document.querySelectorAll('.fp-run, .fp-runlabel').length"), 0, "no runs layer")
            self.assertTrue(pg.js("document.querySelector('#fp-runpanel').hidden"))
            self.assertFalse(visible(pg, ".fp-runsbar"))
            self.assertEqual(pg.js("window.__fathomErrors"), [])
            self.assertEqual(pg.smoke["errors"], [])
            self.assertLessEqual(pg.rect(".fp-toolbar")["height"], 56)

    def test_path_tool_draws_a_path_in_the_harness(self) -> None:
        with self.open(HARNESS, "d") as pg:
            ready(pg)
            self.assertEqual(pg.smoke["errors"], [])
            # the harness has one cable with both ends on the (uncalibrated) main floor: a '?' label with a hint
            pg.wait_for("document.querySelectorAll('.fp-run').length === 1")
            self.assertEqual(labels(pg), ["?"])
            self.assertIn("Calibrate", pg.js("document.querySelector('.fp-runlabel').title"))
            pg.click("#fp-paths")
            pg.wait_for("document.querySelector('#fp-paths').getAttribute('aria-pressed') === 'true'")
            r = pg.rect(".fp-viewport")
            pts = [(0.3, 0.3), (0.6, 0.3), (0.6, 0.6)]
            for fx, fy in pts:
                mouse_click(pg, r["left"] + r["width"] * fx, r["top"] + r["height"] * fy)
            pg.wait_for("document.querySelectorAll('.fp-pathdraft-pt').length === 3")
            pg.press("Enter")
            pg.wait_for("!document.querySelector('.fp-pathform').hidden")
            pg.js("(function(i){i.value='Stage tray';return 1})(document.querySelector('#fp-path-name'))")
            pg.js("(function(s){s.value='tray';return 1})(document.querySelector('#fp-path-kind'))")
            pg.click("#fp-path-save")
            pg.wait_for("document.querySelectorAll('.fp-path').length === 1")
            path = pg.js("window.__w4.store.doc.floorplans.filter(function(f){return f.id==='fp-main-floor'})[0].paths[0]")
            self.assertEqual(path["name"], "Stage tray")
            self.assertEqual(path["kind"], "tray")
            self.assertRegex(path["id"], r"^pt-[0-9a-f]{8}$")
            self.assertEqual(len(path["points"]), 3, "three corners through ctx.commit: %s" % path)
            self.assertTrue(pg.js("document.querySelector('.fp-path').classList.contains('fp-path-tray')"), "kind colours by CSS class")
            self.assertEqual(pg.js("document.querySelector('#fp-paths').getAttribute('aria-pressed')"), "false", "tool released after saving")
            pg.wait_for("!document.querySelector('#fp-runpanel').hidden")
            self.assertIn("Stage tray", pg.js("document.querySelector('#fp-runpanel .fp-runtitle').textContent"))
            self.assertTrue(visible(pg, "#fp-path-delete"))
            pg.click("#fp-path-delete")
            pg.wait_for("document.querySelectorAll('.fp-path').length === 0")
            self.assertEqual(pg.js("(window.__w4.store.doc.floorplans.filter(function(f){return f.id==='fp-main-floor'})[0].paths||[]).length"), 0)
            self.assertEqual(pg.js("window.__fathomErrors"), [])
        with self.open(HARNESS + "?readonly=1", "d") as pg:
            ready(pg)
            self.assertFalse(visible(pg, "#fp-paths"), "no Paths tool for read-only")
            self.assertTrue(visible(pg, "#fp-runs"), "Runs toggle stays for read-only")
            self.assertFalse(visible(pg, "#fp-estimate-all"), "no Estimate all for read-only")

    def test_export_menu_hrefs_and_chrome_hint(self) -> None:
        with self.open(CHAPEL, "d", intercepts=[(RUNS_URL + "*", 200, RUNS_OK, "GET"),
                                                ("/api/v2/projects/campus-demo/floorplans/fp-chapel.png*", 200, "", "HEAD")]) as pg:
            pg.wait_for(RUNS_READY)
            pg.click("#fp-export")
            pg.wait_for("!document.querySelector('.fp-export-pop').hidden")
            pg.wait_for("document.querySelectorAll('.fp-export-item[href]').length === 3")
            hrefs = pg.js("Array.prototype.map.call(document.querySelectorAll('.fp-export-item'), function (a) { return a.getAttribute('data-fmt') + ' ' + a.getAttribute('href'); })")
            for fmt in ("svg", "png", "pdf"):
                self.assertTrue(any(x.startswith(fmt + " ") and "/api/v2/projects/campus-demo/floorplans/fp-chapel.%s?runs=1" % fmt in x for x in hrefs), hrefs)
            pg.shot("plan-export-d")
            pg.press("Escape")
            pg.wait_for("document.querySelector('.fp-export-pop').hidden")
        with self.open(CHAPEL, "m", intercepts=[(RUNS_URL + "*", 200, RUNS_OK, "GET"),
                                                ("/api/v2/projects/campus-demo/floorplans/fp-chapel.png*", 400, {"error": "chrome_missing"}, "HEAD")]) as pg:
            pg.wait_for(RUNS_READY)
            pg.click(".fp-menu-more")
            pg.wait_for("!document.querySelector('#fp-menu').hidden")
            self.assertTrue(visible(pg, "#fp-export"), "Export lives in the overflow menu on a phone")
            pg.click("#fp-export")
            pg.wait_for("document.querySelectorAll('.fp-export-item[aria-disabled=true]').length === 2")
            self.assertEqual(pg.js("document.querySelector('.fp-export-item[data-fmt=png]').title"), "Needs Chrome on the server")
            self.assertTrue(pg.js("!!document.querySelector('.fp-export-item[data-fmt=svg][href]')"), "SVG stays available")
            self.assertLessEqual(pg.page_hscroll(), 0)

    def test_phone_bottom_sheet_and_show_runs_for_device(self) -> None:
        with self.open(CHAPEL, "m", intercepts=[(RUNS_URL + "*", 200, RUNS_OK, "GET")]) as pg:
            pg.wait_for(RUNS_READY)
            pg.wait_for("document.querySelectorAll('.fp-run').length === 5")
            pg.wait_for(DRAWER_CLOSED)
            pg.click(".fp-runlabel[data-run=\"c-0086\"]")
            pg.wait_for("!document.querySelector('#fp-runpanel').hidden")
            r = pg.rect("#fp-runpanel")
            self.assertGreaterEqual(r["width"], 380, "the run panel is a full-width bottom sheet at 390px")
            self.assertAlmostEqual(r["bottom"], pg.rect(".fp-viewport")["bottom"], delta=2, msg="docked to the bottom of the canvas")
            self.assertEqual(pg.offscreen("#fp-runpanel"), 0)
            for sel in ("#fp-use-estimate", "#fp-edit-route", "#fp-runpanel [data-act=close]"):
                rr = pg.rect(sel)
                self.assertGreaterEqual(rr["height"], 44, "%s is a 44px target" % sel)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("plan-runpanel-m")
            pg.click("#fp-runpanel [data-act=close]")
            pg.wait_for("document.querySelector('#fp-runpanel').hidden")
            # marker menu -> Show runs for this device filters the layer and shows a chip
            pg.js("(function(m){m.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:5,clientY:5}));return 1})(document.querySelector('.fp-marker[data-device=\"ch-plate\"]'))")
            pg.wait_for("!!document.querySelector('.fp-pop [data-act=runs]')")
            self.assertIn("Show runs for this device", pg.js("document.querySelector('.fp-pop [data-act=runs]').textContent"))
            pg.click(".fp-pop [data-act=runs]")
            pg.wait_for("document.querySelectorAll('.fp-run').length === 3")
            self.assertIn("Altar wall plate", pg.js("document.querySelector('.fp-runsbar .fp-chip').textContent"))
            pg.click(".fp-runsbar [data-act=clear-filter]")
            pg.wait_for("document.querySelectorAll('.fp-run').length === 5")
            self.assertEqual(pg.js("window.__fathomErrors"), [])


if __name__ == "__main__":
    import unittest
    unittest.main()
