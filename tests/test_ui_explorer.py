"""EXPLORER: headless-Chrome tests of ``js/explorer.js`` on its dev harness (docs/ui-audit.md B.2 EXPLORER).

Drives ``/static/dev/explorer.html`` through ``tests/_ui.py``: resize and collapse persist across reload
(``fathom.ui.explorer.<key>``), list keyboard and chips, and at phone size the slide-in drawer (``.ex-open``,
Esc, backdrop, focus trap, ``setSelected`` closes it) with no page horizontal scroll. Skips without Chrome.
"""
from __future__ import annotations

import json
import unittest

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/explorer.html"
KEY = "fathom.ui.explorer.harness-devices"


SETTLED = ("__ex.handle.isOpen() && getComputedStyle(document.querySelector('.ex-side')).transform === 'none'"
           " && document.querySelector('.ex-side').getBoundingClientRect().left >= 0")


def open_drawer(pg):
    pg.wait_for("!__ex.handle.isOpen() && getComputedStyle(document.querySelector('.ex-side')).visibility === 'hidden'")
    pg.click(".ex-open")
    pg.wait_for(SETTLED)


def stored(pg):
    raw = pg.js("localStorage.getItem(%s)" % json.dumps(KEY))
    return json.loads(raw) if raw else None


class ExplorerUi(UiCase):
    def _drag(self, pg, x0, y, x1):
        pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x0, "y": y})
        pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x0, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
        steps = 6
        for i in range(1, steps + 1):
            x = x0 + (x1 - x0) * i / steps
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
        pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x1, "y": y, "button": "left", "buttons": 0, "clickCount": 1})

    def test_resize_persists_across_reload(self) -> None:
        with self.open(HARNESS + "#device=sound-board", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 300, "default width")
            self.assertEqual(pg.js("document.querySelector('.ex-resizer').getAttribute('aria-valuenow')"), "300")
            r = pg.rect(".ex-resizer")
            x0 = r["left"] + r["width"] / 2
            self._drag(pg, x0, r["top"] + 200, x0 + 100)
            pg.wait_for("Math.round(document.querySelector('.ex-side').getBoundingClientRect().width) === 400")
            self.assertEqual(stored(pg), {"w": 400, "c": False})
            pg.reload()
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 400, "width survives reload")
            self.assertEqual(pg.js("document.querySelector('.ex-resizer').getAttribute('aria-valuenow')"), "400")

            pg.js("document.querySelector('.ex-resizer').focus(); 1")
            pg.press("ArrowRight")
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 416, "ArrowRight is +16px")
            pg.press("End")
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 480)
            self._drag(pg, pg.rect(".ex-resizer")["left"] + 6, 300, 900)
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 480, "drag is clamped to 480")
            pg.press("Home")
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 240)
            pg.press("ArrowLeft")
            self.assertEqual(round(pg.rect(".ex-side")["width"]), 240, "clamped to 240")
            self.assertEqual(stored(pg), {"w": 240, "c": False})
            pg.shot("explorer-resized-d")

    def test_touch_resize_at_tablet(self) -> None:
        with self.open(HARNESS, "t") as pg:
            self.assertEqual(pg.js("__ex.handle.mode()"), "side")
            r = pg.rect(".ex-resizer")
            x0, y = r["left"] + r["width"] / 2, r["top"] + 300
            pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y}]})
            for i in range(1, 6):
                pg.command("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + 12 * i, "y": y}]})
            pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            pg.wait_for("Math.round(document.querySelector('.ex-side').getBoundingClientRect().width) === 360")
            pg.wait_for("JSON.parse(localStorage.getItem(%s) || '{}').w === 360" % json.dumps(KEY))
            self.assertLessEqual(pg.page_hscroll(), 0)

    def test_collapse_persists_and_shows_rail(self) -> None:
        for size in ("d", "t"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.querySelector('.ex-collapse').getAttribute('aria-expanded')"), "true")
                pg.click(".ex-collapse")
                pg.wait_for("document.querySelector('.ex-root').classList.contains('ex-collapsed')")
                self.assertEqual(stored(pg), {"w": 300, "c": True})
                pg.reload()
                self.assertTrue(pg.js("document.querySelector('.ex-root').classList.contains('ex-collapsed')"), "collapsed after reload")
                self.assertEqual(round(pg.rect(".ex-side")["width"]), 56, "56px rail")
                rail = pg.rect(".ex-rail")
                self.assertGreater(rail["width"], 0, "rail visible")
                self.assertEqual(pg.js("document.querySelectorAll('.ex-rail a.ex-rail-item[href]').length"), 4)
                self.assertIsNone(pg.js("document.querySelector('.ex-list').offsetParent"), "list hidden in the rail")
                self.assertEqual(pg.js("document.querySelector('.ex-collapse').getAttribute('aria-expanded')"), "false")
                self.assertEqual(pg.js("getComputedStyle(document.querySelector('.ex-resizer')).display"), "none")
                min_tap = 44 if size == "t" else 40
                for sel in (".ex-collapse", ".ex-rail-item"):
                    box = pg.rect(sel)
                    self.assertGreaterEqual(min(box["width"], box["height"]), min_tap, sel)
                pg.shot("explorer-collapsed-" + size)
                pg.click(".ex-collapse")
                pg.wait_for("!document.querySelector('.ex-root').classList.contains('ex-collapsed')")
                self.assertEqual(round(pg.rect(".ex-side")["width"]), 300)
                self.assertEqual(stored(pg), {"w": 300, "c": False})

    def test_list_keyboard_search_and_chips(self) -> None:
        with self.open(HARNESS + "#device=sound-board", "d") as pg:
            self.assertEqual(pg.js("document.querySelectorAll('.ex-list > li.ex-item[role=option]').length"), 12)
            self.assertEqual(pg.js("document.querySelector('.ex-list').getAttribute('role')"), "listbox")
            self.assertEqual(pg.js("document.querySelector('.ex-item[aria-selected=true]').getAttribute('data-id')"), "sound-board")
            self.assertEqual(pg.js("document.querySelector('.ex-count').textContent"), "12 devices \u00b7 Main Auditorium")
            self.assertEqual(pg.js("document.querySelectorAll('.ex-group').length"), 3, "Audio, Video, Network")

            pg.js("document.querySelector('.ex-list').focus(); 1")
            active = "document.querySelector('.ex-item.ex-active').getAttribute('data-id')"
            self.assertEqual(pg.js(active), "sound-board", "focus starts on the selected item")
            pg.press("ArrowDown")
            self.assertEqual(pg.js(active), "audio-rack-1")
            pg.press("End")
            last = pg.js(active)
            pg.press("ArrowDown")
            self.assertEqual(pg.js(active), "wireless-mics", "ArrowDown wraps to the first item")
            pg.press("ArrowUp")
            self.assertEqual(pg.js(active), last, "ArrowUp wraps to the last item")
            pg.press("Home")
            pg.press("Enter")
            pg.wait_for("location.hash === '#device=wireless-mics'")
            pg.wait_for("document.querySelector('.ex-item[aria-selected=true]').getAttribute('data-id') === 'wireless-mics'")
            pg.wait_for("document.getElementById('ex-harness-title').textContent === 'Wireless Mics'")

            pg.js("document.querySelector('.ex-list').focus(); 1")
            pg.press("a")
            pg.press("t")
            pg.press("e")
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.ex-search')"), "typing focuses search")
            self.assertEqual(pg.js("document.querySelector('.ex-search').value"), "ate")
            self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.ex-item'), function (li) { return li.getAttribute('data-id'); })"),
                             ["atem-mini"])
            pg.press("Escape")
            self.assertEqual(pg.js("document.querySelector('.ex-search').value"), "", "Esc clears the filter")

            pg.click(".ex-chip[data-chip=video]")
            self.assertEqual(pg.js("document.querySelector('.ex-chip[data-chip=video]').getAttribute('aria-pressed')"), "true")
            self.assertEqual(pg.js("document.querySelectorAll('.ex-item').length"), 3)
            pg.click(".ex-chip[data-chip=network]")
            self.assertEqual(pg.js("document.querySelectorAll('.ex-item').length"), 4, "chips are OR")
            self.assertEqual(pg.js("document.querySelector('.ex-count').textContent"), "4 of 12 devices \u00b7 Main Auditorium")
            pg.js("var s = document.querySelector('.ex-search'); s.value = 'zzz'; s.dispatchEvent(new Event('input')); 1")
            self.assertFalse(pg.js("document.querySelector('.ex-empty').hidden"), "empty state shown")
            self.assertIn("zzz", pg.js("document.querySelector('.ex-empty').textContent"))

            pg.js("var s = document.querySelector('.ex-search'); s.value = ''; s.dispatchEvent(new Event('input')); 1")
            pg.click(".ex-chip[data-chip=video]")
            pg.click(".ex-chip[data-chip=network]")
            pg.click(".ex-item[data-id=atem-mini] a")
            pg.wait_for("location.hash === '#device=atem-mini'")
            self.assertEqual(pg.smoke["errors"], [])
            pg.shot("explorer-d")

    def test_phone_drawer(self) -> None:
        with self.open(HARNESS + "#device=sound-board", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at m")
            self.assertEqual(pg.js("__ex.handle.mode()"), "drawer")
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('.ex-side')).visibility"), "hidden",
                             ".ex-side hidden until .ex-open")
            btn = pg.rect(".ex-open")
            self.assertGreaterEqual(btn["height"], 44)
            self.assertEqual(pg.js("document.querySelector('.ex-open').textContent"), "\u2630 Devices (12)")
            self.assertLess(btn["top"], pg.rect(".h-page")["top"], ".ex-open sits at the top of the content")

            open_drawer(pg)
            side = pg.rect(".ex-side")
            rem = pg.js("parseFloat(getComputedStyle(document.documentElement).fontSize)")
            self.assertAlmostEqual(side["width"], min(390 * 0.85, 24 * rem), delta=1.5, msg="85vw, max 24rem")
            self.assertEqual(pg.js("document.querySelector('.ex-side').getAttribute('aria-modal')"), "true")
            self.assertFalse(pg.js("document.querySelector('.ex-backdrop').hidden"))
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.ex-search')"), "focus moves into the drawer")
            self.assertEqual(pg.js("document.querySelector('.ex-open').getAttribute('aria-expanded')"), "true")
            for sel in (".ex-item > a", ".ex-chip", ".ex-close", ".ex-search"):
                self.assertGreaterEqual(pg.rect(sel)["height"], 44, sel)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("explorer-drawer-m")

            for _ in range(30):
                pg.press("Tab")
            self.assertTrue(pg.js("document.querySelector('.ex-side').contains(document.activeElement)"), "focus is trapped")
            pg.press("Escape")
            pg.wait_for("!__ex.handle.isOpen()")
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.ex-open')"), "focus returns to .ex-open")
            pg.wait_for("getComputedStyle(document.querySelector('.ex-side')).visibility === 'hidden'")

            open_drawer(pg)
            pg.js("__ex.handle.setSelected('sound-board'); 1")
            self.assertTrue(pg.js("__ex.handle.isOpen()"), "same id keeps the drawer open")
            pg.js("__ex.handle.setSelected('atem-mini'); 1")
            self.assertFalse(pg.js("__ex.handle.isOpen()"), "setSelected with a new id closes the drawer")

            open_drawer(pg)
            pg.click(".ex-item[data-id=video-converter] a")
            pg.wait_for("location.hash === '#device=video-converter'")
            self.assertFalse(pg.js("__ex.handle.isOpen()"), "picking an item closes the drawer")
            pg.wait_for("document.getElementById('ex-harness-title').textContent === 'Video Converter'")

            open_drawer(pg)
            pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 370, "y": 420}]})
            pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            pg.wait_for("!__ex.handle.isOpen()")
            open_drawer(pg)
            pg.click(".ex-close")
            pg.wait_for("!__ex.handle.isOpen()")
            pg.js("__ex.handle.open(); __ex.handle.close(); 1")
            self.assertFalse(pg.js("__ex.handle.isOpen()"), "close() closes (drag start)")
            self.assertEqual(pg.smoke["errors"], [])
            pg.shot("explorer-m")

    def test_no_page_hscroll_and_side_mode(self) -> None:
        for size in ("t", "m"):
            with self.subTest(size=size), self.open(HARNESS + "?many=200", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.querySelectorAll('.ex-item').length"), 212)
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.js("__ex.handle.mode()"), "drawer" if size == "m" else "side")
                if size == "t":
                    self.assertFalse(pg.js("__ex.handle.isOpen()"))
                    self.assertEqual(pg.js("getComputedStyle(document.querySelector('.ex-open')).display"), "none")
                    self.assertEqual(pg.offscreen(".ex-foot .ex-collapse"), 0, "collapse button reachable")
                    pg.shot("explorer-t")
                else:
                    open_drawer(pg)
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    self.assertEqual(pg.offscreen(".ex-foot"), 0, "drawer footer on screen %r %r" % (pg.rect(".ex-foot"), pg.rect(".ex-side")))


if __name__ == "__main__":
    unittest.main()
