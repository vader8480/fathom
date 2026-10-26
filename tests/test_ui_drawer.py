"""DRAWER harness in headless Chrome (docs/ui-audit.md B.2 DRAWER, D3, D4).

Drives ``/static/dev/drawer.html`` (``createDrawer`` on a shell-shaped ``#app-inspector``): docked column
at d (no backdrop, focus not trapped), slide-over sheet at t and 88dvh bottom sheet at m (modal: backdrop,
focus trap, Esc and backdrop close, focus returns), the Esc order against a dialog and the assistant,
the canvas-selection rule with ``drawer=0``, URL state across reload and Back, relayout across the
breakpoints, and no horizontal page scroll at 390. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import time

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

H = "/static/dev/drawer.html"
ROW = "[data-open='device:foh-cl5']:not([data-sec])"

STATE = """(function () {
  var h = document.getElementById('app-inspector'), ae = document.activeElement;
  return {cls: h.className, open: h.classList.contains('dr-open'), role: h.getAttribute('role'),
    modal: h.getAttribute('aria-modal'), label: h.getAttribute('aria-label'),
    backdrops: document.querySelectorAll('.dr-backdrop').length, inside: !!ae && h.contains(ae),
    host: ae === h, active: ae ? (ae.id || ae.getAttribute('data-open') || ae.getAttribute('data-canvas') || ae.className || ae.tagName) : null,
    sec: ae ? ae.getAttribute('data-sec') : null, hash: location.hash,
    parentDocked: h.parentElement.classList.contains('dr-docked-open'), shown: h.getClientRects().length > 0,
    anim: getComputedStyle(h).animationName, log: window.__drLog.slice()};
})()"""

FOCUSABLES = ("Array.prototype.filter.call(document.querySelectorAll('#app-inspector button, #app-inspector input, #app-inspector summary'),"
              " function (e) { var d = e.closest('details'); return e.getClientRects().length > 0"
              " && (!d || d.open || e.parentElement === d && e.tagName === 'SUMMARY'); })")


def reduce_motion(pg) -> None:
    feats = [{"name": "prefers-reduced-motion", "value": "reduce"}]
    if pg.touch:
        feats += [{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}]
    pg.command("Emulation.setEmulatedMedia", {"features": feats})


def tap_at(pg, x: float, y: float) -> None:
    if pg.touch:
        pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    else:
        for t in ("mousePressed", "mouseReleased"):
            pg.command("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})


def resize(pg, w: int, hgt: int, touch: bool = False) -> None:
    pg.command("Emulation.setDeviceMetricsOverride", {"width": w, "height": hgt, "deviceScaleFactor": 1, "mobile": touch})


class DrawerHarnessUi(UiCase):

    def st(self, pg):
        return pg.js(STATE)

    def wait_open(self, pg, want=True):
        pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open') === %s" % ("true" if want else "false"))
        return self.st(pg)

    def assertNear(self, a, b, tol=2.0, msg=None):
        self.assertLessEqual(abs(a - b), tol, msg or "%r is not within %r of %r" % (a, tol, b))

    def test_docked_at_desktop(self):
        with self.open(H, "d") as pg:
            reduce_motion(pg)
            self.assertEqual(pg.smoke["errors"], [])
            s = self.st(pg)
            self.assertFalse(s["open"])
            self.assertFalse(s["shown"], "closed drawer is not rendered")
            self.assertIn("dr-docked", s["cls"].split())

            pg.click(ROW)
            s = self.wait_open(pg)
            self.assertEqual(s["role"], "complementary")
            self.assertIsNone(s["modal"])
            self.assertEqual(s["label"], "Details")
            self.assertEqual(s["backdrops"], 0, "docked mode has no backdrop")
            self.assertTrue(s["inside"], "focus moves into the drawer on open")
            self.assertTrue(s["parentDocked"])
            self.assertIn("sel=device:foh-cl5", s["hash"])
            self.assertNotIn("drawer=", s["hash"])
            r = pg.rect("#app-inspector")
            self.assertNear(r["right"], 1280)
            self.assertNear(r["width"], 360)
            self.assertNear(pg.rect("#app-main")["right"], r["left"], msg="main area sits beside the docked column")

            pg.js("(function () { var l = %s; l[l.length - 1].focus(); })()" % FOCUSABLES)
            pg.press("Tab")
            self.assertFalse(self.st(pg)["inside"], "docked drawer does not trap focus")
            pg.press("Escape")
            self.assertTrue(self.st(pg)["open"], "Esc with focus outside the docked drawer leaves it open")

            pg.click("#dr-h-name")
            pg.press("Escape")
            s = self.st(pg)
            self.assertTrue(s["open"] and s["host"], "first Esc in a field leaves the field")
            pg.press("Escape")
            s = self.wait_open(pg, False)
            self.assertEqual(s["active"], "device:foh-cl5", "focus returns to the opener")
            self.assertIsNone(s["sec"])
            self.assertNotIn("sel=", s["hash"])
            self.assertFalse(s["parentDocked"])
            self.assertIn("onClose: escape", s["log"])

            pg.click("[data-canvas='device:foh-cl5']")
            s = self.wait_open(pg)
            self.assertEqual(s["active"], "device:foh-cl5", "canvas selection at lg keeps focus on the canvas")
            self.assertNotIn("drawer=0", s["hash"])
            self.assertFalse(pg.js("document.getElementById('dr-h-selbar').getClientRects().length > 0"))
            pg.shot("drawer-d")

    def test_sheet_at_tablet(self):
        with self.open(H, "t") as pg:
            reduce_motion(pg)
            pg.click("[data-open='cable:c-0001']")
            s = self.wait_open(pg)
            self.assertIn("dr-sheet", s["cls"].split())
            self.assertEqual(s["role"], "dialog")
            self.assertEqual(s["modal"], "true")
            self.assertEqual(s["label"], "Details")
            self.assertEqual(s["backdrops"], 1)
            self.assertTrue(s["inside"])
            r = pg.rect("#app-inspector")
            self.assertNear(r["right"], 820)
            self.assertNear(r["width"], 420)
            self.assertNear(r["top"], 0)
            self.assertNear(r["bottom"], 1180)

            n = pg.js(FOCUSABLES + ".length")
            seen = set()
            for _ in range(n + 2):
                pg.press("Tab")
                s = self.st(pg)
                self.assertTrue(s["inside"], "Tab stays in the modal drawer")
                seen.add(pg.js("(function () { var l = %s; return l.indexOf(document.activeElement); })()" % FOCUSABLES))
            self.assertEqual(seen, set(range(n)), "Tab visits every control and wraps")
            for _ in range(n + 2):
                pg.press("Shift+Tab")
                self.assertTrue(self.st(pg)["inside"], "Shift+Tab stays in the modal drawer")

            pg.js("document.getElementById('app-inspector').focus()")
            pg.press("Escape")
            s = self.wait_open(pg, False)
            self.assertEqual(s["backdrops"], 0)
            self.assertEqual(s["active"], "cable:c-0001", "focus returns to the opener")
            self.assertNotIn("sel=", s["hash"])

            pg.click(ROW)
            self.wait_open(pg)
            tap_at(pg, 40, 900)
            s = self.wait_open(pg, False)
            self.assertIn("onClose: backdrop", s["log"])
            self.assertEqual(s["active"], "device:foh-cl5")

            pg.click("[data-canvas='device:foh-cl5']")
            pg.wait_for("document.getElementById('dr-h-selbar').getClientRects().length > 0")
            s = self.st(pg)
            self.assertFalse(s["open"], "canvas selection below lg keeps the drawer closed")
            self.assertIn("drawer=0", s["hash"])
            pg.click("#dr-h-selbar-open")
            s = self.wait_open(pg)
            self.assertNotIn("drawer=", s["hash"])
            self.assertIn("sel=device:foh-cl5", s["hash"])
            pg.shot("drawer-t")
            pg.js("history.back()")
            s = self.wait_open(pg, False)
            self.assertIn("drawer=0", s["hash"], "Back closes a drawer opened from closed")

    def test_full_at_phone(self):
        with self.open(H + "#sel=device:foh-cl5&sec=inventory", "m") as pg:
            reduce_motion(pg)
            s = self.wait_open(pg)
            self.assertIn("dr-full", s["cls"].split())
            self.assertEqual(s["role"], "dialog")
            self.assertEqual(s["backdrops"], 1)
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=inventory]').open"))
            r = pg.rect("#app-inspector")
            self.assertNear(r["left"], 0)
            self.assertNear(r["right"], 390)
            self.assertNear(r["bottom"], 844)
            self.assertNear(r["height"], 844 * 0.88, 3)
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.offscreen("#app-inspector button"), 0)
            close = pg.rect(".dr-h-close")
            self.assertGreaterEqual(close["width"], 44)
            self.assertGreaterEqual(close["height"], 44)
            pg.shot("drawer-m")

            pg.press("Escape")
            s = self.wait_open(pg, False)
            self.assertNotIn("sel=", s["hash"])
            self.assertLessEqual(pg.page_hscroll(), 0)

            pg.click("[data-open='device:foh-cl5'][data-sec]")
            self.wait_open(pg)
            pg.reload()
            s = self.wait_open(pg)
            self.assertIn("sec=inventory", s["hash"])
            self.assertTrue(pg.js("document.querySelector('#app-inspector details[data-section=inventory]').open"),
                            "reload reopens the drawer at the same section")
            self.assertTrue(s["inside"])

    def test_escape_order(self):
        with self.open(H, "t") as pg:
            reduce_motion(pg)
            pg.click(ROW)
            self.wait_open(pg)
            pg.click(".dr-h-dialog-btn")
            pg.wait_for("document.activeElement && document.activeElement.id === 'dr-h-dialog-input'")
            pg.press("Escape")
            s = self.st(pg)
            self.assertFalse(pg.js("!!document.getElementById('dr-h-dialog')"), "Esc closes the dialog first")
            self.assertTrue(s["open"], "the drawer below the dialog stays open")
            self.assertTrue(s["inside"])

            # Like the shell's globalKeys: closes the assistant on Esc without preventDefault, before the
            # drawer's bubble listener runs. The drawer must judge the layers as they were when Esc arrived.
            pg.js("""(function () {
              var a = Object.assign(document.createElement('div'), {id: 'app-assistant', className: 'open'});
              document.body.appendChild(a);
              document.body.addEventListener('keydown', function (e) { if (e.key === 'Escape') a.classList.remove('open'); });
            })()""")
            pg.press("Escape")
            self.assertFalse(pg.js("document.getElementById('app-assistant').classList.contains('open')"))
            self.assertTrue(self.st(pg)["open"], "Esc closed the assistant above the drawer, not the drawer")
            pg.press("Escape")
            self.wait_open(pg, False)

    def test_relayout_across_breakpoints(self):
        with self.open(H, "d") as pg:
            reduce_motion(pg)
            pg.click(ROW)
            self.assertEqual(self.wait_open(pg)["backdrops"], 0)
            resize(pg, 820, 1180)
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-sheet')")
            s = self.st(pg)
            self.assertEqual((s["role"], s["modal"], s["backdrops"], s["parentDocked"]), ("dialog", "true", 1, False))
            self.assertTrue(s["inside"])
            resize(pg, 390, 844)
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-full')")
            self.assertEqual(pg.js("window.__drawer.mode()"), "full")
            resize(pg, 1280, 900)
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-docked')")
            s = self.st(pg)
            self.assertEqual((s["role"], s["modal"], s["backdrops"], s["parentDocked"], s["open"]), ("complementary", None, 0, True, True))
            pg.command("Emulation.setEmulatedMedia", {"media": "print"})
            self.assertFalse(self.st(pg)["shown"], "the open drawer is not printed (app.css print rule)")
            reduce_motion(pg)
            pg.js("window.__drawer.destroy()")
            s = self.st(pg)
            self.assertEqual(s["label"], "Inspector", "destroy restores the host's attributes")
            self.assertIsNone(s["role"])
            self.assertFalse(s["parentDocked"])
            self.assertFalse([c for c in s["cls"].split() if c.startswith("dr-")])

    def test_slide_motion_respects_reduced_motion(self):
        with self.open(H, "t") as pg:
            pg.click(ROW)
            s = self.wait_open(pg)
            self.assertEqual(s["anim"], "dr-in-right")
            time.sleep(0.3)
            pg.js("document.getElementById('app-inspector').focus()")
            pg.press("Escape")
            self.wait_open(pg, False)
            reduce_motion(pg)
            pg.click(ROW)
            self.assertEqual(self.wait_open(pg)["anim"], "none")
