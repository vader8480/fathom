"""ST-LISTS: loading, empty, error, confirm and review states of inventory and schedules (docs/ui-audit.md B.5).

Runs the real app on a ``tests/_ui.py`` server whose throwaway ``campus-demo`` gets an empty room
("Empty Hall"), a room whose only device is planned ("Planned Hall") and a second "FOH CL5" in the Chapel
(a likely duplicate). Covered: the inventory table
skeleton until the project document is ready; the empty-room copy with Bulk add (editors) and Open patch;
bulk room/location/mark-installed edits of several devices ask ``confirmScope`` with the count and room;
the duplicates review badge beside ``#inv-dups`` opens the duplicates dialog; the schedules skeleton while
the server schedule loads (request held through CDP ``Fetch``); a failing schedule shows an inline error
with Retry in place of the table, Retry asks the server again and renders the table, and "Show local
rows" falls back to the browser's rows; per-kind empty copy naming the cause and the creating view; the
state-filter empty copy; tag assignment asks "Assign tags to N untagged cables in <room>?". Viewers get no
write actions. No horizontal page scroll at m for any state; ``smoke["errors"]`` stays empty. With
``FATHOM_UI_SHOTS`` set it writes ``st-<state>-<size>`` screenshots. Skips without Chrome (set
``FATHOM_CHROME``).
"""
from __future__ import annotations

import fnmatch
import json
import re
import time
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/"
EMPTY = "#/campus-demo/empty-hall/"
PROJECT = "/api/v2/projects/campus-demo"
ROWS = "#inv-table tbody tr.dt-row"
DIALOG = "!!document.querySelector('.app-dialog')"
NO_DIALOG = "!document.querySelector('.app-dialog')"

SCH_ROWS = """(function (kind) {
  var t = document.querySelector('#sch-dt .dt-table');
  return !!t && t.getAttribute('data-kind') === kind && t.getAttribute('aria-busy') === 'false'
    && !document.querySelector('#sch-dt .sch-statebox:not([hidden])')
    && document.querySelectorAll('#sch-dt tbody tr.dt-row').length > 0;
})(%s)"""

SHOWN = """(function (sel) {
  var el = document.querySelector(sel); if (!el) return false;
  var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
})(%s)"""


def _q(s: str) -> str:
    return json.dumps(s)


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read().decode())


def _post(base: str, path: str, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Fathom": "1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


class _Hold(object):
    """Holds matching requests in CDP ``Fetch`` until ``release()`` (``UiPage.intercept`` answers at once)."""

    def __init__(self, pg, glob: str) -> None:
        self.pg = pg
        self.glob = "*" + glob if glob.startswith("/") else glob
        self.held = []
        self._orig = pg._event

        def event(msg):
            if msg.get("method") == "Fetch.requestPaused" and fnmatch.fnmatchcase(msg["params"]["request"].get("url", ""), self.glob):
                pg.events.append(msg)
                self.held.append(msg["params"]["requestId"])
                return
            self._orig(msg)

        pg._event = event
        pg.command("Network.enable")
        pg.command("Network.setBypassServiceWorker", {"bypass": True})
        pg.command("Fetch.enable", {"patterns": [{"urlPattern": self.glob, "requestStage": "Request"}]})

    def release(self) -> None:
        self.pg._event = self._orig
        for rid in self.held:
            self.pg.command("Fetch.continueRequest", {"requestId": rid})
        self.held = []
        self.pg.command("Fetch.disable")


class ListStatesUi(UiCase):

    @classmethod
    def setUpClass(cls) -> None:
        super(ListStatesUi, cls).setUpClass()
        p = _get(cls.base, PROJECT)
        dev = [d for d in p["doc"]["devices"] if d["id"] == "foh-cl5"][0]
        twin = {k: v for k, v in dev.items() if k not in ("rack", "ports", "interfaces", "location")}
        twin.update({"id": "foh-cl5-spare", "room": "chapel"})
        venue = p["doc"]["rooms"][0].get("venue")
        vox = [d for d in p["doc"]["devices"] if d["id"] == "vox-1"][0]
        planned = {"id": "ph-future", "name": "Future lectern", "kind": vox["kind"], "manufacturer": "Nobody",
                   "model": "ST-LISTS 1", "room": "planned-hall", "status": "planned"}
        _post(cls.base, PROJECT + "/changes", {
            "base_revision": p.get("revision", 0), "summary": "fixtures for test_ui_states_lists",
            "ops": [{"op": "put", "coll": "rooms", "id": "empty-hall", "value": {"id": "empty-hall", "name": "Empty Hall", "venue": venue}},
                    {"op": "put", "coll": "rooms", "id": "planned-hall", "value": {"id": "planned-hall", "name": "Planned Hall", "venue": venue}},
                    {"op": "put", "coll": "devices", "id": "ph-future", "value": planned},
                    {"op": "put", "coll": "devices", "id": "foh-cl5-spare", "value": twin}]})

    # ------------------------------------------------------------ helpers

    def _viewer(self):
        proj = _get(self.base, PROJECT)
        proj["role"] = "viewer"
        return [(PROJECT, 200, proj, "GET")]

    def _clean(self, pg) -> None:
        self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)

    def _no_hscroll(self, pg, what: str) -> None:
        self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll: %s at %s" % (what, pg.size))

    def _text(self, pg, sel: str) -> str:
        return pg.js("(document.querySelector(%s) || {}).textContent || ''" % _q(sel))

    def _dialog_text(self, pg) -> str:
        pg.wait_for(DIALOG)
        return pg.js("document.querySelector('.app-dialog .body').textContent").split("\n")[0]

    def _cancel(self, pg) -> None:
        pg.press("Escape")
        pg.wait_for(NO_DIALOG)

    def _select(self, pg, ident: str, value: str) -> None:
        pg.js("(function (s) { s.value = %s; s.dispatchEvent(new Event('change', {bubbles: true})); })(document.getElementById(%s))"
              % (_q(value), _q(ident)))

    def _revision(self, pg) -> int:
        return pg.js("fetch(%s).then(function (r) { return r.json(); }).then(function (p) { return p.revision; })" % _q(PROJECT))

    # ------------------------------------------------------------ inventory

    def test_inventory_skeleton_until_the_doc_is_ready(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(CAMPUS + "home", size) as pg:
                self._clean(pg)
                st = pg.js("""import('/static/js/inventory.js').then(function (m) {
                  var host = document.createElement('div'); host.id = 'st-inv-host';
                  var main = document.getElementById('app-main'); main.innerHTML = ''; main.appendChild(host);
                  var store = new EventTarget(); store.doc = null; store.room = 'main'; store.readOnly = false;
                  window.__stInv = {store: store, handle: m.mount(host, {store: store, vocab: {}, api: null, project: 'x',
                    toast: function () {}, commit: function () {}, confirm: function () { return Promise.resolve(true); }})};
                  var sk = host.querySelector('.fb-skeleton');
                  return {skeleton: !!sk, busy: sk && sk.getAttribute('aria-busy'), kind: sk && sk.getAttribute('data-kind'),
                    table: !!host.querySelector('#inv-table')};
                })""")
                self.assertEqual(st, {"skeleton": True, "busy": "true", "kind": "table", "table": False})
                self._no_hscroll(pg, "inventory skeleton")
                pg.shot("st-inv-skeleton-" + size)
                pg.js("""(function () { var s = window.__stInv.store;
                  s.doc = {rooms: [{id: 'main', name: 'Main Auditorium'}], devices: [{id: 'mic-1', name: 'Mic 1', kind: 'mic', room: 'main'}]};
                  s.dispatchEvent(new Event('doc')); })()""")
                pg.wait_for("!!document.querySelector('#st-inv-host #inv-table tr[data-device=\"mic-1\"]')")
                self.assertFalse(pg.js("!!document.querySelector('#st-inv-host .fb-skeleton')"), "the skeleton is replaced, not kept")
                pg.js("window.__stInv.handle.destroy(); 1")
                self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def test_inventory_empty_room(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(EMPTY + "inventory", size) as pg:
                self._clean(pg)
                pg.wait_for("!!document.querySelector('.inv-root .fb-empty')")
                self.assertEqual(self._text(pg, ".inv-root .fb-empty-title"), "No devices in Empty Hall.")
                self.assertEqual(self._text(pg, ".inv-root .fb-empty-text"), "Add gear in Patch or bulk add from a spreadsheet.")
                self.assertEqual(self._text(pg, ".inv-root .fb-empty-action"), "Bulk add\u2026")
                self.assertEqual(self._text(pg, ".inv-root .fb-empty-secondary"), "Open patch")
                self.assertEqual(pg.js("document.querySelector('.inv-root .fb-empty-secondary').getAttribute('href')"), EMPTY + "patch")
                self._no_hscroll(pg, "inventory empty")
                self.assertEqual(pg.offscreen(".inv-root .fb-empty-actions > *", "x"), 0)
                pg.shot("st-inv-empty-" + size)
                if size == "d":
                    pg.click(".inv-root .fb-empty-action")
                    pg.wait_for("!!document.querySelector('.wz') && document.querySelector('.wz').getAttribute('data-step') === 'paste'")
                    self.assertEqual(pg.js("document.getElementById(document.querySelector('.wz').getAttribute('aria-labelledby')).textContent"),
                                     "Bulk add devices")
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.wz')")
                    pg.click(".inv-root .fb-empty-secondary")
                    pg.wait_for("location.hash.split('?')[0] === %s" % _q(EMPTY + "patch"))
        with self.open(EMPTY + "inventory", "m", intercepts=self._viewer()) as pg:
            self._clean(pg)
            pg.wait_for("!!document.querySelector('.inv-root .fb-empty')")
            self.assertEqual(self._text(pg, ".inv-root .fb-empty-text"), "Add gear in Patch.")
            self.assertEqual(self._text(pg, ".inv-root .fb-empty-action"), "Open patch", "viewers keep the navigation")
            self.assertNotIn("Bulk add", pg.js("document.querySelector('.inv-root').innerText"), "no Bulk add for viewers")
            self.assertTrue(pg.js("document.getElementById('inv-bulk-add').hidden"))
            self._no_hscroll(pg, "inventory empty (viewer)")
            pg.shot("st-inv-empty-viewer-m")

    def test_inventory_bulk_edits_confirm_with_count_and_room(self) -> None:
        with self.open(CAMPUS + "inventory?q=hang", "d") as pg:
            self._clean(pg)
            pg.wait_for("document.querySelectorAll(%s).length === 2" % _q(ROWS))
            pg.click("#inv-table thead .dt-check-hit")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
            rev = self._revision(pg)
            self._select(pg, "inv-bulk-room", "chapel")
            self.assertEqual(self._dialog_text(pg), "Move 2 devices in Main Auditorium?")
            self.assertIn("They move to Chapel.", pg.js("document.querySelector('.app-dialog .body').textContent"))
            pg.shot("st-inv-confirm-d")
            self._cancel(pg)
            self._select(pg, "inv-bulk-location", "catwalk")
            self.assertEqual(self._dialog_text(pg), "Set location of 2 devices in Main Auditorium?")
            self.assertIn("New location: Catwalk.", pg.js("document.querySelector('.app-dialog .body').textContent"))
            self._cancel(pg)
            pg.wait_for("document.getElementById('inv-bulk-location').value === ''")
            self.assertEqual(self._revision(pg), rev, "cancelled bulk edits write nothing")
        with self.open(CAMPUS + "inventory?q=light", "m") as pg:
            self._clean(pg)
            pg.wait_for("!!document.querySelector('#inv-table tr[data-device=\"bc-ma3\"]') && "
                        "document.querySelectorAll(%s).length >= 2" % _q(ROWS))
            pg.js("""['bc-ma3', 'lustr-1'].forEach(function (id) {
              var cb = document.querySelector('#inv-table tr[data-device="' + id + '"] .dt-row-check');
              cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles: true})); }); 1""")
            pg.wait_for("document.querySelectorAll('#inv-table tbody .dt-row-check:checked').length === 2")
            pg.js("document.getElementById('inv-mark-installed').click(); 1")
            self.assertEqual(self._dialog_text(pg), "Mark installed: 1 device in Main Auditorium?")
            self._no_hscroll(pg, "inventory confirm")
            pg.shot("st-inv-confirm-m")
            self._cancel(pg)

    def test_duplicates_review_badge(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(CAMPUS + "inventory", size) as pg:
                self._clean(pg)
                pg.wait_for("!!document.querySelector('.inv-review:not([hidden]) .fb-review')", 20)
                self.assertEqual(self._text(pg, ".inv-review .fb-review-label"), "1 duplicate to review")
                self.assertTrue(pg.js("document.querySelector('#inv-dups').nextElementSibling === document.querySelector('.inv-review')"),
                                "the badge sits beside #inv-dups")
                self._no_hscroll(pg, "duplicates badge")
                self.assertEqual(pg.offscreen(".inv-review .fb-review", "x"), 0)
                pg.shot("st-inv-review-" + size)
                if size == "d":
                    pg.click(".inv-review .fb-review")
                    pg.wait_for("!!document.querySelector('.mg-dups .mg-hint')", 20)
                    self.assertIn("FOH CL5", pg.js("document.querySelector('.mg-dups').textContent"))
                    pg.shot("st-inv-review-dialog-d")
        with self.open(CAMPUS + "inventory", "d", intercepts=[("/api/v2/projects/campus-demo/devices/duplicates*", 200,
                                                               {"revision": 1, "min_score": 0.5, "total": 0, "duplicates": []})]) as pg:
            self._clean(pg)
            pg.wait_for("document.querySelectorAll(%s).length > 0" % _q(ROWS))
            deadline = time.time() + 15
            while not pg.rules[0]["hits"] and time.time() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(pg.rules[0]["hits"], 1, "the duplicates count was requested")
            pg.js("new Promise(function (r) { setTimeout(r, 200); })")
            self.assertFalse(pg.js("!!document.querySelector('.inv-review .fb-review')"), "no badge at 0")

    # ------------------------------------------------------------ schedules

    def test_schedules_skeleton_while_the_server_schedule_loads(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(CAMPUS + "schedules/cables", size) as pg:
                self._clean(pg)
                pg.wait_for(SCH_ROWS % _q("cables"), 20)
                hold = _Hold(pg, "/api/v2/projects/campus-demo/schedules/ip*")
                try:
                    pg.js("document.getElementById('sch-tab-ip').click(); 1")
                    pg.wait_for("!!document.querySelector('#sch-dt .sch-statebox:not([hidden]) .fb-skeleton[aria-busy=true]')")
                    self.assertEqual(pg.js("document.querySelector('#sch-dt .sch-statebox .fb-skeleton').getAttribute('data-kind')"), "table")
                    self.assertTrue(pg.js(SHOWN % _q("#sch-filter")), "the toolbar stays while loading")
                    self.assertFalse(pg.js(SHOWN % _q("#sch-dt .dt-scroll")), "the skeleton stands in for the table body")
                    self._no_hscroll(pg, "schedules skeleton")
                    pg.shot("st-sch-skeleton-" + size)
                    self.assertGreaterEqual(len(hold.held), 1)
                finally:
                    hold.release()
                pg.wait_for(SCH_ROWS % _q("ip"), 20)
                self.assertFalse(pg.js("!!document.querySelector('#sch-dt .fb-skeleton')"))

    def test_schedules_load_error_retry_and_local_rows(self) -> None:
        for size in ("d", "t", "m"):
            with self.open(CAMPUS + "schedules/ip", size, intercepts=[("/api/v2/projects/campus-demo/schedules/ip*", 500, {"error": "schedule backend down"})]) as pg:
                self._clean(pg)
                rule = pg.rules[0]
                pg.wait_for("!!document.querySelector('#sch-dt .sch-loadfail .fb-error[role=alert]')", 20)
                self.assertIn("schedule backend down", self._text(pg, "#sch-dt .sch-loadfail .fb-error-msg"))
                self.assertEqual(self._text(pg, "#sch-dt .sch-loadfail .fb-retry"), "Retry")
                self.assertEqual(self._text(pg, "#sch-dt .sch-loadfail .sch-local"), "Show local rows")
                self.assertFalse(pg.js(SHOWN % _q("#sch-dt .dt-scroll")), "the error is in place of the table")
                self._no_hscroll(pg, "schedules error")
                self.assertEqual(pg.offscreen("#sch-dt .sch-loadfail button", "x"), 0)
                pg.shot("st-sch-error-" + size)
                if size != "d":
                    continue
                hits = rule["hits"]
                pg.click("#sch-dt .sch-loadfail .fb-retry")
                pg.wait_for("!!document.querySelector('#sch-dt .sch-loadfail .fb-retry:not([disabled])')", 20)
                self.assertGreater(rule["hits"], hits, "Retry asks the server again")
                pg.clear_intercepts()
                pg.click("#sch-dt .sch-loadfail .fb-retry")
                pg.wait_for(SCH_ROWS % _q("ip"), 20)
                self.assertFalse(pg.js("!!document.querySelector('#sch-dt .fb-error')"))
                server = _get(self.base, PROJECT + "/schedules/ip?room=main")["rows"]
                self.assertEqual(pg.js("document.querySelector('#sch-dt .dt-count').textContent"),
                                 "%d address%s" % (len(server), "" if len(server) == 1 else "es"))
        with self.open(CAMPUS + "schedules/ip", "d", intercepts=[("/api/v2/projects/campus-demo/schedules/ip*", 503, {"error": "busy"})]) as pg:
            pg.wait_for("!!document.querySelector('#sch-dt .sch-loadfail .sch-local')", 20)
            pg.click("#sch-dt .sch-loadfail .sch-local")
            pg.wait_for(SCH_ROWS % _q("ip"), 20)
            self.assertIn("computed in the browser", self._text(pg, ".sch-error .sch-error-note"))

    def test_schedules_empty_per_kind(self) -> None:
        copy = {
            "cables": ("No cables in Empty Hall yet.", "bulk add cables from a spreadsheet", "Bulk add cables\u2026", "Open patch", "patch"),
            "ip": ("No IP addresses recorded in Empty Hall yet.", "Network tab", "Open devices", None, "devices"),
            "dmx": ("No DMX addresses in Empty Hall yet.", "universe/address on a lighting device", "Open devices", None, "devices"),
            "bom": ("Nothing to count in Empty Hall yet.", "Patch or Inventory", "Open inventory", None, "inventory"),
            "patch": ("No ports in Empty Hall yet.", "Patch view", "Open patch", None, "patch"),
            "racks": ("No racks in Empty Hall yet.", "Racks view", "Open racks", None, "racks"),
        }
        for size in ("m", "t", "d"):
            with self.open(EMPTY + "schedules/cables", size) as pg:
                self._clean(pg)
                for kind, (title, text, action, secondary, view) in copy.items():
                    with self.subTest(size=size, kind=kind):
                        pg.goto(EMPTY + "schedules/" + kind)
                        pg.wait_for("(function () { var t = document.querySelector('#sch-dt .dt-table');"
                                    " return !!t && t.getAttribute('data-kind') === %s && !!document.querySelector('#sch-dt .fb-empty'); })()" % _q(kind), 20)
                        self.assertEqual(self._text(pg, "#sch-dt .fb-empty-title"), title)
                        self.assertIn(text, self._text(pg, "#sch-dt .fb-empty-text"))
                        self.assertEqual(self._text(pg, "#sch-dt .fb-empty-action"), action)
                        if secondary:
                            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-secondary"), secondary)
                        nav = "#sch-dt .fb-empty-secondary" if secondary else "#sch-dt .fb-empty-action"
                        self.assertEqual(pg.js("document.querySelector(%s).getAttribute('href')" % _q(nav)), EMPTY + view)
                        self._no_hscroll(pg, "schedules %s empty" % kind)
                        self.assertEqual(pg.offscreen("#sch-dt .fb-empty-actions > *", "x"), 0)
                        pg.shot("st-sch-empty-%s-%s" % (kind, size))
                if size == "d":
                    pg.goto(EMPTY + "schedules/cables")
                    pg.wait_for("!!document.querySelector('#sch-dt .fb-empty-action')", 20)
                    pg.click("#sch-dt .fb-empty-action")
                    pg.wait_for("!!document.querySelector('.wz textarea[name=text]')")
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.wz')")
        self.assertEqual(_get(self.base, PROJECT + "/schedules/bom?room=planned-hall&state=as_built")["rows"], [])
        self.assertTrue(_get(self.base, PROJECT + "/schedules/bom?room=planned-hall&state=everything")["rows"])
        with self.open("#/campus-demo/planned-hall/schedules/bom", "m") as pg:
            self._clean(pg)
            pg.wait_for(SCH_ROWS % _q("bom"), 20)
            self._select(pg, "sch-state", "as_built")
            pg.wait_for("!!document.querySelector('#sch-dt .fb-empty')", 20)
            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-title"), "No lines match the state filter.")
            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-text"), "State \u201cAs built\u201d hides planned, spare and retired items.")
            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-action"), "Show everything")
            self._no_hscroll(pg, "schedules state-filter empty")
            pg.shot("st-sch-empty-statefilter-m")
            pg.click("#sch-dt .fb-empty-action")
            pg.wait_for(SCH_ROWS % _q("bom"), 20)
            self.assertEqual(pg.js("document.getElementById('sch-state').value"), "everything")
        with self.open(EMPTY + "schedules/cables", "m", intercepts=self._viewer()) as pg:
            self._clean(pg)
            pg.wait_for("!!document.querySelector('#sch-dt .fb-empty')", 20)
            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-text"), "Patch ports in the Patch view to create cables.")
            self.assertEqual(self._text(pg, "#sch-dt .fb-empty-action"), "Open patch")
            self.assertFalse(pg.js("!!document.querySelector('#sch-dt .fb-empty-secondary')"))
            self.assertFalse(pg.js("!!document.getElementById('sch-bulk-add')"), "no Bulk add cables for viewers")
            self.assertFalse(pg.js("!!document.getElementById('sch-assign-tags')"), "no Assign tags for viewers")
            self._no_hscroll(pg, "schedules empty (viewer)")
            pg.shot("st-sch-empty-viewer-m")

    def test_tag_assignment_confirms_with_count_and_room(self) -> None:
        preview = _get(self.base, PROJECT + "/cables/tag-preview?scope=missing")
        cables = [o for o in preview["ops"] if o.get("coll", "cables") == "cables"]
        doc = _get(self.base, PROJECT)["doc"]
        devs = {d["id"]: d for d in doc["devices"]}
        rooms = {r["id"]: r["name"] for r in doc["rooms"]}
        cabs = {c["id"]: c for c in doc["cables"]}
        seen = set()
        for o in cables:
            c = cabs[o["id"]]
            for end in (c["from"], c["to"]):
                if end.get("device") in devs:
                    seen.add(devs[end["device"]].get("room") or "")
        scope = rooms.get(next(iter(seen)), "shared inventory") if len(seen) == 1 else "%d rooms" % len(seen)
        expect = "Assign tags to %d untagged cables in %s?" % (len(cables), scope)
        for size in ("d", "t", "m"):
            with self.open(CAMPUS + "schedules/cables", size) as pg:
                self._clean(pg)
                pg.wait_for(SCH_ROWS % _q("cables"), 20)
                pg.click("#sch-assign-tags")
                pg.wait_for("!!document.querySelector('.sch-tagresult [data-act=confirm]')", 20)
                rev = self._revision(pg)
                pg.click(".sch-tagresult [data-act=confirm]")
                self.assertEqual(self._dialog_text(pg), expect)
                self.assertTrue(re.match(r"^Assign tags to \d+ untagged cables in .+\?$", expect))
                self._no_hscroll(pg, "tag confirm")
                pg.shot("st-sch-tags-confirm-" + size)
                if size != "d":
                    self._cancel(pg)
                    continue
                self._cancel(pg)
                self.assertEqual(self._revision(pg), rev, "cancelling assigns nothing")
                self.assertFalse(pg.js("document.querySelector('.sch-tagpanel').hidden"), "the preview stays open after cancel")
                pg.click(".sch-tagresult [data-act=confirm]")
                pg.wait_for(DIALOG)
                pg.click(".app-dialog footer button:last-child")
                pg.wait_for(NO_DIALOG)
                pg.wait_for("fetch(%s).then(function (r) { return r.json(); }).then(function (p) {"
                            " return p.doc.cables.filter(function (c) { return !c.auto && !c.tag; }).length === 0; })" % _q(PROJECT), 20)
                pg.click("#app-undo")
                pg.wait_for("fetch(%s).then(function (r) { return r.json(); }).then(function (p) {"
                            " return p.doc.cables.filter(function (c) { return !c.auto && !c.tag; }).length === %d; })"
                            % (_q(PROJECT), len(cables)), 20)


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
