"""TABLE: browser tests of the shared DataTable on its dev harness (docs/ui-audit.md B.2 TABLE, D1, D3, D8).

Drives ``/static/dev/datatable.html`` (240 synthetic cables bound to the hash query, plus fixture-v2 ports)
at d, t and m through ``tests/_ui.py``. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import unittest

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/datatable.html"
MAIN = "#h-main"
STORE_KEY = "fathom.ui.table.dev.harness.main"


def _q(s: str) -> str:
    return json.dumps(s)


class DataTableUi(UiCase):
    def _open(self, size: str = "d", query: str = ""):
        return self.open(HARNESS + query, size)

    def _ready(self, pg) -> None:
        self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
        pg.wait_for("window.__dt && __dt.main && document.querySelectorAll('#h-main tbody tr.dt-row').length > 0")

    def _type(self, pg, selector: str, text: str) -> None:
        pg.click(selector)
        for ch in text:
            pg.press(ch)

    def _info(self, pg):
        return pg.js("__dt.main.info()")

    def _query(self, pg):
        return pg.js("(function () { var h = location.hash, i = h.indexOf('?'), o = {};"
                     " new URLSearchParams(i >= 0 ? h.slice(i + 1) : '').forEach(function (v, k) { o[k] = v; }); return o; })()")

    # ------------------------------------------------------------ search, sort, filter, URL, reload

    def test_search_sort_filter_write_the_url_and_survive_reload(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-count').textContent"), "240 cables")
            self._type(pg, "#h-search", "drum")
            pg.wait_for("__dt.main.info().filtered < 240")
            info = self._info(pg)
            self.assertGreater(info["filtered"], 0)
            count = pg.js("document.querySelector('#h-main .dt-count').textContent")
            self.assertEqual(count, "%d of 240 cables" % info["filtered"], "count text follows the search")
            self.assertEqual(self._query(pg).get("q"), "drum")

            th = "#h-main th[data-col=length]"
            self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-sort')" % _q(th)), "none")
            pg.click(th + " .dt-sort")
            pg.wait_for("document.querySelector(%s).getAttribute('aria-sort') === 'ascending'" % _q(th))
            pg.click(th + " .dt-sort")
            pg.wait_for("document.querySelector(%s).getAttribute('aria-sort') === 'descending'" % _q(th))
            self.assertEqual(self._query(pg).get("sort"), "-length")
            lens = pg.js("Array.prototype.map.call(document.querySelectorAll('#h-main tbody tr.dt-row td[data-col=length]'),"
                         " function (td) { return parseFloat(td.textContent); })")
            self.assertEqual(lens, sorted(lens, reverse=True), "rows are sorted by length, descending")

            pg.click("#h-state")
            pg.wait_for("!!document.querySelector('#h-main .dt-pop[data-col=state]')")
            vals = pg.js("Array.prototype.map.call(document.querySelectorAll('#h-main .dt-pop input[type=checkbox]'), function (i) { return i.value; })")
            self.assertIn("(empty)", vals, "the filter popover lists (empty)")
            self.assertEqual(pg.js("document.getElementById('h-state').getAttribute('aria-expanded')"), "true")
            pg.click("#h-main .dt-pop input[value='(empty)']")
            pg.wait_for("location.hash.indexOf('f.state=~') > 0")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('#h-main .dt-pop') && document.activeElement && document.activeElement.id === 'h-state'")
            filtered = self._info(pg)["filtered"]
            states = pg.js("__dt.main.info() && Array.prototype.map.call(document.querySelectorAll('#h-main tbody tr.dt-row td[data-col=state]'),"
                           " function (td) { return td.textContent; })")
            self.assertTrue(all(s == "\u2014" for s in states), states)

            pg.reload()
            self._ready(pg)
            self.assertEqual(pg.js("document.getElementById('h-search').value"), "drum")
            self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-sort')" % _q(th)), "descending")
            self.assertEqual(pg.js("document.querySelector('#h-state .dt-filter-n').textContent"), "1")
            self.assertEqual(self._info(pg)["filtered"], filtered)

    def test_storage_restores_sort_and_filters_on_a_fresh_visit(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.js("__dt.main.setState({sort: {col: 'tag', dir: -1}, filters: {state: ['spare']}, q: 'foh'}); 1")
            saved = json.loads(pg.js("localStorage.getItem(%s)" % _q(STORE_KEY)))
            self.assertEqual(saved["v"], 1)
            self.assertEqual(saved["sort"], {"col": "tag", "dir": -1})
            self.assertEqual(saved["filters"], {"state": ["spare"]})
            self.assertNotIn("q", saved, "search text is URL-only (D8 shape)")
            pg.goto(HARNESS)  # new document without the hash query: storage applies
            self._ready(pg)
            st = pg.js("__dt.main.getState()")
            self.assertEqual(st["sort"], {"col": "tag", "dir": -1})
            self.assertEqual(st["filters"], {"state": ["spare"]})
            self.assertEqual(st["q"], "")
            # URL beats storage
            pg.goto(HARNESS + "?fresh=1#/dev/main/datatable?sort=length&f.state=planned")
            self._ready(pg)
            st = pg.js("__dt.main.getState()")
            self.assertEqual(st["sort"], {"col": "length", "dir": 1})
            self.assertEqual(st["filters"], {"state": ["planned"]})

    def test_pagination_page_size_and_pg(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.js("var s = document.querySelector('#h-main .dt-size'); s.value = '25'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.wait_for("document.querySelector('#h-main .dt-pager').getAttribute('data-pages') === '10'")
            self.assertEqual(pg.js("document.querySelectorAll('#h-main tbody tr.dt-row').length"), 25)
            pg.click("#h-main .dt-next")
            pg.wait_for("location.hash.indexOf('pg=2') > 0")
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-range').textContent"), "26\u201350 of 240")
            pg.click("#h-main .dt-last")
            pg.wait_for("location.hash.indexOf('pg=10') > 0")
            self.assertTrue(pg.js("document.querySelector('#h-main .dt-next').disabled"))
            pg.reload()
            self._ready(pg)
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-pager').getAttribute('data-page')"), "10")
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-range').textContent"), "226\u2013240 of 240")

    def test_column_chooser_hides_a_column_across_reload_and_density(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.click("#h-columns > summary")
            pg.wait_for("document.getElementById('h-columns').open")
            pg.click("#h-columns input[data-col=notes]")
            pg.wait_for("!document.querySelector('#h-main th[data-col=notes]')")
            self.assertFalse(pg.js("!!document.querySelector('#h-main td[data-col=notes]')"))
            pg.click("#h-columns .dt-density")
            pg.wait_for("document.getElementById('h-main').classList.contains('dt-compact')")
            pg.press("Escape")
            pg.wait_for("!document.getElementById('h-columns').open")
            pg.reload()
            self._ready(pg)
            self.assertFalse(pg.js("!!document.querySelector('#h-main th[data-col=notes]')"), "still hidden after reload")
            self.assertTrue(pg.js("document.getElementById('h-main').classList.contains('dt-compact')"))
            self.assertEqual(json.loads(pg.js("localStorage.getItem(%s)" % _q(STORE_KEY)))["hidden"], ["notes"])

    def test_csv_link_holds_the_filtered_rows(self) -> None:
        with self._open("d") as pg:
            # connect-src 'self' blocks fetch(blob:) in the page; a download navigation is not affected.
            pg.command("Page.setBypassCSP", {"enabled": True})
            pg.reload()
            self._ready(pg)
            pg.js("__dt.main.setState({filters: {state: ['(empty)']}, sort: {col: 'tag', dir: 1}}); 1")
            filtered = self._info(pg)["filtered"]
            self.assertLess(filtered, 240)
            pg.wait_for("document.getElementById('h-csv').getAttribute('href').indexOf('blob:') === 0"
                        " && document.getElementById('h-csv').getAttribute('data-rows') === %s" % _q(str(filtered)))
            text = pg.js("fetch(document.getElementById('h-csv').href).then(function (r) { return r.text(); })")
            lines = text.split("\r\n")
            self.assertEqual(lines[-1], "", "CRLF after the last line")
            self.assertEqual(lines[0], "Tag,From,To,Medium,State,Length,Room,Notes")
            self.assertEqual(len(lines) - 2, filtered, "header plus exactly the filtered rows (all pages)")
            self.assertTrue(lines[1].startswith("A-"))
            self.assertEqual(pg.js("document.getElementById('h-csv').getAttribute('download')"), "synthetic-cables.csv")

    def test_rows_fire_dt_row_on_enter_and_click_but_not_from_controls(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.js("window.__rows = []; document.getElementById('h-main').addEventListener('dt:row', function (e) { __rows.push(e.detail.id); }); 1")
            first = pg.js("document.querySelector('#h-main tbody tr.dt-row').getAttribute('data-id')")
            pg.js("document.querySelector('#h-main tbody tr.dt-row').focus(); 1")
            pg.press("Enter")
            pg.wait_for("__rows.length === 1")
            self.assertEqual(pg.js("__rows[0]"), first)
            pg.press("ArrowDown")
            second = pg.js("document.activeElement.getAttribute('data-id')")
            self.assertNotEqual(second, first, "ArrowDown moves to the next row")
            pg.click("#h-main tbody tr.dt-row:nth-child(3) td[data-col=from]")
            pg.wait_for("__rows.length === 2")
            pg.click("#h-main tbody tr.dt-row:nth-child(4) .dt-row-check")
            pg.wait_for("__dt.main.getSelection().length === 1")
            self.assertEqual(pg.js("__rows.length"), 2, "the checkbox does not open the row")
            self.assertIn("onRow " + first, pg.js("__dt.events"))

    def test_select_all_selects_the_filtered_set_across_pages(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.js("__dt.main.setState({filters: {state: ['installed']}, pageSize: 25}); 1")
            filtered = self._info(pg)["filtered"]
            self.assertGreater(filtered, 25, "fixture spans several pages")
            label = pg.js("document.getElementById('h-select-all').getAttribute('aria-label')")
            self.assertEqual(label, "Select all %d matching" % filtered)
            pg.click("#h-main thead .dt-check-hit")
            pg.wait_for("__dt.main.getSelection().length === %d" % filtered)
            self.assertFalse(pg.js("document.querySelector('#h-main .dt-bulk').hidden"))
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-bulk-count').textContent"), "%d cables selected" % filtered)
            sel = pg.js("__dt.main.getSelection()")
            states = pg.js("(function (ids) { var by = {}; __dt.rows().forEach(function (r) { by[r.id] = r.state; });"
                           " return ids.map(function (i) { return by[i]; }); })(%s)" % json.dumps(sel))
            self.assertEqual(set(states), {"installed"})
            pg.click("#h-main .dt-bulk-act")
            pg.wait_for("__dt.main.getSelection().length === 0 && __dt.main.info().filtered === 0")
            self.assertTrue(pg.js("!document.querySelector('#h-main .dt-empty').hidden"))
            pg.click("#h-main .dt-clear")
            pg.wait_for("__dt.main.info().filtered === 240")

    def test_header_is_sticky_and_th_have_scope(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            self.assertEqual(pg.js("document.querySelectorAll('th:not([scope])').length"), 0, "every th has scope")
            self.assertEqual(pg.js("document.querySelector('#h-table caption').textContent"), "Synthetic cables")
            pg.js("__dt.main.setState({pageSize: 200}); 1")
            top0 = pg.rect("#h-main .dt-scroll")["top"]
            pg.js("document.querySelector('#h-main .dt-scroll').scrollTop = 2000; 1")
            pg.wait_for("document.querySelector('#h-main .dt-scroll').scrollTop > 500")
            th = pg.rect("#h-main thead th[data-col=tag]")
            self.assertLessEqual(abs(th["top"] - top0), 2, "thead stays at the top of the scroller (%r vs %r)" % (th["top"], top0))
            pg.shot("datatable-d")

    def test_phone_hides_mobile_columns_and_has_no_page_scroll(self) -> None:
        with self._open("m") as pg:
            self._ready(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            for col in ("medium", "room", "notes"):
                self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main th[data-col=%s]')).display" % col), "none", col)
                self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main td[data-col=%s]')).display" % col), "none", col)
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main td[data-col=tag]')).position"), "sticky")
            controls = "#h-main .dt-toolbar button, #h-main .dt-toolbar summary, #h-main .dt-search, #h-main .dt-csv, #h-main .dt-pager select"
            self.assertEqual(pg.offscreen(controls, "x"), 0, "toolbar controls fit the width")
            small = pg.js("Array.prototype.filter.call(document.querySelectorAll(%s), function (e) {"
                          " var r = e.getBoundingClientRect(); return r.height < 44; }).length" % _q(controls))
            self.assertEqual(small, 0, "44px targets under (pointer: coarse)")
            left0 = pg.rect("#h-main tbody tr.dt-row td[data-col=tag]")["left"]
            pg.js("document.querySelector('#h-main .dt-scroll').scrollLeft = 200; 1")
            pg.wait_for("document.querySelector('#h-main .dt-scroll').scrollLeft > 0")
            self.assertLessEqual(abs(pg.rect("#h-main tbody tr.dt-row td[data-col=tag]")["left"] - left0), 2, "first column stays put")
            pg.click("#h-state")
            pop = pg.rect("#h-main .dt-pop")
            self.assertGreaterEqual(pop["left"], 0)
            self.assertLessEqual(pop["right"], 390.5, "filter popover is a sheet inside the viewport")
            pg.press("Escape")
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.click("#h-columns > summary")
            self.assertTrue(pg.js("/wider screens/.test(document.querySelector('#h-columns .dt-cols-list').textContent)"))
            pg.shot("datatable-m")

    def test_phone_card_mode(self) -> None:
        with self._open("m", "?cards=1") as pg:
            self._ready(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main tbody tr.dt-row')).display"), "block")
            self.assertTrue(pg.js("(function (s) { return s.scrollWidth <= s.clientWidth + 1; })(document.querySelector('#h-main .dt-scroll'))"),
                            "cards do not scroll sideways")
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main td[data-col=from]'), '::before').content"), '"From"')
            pg.js("var s = document.querySelector('#h-main .dt-sort-select'); s.value = '-length'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.wait_for("location.hash.indexOf('sort=-length') > 0")
            self.assertGreater(pg.rect("#h-main .dt-sort-select")["height"], 0, "sort select is visible in card mode")
            pg.shot("datatable-m-cards")
        with self._open("d", "?cards=1") as pg:
            self._ready(pg)
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('#h-main tbody tr.dt-row')).display"), "table-row",
                             "cards apply only below 700px")

    def test_tablet_fits(self) -> None:
        with self._open("t") as pg:
            self._ready(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertNotEqual(pg.js("getComputedStyle(document.querySelector('#h-main th[data-col=notes]')).display"), "none",
                                "hideOnMobile columns show at md")
            pg.shot("datatable-t")

    def test_drill_down_dialog(self) -> None:
        for query in ("", "?appdialog=1"):
            with self.subTest(query=query), self._open("d", query) as pg:
                self._ready(pg)
                pg.click("#h-drill")
                pg.wait_for("!!document.querySelector('.app-dialog-backdrop .dt-dialog .dt-root')")
                self.assertEqual(pg.js("document.querySelector('.dt-dialog h2').textContent"), "15 cables")
                pg.wait_for("document.activeElement && document.activeElement.classList.contains('dt-search')")
                for ch in "rf":
                    pg.press(ch)
                pg.wait_for("document.querySelectorAll('.dt-dialog tbody tr.dt-row').length < 15")
                pg.press("Escape")  # first Esc clears the search
                if not query:
                    pg.wait_for("document.querySelectorAll('.dt-dialog tbody tr.dt-row').length === 15")
                    pg.press("Escape")
                pg.wait_for("!document.querySelector('.dt-dialog')")
                self.assertEqual(pg.js("document.activeElement && document.activeElement.id"), "h-drill", "focus returns to the opener")
                pg.click("#h-drill")
                pg.wait_for("!!document.querySelector('.dt-dialog tbody tr.dt-row')")
                pg.click(".dt-dialog tbody tr.dt-row td[data-col=from]")
                pg.wait_for("!document.querySelector('.dt-dialog')")
                pg.wait_for("__dt.events.some(function (e) { return e.indexOf('drill closed c-') === 0; })")
                self.assertTrue(pg.js("__dt.events.some(function (e) { return e.indexOf('drill row c-') === 0; })"))

    def test_loading_error_and_grouped_fixture_table(self) -> None:
        with self._open("d") as pg:
            self._ready(pg)
            pg.js("__dt.main.setLoading(true); 1")
            self.assertEqual(pg.js("document.querySelectorAll('#h-main tbody tr.dt-skel').length"), 8)
            self.assertEqual(pg.js("document.querySelectorAll('#h-main tbody tr.dt-skel td').length"), 8 * 9, "8 rows of the visible columns")
            pg.js("window.__retried = 0; __dt.main.setError(new Error('Server said no'), function () { __retried++; }); 1")
            self.assertEqual(pg.js("document.querySelector('#h-main .dt-error-text').textContent"), "Server said no")
            pg.click("#h-main .dt-retry")
            self.assertEqual(pg.js("__retried"), 1)
            pg.js("__dt.main.setRows(__dt.rows()); 1")
            self.assertTrue(pg.js("document.querySelector('#h-main .dt-error').hidden"))
            self.assertEqual(pg.js("document.querySelectorAll('#h-main tbody tr.dt-row').length"), 50)
            groups = pg.js("Array.prototype.map.call(document.querySelectorAll('[data-table=\"harness.ports\"] tr.dt-group th'), function (t) { return t.textContent; })")
            self.assertGreater(len(groups), 1)
            self.assertEqual(len(groups), len(set(groups)), "each device group appears once")
            self.assertFalse(pg.js("!!document.querySelector('[data-table=\"harness.ports\"] th[data-col=device]')"), "default-hidden column")
            pg.js("__dt.main.setHighlight('c-00200'); 1")
            pg.wait_for("!!document.querySelector('#h-main tr.dt-hl[data-id=c-00200]')")
            self.assertEqual(pg.js("__dt.main.info().page"), 4, "highlight jumps to the row's page")

    def test_twenty_thousand_rows_render_one_page(self) -> None:
        with self._open("d", "?rows=20000") as pg:
            self._ready(pg)
            stats = pg.smoke.get("stats") or {}
            self.assertEqual(stats.get("rows"), 20000)
            self.assertEqual(stats.get("domRows"), 50, "only the page is in the DOM")
            self.assertLess(stats.get("firstRenderMs"), 1500)
            search_ms = pg.js("__dt.time(function () { __dt.main.setState({q: 'foh'}); })")
            sort_ms = pg.js("__dt.time(function () { __dt.main.setState({sort: {col: 'tag', dir: -1}}); })")
            more_ms = pg.js("__dt.time(function () { __dt.main.setState({q: 'foh cl5 1'}); })")
            self.assertLess(search_ms, 500, "search %.0f ms" % search_ms)
            self.assertLess(sort_ms, 1500, "sort %.0f ms" % sort_ms)
            self.assertLess(more_ms, 300, "next keystroke %.0f ms" % more_ms)
            self.assertLessEqual(pg.js("document.querySelectorAll('#h-main tbody tr.dt-row').length"), 50)
            self.assertLessEqual(pg.page_hscroll(), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
