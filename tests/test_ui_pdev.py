"""PDEV: the device landing table and the device page (docs/ui-audit.md B.3 PDEV).

Runs against campus-demo (``#/campus-demo/main/devices``); ``foh-cl5`` has 24 ports and 8 cables.
Skips without Chrome. ``FATHOM_UI_SHOTS=<dir>`` writes landing/overview/ports screenshots at d, t and m.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

LAND = "#/campus-demo/main/devices"
DEV = LAND + "/foh-cl5"
ROWS = "document.querySelectorAll('.pd-body tr.dt-row').length"


class DeviceUi(UiCase):
    def ready(self, pg, tab=None) -> None:
        if tab:
            pg.wait_for("!!document.querySelector('.eh-tab[data-tab=%s][aria-selected=true]')" % tab)
            pg.wait_for("!!document.querySelector('.pd-body > *')")
        else:
            pg.wait_for("document.querySelectorAll('.pd-landing tr.dt-row').length > 0")

    def no_errors(self, pg) -> None:
        self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def test_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(LAND, size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.ready(pg)
                self.assertEqual(pg.js("document.querySelectorAll('.pd-landing tr.dt-row').length"), 49)
                self.assertIn("Main Auditorium", pg.js("document.querySelector('.pd-sub').textContent"))
                self.assertLessEqual(pg.page_hscroll(), 0, "landing at %s scrolls horizontally" % size)
                pg.shot("landing-" + size)
                pg.goto(DEV)
                self.ready(pg, "overview")
                self.assertEqual(pg.js("document.querySelectorAll('.pd-card').length") > 3, True)
                self.assertLessEqual(pg.page_hscroll(), 0, "overview at %s scrolls horizontally" % size)
                compact = pg.js("document.querySelector('.eh').classList.contains('eh--compact')")
                self.assertEqual(compact, size == "m")
                pg.shot("overview-" + size)
                pg.goto(DEV + "/ports")
                self.ready(pg, "ports")
                pg.wait_for(ROWS + " === 24")
                self.assertLessEqual(pg.page_hscroll(), 0, "ports at %s scrolls horizontally" % size)
                pg.shot("ports-" + size)
                self.no_errors(pg)

    def test_landing_url_state_and_row_click(self):
        with self.open(LAND, "d") as pg:
            self.ready(pg)
            pg.js("""(function () { var s = document.querySelector('.pd-landing .dt-search');
              s.value = 'cl5'; s.dispatchEvent(new Event('input', {bubbles: true})); })()""")
            pg.wait_for("location.hash.indexOf('q=cl5') > 0")
            self.assertTrue(pg.hash.startswith(LAND + "?"))
            pg.reload()
            pg.wait_for("document.querySelectorAll('.pd-landing tr.dt-row').length === 1")
            self.assertEqual(pg.js("document.querySelector('.pd-landing .dt-search').value"), "cl5")
            pg.click(".pd-landing tr.dt-row[data-id=foh-cl5] td[data-col=kind]")
            pg.wait_for("location.hash.indexOf('/devices/foh-cl5') > 0")
            self.ready(pg, "overview")
            self.assertNotIn("q=", pg.hash)
            self.no_errors(pg)

    def test_default_tab_replace_and_tab_in_url(self):
        with self.open(LAND, "d") as pg:
            self.ready(pg)
            n = pg.js("history.length")
            pg.goto(DEV)
            pg.wait_for("location.hash === %s" % json.dumps(DEV + "/overview"))
            self.assertEqual(pg.js("history.length"), n + 1, "the default tab must replace, not push")
            pg.click(".eh-tab[data-tab=cables]")
            pg.wait_for("location.hash === %s" % json.dumps(DEV + "/cables"))
            pg.wait_for(ROWS + " === 8")
            pg.goto(DEV + "/ports")
            pg.reload()
            self.ready(pg, "ports")
            self.assertEqual(pg.hash, DEV + "/ports")
            pg.goto(DEV + "/ports/omni-in-3")
            pg.wait_for("!!document.querySelector('.pd-body tr.dt-row.dt-hl[data-id=omni-in-3]')")
            pg.goto("#/campus-demo/main/devices/no-such-device")
            pg.wait_for("!!document.querySelector('.pd-notfound')")
            self.assertTrue(pg.js("!!document.querySelector('a.pd-back')"))
            self.no_errors(pg)

    def test_port_row_opens_drawer_and_reload_keeps_it(self):
        with self.open(DEV + "/ports", "d") as pg:
            self.ready(pg, "ports")
            pg.wait_for(ROWS + " === 24")
            pg.click(".pd-body tr.dt-row[data-id=omni-in-2] td[data-col=label]")
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
            pg.wait_for("location.hash.indexOf('sel=') > 0")
            h = pg.hash
            self.assertTrue(h.startswith(DEV + "/ports?"), h)
            self.assertIn("omni-in-2", h)
            pg.reload()
            self.ready(pg, "ports")
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
            self.assertTrue(pg.hash.startswith(DEV + "/ports?"))
            self.no_errors(pg)

    def test_sticky_header_and_explorer_width(self):
        with self.open(DEV + "/ports", "d") as pg:
            self.ready(pg, "ports")
            pg.wait_for(ROWS + " === 24")
            self.assertTrue(pg.js("getComputedStyle(document.querySelector('.ex-side')).display !== 'none'"))
            side, page = pg.rect(".ex-side"), pg.rect(".ex-content")
            self.assertLessEqual(side["right"], page["left"] + 1, "explorer sits beside the page at lg")
            pg.js("document.querySelector('.ex-content').scrollTop = 1500")
            pg.wait_for("document.querySelector('.eh').classList.contains('eh--stuck')")
            top = pg.rect(".eh")["top"]
            self.assertLessEqual(abs(top - pg.rect(".ex-content")["top"]), 2)
            w0 = pg.js("document.querySelector('.ex-side').getBoundingClientRect().width")
            pg.js("document.querySelector('.ex-resizer').focus()")
            for _ in range(3):
                pg.press("ArrowRight")
            pg.wait_for("document.querySelector('.ex-side').getBoundingClientRect().width > %f" % (w0 + 10))
            w1 = pg.js("Math.round(document.querySelector('.ex-side').getBoundingClientRect().width)")
            self.assertIn('"w":', pg.js("localStorage.getItem('fathom.ui.explorer.devices') || ''"))
            pg.reload()
            self.ready(pg, "ports")
            self.assertEqual(pg.js("Math.round(document.querySelector('.ex-side').getBoundingClientRect().width)"), w1)
            self.no_errors(pg)

    def test_mobile_explorer_drawer(self):
        with self.open(DEV + "/ports", "m") as pg:
            self.ready(pg, "ports")
            self.assertTrue(pg.js("document.querySelector('.eh').classList.contains('eh--compact')"))
            self.assertLessEqual(pg.page_hscroll(), 0)
            visible = "(function () { var r = document.querySelector('.ex-side').getBoundingClientRect(); return r.right > 0 && r.left < innerWidth && r.width > 0; })()"
            self.assertFalse(pg.js(visible), "explorer is a drawer at sm")
            pg.click(".ex-open")
            pg.wait_for("document.querySelector('.ex-root').classList.contains('ex-is-open')")
            pg.wait_for(visible)
            pg.wait_for("document.querySelectorAll('.ex-item').length === 49")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.ex-root').classList.contains('ex-is-open')")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.no_errors(pg)

    def test_overview_drill_and_delete_asks_with_scope(self):
        with self.open(DEV, "d") as pg:
            self.ready(pg, "overview")
            pg.click("button.pd-count[data-drill=cable]")
            pg.wait_for("!!document.querySelector('.dt-dialog-body tr.dt-row')")
            self.assertEqual(pg.js("document.querySelectorAll('.dt-dialog-body tr.dt-row').length"), 8)
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.dt-dialog-body')")
            self.assertEqual(pg.js("""[].filter.call(document.querySelectorAll('.eh-actions button'), function (b) {
              return !b.closest('.eh-menu') && /delete/i.test(b.textContent); }).length"""), 0)
            pg.click(".eh-more")
            pg.wait_for("!document.querySelector('.eh-menu').hidden")
            pg.click(".eh-menu .eh-menu-item.danger")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            self.assertIn("Delete FOH CL5 in Main Auditorium?", pg.js("document.querySelector('.app-dialog').textContent"))
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self.assertEqual(pg.hash, DEV + "/overview")
            self.assertTrue(pg.js("!!document.querySelector('.pd-cards')"))
            self.no_errors(pg)
