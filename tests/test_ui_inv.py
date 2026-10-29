"""INV: the inventory view on the shared DataTable in the real app (docs/ui-audit.md B.3 INV, B.8).

Drives ``#/<project>/main/inventory`` through ``tests/_ui.py``: a row opens the device drawer at the
inventory section (URL ``sel``/``sec``, kept across reload); search, filters and sort live in the URL and
filters and sort come back from storage on a fresh visit; ``#inv-csv`` holds the filtered rows; select-all
takes only the filtered set; quick chips, group by location and the room scope; bulk status with the
confirm dialog, committed and undone; bulk add end to end through the wizard and undone; the viewer role
hides every editing control; the schedules harness smoke; d, t and m with no horizontal page scroll and
the toolbar inside the viewport at m. Each ``UiServer`` serves a throwaway copy of the fixtures.
Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/inventory"
SUNDAY = "#/sunday-demo/main/inventory"
STORE_KEY = "fathom.ui.table.campus-demo.inventory"
ROWS = "#inv-table tbody tr.dt-row"

QUERY = ("(function () { var h = location.hash, i = h.indexOf('?'), o = {};"
         " new URLSearchParams(i >= 0 ? h.slice(i + 1) : '').forEach(function (v, k) { o[k] = v; }); return o; })()")


def _q(s: str) -> str:
    return json.dumps(s)


# Knox-parity fields (FR-INV-10..13) the sibling backend assigns; the UI only reads and writes them.
# `knox_seed` adds a container (``case-foh``), an accessory stored in it (``di-kit``), gives ``foh-cl5``
# a short code, condition, container and custom fields, and spreads conditions over a few devices.
def knox_seed(doc: dict) -> dict:
    by = {d["id"]: d for d in doc["devices"]}
    if "case-foh" not in by:
        doc["devices"].append({"id": "case-foh", "name": "FOH road case", "kind": "container", "room": "main", "discipline": "other",
                               "ports": [], "short_code": "CASE2345", "inventory": {"condition": "good"}})
    if "di-kit" not in by:
        doc["devices"].append({"id": "di-kit", "name": "DI box kit", "kind": "other", "room": "main", "discipline": "audio", "ports": [],
                               "container": "case-foh", "inventory": {"condition": "fair", "fields": {"owner": "AV office", "insured": "yes", "bin": "B-07"}}})
    cl5 = by["foh-cl5"]
    cl5["short_code"] = "ABCD2345"
    cl5["container"] = "case-foh"
    cl5.setdefault("inventory", {})
    cl5["inventory"]["condition"] = "good"
    cl5["inventory"]["fields"] = {"owner": "AV office", "insured": "yes", "bin": "B-01", "lease": "2027-01"}
    by["cam-3"].setdefault("inventory", {})["condition"] = "broken"
    by["rio-sr"].setdefault("inventory", {})["condition"] = "poor"
    by["rio-sr"]["short_code"] = "RIOS2345"
    by["projector"].setdefault("inventory", {})["condition"] = "new"
    return doc


def seed_campus(server, seed=knox_seed) -> None:
    """Rewrite the throwaway campus-demo copy of ``server`` (before any page loads it)."""
    path = Path(server.data) / "projects" / "campus-demo" / "project.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(seed(doc)), encoding="utf-8")


class _InventoryBase(UiCase):
    """Shared page helpers; the test classes below each get their own ``UiServer``."""

    def _ready(self, pg, rows: int = 1) -> None:
        self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
        pg.wait_for("document.querySelectorAll(%s).length >= %d" % (_q(ROWS), rows))

    def _count(self, pg) -> str:
        return pg.js("document.querySelector('.inv-root .dt-count').textContent")

    def _query(self, pg):
        return pg.js(QUERY)

    def _ids(self, pg):
        return pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (tr) { return tr.getAttribute('data-device'); })" % _q(ROWS))

    def _cells(self, pg, col: str):
        return pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (td) { return td.textContent; })"
                     % _q(ROWS + " td[data-col=%s]" % col))

    def _type(self, pg, selector: str, text: str) -> None:
        pg.click(selector)
        for ch in text:
            pg.press(ch)

    def _filter(self, pg, col: str, value: str) -> None:
        pg.click("#inv-" + col)
        pg.wait_for("!!document.querySelector('.inv-root .dt-pop[data-col=%s]')" % col)
        pg.click(".inv-root .dt-pop input[value=%s]" % _q(value))
        pg.wait_for("location.hash.indexOf('f.%s=') > 0" % col)
        pg.press("Escape")
        pg.wait_for("!document.querySelector('.inv-root .dt-pop')")

    def _select(self, pg, ident: str, value: str) -> None:
        pg.js("(function (s) { s.value = %s; s.dispatchEvent(new Event('change', {bubbles: true})); })(document.getElementById(%s))"
              % (_q(value), _q(ident)))

    def _doc(self, pg, project: str):
        return pg.js("fetch('/api/v2/projects/%s', {headers: {Accept: 'application/json'}}).then(function (r) { return r.json(); })"
                     " .then(function (p) { return p.doc; })" % project)

    def _device(self, pg, project: str, dev_id: str):
        for d in self._doc(pg, project)["devices"]:
            if d["id"] == dev_id:
                return d
        return None

    def _wait_server(self, pg, project: str, js_pred: str, timeout: float = 15.0) -> None:
        pg.wait_for("fetch('/api/v2/projects/%s', {headers: {Accept: 'application/json'}}).then(function (r) { return r.json(); })"
                    " .then(function (p) { var doc = p.doc; return !!(%s); })" % (project, js_pred), timeout)



class InventoryUi(_InventoryBase):

    # ------------------------------------------------------------ row -> drawer

    def test_row_click_opens_the_drawer_at_the_inventory_section(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            self.assertEqual(self._count(pg), "49 devices")
            pg.click("#inv-table tr[data-device=foh-cl5] td[data-col=model]")
            pg.wait_for("location.hash.indexOf('sel=device%3Afoh-cl5') > 0 || location.hash.indexOf('sel=device:foh-cl5') > 0")
            q = self._query(pg)
            self.assertEqual(q.get("sel"), "device:foh-cl5")
            self.assertEqual(q.get("sec"), "inventory")
            self.assertTrue(pg.js("location.hash.split('?')[0]").endswith("/inventory"), "the view stays inventory")
            pg.wait_for("!!document.querySelector('#app-inspector details[data-section=inventory]')"
                        " && document.querySelector('#app-inspector details[data-section=inventory]').open")
            self.assertTrue(pg.js("!!document.querySelector('#inv-table')"), "the table stays mounted behind the drawer")
            pg.reload()
            self._ready(pg)
            pg.wait_for("!!document.querySelector('#app-inspector details[data-section=inventory]')"
                        " && document.querySelector('#app-inspector details[data-section=inventory]').open")
            self.assertEqual(self._query(pg).get("sel"), "device:foh-cl5")
            self.assertTrue(pg.js("location.hash.split('?')[0]").endswith("/inventory"))

            # the row's own controls do not open the drawer: Edit opens the inventory form
            pg.press("Escape")
            pg.click("#inv-table .inv-edit[data-device=main-l]")
            pg.wait_for("!!document.querySelector('.inv-form [data-field=serial]')")
            self.assertIn("Main hang L", pg.js("document.getElementById('inv-form-title').textContent"))

    # ------------------------------------------------------------ URL state and storage

    def test_search_filters_and_sort_survive_reload_and_a_fresh_visit(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            pg.js("localStorage.removeItem(%s); 1" % _q(STORE_KEY))
            self._filter(pg, "status", "installed")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '48 of 49 devices'")
            self._filter(pg, "kind", "speaker")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '4 of 49 devices'")
            th = "#inv-table th[data-col=name]"
            pg.click(th + " .dt-sort")
            pg.wait_for("document.querySelector(%s).getAttribute('aria-sort') === 'ascending'" % _q(th))
            pg.click(th + " .dt-sort")
            pg.wait_for("document.querySelector(%s).getAttribute('aria-sort') === 'descending'" % _q(th))
            self._type(pg, "#inv-filter", "hang")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '2 of 49 devices'")
            q = self._query(pg)
            self.assertEqual((q.get("q"), q.get("f.status"), q.get("f.kind"), q.get("sort")), ("hang", "installed", "speaker", "-name"))
            self.assertEqual(self._ids(pg), ["main-r", "main-l"], "sorted by name, descending")

            pg.reload()
            self._ready(pg)
            self.assertEqual(self._count(pg), "2 of 49 devices", "the URL restores search, filters and sort")
            self.assertEqual(self._ids(pg), ["main-r", "main-l"])
            self.assertEqual(pg.js("document.getElementById('inv-filter').value"), "hang")
            self.assertEqual(pg.js("document.querySelector('#inv-status .dt-filter-n').textContent"), "1")

            saved = json.loads(pg.js("localStorage.getItem(%s)" % _q(STORE_KEY)))
            self.assertEqual(saved["sort"], {"col": "name", "dir": -1})
            self.assertEqual(saved["filters"], {"kind": ["speaker"], "status": ["installed"]})
            pg.goto("/?fresh=1" + CAMPUS)
            self._ready(pg)
            self.assertEqual(self._count(pg), "4 of 49 devices", "storage restores filters and sort; search text is URL-only")
            self.assertEqual(self._ids(pg), ["subs", "main-r", "main-l", "front-fills"])
            self.assertEqual(pg.js("document.getElementById('inv-filter').value"), "")

            # Clear filters from the empty state
            self._type(pg, "#inv-filter", "zzzz-nothing")
            pg.wait_for("!!document.querySelector('.inv-root .inv-empty .dt-clear')")
            self.assertIn("No devices match these filters.", pg.js("document.querySelector('.inv-root .inv-empty').textContent"))
            pg.click(".inv-root .inv-empty .dt-clear")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '49 devices'")
            pg.js("localStorage.removeItem(%s); 1" % _q(STORE_KEY))

    # ------------------------------------------------------------ CSV and select-all

    def test_csv_holds_the_filtered_rows_and_export_all_is_the_server_export(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            pg.command("Page.setBypassCSP", {"enabled": True})
            pg.reload()
            self._ready(pg)
            self._filter(pg, "kind", "fixture")
            pg.wait_for("document.getElementById('inv-csv').getAttribute('data-rows') === '8'"
                        " && document.getElementById('inv-csv').getAttribute('href').indexOf('blob:') === 0")
            text = pg.js("fetch(document.getElementById('inv-csv').href).then(function (r) { return r.text(); })")
            lines = text.split("\r\n")
            self.assertEqual(lines[-1], "")
            self.assertEqual(len(lines) - 2, 8, "header plus the 8 filtered rows")
            self.assertEqual(lines[0], "Name,Room,Location,Kind,Model,Status,Condition,Container,Code,Serial,Asset tag,Warranty until,Cost,Rack,RU,IPs",
                             "visible columns only; the Edit column is not exported")
            self.assertTrue(all(",fixture," in ln for ln in lines[1:-1]), lines)
            self.assertEqual(pg.js("document.getElementById('inv-csv').getAttribute('download')"), "campus-demo-inventory.csv")

            pg.click(".inv-more > summary")
            pg.wait_for("document.querySelector('.inv-more').open")
            href = pg.js("document.getElementById('inv-csv-all').getAttribute('href')")
            self.assertIn("/schedules/inventory", href)
            self.assertIn("format=csv", href)
            self.assertIn("room=main", href)
            server = pg.js("fetch(document.getElementById('inv-csv-all').href).then(function (r) { return r.text(); })")
            self.assertTrue(server.splitlines()[0].startswith("id,name,"), server[:120])
            self.assertEqual(len([ln for ln in server.splitlines()[1:] if ln]), 49, "the server export ignores the table filters")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.inv-more').open")

    def test_select_all_selects_only_the_filtered_rows(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            self._filter(pg, "kind", "fixture")
            pg.wait_for("document.querySelectorAll(%s).length === 8" % _q(ROWS))
            self.assertEqual(pg.js("document.getElementById('inv-select-all').getAttribute('aria-label')"), "Select all 8 matching")
            pg.click("#inv-table thead .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 8")
            self.assertFalse(pg.js("document.querySelector('.inv-root .dt-bulk').hidden"))
            self.assertEqual(pg.js("document.querySelector('.inv-root .dt-bulk-count').textContent"), "8 devices selected")
            for ident in ("inv-bulk-status", "inv-bulk-room", "inv-bulk-location", "inv-mark-installed"):
                self.assertTrue(pg.js("!!document.querySelector('.inv-root .dt-bulk #%s')" % ident), ident)
            self.assertFalse(pg.js("document.getElementById('inv-merge').hidden"), "merge shows with 2+ selected")
            self.assertEqual(set(self._cells(pg, "kind")), {"fixture"})

    # ------------------------------------------------------------ quick chips, grouping, scope

    def test_quick_chips_group_and_scope(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            pg.click("#inv-q-serial")
            pg.wait_for("location.hash.indexOf('quick=serial') > 0")
            self.assertEqual(pg.js("document.getElementById('inv-q-serial').getAttribute('aria-pressed')"), "true")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '40 devices'")
            self.assertEqual(set(self._cells(pg, "serial")), {""})
            pg.reload()
            self._ready(pg)
            self.assertEqual(self._count(pg), "40 devices", "quick filters live in the URL")
            self.assertEqual(pg.js("document.getElementById('inv-q-serial').getAttribute('aria-pressed')"), "true")
            pg.click("#inv-q-serial")
            pg.wait_for("location.hash.indexOf('quick=') < 0")

            pg.click("#inv-q-warranty")
            pg.wait_for("location.hash.indexOf('quick=warranty') > 0")
            ids = self._ids(pg)
            self.assertIn("foh-cl5", ids)
            self.assertIn("(expired)", pg.js("document.querySelector('#inv-table tr[data-device=foh-cl5] td[data-col=warranty_until]').textContent"))
            pg.click("#inv-q-warranty")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '49 devices'")

            pg.click("#inv-group")
            pg.wait_for("document.querySelectorAll('.inv-root .dt-group').length > 1")
            groups = pg.js("Array.prototype.map.call(document.querySelectorAll('.inv-root .dt-group'), function (g) { return g.textContent.trim(); })")
            self.assertEqual(groups[-1], "No location")
            pg.reload()
            self._ready(pg)
            self.assertTrue(pg.js("document.getElementById('inv-group').checked"), "grouping is persisted")
            self.assertGreater(pg.js("document.querySelectorAll('.inv-root .dt-group').length"), 1)
            pg.click("#inv-group")
            pg.wait_for("document.querySelectorAll('.inv-root .dt-group').length === 0")

            self._select(pg, "inv-scope", "*")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent !== '49 devices'")
            self.assertGreater(len(self._ids(pg)), 49)
            self.assertGreater(len(set(self._cells(pg, "room"))), 2, "all rooms are listed")
            self._select(pg, "inv-scope", "__shared")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '2 devices'")
            self.assertEqual(set(self._cells(pg, "room")), {"Shared"})
            self._select(pg, "inv-scope", "current")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '49 devices'")

    # ------------------------------------------------------------ bulk edit, confirm, undo

    def test_bulk_status_confirms_commits_and_undoes(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            self._type(pg, "#inv-filter", "hang")
            pg.wait_for("document.querySelectorAll(%s).length === 2" % _q(ROWS))
            pg.click("#inv-table thead .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
            self._select(pg, "inv-bulk-status", "spare")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            self.assertEqual(pg.js("document.querySelector('.app-dialog .body').textContent").split("\n")[0],
                             "Set status of 2 devices in Main Auditorium?")
            pg.click(".app-dialog footer button:last-child")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && d.status === 'spare'; }).length === 2")
            pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=status]').textContent === 'spare'")
            self.assertEqual(pg.js("document.getElementById('inv-bulk-status').value"), "")

            pg.click("#app-undo")
            self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && !d.status; }).length === 2")
            pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=status]').textContent === 'installed'")

            # one selected row: no confirm, straight commit
            pg.click("#inv-table thead .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 0")
            pg.click("#inv-table tr[data-device=main-l] .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 1")
            self._select(pg, "inv-bulk-status", "retired")
            self._wait_server(pg, "campus-demo", "doc.devices.some(function (d) { return d.id === 'main-l' && d.status === 'retired'; })")
            self.assertFalse(pg.js("!!document.querySelector('.app-dialog')"))
            pg.click("#app-undo")
            self._wait_server(pg, "campus-demo", "doc.devices.some(function (d) { return d.id === 'main-l' && !d.status; })")

            # declining the confirm writes nothing
            pg.click("#inv-table tr[data-device=main-r] .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
            rev = pg.js("fetch('/api/v2/projects/campus-demo').then(function (r) { return r.json(); }).then(function (p) { return p.revision; })")
            self._select(pg, "inv-bulk-status", "planned")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            pg.wait_for("document.getElementById('inv-bulk-status').value === ''")
            self.assertEqual(pg.js("fetch('/api/v2/projects/campus-demo').then(function (r) { return r.json(); }).then(function (p) { return p.revision; })"), rev)

    def test_bulk_add_end_to_end(self) -> None:
        with self.open(SUNDAY, "d") as pg:
            self._ready(pg)
            before = len(self._ids(pg))
            self.assertEqual(self._count(pg), "%d devices" % before)
            pg.click("#inv-bulk-add")
            pg.wait_for("!!document.querySelector('.wz .wz-body') && document.querySelector('.wz').getAttribute('data-step') === 'paste'")
            self.assertEqual(pg.js("document.getElementById(document.querySelector('.wz').getAttribute('aria-labelledby')).textContent"), "Bulk add devices")
            tsv = "Name\tKind\tModel\tSerial\nINV test mic A\tmic\tSM58\tSN-INV-1\nINV test mic B\tmic\tSM58\tSN-INV-2"
            pg.js("(function () { var ta = document.querySelector('.wz textarea[name=text]'); ta.focus(); ta.value = %s;"
                  " ta.dispatchEvent(new Event('input', {bubbles: true})); })()" % _q(tsv))
            for step in ("map", "preview", "review", "result"):
                pg.wait_for("!document.querySelector('.wz .wz-next').disabled")
                pg.click(".wz .wz-next")
                pg.wait_for("document.querySelector('.wz-steps li[aria-current=step]').getAttribute('data-step') === %s" % _q(step))
                if step == "review":
                    self.assertEqual(pg.js("document.querySelector('.wz .wz-review-title').textContent"), "Add 2 devices to Main Auditorium")
            self._wait_server(pg, "sunday-demo", "doc.devices.filter(function (d) { return /^INV test mic/.test(d.name) && d.room === 'main'; }).length === 2")
            pg.click(".wz .wz-next")
            pg.wait_for("!document.querySelector('.wz')")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '%d devices'" % (before + 2))
            names = pg.js("Array.prototype.map.call(document.querySelectorAll('#inv-table td[data-col=name]'), function (td) { return td.textContent; })")
            self.assertIn("INV test mic A", names)
            self.assertEqual(pg.js("document.getElementById('app-undo').title || document.getElementById('app-undo').getAttribute('aria-label')").count("Bulk add 2 devices"), 1)

            pg.click("#app-undo")
            self._wait_server(pg, "sunday-demo", "!doc.devices.some(function (d) { return /^INV test mic/.test(d.name); })")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '%d devices'" % before)

    # ------------------------------------------------------------ viewer role

    def test_viewer_sees_no_editing_controls(self) -> None:
        with urllib.request.urlopen(self.base + "/api/v2/projects/sunday-demo") as r:
            proj = json.loads(r.read().decode())
        proj["role"] = "viewer"
        with self.open(SUNDAY, "d", intercepts=[("/api/v2/projects/sunday-demo", 200, proj, "GET")]) as pg:
            self._ready(pg)
            st = pg.js("""(function () {
              function shown(sel) { var e = document.querySelector(sel); return !!e && !e.hidden && e.getClientRects().length > 0; }
              return {checks: document.querySelectorAll('.inv-root .dt-row-check, #inv-select-all').length,
                bulk: !!document.querySelector('.inv-root .dt-bulk #inv-bulk-status'), add: shown('#inv-bulk-add'),
                edit: Array.prototype.map.call(document.querySelectorAll('#inv-table .inv-edit'), function (b) { return b.textContent; }),
                csv: shown('#inv-csv')}; })()""")
            self.assertEqual(st["checks"], 0, "no selection for viewers")
            self.assertFalse(st["bulk"], "no bulk controls for viewers")
            self.assertFalse(st["add"], "no Bulk add for viewers")
            self.assertTrue(st["edit"] and set(st["edit"]) == {"View"}, st["edit"])
            self.assertTrue(st["csv"], "viewers can still export")
            pg.click("#inv-table .inv-edit")
            pg.wait_for("!!document.querySelector('.inv-form [data-field=serial]')")
            self.assertTrue(pg.js("document.querySelector('.inv-form [data-field=serial]').disabled"))

    # ------------------------------------------------------------ sizes

    def test_three_sizes_without_horizontal_page_scroll(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(CAMPUS, size) as pg:
                self._ready(pg)
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at %s" % size)
                self.assertEqual(self._count(pg), "49 devices")
                cols = pg.js("Array.prototype.filter.call(document.querySelectorAll('#inv-table thead th[data-col]'), function (th) { return th.getClientRects().length > 0; })"
                             ".map(function (th) { return th.getAttribute('data-col'); })")
                if size == "m":
                    self.assertEqual(cols, ["name", "kind", "status", "condition", "container", "code", "edit"],
                                     "cards at sm show name, kind, status, condition, container, code (and the row action)")
                    self.assertTrue(pg.js("document.querySelector('.inv-root .dt-root').classList.contains('dt-cards')"), "card mode at sm")
                    self.assertEqual(pg.js("getComputedStyle(document.querySelector('#inv-table tbody tr.dt-row')).display"), "block", "one card per device")
                    for sel in ("#inv-filter", ".inv-root .dt-filter", "#inv-bulk-add", "#inv-csv", "#inv-scope"):
                        self.assertEqual(pg.offscreen(sel, "x"), 0, "%s is inside the viewport at m" % sel)
                    self.assertEqual(pg.offscreen("#inv-table tbody tr.dt-row:first-child td[data-col=status]", "x"), 0)
                    for sel in ("#inv-filter", "#inv-bulk-add"):
                        r = pg.rect(sel)
                        self.assertGreaterEqual(r["height"], 44 - 0.5, "%s is a 44px touch target" % sel)
                else:
                    self.assertIn("serial", cols)
                    self.assertIn("warranty_until", cols)
                pg.shot("inv-%s" % size)
                pg.click("#inv-table tr[data-device=foh-cl5] td[data-col=name]")
                pg.wait_for("!!document.querySelector('#app-inspector details[data-section=inventory]')"
                            " && document.querySelector('#app-inspector details[data-section=inventory]').open")
                pg.wait_for("(function () { var r = document.querySelector('#app-inspector details[data-section=inventory] > summary').getBoundingClientRect();"
                            " return r.height > 0 && r.top >= 0 && r.bottom <= innerHeight; })()")
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll with the drawer open at %s" % size)
                pg.shot("inv-drawer-%s" % size)
                pg.press("Escape")
                pg.click("#inv-table .inv-edit[data-device=foh-cl5]")
                pg.wait_for("!!document.querySelector('.inv-form [data-field=serial]')")
                if size == "m":
                    r = pg.rect(".inv-form")
                    self.assertGreaterEqual(r["width"], 390 - 32, "the inventory form is full width at sm")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("inv-form-%s" % size)

    def test_schedules_harness_smoke(self) -> None:
        with self.open("/static/dev/schedules.html", "d") as pg:
            self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
            pg.wait_for("!!document.querySelector('.inv-root #inv-table')")


class InventoryKnoxUi(_InventoryBase):
    """FR-INV-10..13 on a campus-demo copy seeded by ``knox_seed`` (51 devices in Main Auditorium)."""

    @classmethod
    def setUpClass(cls) -> None:
        super(InventoryKnoxUi, cls).setUpClass()
        seed_campus(cls.server)

    def _cell(self, pg, dev: str, col: str) -> str:
        return pg.js("(function () { var td = document.querySelector('#inv-table tr[data-device=%s] td[data-col=%s]'); return td ? td.textContent : null; })()" % (dev, _q(col)))

    def _clear_filter(self, pg, col: str) -> None:
        pg.click("#inv-" + col)
        pg.wait_for("!!document.querySelector('.inv-root .dt-pop[data-col=%s]')" % col)
        pg.click(".inv-root .dt-pop .dt-pop-clear")
        pg.wait_for("location.hash.indexOf('f.%s=') < 0" % col)
        pg.press("Escape")
        pg.wait_for("!document.querySelector('.inv-root .dt-pop')")

    def _undo(self, pg, size: str) -> None:
        # the header undo button is in the user menu at sm; the shortcut works everywhere
        if size == "m":
            pg.press("Control+z")
        else:
            pg.click("#app-undo")

    def test_knox_columns_filters_and_quick_filters(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg)
            self.assertEqual(self._count(pg), "51 devices")
            cols = pg.js("Array.prototype.map.call(document.querySelectorAll('#inv-table thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
            for c in ("condition", "container", "code", "field:owner", "field:insured", "field:bin"):
                self.assertIn(c, cols, "%s is a visible column by default" % c)
            self.assertNotIn("field:lease", cols, "only the first three custom-field columns show by default")
            self.assertTrue(pg.js("!!document.querySelector('.inv-root .dt-cols-list input[data-col=%s]')" % _q("field:lease")), "the fourth custom field is in the Columns menu")
            self.assertEqual(self._cell(pg, "foh-cl5", "condition"), "good")
            self.assertEqual(pg.js("document.querySelector('#inv-table tr[data-device=foh-cl5] td[data-col=condition] .inv-cond').getAttribute('data-condition')"), "good")
            self.assertEqual(self._cell(pg, "foh-cl5", "container"), "FOH road case")
            self.assertEqual(self._cell(pg, "foh-cl5", "field:owner"), "AV office")
            self.assertEqual(pg.js("document.querySelector('#inv-table tr[data-device=foh-cl5] td[data-col=code] .inv-code-text').textContent"), "ABCD-2345")
            copy = pg.js("document.querySelector('#inv-table tr[data-device=foh-cl5] td[data-col=code] .inv-copy').getAttribute('data-copy')")
            self.assertTrue(copy.endswith("/c/ABCD-2345"), copy)
            self.assertRegex(self._cell(pg, "cam-1", "code"), r"^(\u2014|[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4})", "an em dash until the server assigns a code on save (FR-INV-09)")
            self.assertEqual(self._cell(pg, "cam-1", "container"), "")

            # the container cell selects the container
            pg.click("#inv-table tr[data-device=foh-cl5] td[data-col=container] .inv-container-link")
            pg.wait_for("location.hash.indexOf('sel=device%3Acase-foh') > 0 || location.hash.indexOf('sel=device:case-foh') > 0")
            pg.press("Escape")

            # condition filter (multi) and the container filter
            self._filter(pg, "condition", "good")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '2 of 51 devices'")
            self.assertEqual(sorted(self._ids(pg)), ["case-foh", "foh-cl5"])
            pg.click("#inv-condition")
            pg.wait_for("!!document.querySelector('.inv-root .dt-pop[data-col=condition]')")
            pg.click(".inv-root .dt-pop input[value=broken]")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '3 of 51 devices'")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.inv-root .dt-pop')")
            self._clear_filter(pg, "condition")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '51 devices'")
            self._filter(pg, "container", "FOH road case")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '2 of 51 devices'")
            self.assertEqual(sorted(self._ids(pg)), ["di-kit", "foh-cl5"])
            self._clear_filter(pg, "container")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '51 devices'")

            # quick filters: accessories (no ports, not a container), in containers, containers
            pg.click("#inv-q-accessories")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '1 device'")
            self.assertEqual(self._ids(pg), ["di-kit"])
            self.assertEqual(self._query(pg).get("quick"), "accessories")
            pg.click("#inv-q-accessories")
            pg.click("#inv-q-contained")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '2 devices'")
            self.assertEqual(sorted(self._ids(pg)), ["di-kit", "foh-cl5"])
            pg.click("#inv-q-contained")
            pg.click("#inv-q-containers")
            pg.wait_for("document.querySelector('.inv-root .dt-count').textContent === '1 device'")
            self.assertEqual(self._ids(pg), ["case-foh"])
            self.assertEqual(pg.js("document.getElementById('inv-q-containers').getAttribute('aria-pressed')"), "true")
            pg.reload()
            self._ready(pg)
            self.assertEqual(self._ids(pg), ["case-foh"], "quick filters live in the URL")
            pg.shot("inv-knox-d")

    def test_knox_bulk_condition_and_container_commit_and_undo(self) -> None:
        for size in ("d", "m"):
            with self.open(CAMPUS, size) as pg:
                self._ready(pg)
                self._type(pg, "#inv-filter", "hang")
                pg.wait_for("document.querySelectorAll(%s).length === 2" % _q(ROWS))
                # cards at m have no header row: select by the per-card checkboxes
                pg.click("#inv-table tr[data-device=main-l] .dt-check-hit")
                pg.click("#inv-table tr[data-device=main-r] .dt-check-hit")
                pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
                opts = pg.js("Array.prototype.map.call(document.querySelectorAll('#inv-bulk-condition option'), function (o) { return o.value; })")
                self.assertEqual(opts, ["", "new", "good", "fair", "poor", "broken", "__none"], "the five conditions plus clear")
                self._select(pg, "inv-bulk-condition", "poor")
                pg.wait_for("!!document.querySelector('.app-dialog')")
                self.assertEqual(pg.js("document.querySelector('.app-dialog .body').textContent").split("\n")[0],
                                 "Set condition of 2 devices in Main Auditorium?")
                pg.click(".app-dialog footer button:last-child")
                pg.wait_for("!document.querySelector('.app-dialog')")
                self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && d.inventory && d.inventory.condition === 'poor'; }).length === 2")
                pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=condition]').textContent === 'poor'")
                self.assertEqual(pg.js("document.getElementById('inv-bulk-condition').value"), "")
                self._undo(pg, size)
                self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && !(d.inventory && d.inventory.condition); }).length === 2")
                pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=condition]').textContent === ''")

                # put in container, then undo
                pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
                conts = pg.js("Array.prototype.map.call(document.querySelectorAll('#inv-bulk-container option'), function (o) { return o.value; })")
                self.assertEqual(conts, ["", "__none", "case-foh"], "containers of the project plus None")
                self._select(pg, "inv-bulk-container", "case-foh")
                pg.wait_for("!!document.querySelector('.app-dialog')")
                pg.click(".app-dialog footer button:last-child")
                self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && d.container === 'case-foh'; }).length === 2")
                pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=container]').textContent === 'FOH road case'")
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at m")
                    for sel in ("#inv-bulk-condition", "#inv-bulk-container", "#inv-q-accessories"):
                        self.assertGreaterEqual(pg.rect(sel)["height"], 44 - 0.5, "%s is a 44px touch target" % sel)
                pg.shot("inv-knox-bulk-%s" % size)
                self._undo(pg, size)
                self._wait_server(pg, "campus-demo", "doc.devices.filter(function (d) { return (d.id === 'main-l' || d.id === 'main-r') && !d.container; }).length === 2")
                pg.wait_for("document.querySelector('#inv-table tr[data-device=main-l] td[data-col=container]').textContent === ''")

    def test_knox_cards_at_m_show_the_knox_fields(self) -> None:
        with self.open(CAMPUS + "?q=foh", "m") as pg:
            self._ready(pg)
            self.assertLessEqual(pg.page_hscroll(), 0)
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('#inv-table tr[data-device=foh-cl5] td[data-col]'), function (td) {"
                           " return getComputedStyle(td).display === 'none' ? null : td.getAttribute('data-col'); }).filter(Boolean)")
            self.assertEqual(labels, ["name", "kind", "status", "condition", "container", "code", "edit"])
            self.assertEqual(self._cell(pg, "foh-cl5", "condition"), "good")
            self.assertEqual(pg.js("document.querySelector('#inv-table tr[data-device=foh-cl5] td[data-col=code] .inv-code-text').textContent"), "ABCD-2345")
            self.assertGreaterEqual(pg.rect("#inv-table tr[data-device=foh-cl5] .inv-copy")["height"], 44 - 0.5, "Copy link is a 44px target")
            self.assertEqual(pg.offscreen("#inv-table tr[data-device=foh-cl5] .inv-copy", "x"), 0)
            pg.shot("inv-knox-m")


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
