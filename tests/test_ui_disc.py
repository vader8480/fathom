"""Discovery view in headless Chrome (docs/ui-audit.md B.3 DISC, B.5 ST-ADMIN discovery, B.8).

Runs replay the recorded captures in ``tests/fixtures/discovery`` (``FATHOM_DISCOVERY_FIXTURES``), so
nothing touches the network. ``campus-demo`` gets two runs (the URL / layout tests); ``disc-copy`` (a copy
of it) gets one run that the promote test is free to change. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ENV = {"FATHOM_DISCOVERY_FIXTURES": str(ROOT / "tests" / "fixtures" / "discovery"), "FATHOM_DISCOVERY_FIXTURE_DELAY": "0.1"}
TABS = ["new", "matches", "connections", "networks", "unresolved", "changes", "runs"]
TABLE = "!!document.querySelector('.disc-tab-body .dt-table')"


class DiscoveryUi(UiCase):
    runs = []  # newest first, campus-demo
    copy_run = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls._old = {k: os.environ.get(k) for k in FIXTURE_ENV}
        os.environ.update(FIXTURE_ENV)
        super(DiscoveryUi, cls).setUpClass()
        projects = Path(cls.server.data) / "projects"
        shutil.copytree(str(projects / "campus-demo"), str(projects / "disc-copy"))
        older = cls._run("campus-demo")
        time.sleep(1.1)  # distinct `started` seconds, so the listing order is stable
        newer = cls._run("campus-demo")
        cls.runs = [newer, older]
        cls.copy_run = cls._run("disc-copy")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            super(DiscoveryUi, cls).tearDownClass()
        finally:
            for k, v in cls._old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @classmethod
    def _api(cls, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cls.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    @classmethod
    def _run(cls, project: str) -> str:
        base = "/api/v2/projects/%s/discovery/runs" % project
        rid = cls._api("POST", base, {"window": 10})["run"]["id"]
        t0 = time.time()
        while time.time() - t0 < 60:
            run = cls._api("GET", base + "/" + rid)["run"]
            if not run["active"]:
                assert run["status"] == "done", run
                return rid
            time.sleep(0.1)
        raise AssertionError("discovery run %s did not finish" % rid)

    def _open(self, path: str, size: str = "d", **kw):
        return self.open("#/campus-demo/main/" + path, size, **kw)

    def _query(self, pg) -> dict:
        return pg.js("""(function () {
          var h = location.hash, i = h.indexOf('?'), out = {};
          if (i >= 0) h.slice(i + 1).split('&').forEach(function (kv) {
            var p = kv.split('='); out[decodeURIComponent(p[0])] = decodeURIComponent((p[1] || '').replace(/\\+/g, ' '));
          });
          return out;
        })()""")

    # ------------------------------------------------------------------ URL (D1)

    def test_tab_and_run_live_in_the_url(self):
        newer, older = self.runs
        with self._open("discovery") as pg:
            pg.wait_for("location.hash.indexOf('/discovery/new?') > 0")
            self.assertEqual(self._query(pg).get("run"), newer)
            self.assertEqual(pg.js("history.length"), 2, "the canonical tab and run replace, not push")
            pg.wait_for(TABLE, 20)
            self.assertEqual(pg.js("document.querySelector('.disc-tab[aria-selected=true]').dataset.discTab"), "new")

            pg.click("[data-disc-tab=connections]")
            pg.wait_for("location.hash.indexOf('/discovery/connections?') > 0")
            self.assertEqual(self._query(pg).get("run"), newer, "a tab change keeps the run")
            pg.wait_for("document.querySelector('.disc-tab-body').dataset.discTab === 'connections'")
            pg.wait_for(TABLE)
            pg.js("history.back()")
            pg.wait_for("location.hash.indexOf('/discovery/new?') > 0")
            pg.wait_for("document.querySelector('.disc-tab-body').dataset.discTab === 'new'")

            pg.goto("#/campus-demo/main/discovery/unresolved?run=" + older)
            pg.reload()
            pg.wait_for("document.querySelector('.disc-tab-body') && document.querySelector('.disc-tab-body').dataset.discTab === 'unresolved'", 20)
            self.assertIn("/discovery/unresolved?run=" + older, pg.hash)
            pg.wait_for("document.querySelector('.disc-run-pick') && document.querySelector('.disc-run-pick').value === %s" % json.dumps(older))
            self.assertIn(older, pg.js("document.querySelector('.disc-run-id').textContent"))
            self.assertEqual(pg.smoke["errors"], [])

    def test_bad_tab_is_canonicalised(self):
        with self._open("discovery/nonsense") as pg:
            pg.wait_for("location.hash.indexOf('/discovery/new?run=') > 0", 20)
            pg.wait_for(TABLE, 20)

    def test_runs_tab_row_shows_that_run(self):
        newer, older = self.runs
        with self._open("discovery/runs?run=" + newer) as pg:
            pg.wait_for("document.querySelectorAll('.disc-tab-body tr[data-run]').length === 2", 20)
            self.assertTrue(pg.js("document.querySelector('tr[data-run=%s]').classList.contains('disc-run-shown')" % json.dumps(newer)))
            pg.click("tr[data-run=%s] td:last-child" % json.dumps(older))
            pg.wait_for("location.hash.indexOf('run=%s') > 0" % older)
            self.assertIn("/discovery/runs?", pg.hash)
            pg.wait_for("document.querySelector('.disc-run-pick').value === %s" % json.dumps(older))
            pg.wait_for("!!document.querySelector('tr[data-run=%s] .disc-shown')" % json.dumps(older))

    def test_table_state_round_trips_through_the_url(self):
        with self._open("discovery/new") as pg:
            pg.wait_for(TABLE, 20)
            total = pg.js("document.querySelectorAll('.disc-tab-body tr.dt-row').length")
            self.assertGreater(total, 3)
            pg.js("""(function () { var s = document.querySelector('.disc-tab-body .dt-search');
              s.value = 'computer'; s.dispatchEvent(new Event('input', {bubbles: true})); })()""")
            pg.wait_for("location.hash.indexOf('q=computer') > 0")
            n = pg.wait_for("(function () { var n = document.querySelectorAll('.disc-tab-body tr.dt-row').length; return n && n < %d ? n : 0; })()" % total)
            pg.click(".disc-tab-body .dt-sort[data-col=label]")
            pg.wait_for("location.hash.indexOf('sort=') > 0")
            pg.reload()
            pg.wait_for(TABLE, 20)
            self.assertEqual(self._query(pg).get("q"), "computer")
            self.assertEqual(pg.js("document.querySelector('.disc-tab-body .dt-search').value"), "computer")
            self.assertEqual(pg.js("document.querySelectorAll('.disc-tab-body tr.dt-row').length"), n)
            q = self._query(pg)
            pg.click("[data-disc-tab=matches]")
            pg.wait_for("location.hash.indexOf('/discovery/matches?') > 0")
            pg.wait_for(TABLE)
            self.assertEqual(self._query(pg), {"run": q["run"]}, "another tab starts from its own table state")
            self.assertEqual(pg.js("document.querySelector('.disc-tab-body .dt-search').value"), "")

    # ------------------------------------------------------------ layout (B.3, B.8)

    def test_three_sizes(self):
        for size in ("d", "t", "m"):
            with self._open("discovery", size) as pg:
                pg.wait_for(TABLE, 20)
                self.assertEqual(pg.smoke["errors"], [], size)
                sources = pg.js("""(function () { var d = document.querySelector('details.disc-sources');
                  return {open: d.open, text: d.querySelector('summary').textContent, n: d.getAttribute('data-configured')}; })()""")
                self.assertFalse(sources["open"], "configured sources stay collapsed")
                self.assertIn("4 sources configured", sources["text"])
                self.assertIn("Edit", sources["text"])
                self.assertIn("Run", pg.js("document.querySelector('.disc-age').textContent"))
                self.assertFalse(pg.js("document.querySelector('.disc-age').hidden"))
                if size in ("t", "m"):
                    top = pg.rect("[data-disc-tab=new]")["top"]
                    self.assertLess(top, pg.js("innerHeight"), "%s: the findings tabs show without scrolling" % size)
                if size == "t":
                    self.assertLess(pg.rect(".disc-tab-body .dt-table")["top"], pg.js("innerHeight"), "t: findings rows show without scrolling")
                for tab in TABS:
                    pg.click("[data-disc-tab=%s]" % tab)
                    pg.wait_for("document.querySelector('.disc-tab-body').dataset.discTab === %s" % json.dumps(tab))
                    pg.wait_for("!document.querySelector('.disc-tab-body .fb-skel-bar, .disc-tab-body .dt-skel')", 20)
                    pg.wait_for("!!document.querySelector('.disc-tab-body .dt-table, .disc-tab-body .fb-empty')", 20)
                    self.assertLessEqual(pg.page_hscroll(), 0, "%s/%s: no horizontal page scroll" % (size, tab))
                    self.assertEqual(pg.js("document.querySelectorAll('.disc table:not(.dt-table)').length"), 0, "%s/%s: every table is a DataTable" % (size, tab))
                    self.assertEqual(pg.offscreen("[data-disc-tab=%s]" % tab, "x"), 0, "%s/%s: the selected tab is scrolled into view" % (size, tab))
                pg.click("[data-disc-tab=new]")
                pg.wait_for("document.querySelector('.disc-tab-body').dataset.discTab === 'new'")
                pg.wait_for(TABLE)
                pg.js("(function () { for (var e = document.querySelector('.disc'); e; e = e.parentElement) e.scrollTop = 0; scrollTo(0, 0); })()")
                pg.shot("discovery-" + size)
                if size == "m":
                    for sel in (".disc-run-btn", ".disc-tab", ".disc-sources summary", ".disc-run-pick"):
                        self.assertGreaterEqual(pg.rect(sel)["height"], 43.5, "m: %s is a 44px target" % sel)
                    self.assertEqual(pg.js("getComputedStyle(document.querySelector('.disc-tabs')).flexWrap"), "nowrap")

    def test_no_sources_configured_opens_the_editor(self):
        st = self._api("GET", "/api/v2/projects/campus-demo/discovery/settings")
        for s in st["sources"]:
            s["settings"] = dict(s.get("settings") or {}, enabled=False)
        with self._open("discovery", "m", intercepts=[("/api/v2/projects/campus-demo/discovery/settings", 200, st, "GET")]) as pg:
            pg.wait_for("document.querySelector('details.disc-sources').getAttribute('data-configured') === '0'", 20)
            self.assertTrue(pg.js("document.querySelector('details.disc-sources').open"))
            self.assertIn("0 sources configured", pg.js("document.querySelector('.disc-sources summary').textContent"))
            self.assertLessEqual(pg.page_hscroll(), 0)

    # --------------------------------------------------------------- actions

    def test_matched_row_opens_the_device_drawer(self):
        with self._open("discovery/matches") as pg:
            pg.wait_for("!!document.querySelector('.disc-tab-body tr.disc-linked')", 20)
            self.assertGreater(pg.js("document.querySelectorAll('.disc-tab-body .disc-actions button').length"), 0, "row actions stay in .disc-actions")
            pg.click(".disc-tab-body tr.disc-linked .disc-name")
            pg.wait_for("location.hash.indexOf('sel=device') > 0")
            dev = self._query(pg)["sel"].split(":", 1)[1]
            self.assertIn("/discovery/matches?", pg.hash)
            doc = self._api("GET", "/api/v2/projects/campus-demo")
            doc = doc.get("doc", doc)
            name = [d.get("name") for d in doc["devices"] if d["id"] == dev][0]
            pg.wait_for("(document.getElementById('app-inspector').textContent || '').indexOf(%s) >= 0" % json.dumps(name))
            pg.click(".disc-tab-body tr.disc-linked select.disc-target")
            self.assertEqual(self._query(pg)["sel"], "device:" + dev, "controls inside a row do not reopen the drawer")

    def test_bulk_promote_confirms_scope(self):
        with self.open("#/disc-copy/main/discovery/new", "d") as pg:
            pg.wait_for(TABLE, 20)
            before = pg.js("document.querySelectorAll('.disc-tab-body tr.dt-row').length")
            pg.click(".disc-tab-body tr.dt-row:nth-child(1) .dt-row-check")
            pg.click(".disc-tab-body tr.dt-row:nth-child(2) .dt-row-check")
            pg.wait_for("!document.querySelector('.disc-tab-body .dt-bulk').hidden")
            pg.js("""Array.prototype.filter.call(document.querySelectorAll('.disc-tab-body .dt-bulk-act'),
                     function (b) { return b.textContent === 'Promote selected'; })[0].click()""")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            self.assertIn("2 hosts", pg.js("document.querySelector('.app-dialog').textContent"))
            pg.click(".app-dialog footer button:not(.primary)")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self.assertEqual(pg.js("document.querySelectorAll('.disc-tab-body tr.dt-row').length"), before, "cancel promotes nothing")
            pg.js("""Array.prototype.filter.call(document.querySelectorAll('.disc-tab-body .dt-bulk-act'),
                     function (b) { return b.textContent === 'Promote selected'; })[0].click()""")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("document.querySelectorAll('.disc-tab-body tr.dt-row').length === %d" % (before - 2), 20)
            self.assertIn("/discovery/new?run=" + self.copy_run, pg.hash)
            pg.click(".disc-tab-body tr.dt-row .disc-actions button.primary")
            pg.wait_for("document.querySelectorAll('.disc-tab-body tr.dt-row').length === %d" % (before - 3), 20)
            self.assertFalse(pg.js("!!document.querySelector('.app-dialog')"), "a single promote does not ask")

    def test_viewer_sees_no_write_controls(self):
        doc = self._api("GET", "/api/v2/projects/campus-demo")
        doc["role"] = "viewer"
        with self._open("discovery/new", "t", intercepts=[("/api/v2/projects/campus-demo", 200, doc, "GET")]) as pg:
            pg.wait_for(TABLE, 20)
            self.assertEqual(pg.smoke["errors"], [])
            for sel in (".disc-run-btn", ".disc-cancel", ".disc-card-acts", ".disc-tab-body .dt-row-check", ".disc-room-pick"):
                self.assertEqual(pg.js("document.querySelectorAll(%s).length" % json.dumps(sel)), 0, "viewer: no %s" % sel)
            self.assertEqual(pg.js("document.querySelectorAll('.disc-actions button:not([aria-expanded])').length"), 0, "viewer: only Evidence in row actions")
            self.assertIn("Details", pg.js("document.querySelector('.disc-sources summary').textContent"))
            self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('.disc-source-cards input'), function (i) { return i.disabled; })"))
            pg.click("[data-disc-tab=runs]")
            pg.wait_for("document.querySelectorAll('.disc-tab-body tr[data-run]').length === 2")


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
