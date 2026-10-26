"""SOP: the SOP wiki after the light-touch migration (docs/ui-audit.md B.3 SOP).

Covers the wide-screen landing (recents, review-due pages, pages per room), recents and the document
title on page open, the "Applies to" device chip opening the drawer with ``sec=procedures``, and the
problem reports DataTable ``sop.problems``, at d, t and m. The three SOP phone tests in
``test_frontend_smoke.py`` stay the guard for the phone flows. Skips without Chrome.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

SOP = "#/campus-demo/main/sop"
PROJECT_API = "/api/v2/projects/campus-demo"


class SopUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(SopUi, cls).setUpClass()
        # One page overdue for review and one open problem report, so the landing and the table have rows.
        rev = cls.api("GET", PROJECT_API)["revision"]
        cls.api("POST", PROJECT_API + "/changes", {"base_revision": rev, "summary": "review due",
                                                    "ops": [{"op": "merge", "coll": "pages", "id": "pg-shut-down", "value": {"review_due": "2020-01-01"}}]})
        cls.api("POST", PROJECT_API + "/problems", {"text": "Hum on the lectern mic", "page": "power-up", "device": "foh-cl5"})

    @classmethod
    def api(cls, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(cls.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def ready(self, pg, expr: str) -> None:
        self.assertEqual(pg.smoke.get("errors"), [], "no errors while mounting %s" % pg.hash)
        pg.wait_for(expr)

    # ------------------------------------------------------------ landing

    def test_landing_shows_recents_after_opening_power_up(self):
        for size in ("d", "t"):
            with self.subTest(size=size), self.open(SOP, size) as pg:
                self.ready(pg, "!!document.querySelector('.sop-landing')")
                self.assertFalse(pg.js("!!document.querySelector('.sop-placeholder')"), "the placeholder is replaced")
                self.assertFalse(pg.js("!!document.querySelector('.sop-landing-recent')"), "no recents in a fresh browser")
                land = pg.js("""({
                  due: Array.from(document.querySelectorAll('.sop-landing-due a[data-page]')).map(function (a) { return a.getAttribute('data-page'); }),
                  dueBadge: (document.querySelector('.sop-landing-due .fb-review') || {}).textContent || '',
                  dueRowBadge: !!document.querySelector('.sop-landing-due a[data-page=shut-down] .sop-badge-due'),
                  main: document.querySelectorAll('.sop-landing-room[data-room=main] a[data-page]').length,
                  chapel: document.querySelectorAll('.sop-landing-room[data-room=chapel] a[data-page]').length,
                  minTap: Math.min.apply(null, Array.from(document.querySelectorAll('.sop-landing-link')).map(function (a) { return a.getBoundingClientRect().height; })),
                })""")
                self.assertEqual(land["due"], ["shut-down"], "pages due for review (reviewState)")
                self.assertIn("1 due for review", land["dueBadge"], "reviewBadge counts the due pages")
                self.assertTrue(land["dueRowBadge"], "each due page carries its own review badge")
                self.assertGreaterEqual(land["main"], 3, "pages per room: Main Auditorium")
                self.assertEqual(land["chapel"], 1, "pages per room: Chapel (draft visible to editors)")
                self.assertGreaterEqual(land["minTap"], 44 if size == "t" else 40, "landing links are tap targets")
                more = pg.rect(".sop-tree-head .sop-more")
                self.assertGreaterEqual(min(more["width"], more["height"]) if size == "t" else more["width"], (44 if size == "t" else 40) - 0.5,
                                        "the procedures-tree \u22ef is a tap target")
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll")
                pg.shot("sop-" + size)

                pg.click(".sop-side .sop-item[data-page=power-up] .sop-item-main")
                pg.wait_for("!!document.querySelector('.sop-page[data-page=power-up] h1')")
                title = pg.js("document.querySelector('.sop-page h1').textContent")
                pg.wait_for("document.title.indexOf(%s) === 0" % json.dumps(title))
                stored = json.loads(pg.js("localStorage.getItem('fathom.ui.recent.campus-demo')") or "{}")
                self.assertEqual([e["id"] for e in stored.get("page", [])][:1], ["power-up"], "ctx.recent.push('page', slug)")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("sop-page-" + size)

                pg.click(".sop-page .sop-topbar .sop-back")
                pg.wait_for("!!document.querySelector('.sop-landing-recent a[data-page=power-up]')")
                pg.shot("sop-recent-" + size)
                self.assertTrue(pg.js("document.title.indexOf('SOPs') === 0"), "the tree restores the view title")
                pg.click(".sop-landing-recent a[data-page=power-up]")
                pg.wait_for("!!document.querySelector('.sop-page[data-page=power-up]')")
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def test_phone_keeps_the_tree_without_a_landing(self):
        with self.open(SOP, "m") as pg:
            self.ready(pg, "document.querySelectorAll('.sop-item').length > 0")
            self.assertFalse(pg.js("!!document.querySelector('.sop-landing')"), "the landing is wide-screen only")
            self.assertTrue(pg.js("!!document.querySelector('#app-tabbar [data-tab=sop]')"))
            self.assertLessEqual(pg.page_hscroll(), 0)
            more = pg.rect(".sop-tree-head .sop-more")
            self.assertGreaterEqual(min(more["width"], more["height"]), 44 - 0.5, "the procedures-tree \u22ef is a 44px target")
            pg.shot("sop-m")
            pg.goto(SOP + "?page=power-up")
            pg.wait_for("!!document.querySelector('.sop-page[data-page=power-up] h1')")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.offscreen("#sop-report", "x"), 0, "Report a problem is reachable")
            pg.shot("sop-page-m")

    # ------------------------------------------------------------ device chip → drawer

    def test_device_chip_opens_the_drawer_on_procedures(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(SOP + "?page=power-up", size) as pg:
                self.ready(pg, "!!document.querySelector('.sop-applies .chip[data-device]')")
                dev = pg.js("document.querySelector('.sop-applies .chip[data-device]').getAttribute('data-device')")
                pg.js("window.__sopPage = document.querySelector('.sop-page'); 1")
                pg.js("document.querySelector('.sop-applies .chip[data-device]').click(); 1")
                pg.wait_for("location.hash.indexOf('sec=procedures') > 0")
                self.assertIn("sel=device:" + dev, pg.hash)
                self.assertIn("/sop?page=power-up", pg.hash, "the view and page stay in the URL")
                pg.wait_for("document.querySelectorAll('#app-inspector [data-section=procedures] .ins-procs li').length > 0")
                self.assertTrue(pg.js("document.querySelector('.sop-page') === window.__sopPage"), "opening the drawer keeps the page")
                pg.js("history.back(); 1")
                pg.wait_for("location.hash.indexOf('sel=') < 0")
                self.assertIn("page=power-up", pg.hash)
                pg.wait_for("document.querySelector('.sop-page') === window.__sopPage")
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    # ------------------------------------------------------------ problems table

    def test_problem_reports_are_a_datatable(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(SOP + "?problems=1", size) as pg:
                self.ready(pg, "document.querySelectorAll('.dt-root[data-table=\"sop.problems\"] tr.sop-problem[data-problem]').length > 0")
                info = pg.js("""({
                  search: !!document.querySelector('.dt-root[data-table="sop.problems"] input.dt-search'),
                  csv: !!document.querySelector('.dt-root[data-table="sop.problems"] a.dt-csv'),
                  text: document.querySelector('tr.sop-problem .sop-problem-text').textContent,
                  resolve: !!document.querySelector('tr.sop-problem button[data-action=resolve]'),
                  chip: (document.querySelector('tr.sop-problem .sop-chip-device') || {}).textContent || '',
                  bare: document.querySelectorAll('.sop table:not(.dt-table)').length,
                })""")
                self.assertTrue(info["search"] and info["csv"], "DataTable toolbar (search, CSV)")
                self.assertIn("Hum on the lectern mic", info["text"])
                self.assertTrue(info["resolve"], "editors can resolve from the row")
                self.assertTrue(info["chip"], "device chip in the row")
                self.assertEqual(info["bare"], 0, "D9: no table outside the DataTable")
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll")
                if size == "m":
                    self.assertEqual(pg.offscreen("tr.sop-problem button[data-action=resolve]", "x"), 0, "Resolve is reachable on a phone")
                pg.shot("sop-problems-" + size)
                pg.js("var s = document.querySelector('.dt-root[data-table=\"sop.problems\"] input.dt-search'); s.value = 'zzzz-no-match'; s.dispatchEvent(new Event('input', {bubbles: true})); 1")
                pg.wait_for("document.querySelectorAll('tr.sop-problem').length === 0")
                pg.js("var s = document.querySelector('.dt-root[data-table=\"sop.problems\"] input.dt-search'); s.value = ''; s.dispatchEvent(new Event('input', {bubbles: true})); 1")
                pg.wait_for("document.querySelectorAll('tr.sop-problem').length > 0")
                pg.js("document.querySelector('tr.sop-problem .sop-chip-device').click(); 1")
                pg.wait_for("location.hash.indexOf('sec=problems') > 0")
                self.assertIn("problems=1", pg.hash)
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])


if __name__ == "__main__":
    import unittest
    unittest.main()
