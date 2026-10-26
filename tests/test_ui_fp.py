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


if __name__ == "__main__":
    import unittest
    unittest.main()
