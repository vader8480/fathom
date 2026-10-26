"""SHELL: app shell layout, sections, nav memory, drawer and selection bar (docs/ui-audit.md B.2 SHELL, D1-D6).

Runs against the real app on a ``tests/_ui.py`` server (``sunday-demo`` fixture and ``campus-demo``
sample). Skips without Chrome; set ``FATHOM_CHROME=/usr/bin/google-chrome-stable``. With
``FATHOM_UI_SHOTS`` set it writes ``home``, ``patch`` and ``schedules`` screenshots at d, t and m.
"""
from __future__ import annotations

import json
import unittest

try:
    from _ui import UiCase
    from test_frontend_smoke import VIEWS
except ImportError:  # pragma: no cover
    from tests._ui import UiCase
    from tests.test_frontend_smoke import VIEWS

CAMPUS = "#/campus-demo/main/"
SUNDAY = "#/sunday-demo/main/"
SHOT_VIEWS = ("home", "patch", "schedules")

VISIBLE = """(function (sel) {
  return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }).length;
})(%s)"""

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")


def visible(pg, selector: str) -> int:
    return int(pg.js(VISIBLE % json.dumps(selector)))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading');
    })(%s)""" % json.dumps(view), timeout)


class ShellUi(UiCase):
    def test_sections_and_tab_bar(self):
        for size in ("d", "t"):
            with self.subTest(size=size), self.open(CAMPUS + "patch", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(visible(pg, "#app-views .app-sec"), 7, "7 section buttons (home is #app-home)")
                self.assertEqual(visible(pg, "#app-tabbar button"), 0)
                cur = pg.js("document.querySelector('#app-views .app-sec[aria-current=page]').getAttribute('data-section')")
                self.assertEqual(cur, "patch")
                self.assertEqual(pg.js("document.querySelectorAll('#app-subnav a.app-subtab[data-view][href]').length"), 3)
                self.assertTrue(visible(pg, "#app-subnav"))
                if size == "d":
                    self.assertEqual(visible(pg, "#app-views .app-sec .app-sec-label"), 7, "labels visible at d")
                    self.assertTrue(visible(pg, "#app-home"), "brand links home at lg")
        with self.open(CAMPUS + "sop", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            tabs = pg.js("""Array.prototype.map.call(document.querySelectorAll('#app-tabbar button[data-tab]'), function (b) {
              var r = b.getBoundingClientRect(); return {key: b.getAttribute('data-tab'), w: r.width, h: r.height, label: b.getAttribute('aria-label')};
            })""")
            self.assertEqual(len(tabs), 8)
            self.assertEqual([t["key"] for t in tabs], ["home", "patch", "rooms", "devices", "schedules", "sop", "data", "settings"])
            for t in tabs:
                self.assertGreaterEqual(t["w"], 40, t)
                self.assertGreaterEqual(t["h"], 40, t)
                self.assertTrue(t["label"], t)
            self.assertEqual(visible(pg, "#app-views"), 0, "#app-views hidden at m")
            self.assertEqual(visible(pg, "#app-subnav"), 0, "SOPs has one view: no subnav")
            self.assertEqual(pg.js("document.querySelector('#app-tabbar [aria-current=page]').getAttribute('data-tab')"), "sop")
            pg.click("#app-tabbar [data-tab=home]")
            view_ready(pg, "home")
            self.assertEqual(pg.js("location.hash"), CAMPUS + "home")

    def test_nav_memory(self):
        with self.open(CAMPUS + "schedules?q=drum", "d") as pg:
            view_ready(pg, "schedules")
            pg.goto(CAMPUS + "patch")
            view_ready(pg, "patch")
            pg.click("#app-views [data-section=schedules]")
            pg.wait_for("location.hash.indexOf('/schedules') > 0")
            view_ready(pg, "schedules")
            self.assertEqual(pg.js("location.hash"), CAMPUS + "schedules?q=drum", "remembered hash")
            pg.click("#app-views [data-section=schedules]")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "schedules"))
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "schedules?q=drum"))
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "patch"))
            view_ready(pg, "patch")
            stored = json.loads(pg.js("sessionStorage.getItem('fathom.ui.nav')"))
            self.assertEqual(stored["campus-demo"]["patch"], CAMPUS + "patch")

    def test_section_menu_lists_views(self):
        with self.open(CAMPUS + "patch", "d") as pg:
            pg.js("document.querySelector('#app-views [data-section=rooms]').focus(); 1")
            pg.press("ArrowDown")
            pg.wait_for("!document.querySelector('#app-views [data-section=rooms] + .app-sec-menu').hidden")
            views = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-views [data-section=rooms] + .app-sec-menu [data-view]'), function (b) { return b.getAttribute('data-view'); })")
            self.assertEqual(views, ["rooms", "plan", "racks"])
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-view')"), "rooms")
            pg.press("ArrowDown")
            pg.press("Enter")
            pg.wait_for("location.hash.indexOf('/plan') > 0")
            view_ready(pg, "plan")
            self.assertTrue(pg.js("document.querySelector('#app-views [data-section=rooms] + .app-sec-menu').hidden"))

    def test_banner_precedes_header(self):
        with self.open(SUNDAY + "patch", "d") as pg:
            order = pg.js("""(function () {
              var ids = Array.prototype.map.call(document.getElementById('app').children, function (c) { return c.id; });
              return ids;
            })()""")
            self.assertEqual(order, ["app-banner", "app-top", "app-views", "app-subnav", "app-body", "app-selbar", "app-tabbar"])

    def test_deep_link_opens_drawer(self):
        for size in ("m", "d"):
            with self.subTest(size=size), self.open(SUNDAY + "patch?sel=device:atem-mini", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('ATEM Mini') >= 0")
                self.assertTrue(pg.wait_for(DRAWER_OPEN))
                self.assertEqual(visible(pg, "#app-selbar"), 0)

    def test_drawer_closed_shows_selection_bar(self):
        with self.open(SUNDAY + "patch?sel=device:atem-mini&drawer=0", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))
            self.assertIn("ATEM Mini", pg.js("document.querySelector('#app-selbar .app-selbar-title').textContent"))
            bar = pg.rect("#app-selbar")
            tabbar = pg.rect("#app-tabbar")
            self.assertLessEqual(bar["bottom"], tabbar["top"] + 1, "selection bar sits above the tab bar")
            pg.click("#app-selbar .app-selbar-open")
            pg.wait_for(DRAWER_OPEN)
            pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('ATEM Mini') >= 0")
            self.assertNotIn("drawer=0", pg.js("location.hash"))
            self.assertIn("sel=device:atem-mini", pg.js("location.hash"))
            # opening pushed a history entry: Back closes the drawer and keeps the selection
            pg.js("history.back(); 1")
            pg.wait_for("location.hash.indexOf('drawer=0') > 0")
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))
            pg.click("#app-selbar .app-selbar-close")
            pg.wait_for("document.getElementById('app-selbar').hidden")
            self.assertNotIn("sel=", pg.js("location.hash"))

    def test_canvas_selection_below_lg_keeps_drawer_closed(self):
        with self.open(SUNDAY + "patch", "t") as pg:
            pg.wait_for("!!document.querySelector('.pv-card[data-device=atem-mini]')")
            pg.click(".pv-card[data-device=atem-mini] .pv-title")
            sel = pg.wait_for("(location.hash.match(/sel=([^&]*)/) || [])[1]")
            self.assertTrue(sel.startswith("device:atem-mini") or sel.startswith("port:atem-mini"), sel)
            self.assertIn("drawer=0", pg.js("location.hash"))
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))

    def test_no_page_hscroll_on_any_view(self):
        for size in ("m", "t"):
            with self.subTest(size=size), self.open(CAMPUS + "home", size) as pg:
                for i, v in enumerate(VIEWS):
                    with self.subTest(view=v):
                        if i or v != "home":
                            pg.goto(CAMPUS + v)
                        view_ready(pg, v)
                        self.assertLessEqual(pg.page_hscroll(), 0, "%s at %s scrolls horizontally" % (v, size))
                        if v in SHOT_VIEWS:
                            pg.shot("%s-%s" % (v, size))
                self.assertEqual(pg.js("window.__fathomErrors"), [])
        with self.open(CAMPUS + "home", "d") as pg:
            for v in SHOT_VIEWS:
                if v != "home":
                    pg.goto(CAMPUS + v)
                view_ready(pg, v)
                pg.shot("%s-d" % v)

    def test_search_palette_keyboard(self):
        with self.open(SUNDAY + "patch", "d") as pg:
            pg.press("Meta+k")
            pg.wait_for("!!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-palette-input")
            pg.press("Escape")
            pg.wait_for("!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-search")
            pg.click("#app-search")
            pg.wait_for("!!document.getElementById('app-palette')")

    def test_legacy_project_url_lands_on_home(self):
        with self.open("/?p=sunday-demo", "d") as pg:
            view_ready(pg, "home")
            self.assertTrue(pg.js("location.hash").startswith("#/sunday-demo/"))
            self.assertEqual(pg.js("location.hash").split("?")[0].split("/")[3], "home")

    def test_empty_view_canonicalizes_to_home_and_keeps_selection(self):
        with self.open("#/sunday-demo/main?sel=device:atem-mini", "d") as pg:
            view_ready(pg, "home")
            self.assertEqual(pg.js("location.hash"), SUNDAY + "home?sel=device:atem-mini")
            pg.wait_for(DRAWER_OPEN)

    def test_phone_user_menu_holds_header_actions(self):
        with self.open(CAMPUS + "patch", "m") as pg:
            for ident in ("app-undo", "app-redo", "app-assistant-btn", "app-project"):
                self.assertEqual(visible(pg, "#" + ident), 0, "#%s hidden at sm" % ident)
            for ident in ("app-room", "app-search", "app-notify", "app-save", "app-user"):
                self.assertEqual(visible(pg, "#" + ident), 1, "#%s shown at sm" % ident)
            pg.click("#app-user")
            pg.wait_for("!!document.querySelector('.app-menu')")
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('.app-menu button'), function (b) { return b.textContent; })")
            for want in ("Undo", "Redo", "Helper", "campus-demo", "sunday-demo", "New project\u2026"):
                self.assertTrue(any(l.startswith(want) for l in labels), "%r not in user menu %r" % (want, labels))
            self.assertLessEqual(pg.page_hscroll(), 0)


if __name__ == "__main__":
    unittest.main()
