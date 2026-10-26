"""PT: patch table Blocks/Rows modes (docs/ui-audit.md B.3 PT, D1 `mode`/`q`, D4 row → drawer, D8, D9).

Runs against the real app on a ``tests/_ui.py`` server (``campus-demo`` sample, ``sunday-demo``
fixture) and the ``/static/dev/patchtable.html`` harness. Skips without Chrome; set
``FATHOM_CHROME=/usr/bin/google-chrome-stable``. With ``FATHOM_UI_SHOTS`` set it writes
``table-<d|t|m>.png`` (the default mode at that size) and ``table-rows-<d|t|m>.png``.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

TABLE = "#/campus-demo/main/table"
HARNESS = "/static/dev/patchtable.html"
IDS = ("pt-mode", "pt-filter-text", "pt-filter-room", "pt-filter-disc", "pt-only-patched", "pt-show-overlay",
       "pt-csv", "pt-print", "pt-split")
HIDDEN_SM = ("room", "signal", "medium")
SHOWN = ("device", "port", "dir", "peer_device", "peer_port", "tag", "remove")

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")


def mode_ready(pg, mode: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (m) {
      var r = document.querySelector('.pt-root');
      if (!r || r.getAttribute('data-mode') !== m) return false;
      return m === 'rows' ? !!document.querySelector('.pt-rows tr.dt-row') : !!document.querySelector('.pt-block');
    })(%s)""" % json.dumps(mode), timeout)


def displayed(pg, selector: str) -> int:
    return int(pg.js("""Array.prototype.filter.call(document.querySelectorAll(%s), function (el) {
      var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
    }).length""" % json.dumps(selector)))


def errors(pg) -> list:
    return pg.js("(window.__fathomErrors || []).slice()")


def id_counts(pg) -> dict:
    return pg.js("(function (ids) { var o = {}; ids.forEach(function (i) { o[i] = document.querySelectorAll('#' + i).length; }); return o; })(%s)"
                 % json.dumps(list(IDS)))


class PatchTableUi(UiCase):
    def test_default_mode_ids_and_no_clipping(self):
        for size, mode in (("d", "blocks"), ("t", "blocks"), ("m", "rows")):
            with self.subTest(size=size), self.open(TABLE, size) as pg:
                mode_ready(pg, mode)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(id_counts(pg), dict((i, 1) for i in IDS), "every #pt-* id exactly once")
                pressed = pg.js("document.querySelector('#pt-mode [aria-pressed=true]').getAttribute('data-mode')")
                self.assertEqual(pressed, mode, "default mode at %s" % size)
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll")
                for b in pg.js("""Array.prototype.map.call(document.querySelectorAll('#pt-mode button, #pt-print'), function (b) {
                  var r = b.getBoundingClientRect(); return {id: b.id || b.getAttribute('data-mode'), w: r.width, h: r.height};
                })"""):
                    self.assertGreaterEqual(min(b["w"], b["h"]), 44 if size != "d" else 40, b)
                pg.shot("table-" + size)
                if size == "m":
                    pg.goto(TABLE + "?mode=blocks")
                    mode_ready(pg, "blocks")
                if size != "d":
                    self.assert_blocks_unclipped(pg)

    def assert_blocks_unclipped(self, pg):
        n = pg.js("document.querySelectorAll('.pt-block button.pt-x').length")
        self.assertGreater(n, 50, "campus has many Remove patch buttons")
        self.assertEqual(pg.offscreen(".pt-block button", "x"), 0, "no .pt-block button clipped sideways")
        self.assertLessEqual(pg.page_hscroll(), 0)
        w = pg.js("document.querySelector('.pt-block button.pt-x').getBoundingClientRect().width")
        self.assertGreaterEqual(w, 44, "Remove patch keeps its 44px touch target")

    def test_rows_columns_at_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(TABLE + "?mode=rows", size) as pg:
                mode_ready(pg, "rows")
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.getElementById('pt-filter-text').classList.contains('dt-search')"), True)
                self.assertEqual(pg.js("document.getElementById('pt-csv').matches('a.dt-csv[download]')"), True)
                self.assertTrue(pg.js("!!document.querySelector('.dt-root[data-table=patch-rows]')"))
                for col in SHOWN:
                    self.assertEqual(displayed(pg, ".pt-rows thead th[data-col=%s]" % col), 1, "%s shown at %s" % (col, size))
                for col in HIDDEN_SM:
                    self.assertEqual(displayed(pg, ".pt-rows thead th[data-col=%s]" % col), 0 if size == "m" else 1,
                                     "%s (hideOnMobile) at %s" % (col, size))
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll in rows mode")
                self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('.pt-rows th'), function (t) { return !!t.getAttribute('scope'); })"))
                if size != "d":
                    h = pg.js("document.querySelector('.pt-rows .pt-remove').getBoundingClientRect().height")
                    self.assertGreaterEqual(h, 44, "row Remove patch is a 44px target on touch")
                pg.shot("table-rows-" + size)

    def test_mode_and_query_survive_reload(self):
        for size in ("d",):
            with self.subTest(size=size), self.open(TABLE + "?mode=rows&q=kick", size) as pg:
                for _ in range(2):
                    mode_ready(pg, "rows")
                    self.assertEqual(pg.js("document.getElementById('pt-filter-text').value"), "kick")
                    rows = pg.js("Array.prototype.map.call(document.querySelectorAll('.pt-rows tr.dt-row'), function (tr) { return tr.textContent.toLowerCase(); })")
                    self.assertTrue(rows, "kick matches rows")
                    self.assertTrue(all("kick" in r for r in rows), rows)
                    self.assertIn("mode=rows", pg.hash)
                    self.assertIn("q=kick", pg.hash)
                    pg.reload()

    def test_toggle_persists_and_shares_the_filter(self):
        with self.open(TABLE, "d") as pg:
            mode_ready(pg, "blocks")
            pg.click("#pt-filter-text")
            pg.js("(function (i) { i.value = 'drum'; i.dispatchEvent(new Event('input', {bubbles: true})); })(document.getElementById('pt-filter-text'))")
            pg.wait_for("location.hash.indexOf('q=drum') > 0")
            pg.wait_for("document.querySelectorAll('.pt-block[data-device=drum-mics]').length === 1")
            pg.click("#pt-mode [data-mode=rows]")
            mode_ready(pg, "rows")
            self.assertIn("mode=rows", pg.hash)
            self.assertEqual(pg.js("document.getElementById('pt-filter-text').value"), "drum", "one filter text across modes")
            stored = json.loads(pg.js("localStorage.getItem('fathom.ui.table.campus-demo.patch-rows')"))
            self.assertEqual(stored["extra"]["mode"], "rows", "explicit choice in the table state's extra.mode")
            pg.click(".pt-rows thead th[data-col=port] .dt-sort")
            pg.wait_for("location.hash.indexOf('sort=port') > 0")
            pg.goto("#/campus-demo/main/patch")
            pg.wait_for("!!document.querySelector('.pv-viewport')")
            pg.goto(TABLE)
            mode_ready(pg, "rows")
            pg.click("#pt-mode [data-mode=blocks]")
            mode_ready(pg, "blocks")
            self.assertEqual(id_counts(pg), dict((i, 1) for i in IDS))
            self.assertEqual(pg.js("document.getElementById('pt-csv').tagName"), "BUTTON", "blocks keeps the server-equal CSV button")
            self.assertNotIn("sort=", pg.hash, "table-only keys leave the URL in blocks mode")
            pg.goto(TABLE + "?mode=rows")
            mode_ready(pg, "rows")
            pg.goto(TABLE + "?mode=blocks")
            mode_ready(pg, "blocks")
            self.assertEqual(errors(pg), [])

    def test_row_click_opens_port_drawer_in_place(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(TABLE + "?mode=rows", size) as pg:
                mode_ready(pg, "rows")
                dev, port = pg.js("(function (tr) { return [tr.getAttribute('data-device'), tr.getAttribute('data-port')]; })(document.querySelector('.pt-rows tr.dt-row[data-port]:not([data-port=\"\"])'))")
                pg.click(".pt-rows tr.dt-row[data-port='%s'] td[data-col=dir]" % port)
                pg.wait_for(DRAWER_OPEN)
                h = pg.hash
                self.assertTrue(h.startswith(TABLE), "view segment unchanged: %s" % h)
                self.assertIn("sel=port:%s:%s" % (dev, port), h)
                if size == "m":
                    pg.reload()
                    pg.wait_for(DRAWER_OPEN)
                    self.assertTrue(pg.hash.startswith(TABLE))

    def test_bulk_remove_confirms_scope(self):
        with self.open(TABLE + "?mode=rows", "d") as pg:
            mode_ready(pg, "rows")
            picked = pg.js("""(function () {
              var seen = {}, out = [];
              Array.prototype.forEach.call(document.querySelectorAll('.pt-rows tr.dt-row'), function (tr) {
                var c = tr.querySelector('.dt-row-check'), cable = tr.getAttribute('data-cable');
                if (out.length < 2 && c && !c.disabled && cable && !seen[cable]) { seen[cable] = 1; out.push([tr.getAttribute('data-id'), cable]); }
              });
              return out;
            })()""")
            self.assertEqual(len(picked), 2)
            for row_id, _ in picked:
                pg.click(".pt-rows tr.dt-row[data-id=%s] .dt-row-check" % json.dumps(row_id))
            pg.wait_for("!document.querySelector('.pt-rows .dt-bulk').hidden")
            pg.click(".pt-rows .dt-bulk-act")
            msg = pg.wait_for("(document.querySelector('.app-dialog .body') || {}).textContent")
            self.assertEqual(msg, "Remove 2 patches in Main Auditorium?")
            pg.js("Array.prototype.filter.call(document.querySelectorAll('.app-dialog footer button'), function (b) { return b.textContent === 'Remove 2 patches'; })[0].click()")
            gone = " && ".join("!document.querySelector('.pt-rows tr[data-cable=%s]')" % json.dumps(c) for _, c in picked)
            pg.wait_for(gone)
            self.assertTrue(pg.js("document.querySelector('.pt-rows .dt-bulk').hidden"), "selection cleared")
            self.assertEqual(errors(pg), [])

    def test_harness_both_modes_and_viewer(self):
        with self.open(HARNESS, "d") as pg:
            mode_ready(pg, "blocks")
            self.assertTrue(pg.js("document.querySelectorAll('th').length > 0"))
            self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('th'), function (t) { return !!t.getAttribute('scope'); })"))
            pg.click("#pt-mode [data-mode=rows]")
            mode_ready(pg, "rows")
            self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('th'), function (t) { return !!t.getAttribute('scope'); })"))
            self.assertTrue(pg.js("document.querySelectorAll('.pt-rows .pt-remove').length > 0"))
            pg.click(".pt-rows tr.dt-row[data-port]:not([data-port='']) td[data-col=dir]")
            pg.wait_for("!!window.__harness.store.selection && window.__harness.store.selection.type === 'port'")
            self.assertEqual(errors(pg), [])
        with self.open(HARNESS + "?readonly=1", "d") as pg:
            mode_ready(pg, "blocks")
            self.assertEqual(pg.js("document.querySelectorAll('.pt-block .pt-x, .pt-block .pt-patch').length"), 0, "viewer: no edit controls in blocks")
            pg.click("#pt-mode [data-mode=rows]")
            mode_ready(pg, "rows")
            self.assertEqual(pg.js("document.querySelectorAll('.pt-rows .pt-remove, .pt-rows .pt-patch, .pt-rows .dt-check, .pt-rows th[data-col=remove]').length"), 0,
                             "viewer: no remove column, Patch… buttons or checkboxes in rows")
            self.assertEqual(errors(pg), [])
