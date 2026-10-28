"""SCH: the schedules view on the shared DataTable with routed tabs (docs/ui-audit.md B.3 SCH).

Runs against the real app on a ``tests/_ui.py`` server (``campus-demo`` sample, ``sunday-demo`` fixture)
and against the dev harness ``/static/dev/schedules.html``. Covered: ``schedules`` replaces to
``schedules/cables`` and every tab is ``schedules/<kind>`` (reload, back, unknown tabs, tab-less legacy
URLs); ``q``/``sort``/``pg`` survive reload; ``?sel=cable:…`` opens the drawer with the row highlighted and
in view; each kind's row opens its drawer (cable, device ``sec=net``/``dmx``/``inventory``, port, rack)
and multi-device BOM lines open a drill-down; the CSV and the print sheet hold every filtered row;
bulk add cables ends on its filtered result; the layout at d/t/m (hidden columns, sticky lead, no
horizontal page scroll); the Labels tab's *Device labels* section (Brady M511 presets, scope, preview /
ZIP / CSV links). Skips without Chrome; set ``FATHOM_CHROME=/usr/bin/google-chrome-stable``.
With ``FATHOM_UI_SHOTS`` set it writes ``schedules-<kind>-<size>`` screenshots.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/"
SUNDAY = "#/sunday-demo/main/"
HARNESS = "/static/dev/schedules.html"
TABLE_KINDS = ("cables", "ip", "dmx", "bom", "patch", "racks")
CABLE_HEADER = ("Tag,From room,From device,From port,To room,To device,To port,Medium,Type,Length,Unit,Color,"
                "Channels,Signal,Status,Bundle,Note,Id")
MOBILE_COLS = {
    "cables": ["tag", "from_device", "from_port", "to_device", "to_port"],
    "ip": ["device", "interface", "ip"],
    "dmx": ["universe", "address", "device"],
    "bom": ["model", "qty", "extended"],
    "patch": ["device", "port", "peer_device", "peer_port"],
    "racks": ["rack", "u", "device"],
}

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); if (!el) return false;"
               " var r = el.getBoundingClientRect(); return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

ROWS_READY = """(function (kind) {
  var t = document.querySelector('#sch-dt .dt-table');
  return !!t && t.getAttribute('data-kind') === kind && t.getAttribute('aria-busy') === 'false'
    && document.querySelectorAll('#sch-dt tbody tr.dt-row').length > 0;
})(%s)"""

IN_VIEW = """(function (sel) {
  var tr = document.querySelector(sel), sc = document.querySelector('#sch-dt .dt-scroll');
  if (!tr || !sc) return false;
  var a = tr.getBoundingClientRect(), b = sc.getBoundingClientRect();
  return a.height > 0 && a.top >= b.top - 1 && a.bottom <= b.bottom + 1 && a.bottom <= window.innerHeight + 1;
})(%s)"""

SHOWN = """(function (sel) {
  var el = document.querySelector(sel); if (!el) return false;
  var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
})(%s)"""


def q(s: str) -> str:
    return json.dumps(s)


def view_ready(pg, timeout: float = 20.0) -> None:
    pg.wait_for("""(function () {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === 'schedules' && !el.querySelector('.app-loading') && !!el.querySelector('.sch-root');
    })()""", timeout)


def rows_ready(pg, kind: str, timeout: float = 20.0) -> None:
    pg.wait_for(ROWS_READY % q(kind), timeout)


def selected_tab(pg) -> str:
    return pg.js("(document.querySelector('.sch-tabs [role=tab][aria-selected=true]') || {}).id || ''")


def shown(pg, sel: str) -> bool:
    return bool(pg.js(SHOWN % q(sel)))


class SchedulesUi(UiCase):

    def api(self, path: str):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read().decode("utf-8"))

    # ------------------------------------------------------------ routing

    def test_default_tab_is_replaced_into_the_url(self):
        with self.open(CAMPUS + "schedules", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables"))
            view_ready(pg)
            rows_ready(pg, "cables")
            pg.goto(CAMPUS + "patch")
            pg.wait_for("document.querySelector('#app-main > .app-view').getAttribute('data-view') === 'patch'")
            depth = pg.js("history.length")
            pg.goto(CAMPUS + "schedules")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables"))
            view_ready(pg)
            self.assertEqual(pg.js("history.length"), depth + 1, "the default tab is replaced, not pushed")
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "patch"))
            pg.js("history.forward(); 1")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables"))
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(selected_tab(pg), "sch-tab-cables")
            tabs = pg.js("""Array.prototype.map.call(document.querySelectorAll('.sch-tabs a[role=tab][href]'), function (a) {
              return [a.id, a.getAttribute('href'), a.getAttribute('aria-controls')]; })""")
            self.assertEqual([t[0] for t in tabs], ["sch-tab-" + k for k in TABLE_KINDS + ("labels",)])
            self.assertEqual([t[1] for t in tabs], [CAMPUS + "schedules/" + k for k in TABLE_KINDS + ("labels",)])
            self.assertTrue(all(t[2] == "sch-panel" for t in tabs))

    def test_tab_in_url_reload_and_back(self):
        with self.open(CAMPUS + "schedules/cables", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            pg.click("#sch-tab-ip")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/ip"))
            rows_ready(pg, "ip")
            self.assertEqual(selected_tab(pg), "sch-tab-ip")
            self.assertEqual(pg.js("document.activeElement.id"), "sch-tab-ip")
            pg.reload()
            view_ready(pg)
            rows_ready(pg, "ip")
            self.assertEqual(selected_tab(pg), "sch-tab-ip", "reload lands on IP")
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables"))
            rows_ready(pg, "cables")
            self.assertEqual(selected_tab(pg), "sch-tab-cables")
            pg.js("document.getElementById('sch-tab-cables').focus(); 1")
            pg.press("ArrowRight")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/ip"))
            rows_ready(pg, "ip")
            self.assertEqual(pg.js("document.activeElement.id"), "sch-tab-ip")
            pg.press("End")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/labels"))
            pg.wait_for("!!document.querySelector('.sch-labelbar #sch-state') && !document.querySelector('#sch-dt')")
            self.assertEqual(pg.js("document.getElementById('sch-csv').getAttribute('aria-disabled')"), "true")

    def test_unknown_and_tabless_urls(self):
        with self.open(CAMPUS + "schedules/nope?q=drum", "d") as pg:
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables?q=drum"))
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(pg.js("document.getElementById('sch-filter').value"), "drum")
            pg.goto(CAMPUS + "schedules/bogus")
            pg.wait_for("location.hash === %s" % q(CAMPUS + "schedules/cables"))
        with self.open(CAMPUS + "schedules?q=drum", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(selected_tab(pg), "sch-tab-cables")
            self.assertEqual(pg.js("location.hash"), CAMPUS + "schedules?q=drum", "tab-less URL with params is kept")
            self.assertEqual(pg.js("document.getElementById('sch-filter').value"), "drum")

    def test_table_state_in_url_survives_reload(self):
        with self.open(CAMPUS + "schedules/cables?sort=-from_port&pg=2", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            pg.wait_for("document.querySelector('#sch-dt .dt-pager').getAttribute('data-page') === '2'")
            self.assertEqual(pg.js("document.querySelector('#sch-dt th[data-col=from_port]').getAttribute('aria-sort')"), "descending")
            pg.js("""(function () { var s = document.getElementById('sch-filter'); s.focus(); s.value = 'snare';
              s.dispatchEvent(new Event('input', {bubbles: true})); })()""")
            pg.wait_for("location.hash.indexOf('q=snare') > 0 && location.hash.indexOf('pg=') < 0")
            pg.click("#sch-dt th[data-col=tag] .dt-sort")
            pg.wait_for("location.hash.indexOf('sort=tag') > 0")
            n = pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length")
            self.assertGreater(n, 0)
            pg.reload()
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(pg.js("document.getElementById('sch-filter').value"), "snare")
            self.assertEqual(pg.js("document.querySelector('#sch-dt th[data-col=tag]').getAttribute('aria-sort')"), "ascending")
            self.assertEqual(pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length"), n)
            self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('#sch-dt tbody tr.dt-row'), function (tr) { return /snare/i.test(tr.textContent); })"))
        with self.open(CAMPUS + "schedules/patch?pg=3", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "patch")
            self.assertEqual(pg.js("document.querySelector('#sch-dt .dt-pager').getAttribute('data-page')"), "3")
            pg.click("#sch-dt .dt-next")
            pg.wait_for("location.hash.indexOf('pg=4') > 0")
            pg.reload()
            view_ready(pg)
            rows_ready(pg, "patch")
            self.assertEqual(pg.js("document.querySelector('#sch-dt .dt-pager').getAttribute('data-page')"), "4")

    # ------------------------------------------------------------ drawers

    def test_sel_deep_link_opens_drawer_with_row_highlighted(self):
        rows = self.api("/api/v2/projects/campus-demo/schedules/cables?room=main")["rows"]
        cid = rows[70]["id"]
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "schedules/cables?sel=cable:" + cid, size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg)
                rows_ready(pg, "cables")
                pg.wait_for(DRAWER_OPEN)
                sel = "#sch-dt tr.dt-row.dt-hl[data-id=%s]" % q(cid)
                pg.wait_for("!!document.querySelector(%s)" % q(sel))
                self.assertEqual(pg.js("document.querySelector('#sch-dt .dt-pager').getAttribute('data-page')"), "2",
                                 "the highlighted row's page is shown")
                pg.wait_for(IN_VIEW % q(sel), 5)
        with self.open(CAMPUS + "schedules?sel=cable:c-0001", "t") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            pg.wait_for(DRAWER_OPEN)
            self.assertEqual(selected_tab(pg), "sch-tab-cables", "legacy schedules?sel= lands on cables")
            pg.wait_for("!!document.querySelector('#sch-dt tr.dt-hl[data-id=\"c-0001\"]')")

    def _row_opens(self, pg, kind, cell, expect_sel, expect_sec=None):
        pg.goto(CAMPUS + "schedules/" + kind)
        rows_ready(pg, kind)
        target = "#sch-dt tbody tr.dt-row td[data-col=%s]" % cell
        rid = pg.js("document.querySelector(%s).parentNode.getAttribute('data-id')" % q(target))
        pg.click(target)
        pg.wait_for(DRAWER_OPEN)
        pg.wait_for("decodeURIComponent(location.hash).indexOf('sel=' + %s) > 0" % q(expect_sel))
        if expect_sec:
            self.assertIn("sec=" + expect_sec, pg.js("location.hash"))
        self.assertTrue(pg.js("!!document.querySelector('#sch-dt tr.dt-hl[data-id=' + JSON.stringify(%s) + ']')" % q(rid)))
        pg.press("Escape")
        pg.wait_for("!(%s)" % DRAWER_OPEN)

    def test_rows_open_their_drawers(self):
        ip = self.api("/api/v2/projects/campus-demo/schedules/ip?room=main")["rows"][0]
        dmx = self.api("/api/v2/projects/campus-demo/schedules/dmx?room=main")["rows"][0]
        patch = self.api("/api/v2/projects/campus-demo/schedules/patch?room=main")["rows"][0]
        racks = self.api("/api/v2/projects/campus-demo/schedules/racks?room=main")["rows"][0]
        cables = self.api("/api/v2/projects/campus-demo/schedules/cables?room=main")["rows"][0]
        for size in ("t", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "schedules/cables", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg)
                self._row_opens(pg, "cables", "from_device", "cable:" + cables["id"])
                self._row_opens(pg, "ip", "device", "device:" + ip["device_id"], "net")
                self._row_opens(pg, "dmx", "device", "device:" + dmx["device_id"], "dmx")
                self._row_opens(pg, "patch", "port", "port:%s:%s" % (patch["device_id"], patch["port_id"]))
                self._row_opens(pg, "racks", "device", "rack:" + racks["rack_id"])

    def test_bom_rows_open_device_or_drill_down(self):
        bom = self.api("/api/v2/projects/campus-demo/schedules/bom?room=main")["rows"]
        single = [r for r in bom if len(r.get("devices") or []) == 1][0]
        multi = [r for r in bom if len(r.get("devices") or []) > 1][0]
        with self.open(CAMPUS + "schedules/bom", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "bom")
            pg.js("""(function () { var s = document.getElementById('sch-filter'); s.value = %s;
              s.dispatchEvent(new Event('input', {bubbles: true})); })()""" % q(single["model"]))
            pg.wait_for("location.hash.indexOf('q=') > 0")
            pg.click("#sch-dt tbody tr.dt-row td[data-col=model]")
            pg.wait_for(DRAWER_OPEN)
            pg.wait_for("decodeURIComponent(location.hash).indexOf('sel=device:' + %s) > 0" % q(single["devices"][0]))
            self.assertIn("sec=inventory", pg.js("location.hash"))
            pg.press("Escape")
            pg.wait_for("!(%s)" % DRAWER_OPEN)
            pg.js("""(function () { var s = document.getElementById('sch-filter'); s.value = %s;
              s.dispatchEvent(new Event('input', {bubbles: true})); })()""" % q(multi["model"]))
            pg.wait_for("Array.prototype.some.call(document.querySelectorAll('#sch-dt tbody tr.dt-row td[data-col=model]'), function (td) { return td.textContent === %s; })" % q(multi["model"]))
            pg.js("""Array.prototype.filter.call(document.querySelectorAll('#sch-dt tbody tr.dt-row td[data-col=model]'), function (td) {
              return td.textContent === %s; })[0].setAttribute('data-pick', '1'); 1""" % q(multi["model"]))
            pg.click("#sch-dt td[data-pick]")
            pg.wait_for("!!document.querySelector('.dt-dialog .dt-root')")
            pg.wait_for("document.querySelectorAll('.dt-dialog tbody tr.dt-row').length === %d" % len(multi["devices"]))
            pg.click(".dt-dialog tbody tr.dt-row td")
            pg.wait_for("!document.querySelector('.dt-dialog')")
            pg.wait_for(DRAWER_OPEN)
            self.assertIn("sec=inventory", pg.js("location.hash"))

    def test_inline_edit_saves_and_survives_reload(self):
        with self.open(CAMPUS + "schedules/cables?q=c-0003", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            inp = "#sch-dt tr[data-id=\"c-0003\"] td[data-col=tag] input[data-edit=tag]"
            pg.wait_for("!!document.querySelector(%s)" % q(inp))
            pg.js("""(function () { var i = document.querySelector(%s); i.focus(); i.value = 'T-777';
              i.dispatchEvent(new Event('change', {bubbles: true})); })()""" % q(inp))
            pg.press("Enter")
            server_tag = ("fetch('/api/v2/projects/campus-demo/schedules/cables?room=main').then(function (r) { return r.json(); })"
                          ".then(function (j) { return j.rows.filter(function (x) { return x.id === 'c-0003'; })[0].tag === 'T-777'; })")
            pg.wait_for(server_tag, 20)
            pg.reload()
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(pg.js("document.querySelector(%s).value" % q(inp)), "T-777")
            self.assertFalse(pg.js("document.querySelector('#sch-dt tr[data-id=\"c-0003\"]').classList.contains('sch-untagged')"))

    # ------------------------------------------------------------ CSV, print

    def _csv(self, pg, n):
        pg.wait_for("document.getElementById('sch-csv').getAttribute('data-rows') === %s"
                    " && (document.getElementById('sch-csv').getAttribute('href') || '').indexOf('blob:') === 0" % q(str(n)))
        return pg.js("fetch(document.getElementById('sch-csv').getAttribute('href')).then(function (r) { return r.text(); })")

    def test_csv_has_the_filtered_rows(self):
        main = self.api("/api/v2/projects/campus-demo/schedules/cables?room=main")["rows"]
        with self.open(CAMPUS + "schedules/cables", "d") as pg:
            # connect-src 'self' stops fetch(blob:) in the test; the download link itself is a navigation.
            pg.command("Page.setBypassCSP", {"enabled": True})
            pg.reload()
            view_ready(pg)
            rows_ready(pg, "cables")
            lines = self._csv(pg, len(main)).split("\r\n")
            self.assertEqual(lines[0], CABLE_HEADER, "CSV columns and labels are unchanged")
            self.assertEqual(lines[-1], "", "CRLF terminated")
            self.assertEqual(len(lines) - 2, len(main), "every row, not just page 1")
            self.assertTrue(pg.js("!!document.getElementById('sch-csv').hasAttribute('download')"))
            pg.goto(CAMPUS + "schedules/cables?q=drum")
            pg.wait_for("document.querySelector('#sch-dt .dt-count').textContent.indexOf(' of ') > 0")
            n = pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length")
            lines = self._csv(pg, n).split("\r\n")
            self.assertEqual(len(lines) - 2, n)
            self.assertTrue(all("drum" in ln.lower() for ln in lines[1:-1]), lines[:4])
            full = pg.js("document.getElementById('sch-csv-all').getAttribute('href')")
            self.assertIn("/schedules/cables", full)
            self.assertIn("format=csv", full)

    def test_print_sheet_holds_every_filtered_row(self):
        main = self.api("/api/v2/projects/campus-demo/schedules/cables?room=main")["rows"]
        with self.open(CAMPUS + "schedules/cables", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            self.assertEqual(pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length"), 50)
            pg.js("window.dispatchEvent(new Event('beforeprint')); 1")
            self.assertEqual(pg.js("document.querySelectorAll('.sch-printsheet tbody tr').length"), len(main))
            pg.command("Emulation.setEmulatedMedia", {"media": "print"})
            try:
                self.assertTrue(shown(pg, ".sch-printsheet"))
                self.assertFalse(shown(pg, "#sch-dt"))
                self.assertFalse(shown(pg, ".sch-tabs"))
            finally:
                pg.command("Emulation.setEmulatedMedia", {"media": ""})
            pg.js("window.dispatchEvent(new Event('afterprint')); 1")
            self.assertFalse(pg.js("!!document.querySelector('.sch-printsheet')"))
            self.assertTrue(shown(pg, "#sch-dt"))

    # ------------------------------------------------------------ bulk add

    def test_bulk_add_cables_lands_on_the_new_rows(self):
        text = "\n".join([
            "From\tTo\tTag\tType\tLength",
            "Main Speakers - L/R:Thru 1\tAudio Rack 1:Input 5\tS-901\tXLR3\t25",
            "main-speakers:thru-2\taudio-rack-1:analog-in-6\tS-902\tXLR3\t25",
        ])
        with self.open(SUNDAY + "schedules/cables", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "cables")
            pg.click("#sch-bulk-add")
            pg.wait_for("!!document.querySelector('.wz textarea[name=text]')")
            pg.js("""(function () { var ta = document.querySelector('.wz textarea[name=text]'); ta.focus(); ta.value = %s;
              ta.dispatchEvent(new Event('input', {bubbles: true})); })()""" % q(text))
            for step in ("map", "preview", "review", "result"):
                pg.wait_for("!document.querySelector('.wz .wz-next').disabled")
                pg.click(".wz .wz-next")
                pg.wait_for("(document.querySelector('.wz-steps li[aria-current=step]') || {getAttribute: function () {}}).getAttribute('data-step') === %s" % q(step))
            href = pg.js("document.querySelector('.wz .wz-result-link').getAttribute('href')")
            self.assertTrue(href.startswith(SUNDAY + "schedules/cables?hl="), href)
            self.assertIn("f.id=", href)
            pg.click(".wz .wz-result-link")
            pg.wait_for("!document.querySelector('.wz')")
            pg.wait_for("location.hash.indexOf('f.id=') > 0")
            pg.wait_for("""(function () { var t = Array.prototype.map.call(document.querySelectorAll('#sch-dt tbody tr.dt-row td[data-col=tag] input'),
              function (i) { return i.value; }).sort().join(); return t === 'S-901,S-902'; })()""")
            pg.wait_for("!!document.querySelector('#sch-dt tr.dt-hl')")
            pg.click("#sch-tab-ip")
            rows_ready(pg, "ip")
            pg.click("#sch-tab-cables")
            rows_ready(pg, "cables")
            self.assertGreater(pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length"), 2, "the f.id filter does not stick")

    # ------------------------------------------------------------ layout

    def test_phone_layout(self):
        with self.open(CAMPUS + "schedules/cables", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            view_ready(pg)
            for kind in TABLE_KINDS:
                with self.subTest(kind=kind):
                    pg.goto(CAMPUS + "schedules/" + kind)
                    rows_ready(pg, kind)
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    lead = MOBILE_COLS[kind][0]
                    cols = pg.js("""Array.prototype.filter.call(document.querySelectorAll('#sch-dt thead th[data-col]'), function (th) {
                      return th.getBoundingClientRect().width > 0; }).map(function (th) { return th.getAttribute('data-col'); })""")
                    self.assertEqual(cols, MOBILE_COLS[kind], "only the phone columns show")
                    td = "#sch-dt tbody tr.dt-row td[data-col=%s]" % lead
                    self.assertEqual(pg.js("getComputedStyle(document.querySelector(%s)).position" % q(td)), "sticky")
                    self.assertEqual(pg.offscreen("#sch-filter, #sch-csv, #sch-state, #sch-print", "x"), 0)
                    pg.shot("schedules-%s-m" % kind)
            heights = pg.js("Array.prototype.map.call(document.querySelectorAll('.sch-tabs [role=tab]'), function (a) { return a.getBoundingClientRect().height; })")
            self.assertTrue(all(hh >= 44 for hh in heights), heights)
            self.assertEqual(pg.offscreen(".sch-tabs [role=tab]", "x"), 0)
            tops = pg.js("Array.prototype.map.call(document.querySelectorAll('.sch-tabs [role=tab]'), function (a) { return Math.round(a.getBoundingClientRect().top); })")
            self.assertEqual(len(set(tops)), 1, "the seven tabs fit one row at 390px")
            pg.goto(CAMPUS + "schedules/labels")
            pg.wait_for("!!document.querySelector('.sch-labelbar')")
            self.assertLessEqual(pg.page_hscroll(), 0)

    def test_tablet_and_desktop_layout(self):
        for size in ("t", "d"):
            with self.subTest(size=size), self.open(CAMPUS + "schedules/cables", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg)
                for kind in TABLE_KINDS:
                    pg.goto(CAMPUS + "schedules/" + kind)
                    rows_ready(pg, kind)
                    self.assertLessEqual(pg.page_hscroll(), 0, kind)
                    self.assertTrue(shown(pg, "#sch-dt th[data-col=disc]"), "every column shows from 700px")
                    self.assertEqual(pg.offscreen("#sch-dt .dt-pager", "y"), 0, "the pager stays on screen")
                    if kind in ("cables", "ip"):
                        col = "tag" if kind == "cables" else "ip"
                        cut = pg.js("""Array.prototype.filter.call(document.querySelectorAll('#sch-dt td[data-col=%s] input[data-edit]'),
                          function (i) { return i.scrollWidth > i.clientWidth + 1; }).length""" % col)
                        self.assertEqual(cut, 0, "inline %s editors show their whole value" % col)
                    pg.shot("schedules-%s-%s" % (kind, size))

    def test_room_and_discipline_filters(self):
        with self.open(CAMPUS + "schedules/ip", "d") as pg:
            view_ready(pg)
            rows_ready(pg, "ip")
            self.assertTrue(pg.js("document.getElementById('sch-room').classList.contains('dt-filter')"))
            self.assertTrue(pg.js("document.getElementById('sch-disc').classList.contains('dt-filter')"))
            self.assertEqual(pg.js("document.getElementById('sch-state').tagName"), "SELECT")
            pg.click("#sch-disc")
            pg.wait_for("!!document.querySelector('.dt-pop[data-col=disc] input[type=checkbox]')")
            val = pg.js("document.querySelector('.dt-pop[data-col=disc] input[type=checkbox]').value")
            pg.click(".dt-pop[data-col=disc] input[type=checkbox]")
            pg.wait_for("location.hash.indexOf('f.disc=') > 0")
            self.assertTrue(pg.js("""Array.prototype.every.call(document.querySelectorAll('#sch-dt tbody tr.dt-row td[data-col=disc]'),
              function (td) { return td.textContent.indexOf(%s) === 0; })""" % q(val)))
            pg.goto(CAMPUS + "schedules/cables")
            rows_ready(pg, "cables")
            self.assertFalse(pg.js("!!document.getElementById('sch-room')"), "cables have no room column")
            n = pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length")
            pg.js("var s = document.getElementById('sch-state'); s.value = 'everything'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.wait_for("document.querySelector('#sch-dt .dt-count').textContent !== ''")
            rows_ready(pg, "cables")
            self.assertGreaterEqual(pg.js("document.querySelectorAll('#sch-dt tbody tr.dt-row').length"), n)

    # ------------------------------------------------------------ device labels (Brady M511, phase 1 P1B)

    def _dl_href(self, pg, el_id):
        return pg.js("document.getElementById(%s).getAttribute('href') || ''" % q(el_id))

    def test_device_labels_section(self):
        presets = self.api("/api/v2/labels/presets")
        main = [d for d in self.api("/api/v2/projects/campus-demo")["doc"]["devices"] if d.get("room") == "main" and not d.get("auto")]
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "schedules/labels", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg)
                pg.wait_for("!!document.querySelector('.sch-labelbar #sch-state') && !!document.querySelector('.sch-devlabels')")
                self.assertTrue(shown(pg, ".sch-devlabels"), "the section renders in the Labels tab")
                self.assertEqual(pg.js("document.querySelector('.sch-devlabels h3').textContent"), "Device labels")
                pg.wait_for("document.querySelectorAll('#sch-dl-preset option').length === 7")
                opts = pg.js("Array.prototype.map.call(document.querySelectorAll('#sch-dl-preset option'), function (o) { return [o.value, o.textContent]; })")
                self.assertEqual([o[0] for o in opts], [p["id"] for p in presets["presets"]], "one option per preset, server order")
                self.assertEqual(opts[0][1], "1\u2033 \u00d7 0.5\u2033 die-cut \u2014 25.4\u00d712.7 mm", "<label> — <w>×<h> mm")
                self.assertEqual(pg.js("document.getElementById('sch-dl-preset').value"), presets["default"], "default preset selected")
                self.assertEqual(pg.js("document.getElementById('sch-dl-scope').value"), "all")
                for el_id, fmt in (("sch-dl-preview", "html"), ("sch-dl-zip", "zip"), ("sch-dl-csv", "csv")):
                    href = self._dl_href(pg, el_id)
                    self.assertIn("/api/v2/projects/campus-demo/labels/devices?", href, el_id)
                    self.assertIn("preset=m511-1x0.5", href, el_id)
                    self.assertIn("format=" + fmt, href, el_id)
                    self.assertNotIn("room=", href)
                    self.assertNotIn("devices=", href)
                self.assertEqual(pg.js("document.getElementById('sch-dl-preview').getAttribute('target')"), "_blank")
                self.assertTrue(pg.js("document.getElementById('sch-dl-zip').hasAttribute('download') && document.getElementById('sch-dl-csv').hasAttribute('download')"))
                self.assertFalse(pg.js("document.getElementById('sch-dl-preview').hasAttribute('download')"))
                # preset change rewrites every link
                pg.js("var s = document.getElementById('sch-dl-preset'); s.value = 'm511-1x2'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
                for el_id in ("sch-dl-preview", "sch-dl-zip", "sch-dl-csv"):
                    self.assertIn("preset=m511-1x2", self._dl_href(pg, el_id))
                self.assertIn("m511-1x2", pg.js("document.getElementById('sch-dl-zip').getAttribute('download')"))
                # this room
                pg.js("var s = document.getElementById('sch-dl-scope'); s.value = 'room'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
                self.assertIn("room=main", self._dl_href(pg, "sch-dl-preview"))
                self.assertEqual(pg.js("document.getElementById('sch-dl-count').textContent"), "%d devices" % len(main))
                # selected devices: picker with a filter box; links carry devices=
                pg.js("var s = document.getElementById('sch-dl-scope'); s.value = 'selected'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
                pg.wait_for("!document.querySelector('.sch-dl-pick').hidden && document.querySelectorAll('#sch-dl-list li[data-pick]').length > 0")
                self.assertEqual(pg.js("document.getElementById('sch-dl-preview').getAttribute('aria-disabled')"), "true", "nothing selected: links disabled")
                self.assertFalse(pg.js("document.getElementById('sch-dl-zip').hasAttribute('href')"))
                pg.js("""(function () { var i = document.getElementById('sch-dl-filter'); i.value = 'vocal mic 1';
                  i.dispatchEvent(new Event('input', {bubbles: true})); })()""")
                pg.wait_for("document.querySelectorAll('#sch-dl-list li[data-pick]').length === 1")
                pg.click("#sch-dl-list li[data-pick]")
                pg.wait_for("document.querySelector('#sch-dl-list li[data-pick]').getAttribute('aria-selected') === 'true'")
                self.assertEqual(pg.js("document.getElementById('sch-dl-count').textContent"), "1 device")
                href = self._dl_href(pg, "sch-dl-zip")
                self.assertIn("devices=vox-1", href)
                self.assertIn("format=zip", href)
                self.assertNotIn("room=", href)
                pg.js("""(function () { var i = document.getElementById('sch-dl-filter'); i.value = 'vocal mic 2';
                  i.dispatchEvent(new Event('input', {bubbles: true})); })()""")
                pg.wait_for("document.querySelectorAll('#sch-dl-list li[data-pick]').length === 1")
                pg.click("#sch-dl-list li[data-pick]")
                pg.wait_for("document.getElementById('sch-dl-count').textContent === '2 devices'")
                self.assertIn("devices=vox-1%2Cvox-2", self._dl_href(pg, "sch-dl-csv"), "selection order kept, comma-joined")
                # the links really resolve
                st = pg.js("fetch(document.getElementById('sch-dl-csv').getAttribute('href')).then(function (r) { return r.status + ' ' + r.headers.get('Content-Type'); })")
                self.assertTrue(st.startswith("200 text/csv"), st)
                # the cable-label controls are untouched
                self.assertTrue(shown(pg, ".sch-labelbar #sch-state") and shown(pg, "#sch-print"))
                self.assertEqual(pg.js("document.getElementById('sch-csv').getAttribute('aria-disabled')"), "true")
                self.assertTrue(shown(pg, ".sch-labels-frame"))
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal overflow at 390px")
                    self.assertEqual(pg.offscreen("#sch-dl-preset, #sch-dl-scope, #sch-dl-preview, #sch-dl-zip, #sch-dl-csv, #sch-dl-filter", "x"), 0)
                    heights = pg.js("""['sch-dl-preset', 'sch-dl-scope', 'sch-dl-preview', 'sch-dl-zip', 'sch-dl-csv', 'sch-dl-filter'].map(function (id) {
                      return Math.round(document.getElementById(id).getBoundingClientRect().height); })""")
                    self.assertTrue(all(44 <= hh <= 60 for hh in heights), ("44 px targets, no stretched controls in the column layout", heights))
                    widths = pg.js("""['sch-dl-preview', 'sch-dl-zip', 'sch-dl-csv'].map(function (id) {
                      return Math.round(document.getElementById(id).getBoundingClientRect().width); })""")
                    self.assertTrue(all(w >= 300 for w in widths), ("full-width buttons on the phone", widths))
                    self.assertLessEqual(pg.js("document.querySelector('#sch-dl-list li[data-pick]').getBoundingClientRect().right"), 390)
                else:
                    heights = pg.js("""['sch-dl-preset', 'sch-dl-scope', 'sch-dl-preview', 'sch-dl-zip', 'sch-dl-csv'].map(function (id) {
                      return Math.round(document.getElementById(id).getBoundingClientRect().height); })""")
                    self.assertTrue(all(hh >= 40 for hh in heights), heights)
                pg.shot("schedules-labels-devices-%s" % size)

    def test_device_labels_selection_survives_rerender(self):
        with self.open(CAMPUS + "schedules/labels", "d") as pg:
            view_ready(pg)
            pg.wait_for("document.querySelectorAll('#sch-dl-preset option').length === 7")
            pg.js("var s = document.getElementById('sch-dl-preset'); s.value = 'm511-1x1'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.js("var s = document.getElementById('sch-dl-scope'); s.value = 'selected'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.wait_for("document.querySelectorAll('#sch-dl-list li[data-pick]').length > 0")
            pg.click("#sch-dl-list li[data-pick=\"vox-1\"]")
            pg.wait_for("document.getElementById('sch-dl-count').textContent === '1 device'")
            # a state change re-renders the labels tab; preset, scope and selection stay
            pg.js("var s = document.getElementById('sch-state'); s.value = 'everything'; s.dispatchEvent(new Event('change', {bubbles: true})); 1")
            pg.wait_for("document.getElementById('sch-dl-preset').value === 'm511-1x1'")
            self.assertEqual(pg.js("document.getElementById('sch-dl-scope').value"), "selected")
            self.assertEqual(pg.js("document.getElementById('sch-dl-count').textContent"), "1 device")
            self.assertIn("devices=vox-1", self._dl_href(pg, "sch-dl-preview"))
            self.assertIn("preset=m511-1x1", self._dl_href(pg, "sch-dl-preview"))
            # another tab and back: no section on table tabs, the section is back on Labels
            pg.click("#sch-tab-ip")
            rows_ready(pg, "ip")
            self.assertFalse(pg.js("!!document.querySelector('.sch-devlabels')"))
            pg.click("#sch-tab-labels")
            pg.wait_for("!!document.querySelector('.sch-devlabels') && document.querySelectorAll('#sch-dl-preset option').length === 7")
            self.assertEqual(pg.js("document.getElementById('sch-dl-preset').value"), "m511-1x1")

    # ------------------------------------------------------------ harness

    def test_harness_walk(self):
        with self.open(HARNESS + "?walk=1", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            walk = json.loads(pg.wait_for("document.documentElement.getAttribute('data-walk')", 30))
            self.assertTrue(walk.get("schedulesOk"), walk)
            self.assertTrue(walk.get("inventoryOk"), walk)
            self.assertTrue(walk.get("ok"), walk)
        with self.open(HARNESS + "?readonly=1", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.assertEqual(pg.js("document.querySelectorAll('.sch-root [data-edit]').length"), 0, "no editors when read-only")
            self.assertFalse(pg.js("!!document.getElementById('sch-bulk-add')"))
            self.assertFalse(pg.js("!!document.getElementById('sch-assign-tags')"), "no Assign tags when read-only")
            self.assertEqual(pg.js("document.getElementById('sch-room').tagName"), "SELECT", "the harness keeps its room picker")
