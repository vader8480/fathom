"""TOUR: first-run coachmarks (tour.js, FR-UX-16) in the real app on a ``tests/_ui.py`` server.

Pages open without ``?smoke=1`` (``ready=False``) because the tour never auto-starts under the smoke flag;
``?tour=1`` forces it, ``?tour=0`` suppresses it. Skips without Chrome (``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import unittest

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/"
CARD = "document.querySelector('.tour-card[data-tour=card]')"
NO_CARD = "!document.querySelector('.tour-card')"
STEP = "(%s || {getAttribute: function () { return null; }}).getAttribute('data-step')" % CARD
COUNT = "(%s ? %s.querySelector('.tour-count').textContent : '')" % (CARD, CARD)


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading');
    })(%s)""" % json.dumps(view), timeout)


def tour_open(pg, timeout: float = 15.0):
    return pg.wait_for("!!" + CARD, timeout)


class TourUi(UiCase):
    def test_first_run_walks_the_steps_and_stores_the_key(self):
        with self.open(CAMPUS + "home", "d", ready=False) as pg:
            view_ready(pg, "home")
            tour_open(pg)
            self.assertEqual(pg.js(STEP), "0")
            self.assertEqual(pg.js(COUNT), "1 of 5")
            pg.wait_for("document.activeElement && document.activeElement.className === 'primary tour-next'", 5)
            self.assertTrue(pg.js(CARD + ".querySelector('.tour-back').disabled"), "Back disabled on the first step")
            # the cut-out frames the target
            hl = pg.rect(".tour-hl")
            target = pg.rect("#app-project")
            self.assertLessEqual(hl["left"], target["left"])
            self.assertGreaterEqual(hl["right"], target["right"])
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('.tour-hl')).boxShadow").count("9999px"), 1)
            self.assertIsNone(pg.js("localStorage.getItem('fathom.ui.tour')"), "nothing stored until the tour ends")
            pg.click(".tour-next")
            pg.wait_for(STEP + " === '1'")
            self.assertEqual(pg.js(COUNT), "2 of 5")
            self.assertEqual(pg.js(CARD + ".getAttribute('data-target')"), "#app-views, #app-tabbar")
            self.assertEqual(pg.js(CARD + ".querySelector('.tour-title').textContent"), "Sections")
            pg.shot("tour-step2-d")
            pg.click(".tour-back")
            pg.wait_for(STEP + " === '0'")
            for want in ("1", "2", "3", "4"):
                pg.click(".tour-next")
                pg.wait_for(STEP + " === '%s'" % want)
            self.assertEqual(pg.js(COUNT), "5 of 5")
            self.assertEqual(pg.js(CARD + ".querySelector('.tour-next').textContent"), "Done")
            # Tab stays inside the card
            pg.press("Tab")
            self.assertTrue(pg.js(CARD + ".contains(document.activeElement)"))
            pg.press("Tab")
            self.assertTrue(pg.js(CARD + ".contains(document.activeElement)"))
            pg.click(".tour-next")
            pg.wait_for(NO_CARD)
            self.assertFalse(pg.js("!!document.querySelector('.tour-backdrop, .tour-hl')"))
            stored = json.loads(pg.js("localStorage.getItem('fathom.ui.tour')"))
            self.assertIs(stored["done"], True)
            self.assertTrue(stored["at"].startswith("20"))
            self.assertEqual(pg.js("window.__fathomErrors"), [])
            # a reload does not start it again
            pg.reload(ready=False)
            view_ready(pg, "home")
            pg.wait_for("!!document.querySelector('#app-user')")
            pg.js("new Promise(function (r) { setTimeout(r, 900); })")
            self.assertTrue(pg.js(NO_CARD), "tour does not start again once fathom.ui.tour is set")
            # re-run from the user menu
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-tour')")
            pg.click("#app-menu-tour")
            tour_open(pg)
            self.assertEqual(pg.js(STEP), "0")
            pg.press("Escape")
            pg.wait_for(NO_CARD)
            self.assertEqual(pg.js("document.activeElement.id"), "app-user", "focus returns to the opener")

    def test_skip_and_escape_store_the_key(self):
        with self.open(CAMPUS + "patch", "d", ready=False) as pg:
            tour_open(pg)
            pg.click(".tour-skip")
            pg.wait_for(NO_CARD)
            stored = json.loads(pg.js("localStorage.getItem('fathom.ui.tour')"))
            self.assertIs(stored["done"], True)
            self.assertEqual(stored.get("reason"), "skip")
        with self.open(CAMPUS + "patch?tour=1", "d") as pg:
            tour_open(pg)
            self.assertEqual(pg.smoke["errors"], [])
            pg.press("Escape")
            pg.wait_for(NO_CARD)
            self.assertEqual(json.loads(pg.js("localStorage.getItem('fathom.ui.tour')")).get("reason"), "esc")
        with self.open(CAMPUS + "patch?tour=0", "d", ready=False) as pg:
            view_ready(pg, "patch")
            pg.js("new Promise(function (r) { setTimeout(r, 900); })")
            self.assertTrue(pg.js(NO_CARD), "?tour=0 never auto-starts")
        with self.open(CAMPUS + "patch", "d") as pg:
            view_ready(pg, "patch")
            pg.js("new Promise(function (r) { setTimeout(r, 900); })")
            self.assertTrue(pg.js(NO_CARD), "smoke runs see the plain shell")

    def test_shortcuts_dialog_offers_the_tour(self):
        with self.open(CAMPUS + "home", "d") as pg:
            pg.click("#app-user")
            pg.wait_for("!!document.querySelector('.app-menu')")
            pg.js("Array.prototype.filter.call(document.querySelectorAll('.app-menu button'), function (b) { return b.textContent === 'Keyboard shortcuts'; })[0].click(); 1")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            pg.js("Array.prototype.filter.call(document.querySelectorAll('.app-dialog footer button'), function (b) { return b.textContent === 'Take the tour'; })[0].click(); 1")
            tour_open(pg)
            self.assertFalse(pg.js("!!document.querySelector('.app-dialog')"), "the shortcuts dialog closed")

    def test_phone_docks_the_card_and_skips_hidden_targets(self):
        with self.open(CAMPUS + "home", "m", ready=False) as pg:
            view_ready(pg, "home")
            tour_open(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            card = pg.rect(".tour-card")
            self.assertGreaterEqual(card["width"], 380, "full-width sheet")
            self.assertGreaterEqual(card["bottom"], pg.js("window.innerHeight") - 1, "docked to the bottom")
            self.assertEqual(pg.js(CARD + ".getAttribute('data-side')"), "sheet")
            # #app-project is hidden at sm: the first step frames the room picker instead
            hl = pg.rect(".tour-hl")
            room = pg.rect("#app-room")
            self.assertLessEqual(hl["left"], room["left"] + 1)
            self.assertGreaterEqual(hl["right"], room["right"] - 1)
            for b in (".tour-skip", ".tour-back", ".tour-next"):
                self.assertGreaterEqual(pg.rect(b)["height"], 44, "%s is a 44 px target on touch" % b)
            pg.click(".tour-next")
            pg.wait_for(STEP + " === '1'")
            self.assertEqual(pg.js(COUNT), "2 of 4", "the Helper step (hidden button) is skipped at sm")
            # the highlight box animates into place (150 ms)
            pg.wait_for("Math.abs(document.querySelector('.tour-hl').getBoundingClientRect().top - (document.querySelector('#app-tabbar').getBoundingClientRect().top - 6)) <= 2", 5)
            pg.shot("tour-step2-m")
            pg.click(".tour-next")
            pg.wait_for(STEP + " === '2'")
            pg.click(".tour-next")
            pg.wait_for(STEP + " === '4'")
            self.assertEqual(pg.js(CARD + ".querySelector('.tour-next').textContent"), "Done")
            pg.click(".tour-next")
            pg.wait_for(NO_CARD)
            self.assertEqual(pg.js("window.__fathomErrors"), [])


if __name__ == "__main__":
    unittest.main()
