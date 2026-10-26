"""ROUTER: smoke test of the shared headless-Chrome helper ``tests/_ui.py`` (docs/ui-audit.md D10).

Proves the helpers other UI units build on: sizes, ready state, real clicks, reload, geometry, key
presses and request interception, on ``campus-demo``.
"""
from __future__ import annotations

import os
import tempfile
import unittest

try:
    from _ui import SIZES, UiCase
except ImportError:  # pragma: no cover
    from tests._ui import SIZES, UiCase

PATCH = "#/campus-demo/main/patch"
OVERLAY = "/api/v2/projects/campus-demo/overlay"


class UiHelperSmoke(UiCase):
    def test_sizes_ready_and_geometry(self) -> None:
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(PATCH, size) as pg:
                self.assertIs(pg.smoke.get("ready"), True, pg.smoke)
                self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
                w, hgt, touch = SIZES[size]
                self.assertEqual(pg.js("[innerWidth, innerHeight]"), [w, hgt])
                self.assertEqual(pg.js("matchMedia('(pointer: coarse)').matches"), touch)
                self.assertEqual(pg.hash, PATCH)
                top = pg.rect("#app-top")
                self.assertIsInstance(top, dict)
                self.assertGreater(top["width"], 0)
                self.assertIsNone(pg.rect("#no-such-element"))
                self.assertIsInstance(pg.offscreen("#app-top"), int)
                self.assertEqual(pg.offscreen("#no-such-element"), 0)
                self.assertIsInstance(pg.page_hscroll(), int)
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at 390px")

    def test_click_reload_press_goto_shot(self) -> None:
        with self.open(PATCH, "d") as pg:
            pg.click("[data-view=table]")
            pg.wait_for("location.hash.indexOf('/table') > 0")
            self.assertNotEqual(pg.hash, PATCH)
            moved = pg.hash
            pg.reload()
            self.assertEqual(pg.hash, moved, "reload keeps the hash")
            self.assertIs(pg.smoke.get("ready"), True)

            pg.js("window.__keys = []; addEventListener('keydown', function (e) {"
                  " __keys.push((e.metaKey ? 'Meta+' : '') + e.key); }, true); 1")
            pg.press("Escape")
            pg.press("Meta+k")
            pg.press("ArrowDown")
            self.assertEqual(pg.js("__keys"), ["Escape", "Meta+k", "ArrowDown"])
            pg.press("Escape")

            pg.goto("#/campus-demo/main/schedules")
            pg.wait_for("!!document.querySelector('#app-main') && location.hash.indexOf('/schedules') > 0")

            old = os.environ.get("FATHOM_UI_SHOTS")
            with tempfile.TemporaryDirectory() as d:
                os.environ["FATHOM_UI_SHOTS"] = d
                try:
                    path = pg.shot("router-smoke-d")
                finally:
                    if old is None:
                        os.environ.pop("FATHOM_UI_SHOTS", None)
                    else:
                        os.environ["FATHOM_UI_SHOTS"] = old
                self.assertTrue(path and os.path.getsize(path) > 1000)
                with open(path, "rb") as f:
                    self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
            if not old:
                self.assertIsNone(pg.shot("not-written"))

    def test_tap_at_phone_size(self) -> None:
        with self.open(PATCH, "m") as pg:
            pg.js("window.__taps = 0; document.addEventListener('click', function () { __taps++; }, true); 1")
            pg.click("#app-top")
            pg.wait_for("__taps > 0", 5)

    def test_intercept_overlay_500(self) -> None:
        with self.open(PATCH, "d", intercepts=[(OVERLAY, 500, {"error": "forced by test"}, "GET")]) as pg:
            self.assertIs(pg.smoke.get("ready"), True, pg.smoke)
            self.assertGreaterEqual(pg.rules[0]["hits"], 1, "overlay request was intercepted")
            status = pg.js("fetch('/api/v2/projects/campus-demo/overlay').then(function (r) { return r.status; })")
            self.assertEqual(status, 500)
            self.assertEqual(pg.js("fetch('/api/v2/projects/campus-demo').then(function (r) { return r.status; })"), 200,
                             "other requests are not touched")
            self.assertTrue(pg.js("document.querySelectorAll('#app-main *').length > 0"), "page still renders")
            pg.clear_intercepts()
            self.assertEqual(pg.js("fetch('/api/v2/projects/campus-demo/overlay').then(function (r) { return r.status; })"), 200)


if __name__ == "__main__":
    unittest.main()
