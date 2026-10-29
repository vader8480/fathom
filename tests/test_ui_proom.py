"""PROOM: room landing and room page (docs/ui-audit.md B.3 PROOM, D1, D4, D5, D7, B.8).

Landing DataTable (row → room page with the room segment set), URL tabs with the default-tab replace,
reload on ``rooms/chapel/cables`` with the room picker on Chapel, cable rows opening the drawer in place,
the sticky header, overview drill-downs through ``openTableDialog``, the explorer, an unknown room, the
viewer role, and d/t/m layout without page horizontal scroll. Skips without Chrome (set
``FATHOM_CHROME``); ``$FATHOM_UI_SHOTS`` collects screenshots.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

P = "#/campus-demo/"
LANDING = P + "main/rooms"

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

ROW_IDS = "[].map.call(document.querySelectorAll('.dt-root[data-table=\"%s\"] tbody tr.dt-row'), function (tr) { return tr.dataset.id; })"

HEADER = """(function () {
  var eh = document.querySelector('header.eh'), sc = document.querySelector('.ex-content');
  if (!eh || !sc) return null;
  var r = eh.getBoundingClientRect(), s = sc.getBoundingClientRect();
  return {top: r.top, scTop: s.top, scrollTop: sc.scrollTop, compact: eh.classList.contains('eh--compact'),
          title: eh.querySelector('.eh-title').textContent, id: eh.getAttribute('data-id'),
          tab: (eh.querySelector('.eh-tab[aria-selected=true]') || {}).getAttribute ? eh.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab') : null,
          actions: [].map.call(eh.querySelectorAll('[data-action]'), function (a) { return a.getAttribute('data-action'); })};
})()"""

# Visible controls of the room page and their smallest side.
TARGETS = """(function (sel) {
  var out = [];
  document.querySelectorAll(sel).forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') return;
    out.push({el: el.className || el.tagName, text: el.textContent.trim().slice(0, 20), w: Math.round(r.width), h: Math.round(r.height)});
  });
  return out;
})(%s)"""


class RoomPageUi(UiCase):
    # ------------------------------------------------------------ helpers

    def landing_ready(self, pg) -> None:
        self.assertEqual(pg.smoke["errors"], [])
        pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length === 3")

    def page_ready(self, pg, room: str, tab: str) -> None:
        pg.wait_for("location.hash.indexOf('/rooms/%s/%s') > 0" % (room, tab))
        pg.wait_for("(function () { var t = document.querySelector('header.eh[data-id=%s] .eh-tab[aria-selected=true]');"
                    " return !!t && t.getAttribute('data-tab') === '%s' && !!document.querySelector('.pr-panel[data-tab=%s]'); })()"
                    % (room, tab, tab))

    def rows(self, pg, key: str):
        return pg.js(ROW_IDS % key)

    # ------------------------------------------------------------ landing

    def test_landing_table_row_navigates_with_room_segment(self):
        with self.open(LANDING, "d") as pg:
            self.landing_ready(pg)
            self.assertEqual(self.rows(pg, "rooms"), ["main", "chapel", "broadcast"])
            heads = pg.js("[].map.call(document.querySelectorAll('.dt-root[data-table=rooms] thead th'), function (t) { return t.textContent.trim(); })")
            for col in ("Name", "Code", "Devices", "Cables", "Racks", "Plans", "Procedures"):
                self.assertIn(col, heads)
            self.assertTrue(pg.js("[].every.call(document.querySelectorAll('.dt-root[data-table=rooms] th'), function (t) { return t.hasAttribute('scope'); })"))
            cells = pg.js("[].map.call(document.querySelectorAll('.dt-root[data-table=rooms] tr[data-id=chapel] td'), function (t) { return t.textContent.trim(); })")
            self.assertEqual(cells[:2], ["Chapel", "CHPL"])
            self.assertEqual(pg.js("document.querySelector('a.pr-room-link[data-room=chapel]').getAttribute('href')"),
                             P + "chapel/rooms/chapel/overview")
            n = pg.js("history.length")
            pg.click(".dt-root[data-table=rooms] tr[data-id=chapel] td[data-col=devices]")
            self.page_ready(pg, "chapel", "overview")
            self.assertEqual(pg.hash, P + "chapel/rooms/chapel/overview")
            self.assertEqual(pg.js("history.length"), n + 1, "a landing row pushes one entry")
            pg.wait_for("document.getElementById('app-room').value === 'chapel'")
            self.assertEqual(pg.js(HEADER)["title"], "Chapel")
            self.assertIn("Chapel", pg.js("document.title"))
            recent = pg.js("JSON.parse(localStorage.getItem('fathom.ui.recent.campus-demo') || '{}')")
            self.assertEqual([e["id"] for e in recent.get("room", [])][:1], ["chapel"])
            pg.js("history.back()")
            pg.wait_for("location.hash === %s" % json.dumps(LANDING))
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length === 3")
            # landing search is URL state (replaceState)
            pg.js("(function (i) { i.value = 'chap'; i.dispatchEvent(new Event('input', {bubbles: true})); })(document.querySelector('.dt-root[data-table=rooms] .dt-search'))")
            pg.wait_for("location.hash.indexOf('q=chap') > 0")
            self.assertEqual(self.rows(pg, "rooms"), ["chapel"])

    def test_landing_for_all_rooms_at_m(self):
        with self.open(P + "*/rooms", "m") as pg:
            self.landing_ready(pg)
            self.assertFalse(pg.js("!!document.querySelector('header.eh')"))

    # ------------------------------------------------------------ tabs in the URL

    def test_default_tab_is_replaced_not_pushed(self):
        with self.open(LANDING, "d") as pg:
            self.landing_ready(pg)
            n = pg.js("history.length")
            pg.goto(P + "main/rooms/main")
            self.page_ready(pg, "main", "overview")
            self.assertEqual(pg.hash, P + "main/rooms/main/overview")
            self.assertEqual(pg.js("history.length"), n + 1, "the overview redirect replaces the entry")
            pg.goto(P + "chapel/rooms/chapel/bogus")
            self.page_ready(pg, "chapel", "overview")
            self.assertEqual(pg.hash, P + "chapel/rooms/chapel/overview")

    def test_tab_click_pushes_and_back_returns(self):
        with self.open(P + "main/rooms/main/overview", "d") as pg:
            self.page_ready(pg, "main", "overview")
            labels = pg.js("[].map.call(document.querySelectorAll('header.eh .eh-tab'), function (t) { return t.dataset.tab; })")
            self.assertEqual(labels, ["overview", "devices", "cables", "racks", "plans", "procedures"])
            self.assertEqual(pg.js("document.querySelector('.eh-tab[data-tab=devices] .eh-count').textContent"), "49")
            pg.click("header.eh .eh-tab[data-tab=devices]")
            self.page_ready(pg, "main", "devices")
            self.assertEqual(len(self.rows(pg, "room.devices")), 49)
            pg.js("history.back()")
            self.page_ready(pg, "main", "overview")
            pg.js("history.forward()")
            self.page_ready(pg, "main", "devices")
            # a device row opens the drawer in place (D4)
            pg.click(".dt-root[data-table='room.devices'] tr[data-id=foh-cl5] td[data-col=name]")
            pg.wait_for("location.hash.indexOf('sel=device:foh-cl5') > 0")
            pg.wait_for(DRAWER_OPEN)
            self.assertTrue(pg.hash.startswith(P + "main/rooms/main/devices?"))
            pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('FOH') >= 0")

    def test_reload_cables_room_picker_and_cable_row_drawer(self):
        url = P + "chapel/rooms/chapel/cables"
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(url, size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.page_ready(pg, "chapel", "cables")
                self.assertEqual(pg.js("document.getElementById('app-room').value"), "chapel")
                pg.reload()
                self.page_ready(pg, "chapel", "cables")
                self.assertEqual(pg.js("document.getElementById('app-room').value"), "chapel")
                ids = self.rows(pg, "room.cables")
                self.assertEqual(len(ids), 16)
                n = pg.js("history.length")
                pg.click(".dt-root[data-table='room.cables'] tr[data-id=%s] td[data-col=from]" % ids[0])
                pg.wait_for("location.hash.indexOf('sel=cable:%s') > 0" % ids[0])
                pg.wait_for(DRAWER_OPEN)
                self.assertTrue(pg.hash.startswith(url + "?"), pg.hash)
                self.assertEqual(pg.js("document.querySelectorAll('.pr-panel[data-tab=cables]').length"), 1)
                self.assertLessEqual(pg.js("history.length"), n + 1)
                pg.reload()
                self.page_ready(pg, "chapel", "cables")
                pg.wait_for(DRAWER_OPEN)

    # ------------------------------------------------------------ header, explorer, overview

    def test_sticky_header_after_scroll(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "main/rooms/main/cables", size) as pg:
                self.page_ready(pg, "main", "cables")
                pg.js("document.querySelector('.ex-content').scrollTop = 1500")
                pg.wait_for("document.querySelector('.ex-content').scrollTop >= 1000")
                pg.wait_for("document.querySelector('header.eh').classList.contains('eh--compact')")
                st = pg.js(HEADER)
                self.assertGreaterEqual(st["scrollTop"], 1000)
                self.assertLessEqual(abs(st["top"] - st["scTop"]), 1.5, st)
                self.assertTrue(st["compact"])

    def test_overview_cards_drill_down(self):
        with self.open(P + "main/rooms/main/overview", "d") as pg:
            self.page_ready(pg, "main", "overview")
            keys = pg.js("[].map.call(document.querySelectorAll('.pr-card[data-card]'), function (c) { return c.dataset.card; })")
            self.assertEqual(keys, ["devices", "cables", "racks", "plans", "procedures", "problems"])
            n = int(pg.js("document.querySelector('.pr-card[data-card=cables] .pr-card-n').textContent"))
            self.assertEqual(str(n), pg.js("document.querySelector('.eh-tab[data-tab=cables] .eh-count').textContent"))
            pg.click(".pr-card[data-card=cables] .pr-card-main")
            pg.wait_for("!!document.querySelector('.app-dialog.dt-dialog .dt-root')")
            self.assertEqual(pg.js("document.querySelector('.app-dialog.dt-dialog h2').textContent"),
                             "%d cables \u00b7 Main Auditorium" % n)
            pg.wait_for("/ of %d$/.test(document.querySelector('.app-dialog.dt-dialog .dt-range').textContent)" % n)
            first = pg.js("document.querySelector('.app-dialog.dt-dialog tbody tr.dt-row').dataset.id")
            pg.click(".app-dialog.dt-dialog tbody tr.dt-row[data-id=%s] td" % first)
            pg.wait_for("!document.querySelector('.app-dialog.dt-dialog')")
            pg.wait_for("location.hash.indexOf('sel=cable:%s') > 0" % first)
            pg.wait_for(DRAWER_OPEN)
            self.assertTrue(pg.hash.startswith(P + "main/rooms/main/overview?"))
            # the card's tab link switches tab
            pg.press("Escape")
            pg.click(".pr-card[data-card=racks] a.pr-card-tab")
            self.page_ready(pg, "main", "racks")
            self.assertEqual(self.rows(pg, "room.racks"), ["rk-foh", "rk-amp"])

    def test_explorer_switches_room_and_keeps_tab(self):
        with self.open(P + "main/rooms/main/cables", "d") as pg:
            self.page_ready(pg, "main", "cables")
            items = pg.js("[].map.call(document.querySelectorAll('.ex-root[data-explorer=rooms] .ex-item'), function (li) { return [li.dataset.id, li.getAttribute('aria-selected')]; })")
            self.assertEqual(items, [["main", "true"], ["chapel", "false"], ["broadcast", "false"]])
            self.assertEqual(pg.js("document.querySelector('.ex-root[data-explorer=rooms] .ex-group-label').textContent"), "Riverside Campus")
            pg.click(".ex-root[data-explorer=rooms] .ex-item[data-id=broadcast] a")
            self.page_ready(pg, "broadcast", "cables")
            self.assertEqual(pg.hash, P + "broadcast/rooms/broadcast/cables")
            pg.wait_for("document.getElementById('app-room').value === 'broadcast'")
            # the header room picker moves the page to another room
            pg.js("(function (s) { s.value = 'chapel'; s.dispatchEvent(new Event('change', {bubbles: true})); })(document.getElementById('app-room'))")
            self.page_ready(pg, "chapel", "cables")
            self.assertEqual(pg.js("document.querySelector('.ex-item[aria-selected=true]').dataset.id"), "chapel")

    def test_plans_and_procedures_rows_navigate(self):
        with self.open(P + "chapel/rooms/chapel/plans", "d") as pg:
            self.page_ready(pg, "chapel", "plans")
            self.assertEqual(self.rows(pg, "room.plans"), ["fp-chapel"])
            pg.click(".dt-root[data-table='room.plans'] tr[data-id=fp-chapel] td")
            pg.wait_for("location.hash.indexOf('/plan/fp-chapel') > 0")
            pg.goto(P + "chapel/rooms/chapel/procedures")
            self.page_ready(pg, "chapel", "procedures")
            self.assertEqual(self.rows(pg, "room.procedures"), ["chapel-pre-service"])
            pg.click(".dt-root[data-table='room.procedures'] tr.dt-row td")
            pg.wait_for("location.hash.indexOf('/sop?page=chapel-pre-service') > 0")

    def test_unknown_room(self):
        with self.open(P + "main/rooms/nope", "d") as pg:
            pg.wait_for("!!document.querySelector('.pr-notfound .fb-error')")
            self.assertEqual(pg.smoke["errors"], [])
            self.assertIn("Room \u201cnope\u201d not found", pg.js("document.querySelector('.pr-notfound').textContent"))
            self.assertEqual(pg.js("document.querySelector('.pr-notfound a.pr-back').getAttribute('href')"), P + "main/rooms")
            self.assertEqual(pg.js("document.querySelectorAll('.ex-root[data-explorer=rooms] .ex-item').length"), 3)

    def test_header_links_and_viewer_role(self):
        with self.open(P + "main/rooms/main/overview", "d") as pg:
            self.page_ready(pg, "main", "overview")
            hrefs = pg.js("(function () { var o = {}; document.querySelectorAll('header.eh [data-action]').forEach(function (a) { o[a.dataset.action] = a.getAttribute('href'); }); return o; })()")
            self.assertEqual(hrefs["patch"], P + "main/patch")
            self.assertEqual(hrefs["plan"], P + "main/plan")
            self.assertEqual(hrefs["racks"], P + "main/racks")
            self.assertEqual(hrefs["sop"], P + "main/sop")
            self.assertEqual(hrefs["edit"], P + "main/settings/rooms?hl=main")
            self.assertTrue(hrefs["public"].endswith("/p/campus-demo/r/main"))
            self.assertIn("/floorplans/fp-main-floor/image", pg.js("document.querySelector('header.eh .eh-thumb img').getAttribute('src')"))
            self.assertEqual(pg.js("document.querySelector('header.eh a.eh-thumb').getAttribute('href')"), P + "main/plan/fp-main-floor")
        raw = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/campus-demo").read().decode())
        raw["role"] = "viewer"
        with self.open(P + "main/rooms/main/overview", "d", intercepts=[("/api/v2/projects/campus-demo", 200, raw, "GET")]) as pg:
            self.page_ready(pg, "main", "overview")
            self.assertEqual(pg.smoke["errors"], [])
            actions = pg.js(HEADER)["actions"]
            self.assertNotIn("edit", actions)
            self.assertIn("patch", actions)

    # ------------------------------------------------------------ three sizes

    def test_three_sizes_layout(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(LANDING, size) as pg:
                self.landing_ready(pg)
                self.assertLessEqual(pg.page_hscroll(), 0, "landing scrolls horizontally at %s" % size)
                pg.shot("rooms-" + size)
                pg.goto(P + "main/rooms/main/overview")
                self.page_ready(pg, "main", "overview")
                if size != "m":  # the thumbnail is hidden (and lazy) at sm
                    pg.wait_for("document.querySelector('header.eh .eh-thumb img').complete")
                self.assertLessEqual(pg.page_hscroll(), 0, "room page scrolls horizontally at %s" % size)
                self.assertEqual(pg.offscreen("header.eh .eh-action, header.eh .eh-more", "x"), 0)
                self.assertEqual(pg.offscreen(".pr-card", "x"), 0)
                minimum = 44 if size in ("t", "m") else 40
                for t in pg.js(TARGETS % json.dumps("button.pr-card-main, a.pr-card-tab")):
                    self.assertGreaterEqual(min(t["w"], t["h"]), minimum, t)
                pg.shot("room-overview-" + size)
                pg.goto(P + "main/rooms/main/cables")
                self.page_ready(pg, "main", "cables")
                self.assertLessEqual(pg.page_hscroll(), 0, "cables tab scrolls horizontally at %s" % size)
                pg.shot("room-cables-" + size)
                minimum = 44 if size in ("t", "m") else 40
                for t in pg.js(TARGETS % json.dumps("header.eh .eh-tab, header.eh .eh-action, header.eh .eh-more, .ex-open, .dt-search")):
                    self.assertGreaterEqual(min(t["w"], t["h"]), minimum, t)
                if size == "m":
                    self.assertTrue(pg.js("document.querySelector('header.eh').classList.contains('eh--compact')"))
                    self.assertFalse(pg.js("(function () { var s = document.querySelector('.ex-side'); var r = s.getBoundingClientRect(); return r.right > 0 && getComputedStyle(s).visibility !== 'hidden'; })()"))
                    pg.click(".ex-open")
                    pg.wait_for("document.querySelector('.ex-root').classList.contains('ex-is-open')")
                    pg.js("new Promise(function (r) { setTimeout(r, 350); })")
                    pg.shot("room-explorer-m")
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.ex-root').classList.contains('ex-is-open')")
                else:
                    self.assertTrue(pg.js("getComputedStyle(document.querySelector('.ex-side')).position !== 'fixed'"))


# ---------------------------------------------------------------- add room from starter (phase3 P3C)

STARTER_P = "#/starter-ui/"
STARTER_CARDS = "[].map.call(document.querySelectorAll('.app-dialog .pr-starter'), function (c) { return c.getAttribute('data-starter'); })"


class RoomStarterUi(UiCase):
    """Rooms ▸ **Add room from starter…** (FR-ROOM-09/10) on its own ``starter-ui`` copy of campus-demo, so
    the three-room assumptions of ``RoomPageUi`` stay true."""

    @classmethod
    def setUpClass(cls) -> None:
        super(RoomStarterUi, cls).setUpClass()
        req = urllib.request.Request(cls.base + "/api/v2/projects", method="POST",
                                     data=json.dumps({"name": "starter-ui", "template": "campus-demo"}).encode(),
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 201, r.status

    def rooms_ready(self, pg, n: int) -> None:
        self.assertEqual(pg.smoke["errors"], [])
        pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length === %d" % n)

    def test_dialog_lists_starters_and_adds_a_room(self):
        with self.open(STARTER_P + "main/rooms", "d") as pg:
            self.rooms_ready(pg, 3)
            pg.click("button.pr-add-starter[data-action=add-starter]")
            pg.wait_for("document.querySelectorAll('.app-dialog .pr-starter').length === 5")
            self.assertEqual(pg.js(STARTER_CARDS),
                             ["church-sanctuary", "church-youth-room", "church-chapel", "church-portable", "church-broadcast"])
            self.assertEqual(pg.js("document.querySelector('.app-dialog .pr-starter[aria-checked=true]').getAttribute('data-starter')"), "church-sanctuary")
            self.assertEqual(pg.js("document.querySelector('#pr-starter-name').value"), "Sanctuary / auditorium")
            # Cards carry label, counts, blurb and tag chips.
            card = pg.js("(function () { var c = document.querySelector('.pr-starter[data-starter=church-portable]');"
                         " return {label: c.querySelector('.pr-starter-label').textContent, counts: c.querySelector('.pr-starter-counts').textContent,"
                         " blurb: c.querySelector('.pr-starter-blurb').textContent.length,"
                         " tags: [].map.call(c.querySelectorAll('.pr-starter-tags .chip'), function (t) { return t.textContent; })}; })()")
            self.assertEqual(card["label"], "Portable church (road cases)")
            self.assertIn("devices", card["counts"])
            self.assertIn("racks", card["counts"])
            self.assertGreater(card["blurb"], 20)
            self.assertIn("inventory", card["tags"])
            pg.click(".app-dialog .pr-starter[data-starter=church-chapel]")
            self.assertEqual(pg.js("document.querySelector('#pr-starter-name').value"), "Chapel / traditional")
            # A name the user typed is kept when another card is picked.
            pg.js("(function () { var i = document.querySelector('#pr-starter-name'); i.value = 'Prayer Chapel'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
            pg.click(".app-dialog .pr-starter[data-starter=church-youth-room]")
            self.assertEqual(pg.js("document.querySelector('#pr-starter-name').value"), "Prayer Chapel")
            pg.click(".app-dialog .pr-starter[data-starter=church-chapel]")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("location.hash.indexOf('/rooms/prayer-chapel/overview') > 0", timeout=30)
            pg.wait_for("!document.querySelector('.app-dialog')")
            pg.wait_for("!!document.querySelector('header.eh[data-id=prayer-chapel]')")
            self.assertEqual(pg.js("document.querySelector('header.eh .eh-title').textContent").strip(), "Prayer Chapel")
            self.assertEqual(pg.js("document.querySelectorAll('.ex-root[data-explorer=rooms] .ex-item').length"), 4)
            self.assertEqual(pg.smoke["errors"], [])
        raw = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/starter-ui").read().decode())
        doc = raw.get("doc", raw)
        room = [r for r in doc["rooms"] if r["id"] == "prayer-chapel"][0]
        self.assertEqual(room["name"], "Prayer Chapel")
        self.assertTrue(all(d["id"].startswith("prayer-chapel-") for d in doc["devices"] if d.get("room") == "prayer-chapel"))
        hist = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/starter-ui/history").read().decode())
        last = hist["revisions"][0] if hist["revisions"][0]["revision"] >= hist["revisions"][-1]["revision"] else hist["revisions"][-1]
        self.assertEqual(last["source"], "starter")
        self.assertEqual(last["summary"], "Added room Prayer Chapel from starter Chapel / traditional")

    def test_dialog_at_m_stacks_cards_with_44px_targets(self):
        with self.open(STARTER_P + "main/rooms", "m") as pg:
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length >= 3")
            self.assertGreaterEqual(pg.rect("button.pr-add-starter")["height"], 44)
            pg.click("button.pr-add-starter")
            pg.wait_for("document.querySelectorAll('.app-dialog .pr-starter').length === 5")
            self.assertLessEqual(pg.page_hscroll(), 0)
            lefts = pg.js("[].map.call(document.querySelectorAll('.app-dialog .pr-starter'), function (c) { return Math.round(c.getBoundingClientRect().left); })")
            self.assertEqual(len(set(lefts)), 1, "cards stack in one column at m: %r" % lefts)
            for t in pg.js(TARGETS % json.dumps(".app-dialog .pr-starter, .app-dialog #pr-starter-name, .app-dialog footer button")):
                self.assertGreaterEqual(min(t["w"], t["h"]), 44, t)
            pg.shot("starter-dialog-m")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")

    def test_viewer_has_no_starter_button_and_error_is_inline(self):
        raw = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/starter-ui").read().decode())
        raw["role"] = "viewer"
        with self.open(STARTER_P + "main/rooms", "d", intercepts=[("/api/v2/projects/starter-ui", 200, raw, "GET")]) as pg:
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length >= 3")
            self.assertFalse(pg.js("!!document.querySelector('button.pr-add-starter')"))
        with self.open(STARTER_P + "main/rooms", "d",
                       intercepts=[("/api/v2/projects/starter-ui/rooms/from-starter", 423, {"error": "locked", "message": "Project is locked"}, "POST")]) as pg:
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length >= 3")
            pg.click("button.pr-add-starter")
            pg.wait_for("document.querySelectorAll('.app-dialog .pr-starter').length === 5")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("!document.querySelector('.app-dialog .pr-starter-error').hidden")
            self.assertIn("locked", pg.js("document.querySelector('.app-dialog .pr-starter-error').textContent"))
            self.assertTrue(pg.js("!!document.querySelector('.app-dialog')"))
            self.assertFalse(pg.js("document.querySelector('.app-dialog footer button.primary').disabled"))


# ---------------------------------------------------------------- save room as starter (phase6 P6A, FR-ROOM-11)

SAVE_P = "#/save-ui/"
GROUP_TITLES = "[].map.call(document.querySelectorAll('.app-dialog .pr-starter-group-title'), function (t) { return t.textContent; })"
USER_CARDS = "[].map.call(document.querySelectorAll('.app-dialog .pr-starter-group[data-group=user] .pr-starter'), function (c) { return c.getAttribute('data-starter'); })"
CHECKED_TAGS = "[].map.call(document.querySelectorAll('.app-dialog input.pr-ss-tag:checked'), function (i) { return i.value; })"


class RoomSaveStarterUi(UiCase):
    """Rooms ▸ **Save as starter…** (FR-ROOM-11): the dialog (label prefilled, blurb, tag chips from the room's
    disciplines, the "not saved" note), the real ``save-starter`` POST, the **Your starters** group with the admin
    trash button in the Add-room dialog, a 409 ``exists`` turning the primary button into *Replace starter*, and
    the 390 px layout. Runs on its own ``save-ui`` copy of campus-demo; ``setUpClass`` saves one starter through
    the API so both sizes see a user group whatever the test order."""

    @classmethod
    def setUpClass(cls) -> None:
        super(RoomSaveStarterUi, cls).setUpClass()
        cls.api("POST", "/api/v2/projects", {"name": "save-ui", "template": "campus-demo"})
        cls.api("POST", "/api/v2/projects/save-ui/rooms/chapel/save-starter", {"label": "Chapel seed", "blurb": "Seeded by the test", "tags": ["audio"]})

    @classmethod
    def api(cls, method: str, path: str, body=None):
        req = urllib.request.Request(cls.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def open_menu_action(self, pg, action: str) -> None:
        pg.click("header.eh .eh-more")
        pg.wait_for("!!document.querySelector('header.eh .eh-menu:not([hidden])')")
        pg.click("header.eh .eh-menu-item[data-action=%s]" % action)

    def test_landing_button_saves_and_dialog_groups_user_starters(self):
        with self.open(SAVE_P + "main/rooms", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length === 3")
            self.assertEqual(pg.js("document.querySelectorAll('.dt-root[data-table=rooms] button.pr-save-starter').length"), 3,
                             "every room row carries Save as starter… for an editor")
            pg.click(".dt-root[data-table=rooms] tr[data-id=main] button.pr-save-starter")
            pg.wait_for("!!document.querySelector('.app-dialog #pr-ss-label')")
            self.assertEqual(pg.js("location.hash"), SAVE_P + "main/rooms", "the row button does not navigate")
            self.assertEqual(pg.js("document.querySelector('.app-dialog h2').textContent"), "Save as starter")
            self.assertEqual(pg.js("document.querySelector('#pr-ss-label').value"), "Main Auditorium")
            self.assertEqual(pg.js(CHECKED_TAGS), ["audio", "video", "lighting", "network"], "tags come from the room's disciplines")
            self.assertEqual(pg.js("[].map.call(document.querySelectorAll('.app-dialog label.pr-ss-chip'), function (c) { return c.textContent; })"),
                             ["audio", "video", "lighting", "network", "inventory"])
            self.assertEqual(pg.js("document.querySelector('.app-dialog .pr-ss-note').textContent"),
                             "Serials, asset tags, prices, short codes and attached files are not saved.")
            pg.click(".app-dialog label.pr-ss-chip[data-tag=network]")
            pg.click(".app-dialog label.pr-ss-chip[data-tag=inventory]")
            self.assertEqual(pg.js(CHECKED_TAGS), ["audio", "video", "lighting", "inventory"])
            pg.js("(function () { var t = document.querySelector('#pr-ss-blurb'); t.value = 'FOH, two racks, PTZ cameras.'; t.dispatchEvent(new Event('input', {bubbles: true})); })()")
            pg.shot("save-starter-dialog-d")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("!document.querySelector('.app-dialog')", timeout=30)
            toast = pg.wait_for("(function () { var t = document.querySelector('.app-toast.ok'); return t ? t.textContent : ''; })()")
            self.assertTrue(toast.startswith("Saved starter Main Auditorium"), toast)
            self.assertIn("cables to other rooms", toast, "cross-room cables are reported as left out")
            self.assertEqual(pg.smoke["errors"], [])
            # The Add-room dialog now lists it under "Your starters" with a trash button (admin: login is off).
            pg.click("button.pr-add-starter[data-action=add-starter]")
            pg.wait_for("document.querySelectorAll('.app-dialog .pr-starter-group[data-group=user] .pr-starter').length >= 2")
            self.assertEqual(pg.js(GROUP_TITLES), ["Bundled starters", "Your starters"])
            self.assertEqual(pg.js("document.querySelectorAll('.app-dialog .pr-starter-group[data-group=bundled] .pr-starter').length"), 5)
            self.assertEqual(pg.js(USER_CARDS), ["user-chapel-seed", "user-main-auditorium"])
            card = pg.js("(function () { var c = document.querySelector('.pr-starter[data-starter=user-main-auditorium]');"
                         " return {label: c.querySelector('.pr-starter-label').textContent, counts: c.querySelector('.pr-starter-counts').textContent,"
                         " blurb: c.querySelector('.pr-starter-blurb').textContent, tags: [].map.call(c.querySelectorAll('.chip'), function (t) { return t.textContent; })}; })()")
            self.assertEqual(card["label"], "Main Auditorium")
            self.assertEqual(card["blurb"], "FOH, two racks, PTZ cameras.")
            self.assertEqual(card["tags"], ["audio", "video", "lighting", "inventory"])
            self.assertIn("49 devices", card["counts"])
            self.assertTrue(pg.js("!!document.querySelector('.app-dialog .pr-starter-del[data-del=user-main-auditorium]')"), "admin trash button")
            self.assertFalse(pg.js("!!document.querySelector('.app-dialog .pr-starter-group[data-group=bundled] .pr-starter-del')"), "bundled cards have no trash")
            pg.shot("starters-dialog-your-starters-d")
            # Picking the user starter prefills the room name with its label.
            pg.click(".app-dialog .pr-starter[data-starter=user-main-auditorium]")
            self.assertEqual(pg.js("document.querySelector('#pr-starter-name').value"), "Main Auditorium")
            # Trash → confirm → DELETE: the card goes, the selection moves to the first starter.
            pg.click(".app-dialog .pr-starter-del[data-del=user-main-auditorium]")
            pg.wait_for("document.querySelectorAll('.app-dialog').length === 2")
            self.assertIn("Main Auditorium", pg.js("document.querySelectorAll('.app-dialog')[1].textContent"))
            pg.js("document.querySelectorAll('.app-dialog')[1].querySelector('footer button.danger').click()")
            pg.wait_for("document.querySelectorAll('.app-dialog').length === 1 && !document.querySelector('.pr-starter[data-starter=user-main-auditorium]')")
            self.assertEqual(pg.js(USER_CARDS), ["user-chapel-seed"])
            self.assertEqual(pg.js("document.querySelector('.app-dialog .pr-starter[aria-checked=true]').getAttribute('data-starter')"), "church-sanctuary")
            self.assertEqual(pg.smoke["errors"], [])
        st, out = self.api("GET", "/api/v2/starters")
        self.assertEqual([s["id"] for s in out["starters"] if s["source"] == "user"], ["user-chapel-seed"])

    def test_room_menu_at_m_replace_flow_and_targets(self):
        exists = {"error": "a starter 'user-chapel' already exists", "code": "exists"}
        with self.open(SAVE_P + "chapel/rooms/chapel/overview", "m",
                       intercepts=[("/api/v2/projects/save-ui/rooms/chapel/save-starter", 409, exists, "POST")]) as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("!!document.querySelector('header.eh[data-id=chapel] .eh-more')")
            self.open_menu_action(pg, "save-starter")
            pg.wait_for("!!document.querySelector('.app-dialog #pr-ss-label')")
            self.assertEqual(pg.js("document.querySelector('#pr-ss-label').value"), "Chapel")
            self.assertEqual(pg.js(CHECKED_TAGS), ["audio", "video", "network"])
            self.assertLessEqual(pg.page_hscroll(), 0)
            for t in pg.js(TARGETS % json.dumps(".app-dialog #pr-ss-label, .app-dialog label.pr-ss-chip, .app-dialog footer button")):
                self.assertGreaterEqual(t["h"], 44, t)
            pg.shot("save-starter-dialog-m")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("!document.querySelector('.app-dialog .pr-starter-error').hidden")
            self.assertIn("Replace it", pg.js("document.querySelector('.app-dialog .pr-starter-error').textContent"))
            self.assertEqual(pg.js("document.querySelector('.app-dialog footer button.primary').textContent"), "Replace starter")
            self.assertTrue(pg.js("!!document.querySelector('.app-dialog')"), "the dialog stays open")
            # Editing the label drops the replace offer.
            pg.js("(function () { var i = document.querySelector('#pr-ss-label'); i.value = 'Chapel two'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
            self.assertEqual(pg.js("document.querySelector('.app-dialog footer button.primary').textContent"), "Save starter")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            # The Add-room dialog at m: both groups stack in one column, the user card and its trash are ≥ 44 px.
            pg.goto(SAVE_P + "chapel/rooms")
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length >= 3")
            self.assertTrue(pg.js("(function () { var b = document.querySelector('.dt-root[data-table=rooms] button.pr-save-starter');"
                                  " return !b || b.getBoundingClientRect().width === 0; })()"), "the row button is hidden at m (the room page menu has the action)")
            pg.click("button.pr-add-starter")
            pg.wait_for("document.querySelectorAll('.app-dialog .pr-starter-group[data-group=user] .pr-starter').length >= 1")
            self.assertEqual(pg.js(GROUP_TITLES), ["Bundled starters", "Your starters"])
            self.assertLessEqual(pg.page_hscroll(), 0)
            lefts = pg.js("[].map.call(document.querySelectorAll('.app-dialog .pr-starter'), function (c) { return Math.round(c.getBoundingClientRect().left); })")
            self.assertEqual(len(set(lefts)), 1, "cards stack in one column at m: %r" % lefts)
            for t in pg.js(TARGETS % json.dumps(".app-dialog .pr-starter-group[data-group=user] .pr-starter, .app-dialog .pr-starter-del")):
                self.assertGreaterEqual(min(t["w"], t["h"]), 44, t)
            pg.shot("starters-dialog-your-starters-m")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self.assertEqual(pg.smoke["errors"], [])

    def test_viewer_has_no_save_action(self):
        st, raw = self.api("GET", "/api/v2/projects/save-ui")
        raw["role"] = "viewer"
        with self.open(SAVE_P + "main/rooms/main/overview", "d", intercepts=[("/api/v2/projects/save-ui", 200, raw, "GET")]) as pg:
            pg.wait_for("!!document.querySelector('header.eh[data-id=main]')")
            self.assertFalse(pg.js("!!document.querySelector('header.eh [data-action=save-starter]')"))
            pg.goto(SAVE_P + "main/rooms")
            pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length >= 3")
            self.assertFalse(pg.js("!!document.querySelector('.dt-root[data-table=rooms] button.pr-save-starter')"))


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
