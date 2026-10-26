"""RK (docs/ui-audit.md B.3 RK): the racks landing and the rack page in the app shell.

Landing: every ``#rk-*`` id stays, ``#rk-unracked`` is an explorer list, the elevation fits the
container (no inner or page horizontal scroll at 390px). Rack page ``racks/<id>/<tab>[/front|rear]``:
reload lands on the rear face, a devices row opens the drawer and keeps the hash, the header sticks
after scrolling, the explorer width survives a reload, unknown tabs are replaced, unknown racks show
an error. Skips without Chrome (set ``FATHOM_CHROME``); ``$FATHOM_UI_SHOTS`` collects screenshots.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

LANDING = "#/campus-demo/main/racks"
PAGE = "#/campus-demo/main/racks/rk-foh"
LANDING_IDS = ("rk-select", "rk-add", "rk-edit", "rk-face", "rk-print", "rk-unracked")

VIEWPORT_OVERFLOW = """(function () {
  var v = document.querySelector('.rk-viewport');
  return v ? v.scrollWidth - v.clientWidth : -1;
})()"""

HEADER = """(function () {
  var eh = document.querySelector('header.eh'), sc = document.querySelector('.ex-content');
  if (!eh || !sc) return null;
  var r = eh.getBoundingClientRect(), s = sc.getBoundingClientRect();
  var hit = document.elementFromPoint(r.left + 40, r.top + Math.min(16, r.height / 2));
  return {top: r.top, scTop: s.top, scrollTop: sc.scrollTop, stuck: eh.classList.contains('eh--stuck'),
          onTop: !!hit && eh.contains(hit)};
})()"""


class RacksUi(UiCase):
    def ready(self, pg, what: str) -> None:
        self.assertEqual(pg.smoke["errors"], [], "errors on %s" % what)

    def page_ready(self, pg, tab: str) -> None:
        pg.wait_for("!!document.querySelector('header.eh .eh-tab[aria-selected=true][data-tab=%s]')" % tab)
        pg.wait_for("!!document.querySelector('.rp-panel[data-tab=%s]')" % tab)

    # ------------------------------------------------------------ landing

    def test_landing_at_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.open(LANDING, size) as pg:
                self.ready(pg, "racks landing at " + size)
                pg.wait_for("document.querySelectorAll('.rk-rack').length === 2")
                missing = pg.js("%r.filter(function (i) { return !document.getElementById(i); })" % list(LANDING_IDS))
                self.assertEqual(missing, [], "B.3 RK: the landing keeps every #rk-* id")
                self.assertTrue(pg.js("document.getElementById('rk-unracked').classList.contains('ex-list')"),
                                "B.3 RK: #rk-unracked is the explorer list")
                self.assertEqual(pg.js("document.querySelector('[data-explorer]').getAttribute('data-explorer')"), "racks-unracked")
                self.assertGreater(pg.js("document.querySelectorAll('#rk-unracked .rk-devitem .rk-addbtn').length"), 0)
                self.assertTrue(pg.js("!!document.querySelector('#rk-unracked .rk-grip[data-device]')"), "editors get drag grips")
                self.assertTrue(pg.js("!!document.querySelector('.rk-viewport[role=application]')"))
                self.assertLessEqual(pg.js(VIEWPORT_OVERFLOW), 1, "B.3 RK: the elevation fits the container at " + size)
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll at " + size)
                self.assertEqual(pg.offscreen(".rk-slots", "x"), 0, "rack drawings are fully visible horizontally at " + size)
                link = pg.js("(document.querySelector('.rk-rack[data-rack=rk-foh] a.rk-pagelink') || {}).hash || ''")
                self.assertTrue(link.endswith("/racks/rk-foh"), link)
                if size == "m":
                    self.assertFalse(pg.js("document.querySelector('.ex-root').classList.contains('ex-is-open')"))
                    pg.click(".ex-open")
                    pg.wait_for("document.querySelector('.ex-root').classList.contains('ex-is-open')")
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.ex-root').classList.contains('ex-is-open')")
                pg.shot("racks-" + size)

    def test_landing_face_and_rack_select_still_work(self):
        with self.open(LANDING, "d") as pg:
            self.ready(pg, "racks landing")
            pg.click("#rk-face")
            pg.wait_for("document.querySelectorAll('.rk-slots[data-face=rear]').length === 2")
            pg.js("var s = document.getElementById('rk-select'); s.value = 'rk-foh'; s.dispatchEvent(new Event('change'))")
            pg.wait_for("document.querySelectorAll('.rk-rack').length === 1")
            self.assertEqual(pg.hash, LANDING)

    def test_rack_link_opens_the_page(self):
        with self.open(LANDING, "d") as pg:
            self.ready(pg, "racks landing")
            pg.click(".rk-rack[data-rack=rk-foh] a.rk-pagelink")
            pg.wait_for("location.hash.indexOf('/racks/rk-foh/overview') > 0")
            self.page_ready(pg, "overview")
            self.assertEqual(pg.js("document.title.indexOf('FOH rack') >= 0"), True)

    # ------------------------------------------------------------ rack page

    def test_rear_face_survives_reload(self):
        with self.open(PAGE + "/elevation/rear", "d") as pg:
            self.ready(pg, "rack elevation rear")
            self.page_ready(pg, "elevation")
            for _ in range(2):
                pg.wait_for("!!document.querySelector('.rp-elev .rk-slots[data-face=rear][data-rack=rk-foh]')")
                self.assertEqual(pg.js("document.querySelectorAll('.rp-elev .rk-slots').length"), 1)
                self.assertTrue(pg.js("!!document.querySelector('.rp-face[data-face=rear][aria-current]')"))
                self.assertTrue(pg.js("!!document.querySelector('.rp-elev .rk-block[data-device=sw-foh]')"), "rear-mounted switch on the rear face")
                pg.reload()
                self.ready(pg, "reload")
                self.page_ready(pg, "elevation")
            self.assertTrue(pg.hash.endswith("/racks/rk-foh/elevation/rear"), pg.hash)
            pg.click(".rp-face[data-face=front]")
            pg.wait_for("/\\/racks\\/rk-foh\\/elevation$/.test(location.hash)")
            pg.wait_for("!!document.querySelector('.rp-elev .rk-slots[data-face=front]')")
            self.assertTrue(pg.js("!!document.querySelector('.rp-face[data-face=front][aria-current]')"))

    def test_devices_row_opens_drawer_and_keeps_hash(self):
        with self.open(PAGE + "/devices", "d") as pg:
            self.ready(pg, "rack devices")
            self.page_ready(pg, "devices")
            ids = pg.js("Array.prototype.map.call(document.querySelectorAll('tr.dt-row'), function (r) { return r.getAttribute('data-id'); })")
            self.assertEqual(ids, ["sw-foh", "ulxd-main", "switcher", "ctrl-main", "pdu-foh"], "rows run top of the rack first")
            pg.click("tr.dt-row[data-id=switcher]")
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
            h = pg.hash
            self.assertTrue(h.startswith(PAGE + "/devices"), h)
            self.assertIn("sel=device", h)
            self.assertIn("switcher", h)
            self.assertTrue(pg.js("!!document.querySelector('.rp-panel[data-tab=devices] tr.dt-row')"), "the page stays on the devices tab")

    def test_cables_row_opens_drawer(self):
        with self.open(PAGE + "/cables", "d") as pg:
            self.ready(pg, "rack cables")
            self.page_ready(pg, "cables")
            self.assertEqual(pg.js("document.querySelectorAll('tr.dt-row').length"), 31)
            self.assertEqual(pg.js("document.querySelector('.eh-tab[data-tab=cables] .eh-count').textContent"), "31")
            pg.click("tr.dt-row")
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
            self.assertTrue(pg.hash.startswith(PAGE + "/cables"), pg.hash)
            self.assertIn("sel=cable", pg.hash)

    def test_header_sticky_after_scroll(self):
        with self.open(PAGE + "/cables", "d") as pg:
            self.ready(pg, "rack cables")
            self.page_ready(pg, "cables")
            st = pg.js(HEADER)
            self.assertFalse(st["stuck"])
            pg.js("document.querySelector('.ex-content').scrollTop = 900")
            pg.wait_for("document.querySelector('header.eh').classList.contains('eh--stuck')")
            st = pg.js(HEADER)
            self.assertGreater(st["scrollTop"], 150)
            self.assertAlmostEqual(st["top"], st["scTop"], delta=1, msg="D5: the header sticks to the top of the page scroller")
            self.assertTrue(st["onTop"], "the stuck header paints above the table")

    def test_explorer_width_persists(self):
        with self.open(PAGE + "/overview", "d") as pg:
            self.ready(pg, "rack overview")
            self.page_ready(pg, "overview")
            before = pg.js("document.querySelector('.ex-side').getBoundingClientRect().width")
            pg.js("document.querySelector('.ex-resizer').focus()")
            pg.press("ArrowRight")
            pg.press("ArrowRight")
            pg.wait_for("document.querySelector('.ex-side').getBoundingClientRect().width >= %f" % (before + 30))
            self.assertIn('"w"', pg.js("localStorage.getItem('fathom.ui.explorer.racks') || ''"))
            pg.reload()
            self.ready(pg, "reload")
            self.page_ready(pg, "overview")
            after = pg.js("document.querySelector('.ex-side').getBoundingClientRect().width")
            self.assertAlmostEqual(after, before + 32, delta=1)

    def test_tabs_overview_cards_and_explorer(self):
        with self.open(PAGE, "d") as pg:
            self.ready(pg, "rack page")
            pg.wait_for("location.hash === %r" % (PAGE + "/overview"))
            self.page_ready(pg, "overview")
            self.assertEqual(pg.js("document.querySelector('header.eh').getAttribute('data-id')"), "rk-foh")
            self.assertEqual(pg.js("document.querySelector('.eh-title').textContent"), "FOH rack")
            self.assertEqual(pg.js("document.querySelector('.eh-fact[data-fact=height] dd').textContent"), "12 U")
            self.assertEqual(pg.js("document.querySelector('.rp-card[data-card=devices] .rp-card-n').textContent"), "5")
            self.assertEqual(pg.js("JSON.parse(localStorage.getItem('fathom.ui.recent.campus-demo') || '{}').rack[0].id"), "rk-foh")
            pg.click(".rp-card[data-card=cables]")
            pg.wait_for("document.querySelectorAll('.dt-dialog tr.dt-row').length === 25")
            self.assertIn("31", pg.js("document.querySelector('.dt-dialog').textContent"))
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.dt-dialog')")
            pg.click(".eh-tab[data-tab=devices]")
            pg.wait_for("location.hash === %r" % (PAGE + "/devices"))
            self.page_ready(pg, "devices")
            self.assertTrue(pg.js("document.querySelector('#rp-racks .ex-item[data-id=rk-amp] a').hash.indexOf('/racks/rk-amp/devices') > 0"),
                            "explorer links keep the current tab")
            pg.click("#rp-racks .ex-item[data-id=rk-amp]")
            pg.wait_for("location.hash.indexOf('/racks/rk-amp/devices') > 0")
            pg.wait_for("document.querySelector('.eh-title').textContent === 'Amp room rack'")
            self.assertEqual(pg.js("document.querySelector('#rp-racks .ex-item[aria-selected=true]').getAttribute('data-id')"), "rk-amp")

    def test_unknown_tab_and_rack(self):
        with self.open(PAGE + "/bogus", "d") as pg:
            self.ready(pg, "unknown tab")
            pg.wait_for("location.hash === %r" % (PAGE + "/overview"))
            self.page_ready(pg, "overview")
            pg.goto(PAGE + "/devices/rear")
            pg.wait_for("location.hash === %r" % (PAGE + "/devices"))
        with self.open("#/campus-demo/main/racks/nope", "d") as pg:
            self.ready(pg, "unknown rack")
            pg.wait_for("!!document.querySelector('.rp-missing')")
            self.assertIn("nope", pg.js("document.querySelector('.rp-missing').textContent"))
            self.assertTrue(pg.hash.endswith("/racks/nope"), "an unknown rack keeps its URL")
            self.assertEqual(pg.js("document.querySelectorAll('#rp-racks .ex-item').length"), 3)

    def test_no_horizontal_scroll_at_t_and_m(self):
        for size in ("t", "m"):
            for tab in ("overview", "elevation", "devices", "cables"):
                with self.open(PAGE + "/" + tab, size) as pg:
                    self.ready(pg, "rack %s at %s" % (tab, size))
                    self.page_ready(pg, tab)
                    self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll on %s at %s" % (tab, size))
                    if tab == "elevation":
                        self.assertLessEqual(pg.js(VIEWPORT_OVERFLOW), 1)
                        self.assertEqual(pg.offscreen(".rp-elev .rk-slots", "x"), 0)
                    if size == "m":
                        self.assertTrue(pg.js("document.querySelector('header.eh').classList.contains('eh--compact')"))
                        self.assertTrue(pg.js("!!document.querySelector('.ex-open').offsetWidth"))
                    if tab == "overview":
                        pg.shot("rack-page-" + size)
        with self.open(PAGE + "/overview", "d") as pg:
            self.ready(pg, "rack overview at d")
            self.page_ready(pg, "overview")
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("rack-page-d")

    def test_editor_and_viewer_actions(self):
        with self.open(PAGE + "/elevation", "d") as pg:
            self.ready(pg, "rack elevation")
            self.page_ready(pg, "elevation")
            self.assertEqual(pg.js("document.querySelector('.eh-action[data-action=edit]').textContent"), "Edit")
            self.assertTrue(pg.js("!!document.querySelector('.rp-add')"))
            pg.click(".eh-more")
            pg.wait_for("!!document.querySelector('.eh-menu:not([hidden]) [data-action=delete]')")
            pg.press("Escape")
        body = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/campus-demo").read().decode("utf-8"))
        body["role"] = "viewer"
        viewer = [("/api/v2/projects/campus-demo", 200, body, "GET")]
        with self.open(PAGE + "/elevation", "d", intercepts=viewer) as pg:
            self.ready(pg, "rack elevation as viewer")
            self.page_ready(pg, "elevation")
            self.assertEqual(pg.js("document.querySelector('.eh-action[data-action=edit]').textContent"), "Details")
            self.assertFalse(pg.js("!!document.querySelector('.eh-more')"), "viewers get no delete")
            self.assertFalse(pg.js("!!document.querySelector('.rp-add')"))
            pg.click(".eh-action[data-action=edit]")
            pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
            self.assertIn("sel=rack", pg.hash)
        with self.open(LANDING, "d", intercepts=viewer) as pg:
            self.ready(pg, "racks landing as viewer")
            self.assertTrue(pg.js("document.getElementById('rk-add').disabled"))
            self.assertFalse(pg.js("!!document.querySelector('#rk-unracked .rk-grip')"))
            self.assertTrue(pg.js("document.querySelector('#rk-unracked .rk-addbtn').disabled"))
