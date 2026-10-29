"""QA: end-to-end acceptance suite for the UI uplift (docs/ui-audit.md B.8 verification matrix).

One test per owner acceptance criterion, run against the real app on a ``tests/_ui.py`` server
(``campus-demo`` sample, login off) at ``d`` 1280x900, ``t`` 820x1180 touch and ``m`` 390x844 touch
wherever the criterion depends on layout. ``AcceptanceViewer`` runs a login-on server with a viewer user.
Skips without Chrome; set ``FATHOM_CHROME=/usr/bin/google-chrome-stable``. With ``FATHOM_UI_SHOTS`` set it
writes ``qa-<test>-<size>`` screenshots.

Single suite: ``python -m unittest discover -s tests -p test_ui_acceptance.py -v``.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import unittest
import urllib.error
import urllib.request

try:
    from _ui import UiCase, ROOT
    from test_frontend_smoke import VIEWS
except ImportError:  # pragma: no cover
    from tests._ui import UiCase, ROOT
    from tests.test_frontend_smoke import VIEWS

PROJECT = "campus-demo"
CAMPUS = "#/campus-demo/main/"
SIZES = ("d", "t", "m")

SCHEDULE_KINDS = ["cables", "ip", "dmx", "bom", "patch", "racks"]  # labels is a sheet (D9)
SETTINGS_TABS = ["project", "rooms", "systems", "locations", "networks", "templates", "users", "invites", "backups", "sharing", "suggestions", "offline", "trash"]
DISCOVERY_TABS = ["new", "matches", "connections", "networks", "unresolved", "changes", "runs"]
DEVICE_TABS = ["overview", "ports", "cables", "network", "inventory", "procedures", "files"]
ROOM_TABS = ["overview", "devices", "cables", "racks", "plans", "procedures"]
RACK_TABS = ["overview", "elevation", "devices", "cables"]

# D9: tables that need not be DataTables.
EXEMPT = [".pt-block table", ".sch-labels table", ".md-table", ".app-dialog table", "#app-palette-list",
          ".ex-list", "#rk-unracked", "#fp-unplaced", "#app-inspector .ins-ports table", "#app-inspector .ins-channels table"]

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); if (!el) return false; var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

VISIBLE = """(function (sel) {
  return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }).length;
})(%s)"""

STRAY_TABLES = """(function (exempt) {
  return Array.prototype.filter.call(document.querySelectorAll('#app table:not(.dt-table)'), function (t) {
    return !exempt.some(function (s) { return t.matches(s) || !!t.closest(s); });
  }).map(function (t) {
    var chain = [];
    for (var p = t; p && p.id !== 'app-main' && p.id !== 'app-inspector' && p !== document.body; p = p.parentElement) {
      chain.push(p.tagName.toLowerCase() + (p.id ? '#' + p.id : '') + (typeof p.className === 'string' && p.className.trim() ? '.' + p.className.trim().split(/\\s+/).join('.') : ''));
    }
    return chain.slice(0, 4).join(' < ');
  });
})(%s)"""

# A visible cell of the row that holds no control, tagged so ``click`` can hit it.
MARK_CELL = """(function (rowSel) {
  var rows = document.querySelectorAll(rowSel);
  for (var i = 0; i < rows.length; i++) {
    var cells = rows[i].querySelectorAll('td');
    for (var j = 0; j < cells.length; j++) {
      var td = cells[j], r = td.getBoundingClientRect();
      if (r.width < 8 || r.height < 8 || td.querySelector('a, button, input, select, textarea, label')) continue;
      var old = document.querySelector('[data-qa-hit]'); if (old) old.removeAttribute('data-qa-hit');
      td.setAttribute('data-qa-hit', '1');
      return rows[i].getAttribute('data-id') || rows[i].getAttribute('data-device') || String(i);
    }
  }
  return null;
})(%s)"""


def q(s: str) -> str:
    return json.dumps(s)


def visible(pg, selector: str) -> int:
    return int(pg.js(VISIBLE % q(selector)))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading, .fb-skeleton, [aria-busy=true]');
    })(%s)""" % q(view), timeout)


def route_view(route: str) -> str:
    return route.split("?")[0].split("/")[0]


def path_of(pg) -> str:
    return pg.js("location.hash.split('?')[0]")


def errors(pg):
    return pg.js("window.__fathomErrors || []")


def click_row(pg, row_selector: str) -> str:
    """Click a plain cell of the first matching row; returns the row's id."""
    rid = pg.wait_for(MARK_CELL % q(row_selector))
    pg.click("[data-qa-hit]")
    return rid


def sw_version() -> str:
    m = re.search(r"const VERSION = '([^']+)'", (ROOT / "fathom" / "static" / "sw.js").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


class Acceptance(UiCase):
    """B.8 rows with login off (everyone is admin)."""

    # ----------------------------------------------- owner criteria smoke

    def test_owner_criteria_smoke(self):
        """Every view in VIEWS loads at d, t and m without JS errors or horizontal page scroll."""
        results = {}

        def walk(size):
            out = []
            try:
                with self.open(CAMPUS + "home", size) as pg:
                    out.append(("boot", "smoke errors", pg.smoke["errors"]))
                    for i, v in enumerate(VIEWS):
                        if i or v != "home":
                            pg.goto(CAMPUS + v)
                        try:
                            view_ready(pg, v)
                        except AssertionError as e:
                            out.append((v, "not ready", str(e)))
                            continue
                        out.append((v, "hscroll", pg.page_hscroll()))
                    out.append(("all", "errors", errors(pg)))
            except Exception as e:  # pragma: no cover - reported below
                out.append(("walk", "exception", repr(e)))
            results[size] = out

        threads = [threading.Thread(target=walk, args=(s,)) for s in SIZES]
        for t in threads:
            t.start()
        for t in threads:
            t.join(180)
        for size in SIZES:
            self.assertIn(size, results, "walk at %s did not finish" % size)
            for view, what, value in results[size]:
                with self.subTest(size=size, view=view, check=what):
                    if what == "hscroll":
                        self.assertLessEqual(value, 0, "%s at %s scrolls horizontally by %spx" % (view, size, value))
                    elif what in ("errors", "smoke errors"):
                        self.assertEqual(value, [], "%s at %s" % (what, size))
                    else:
                        self.fail("%s at %s: %s %s" % (view, size, what, value))

    # ---------------------------------------------------------- DataTable

    def test_every_list_is_a_datatable(self):
        """At d, no view, tab or drawer shows a <table> outside .dt-table except the D9 exemptions."""
        routes = [v for v in VIEWS] + ["table?mode=rows"]
        routes += ["schedules/" + k for k in SCHEDULE_KINDS]
        routes += ["settings/" + t for t in SETTINGS_TABS]
        routes += ["discovery/" + t for t in DISCOVERY_TABS]
        routes += ["devices/foh-cl5/" + t for t in DEVICE_TABS]
        routes += ["rooms/main/" + t for t in ROOM_TABS]
        routes += ["racks/rk-foh/" + t for t in RACK_TABS]
        routes += ["sop?page=power-up"]
        drawers = ["patch?sel=device:foh-cl5", "schedules/cables?sel=cable:c-0001", "patch?sel=port:rio-sl:analog-in-9",
                   "racks?sel=rack:rk-foh", "inventory?sel=device:foh-cl5&sec=inventory"]
        stray = {}
        with self.open(CAMPUS + "home", "d") as pg:
            for r in routes + drawers:
                pg.goto(CAMPUS + r)
                view_ready(pg, route_view(r))
                if "sel=" in r:
                    pg.wait_for(DRAWER_OPEN)
                    pg.wait_for("!!document.querySelector('#app-inspector .ins-head')")
                # some tabs render their table a task after mount
                pg.wait_for("!document.querySelector('#app-main .fb-skeleton')")
                pg.js("new Promise(function (r) { setTimeout(r, 150); })")
                found = pg.js(STRAY_TABLES % json.dumps(EXEMPT))
                if found:
                    stray[r] = sorted(set(found))
                if r == "schedules/cables":
                    pg.shot("qa-datatable-d")
            self.assertEqual(errors(pg), [])
        self.assertEqual(stray, {}, "tables outside the shared DataTable (D9)")

    # ------------------------------------------------------- entity pages

    def test_entity_tabs_survive_reload(self):
        """Device, room and rack pages: URL tab selected, kept after reload, sticky header, tab clicks push the URL."""
        cases = [
            ("#/campus-demo/main/devices/foh-cl5/ports", "ports", "cables"),
            ("#/campus-demo/chapel/rooms/chapel/cables", "cables", "devices"),
            ("#/campus-demo/main/racks/rk-foh/elevation/rear", "elevation", "devices"),
        ]
        for size in SIZES:
            with self.open(cases[0][0], size) as pg:
                for url, tab, other in cases:
                    with self.subTest(size=size, url=url):
                        pg.goto(url)
                        view_ready(pg, url.split("/")[3])
                        sel = "#app-main header.eh .eh-tab[aria-selected=true]"
                        pg.wait_for("!!document.querySelector(%s)" % q(sel))
                        self.assertEqual(pg.js("document.querySelector(%s).getAttribute('data-tab')" % q(sel)), tab)
                        self.assertEqual(pg.js("getComputedStyle(document.querySelector('#app-main header.eh')).position"), "sticky")
                        self.assertTrue(self.header_stays(pg), "header scrolls away on %s at %s" % (url, size))
                        if "rear" in url:
                            self.assertEqual(pg.js("(document.querySelector('.rp-face[aria-current=true]') || {}).getAttribute ? document.querySelector('.rp-face[aria-current=true]').getAttribute('data-face') : null"), "rear")
                        pg.reload()
                        view_ready(pg, url.split("/")[3])
                        self.assertEqual(pg.js("location.hash"), url, "reload keeps the URL")
                        pg.wait_for("!!document.querySelector(%s)" % q(sel))
                        self.assertEqual(pg.js("document.querySelector(%s).getAttribute('data-tab')" % q(sel)), tab, "tab after reload")
                        if "rear" in url:
                            self.assertEqual(pg.js("document.querySelector('.rp-face[aria-current=true]').getAttribute('data-face')"), "rear")
                        n = pg.js("history.length")
                        pg.click("#app-main header.eh .eh-tab[data-tab=%s]" % other)
                        pg.wait_for("location.hash.split('?')[0].split('/').indexOf(%s) === 5" % q(other))
                        pg.wait_for("(document.querySelector(%s) || {}).textContent !== undefined && document.querySelector(%s).getAttribute('data-tab') === %s"
                                    % (q(sel), q(sel), q(other)))
                        self.assertGreater(pg.js("history.length"), n, "a tab change pushes history")
                pg.shot("qa-entity-" + size)
                self.assertEqual(errors(pg), [])

    @staticmethod
    def header_stays(pg) -> bool:
        return pg.js("""(function () {
          var hd = document.querySelector('#app-main header.eh'), sc = hd.parentElement;
          while (sc && !(sc.scrollHeight > sc.clientHeight + 40 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
          var win = !sc;
          var before = hd.getBoundingClientRect().top;
          if (win) window.scrollTo(0, 400); else sc.scrollTop = 400;
          var moved = win ? window.scrollY : sc.scrollTop;
          var after = hd.getBoundingClientRect().top;
          if (win) window.scrollTo(0, 0); else sc.scrollTop = 0;
          return moved === 0 || (Math.abs(after - before) <= 2 || after >= (win ? 0 : sc.getBoundingClientRect().top) - 1);
        })()""")

    # ---------------------------------------------------------------- drawer

    def test_row_click_opens_drawer_in_place(self):
        """Port, cable and inventory rows open the drawer without navigating; sel is in the URL and survives reload."""
        cases = [
            (CAMPUS + "devices/foh-cl5/ports", ".pd-body tr.dt-row[data-id]", "port:foh-cl5:"),
            (CAMPUS + "schedules/cables", "#sch-dt tbody tr.dt-row", "cable:"),
            (CAMPUS + "inventory", "#inv-table tbody tr[data-device]", "device:"),
        ]
        for size in SIZES:
            with self.open(CAMPUS + "home", size) as pg:
                for url, row, sel in cases:
                    with self.subTest(size=size, url=url):
                        pg.goto(url)
                        view_ready(pg, url.split("/")[3])
                        before = path_of(pg)
                        click_row(pg, row)
                        pg.wait_for(DRAWER_OPEN)
                        pg.wait_for("decodeURIComponent(location.hash).indexOf('sel=' + %s) > 0" % q(sel))
                        self.assertEqual(path_of(pg), before, "row click must not change the view segment")
                        self.assertEqual(pg.js("document.querySelector('#app-main > .app-view').getAttribute('data-view')"), url.split("/")[3])
                        if url.endswith("inventory"):
                            self.assertIn("sec=inventory", pg.js("location.hash"))
                        hash_before = pg.js("location.hash")
                        if size == "m" and url.endswith("ports"):
                            pg.shot("qa-drawer-m")
                        pg.reload()
                        view_ready(pg, url.split("/")[3])
                        self.assertEqual(pg.js("location.hash"), hash_before, "reload keeps sel/sec")
                        pg.wait_for(DRAWER_OPEN)
                        pg.wait_for("!!document.querySelector('#app-inspector .ins-head')")
                        pg.press("Escape")
                        if pg.js(DRAWER_OPEN):  # lg: Esc closes the docked drawer only with focus inside
                            pg.click("#app-inspector .ins-close")
                        pg.wait_for("!(%s)" % DRAWER_OPEN)
                        pg.wait_for("location.hash.indexOf('sel=') < 0")
                self.assertEqual(errors(pg), [])

    # ------------------------------------------- nav memory and explorer

    def test_nav_memory_and_explorer_persistence(self):
        """A section click returns to its last sub-page; explorer width and collapse persist across reload."""
        sub = CAMPUS + "devices/foh-cl5/cables"
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(sub, size) as pg:
                view_ready(pg, "devices")
                nav = "#app-views [data-section=%s]" if size == "d" else "#app-tabbar [data-tab=%s]"
                pg.click(nav % "patch")
                pg.wait_for("location.hash.split('?')[0] === %s" % q(CAMPUS + "patch"))
                view_ready(pg, "patch")
                pg.click(nav % "devices")
                pg.wait_for("location.hash.split('?')[0] === %s" % q(sub))
                view_ready(pg, "devices")
                self.assertEqual(pg.js("document.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab')"), "cables")
                stored = json.loads(pg.js("sessionStorage.getItem('fathom.ui.nav')") or "{}")
                self.assertTrue(stored.get(PROJECT, {}).get("devices", "").startswith(sub), stored)
        with self.open(CAMPUS + "devices/foh-cl5/overview", "d") as pg:
            view_ready(pg, "devices")
            key = pg.wait_for("(document.querySelector('#app-main .ex-root') || {getAttribute: function () { return null; }}).getAttribute('data-explorer')")
            w0 = pg.js("document.querySelector('#app-main .ex-side').getBoundingClientRect().width")
            pg.js("document.querySelector('#app-main .ex-resizer').focus(); 1")
            for _ in range(4):
                pg.press("ArrowRight")
            w1 = pg.wait_for("(function () { var w = document.querySelector('#app-main .ex-side').getBoundingClientRect().width; return w > %f + 20 ? w : 0; })()" % w0)
            stored = json.loads(pg.js("localStorage.getItem(%s)" % q("fathom.ui.explorer." + key)) or "{}")
            self.assertEqual(stored.get("c"), False, stored)
            self.assertAlmostEqual(stored.get("w"), w1, delta=2)
            pg.reload()
            view_ready(pg, "devices")
            pg.wait_for("!!document.querySelector('#app-main .ex-side')")
            self.assertAlmostEqual(pg.js("document.querySelector('#app-main .ex-side').getBoundingClientRect().width"), w1, delta=2)
            pg.click("#app-main .ex-collapse")
            pg.wait_for("document.querySelector('#app-main .ex-root').classList.contains('ex-collapsed')")
            pg.reload()
            view_ready(pg, "devices")
            pg.wait_for("!!document.querySelector('#app-main .ex-root')")
            self.assertTrue(pg.js("document.querySelector('#app-main .ex-root').classList.contains('ex-collapsed')"), "collapse persists")
            self.assertEqual(json.loads(pg.js("localStorage.getItem(%s)" % q("fathom.ui.explorer." + key)))["c"], True)
            pg.click("#app-main .ex-collapse")
            pg.wait_for("!document.querySelector('#app-main .ex-root').classList.contains('ex-collapsed')")
            self.assertAlmostEqual(pg.js("document.querySelector('#app-main .ex-side').getBoundingClientRect().width"), w1, delta=2)
            self.assertEqual(errors(pg), [])

    # ------------------------------------------------------------- search

    def open_search(self, pg):
        pg.click("#app-search")
        pg.wait_for("document.activeElement && document.activeElement.id === 'app-palette-input'")

    def query(self, pg, text):
        """Clear the field (the live region empties), type ``text`` and wait for its results."""
        pg.js("(function () { var i = document.getElementById('app-palette-input'); i.value = '';"
              " i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()")
        pg.wait_for("document.querySelector('#app-palette .sr-only').textContent === ''")
        for ch in text:
            pg.press(ch)
        pg.wait_for("(function () { var p = document.getElementById('app-palette'); return !!p && !p.hasAttribute('aria-busy')"
                    " && document.getElementById('app-palette-input').value === %s"
                    " && /result|No /.test(p.querySelector('.sr-only').textContent); })()" % q(text))

    def hits(self, pg):
        return pg.js("Array.prototype.map.call(document.querySelectorAll('#app-palette-list [role=option]'), function (li) {"
                     " return [li.getAttribute('data-hit-kind'), li.getAttribute('data-hit-id'), li.getAttribute('data-hit-cat'),"
                     " li.querySelector('.sr-title').textContent]; })")

    def test_global_search(self):
        """foh, chapel, A-001 and RC-0001 find a device, room, cable and inventory item; arrows/Enter/Esc work."""
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(CAMPUS + "patch", size) as pg:
                view_ready(pg, "patch")
                self.open_search(pg)
                self.query(pg, "foh")
                self.assertIn(["device", "foh-cl5"], [h[:2] for h in self.hits(pg)])
                self.query(pg, "chapel")
                self.assertIn(["room", "chapel"], [h[:2] for h in self.hits(pg)])
                self.query(pg, "A-001")
                cables = [h for h in self.hits(pg) if h[0] == "cable"]
                self.assertTrue(cables and cables[0][3].startswith("A-001"), self.hits(pg))
                self.query(pg, "RC-0001")
                groups = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-palette-list .sr-group'), function (g) { return g.textContent; })")
                self.assertIn("Inventory", groups)
                self.assertIn(["device", "foh-cl5", "inventory"], [h[:3] for h in self.hits(pg)])
                pg.shot("qa-search-" + size)
                # keyboard: ↓ ↑ move the active option; Enter navigates and closes
                self.query(pg, "foh")
                a0 = pg.js("document.getElementById('app-palette-input').getAttribute('aria-activedescendant')")
                self.assertTrue(a0, "best hit starts active")
                pg.press("ArrowDown")
                a1 = pg.js("document.getElementById('app-palette-input').getAttribute('aria-activedescendant')")
                self.assertNotEqual(a1, a0)
                pg.press("ArrowUp")
                self.assertEqual(pg.js("document.getElementById('app-palette-input').getAttribute('aria-activedescendant')"), a0)
                target = pg.js("(function () { var o = document.getElementById(%s); return [o.getAttribute('data-hit-kind'), o.getAttribute('data-hit-id')]; })()" % q(a0))
                before = pg.js("location.hash")
                pg.press("Enter")
                pg.wait_for("!document.getElementById('app-palette')")
                pg.wait_for("location.hash !== %s" % q(before))
                self.assertIn(target[1], pg.js("decodeURIComponent(location.hash)"), "Enter opens %s" % target)
                # Esc closes
                self.open_search(pg)
                pg.press("Escape")
                pg.wait_for("!document.getElementById('app-palette')")
                self.assertEqual(errors(pg), [])

    # -------------------------------------------------------------- phone

    PRIMARY = ("#app-main button.primary, #app-main a.primary, #app-main .eh-actions > button, #app-main .eh-actions > a,"
               " #app-main .eh-more, #app-main [id$=-bulk-add], #app-main .ex-open, #app-search, #app-user, #app-notify,"
               " #app-tabbar button")

    def test_phone_layout(self):
        """At m: explorer is a drawer, the tab bar is icon-only, no page h-scroll, primary actions on screen."""
        with self.open(CAMPUS + "devices/foh-cl5", "m") as pg:
            view_ready(pg, "devices")
            pg.wait_for("!!document.querySelector('#app-main .ex-root')")
            side = "#app-main .ex-side"
            self.assertEqual(pg.offscreen(side, "x") + (0 if visible(pg, side) else 1), 1, ".ex-side must be hidden or off-canvas until opened")
            self.assertTrue(visible(pg, "#app-main .ex-open"), "explorer opener visible")
            pg.click("#app-main .ex-open")
            pg.wait_for("document.querySelector('#app-main .ex-root').classList.contains('ex-is-open')")
            pg.wait_for("(function () { var r = document.querySelector('#app-main .ex-side').getBoundingClientRect(); return r.left >= -1 && r.right <= innerWidth + 1 && r.width > 100; })()")
            pg.shot("qa-explorer-drawer-m")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('#app-main .ex-root').classList.contains('ex-is-open')")
            tabs = pg.js("""Array.prototype.map.call(document.querySelectorAll('#app-tabbar button'), function (b) {
              var txt = Array.prototype.filter.call(b.querySelectorAll('*'), function (el) {
                var r = el.getBoundingClientRect(); return !el.children.length && r.width > 0 && el.getAttribute('aria-hidden') !== 'true' && el.textContent.trim();
              }).map(function (el) { return el.textContent.trim(); });
              return {tab: b.getAttribute('data-tab'), label: b.getAttribute('aria-label'), text: txt, ico: !!b.querySelector('.ico')};
            })""")
            self.assertEqual(len(tabs), 8)
            for t in tabs:
                self.assertEqual(t["text"], [], "tab bar button %s shows text" % t["tab"])
                self.assertTrue(t["label"] and t["ico"], t)
            for v in VIEWS + ["devices/foh-cl5/ports", "rooms/main/overview", "racks/rk-foh/elevation", "schedules/ip", "settings/networks"]:
                with self.subTest(view=v):
                    pg.goto(CAMPUS + v)
                    view_ready(pg, route_view(v))
                    self.assertLessEqual(pg.page_hscroll(), 0, "%s scrolls horizontally at m" % v)
                    self.assertEqual(pg.offscreen(self.PRIMARY, "x"), 0, "primary actions off-screen on %s: %s" % (v, self.offscreen_names(pg)))
            self.assertEqual(errors(pg), [])

    def offscreen_names(self, pg):
        return pg.js("""(function (sel) {
          return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
            var r = el.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth + 1);
          }).map(function (el) { return (el.id || el.className || el.tagName) + ':' + (el.getAttribute('aria-label') || el.textContent).trim().slice(0, 24); });
        })(%s)""" % q(self.PRIMARY))

    # -------------------------------------------------------------- trace

    def test_trace_drawer(self):
        """The port drawer's Trace opens the trace drawer above it; Esc closes only the trace; a hop selects it."""
        url = CAMPUS + "patch?sel=port:rio-sl:analog-in-9"
        for size in SIZES:
            with self.subTest(size=size), self.open(url, size) as pg:
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("!!document.querySelector('#app-inspector [data-action=trace]')")
                pg.click("#app-inspector [data-action=trace]")
                pg.wait_for("!!document.querySelector('.trace-backdrop .trace-sheet .trace-hop')")
                devs = pg.js("Array.prototype.map.call(document.querySelectorAll('.trace-sheet .trace-dev'), function (d) { return d.getAttribute('data-device'); })")
                self.assertEqual(devs[0], "rio-sl", "the trace starts at the port's device")
                self.assertIn("foh-cl5", devs, "analog-in-9 reaches the FOH console downstream")
                on_top = pg.js("""(function () {
                  var s = document.querySelector('.trace-sheet').getBoundingClientRect();
                  var el = document.elementFromPoint(s.left + s.width / 2, s.top + Math.min(40, s.height / 2));
                  return !!el && !!el.closest('.trace-sheet');
                })()""")
                self.assertTrue(on_top, "trace sheet stacks above the drawer")
                self.assertEqual(pg.offscreen(".trace-sheet .trace-close", "xy"), 0)
                pg.shot("qa-trace-" + size)
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.trace-backdrop')")
                self.assertTrue(pg.js(DRAWER_OPEN), "Esc closes the trace drawer first, not the drawer")
                pg.click("#app-inspector [data-action=trace]")
                hop = ".trace-sheet .trace-dev[data-device=foh-cl5] .trace-hop"
                pg.wait_for("!!document.querySelector(%s)" % q(hop))
                pg.click(hop)
                pg.wait_for("!document.querySelector('.trace-backdrop')")
                pg.wait_for("/sel=(port|channel|device):foh-cl5/.test(decodeURIComponent(location.hash))")
                pg.wait_for(DRAWER_OPEN)
                self.assertEqual(errors(pg), [])

    # ---------------------------------------------------------------- PWA

    def test_pwa_service_worker_and_manifest(self):
        """The service worker registers with the fathom-shell-<VERSION> cache; the manifest is served and linked."""
        version = sw_version()
        self.assertTrue(version)
        with self.open(CAMPUS + "home", "d") as pg:
            got = pg.js("""navigator.serviceWorker.ready.then(function (reg) {
              return new Promise(function (r) { setTimeout(r, 1500); }).then(function () { return caches.keys(); }).then(function (keys) {
                return {scope: reg.scope, active: !!reg.active, keys: keys};
              });
            })""")
            self.assertTrue(got["active"], got)
            self.assertIn("fathom-shell-" + version, got["keys"])
            href = pg.js("document.querySelector('link[rel=manifest]').href")
            man = pg.js("fetch(%s).then(function (r) { return r.json().then(function (j) { return {status: r.status, type: r.headers.get('content-type'), j: j}; }); })" % q(href))
            self.assertEqual(man["status"], 200)
            self.assertTrue(man["j"].get("name") and man["j"].get("icons") and man["j"].get("start_url"), man["j"])
            self.assertIn(man["j"].get("display"), ("standalone", "fullscreen", "minimal-ui"))
            cached = pg.js("caches.open(%s).then(function (c) { return c.keys(); }).then(function (k) { return k.map(function (r) { return new URL(r.url).pathname; }); })"
                           % q("fathom-shell-" + version))
            for path in ("/static/js/app.js", "/static/js/router-core.js", "/static/js/datatable.js", "/static/css/app.css"):
                self.assertIn(path, cached)


class AcceptanceViewer(UiCase):
    """B.8 viewer-role row: a login-on server with a viewer; no write actions rendered, PUT is 403."""

    PASSWORD = "viewer1-password-1"

    WRITE_WORDS = re.compile(r"^(\+\s*)?(add|new|bulk add|delete|remove|merge|upload|import|preview|promote|run discovery|build|save|test|"
                             r"edit|restore|apply|assign|mark|arrange|undo|redo|rename|duplicate)\b", re.I)

    # Enabled form controls a viewer may use: search, filters, paging and scope selects.
    ALLOWED_CONTROLS = ("input[type=search], .dt-toolbar *, .dt-foot *, .dt-pager *, .dt-pop *, .ex-head *, #sch-state, #pt-filter-room,"
                        " #pt-only-patched, #pt-show-overlay, #fp-select, #rk-select, #inv-scope, select[aria-label='Rows per page']")
    NOTES = "#app-inspector [data-section=notes] textarea"

    CONTROLS = """(function (allowed) {
      var out = {buttons: [], fields: [], checks: 0, bulk: 0};
      function shown(el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; }
      Array.prototype.forEach.call(document.querySelectorAll('#app-main button, #app-main a[role=button], #app-inspector button, #app-inspector a[role=button]'), function (b) {
        if (!shown(b) || b.disabled) return;
        out.buttons.push((b.getAttribute('aria-label') || b.textContent || '').trim());
      });
      Array.prototype.forEach.call(document.querySelectorAll('#app-main input, #app-main select, #app-main textarea, #app-inspector input, #app-inspector select, #app-inspector textarea, #app-main [contenteditable=true], #app-inspector [contenteditable=true]'), function (f) {
        if (!shown(f) || f.disabled || f.readOnly || f.matches(allowed)) return;
        if (f.type === 'checkbox' && f.closest('.dt-cols-panel')) return;
        out.fields.push((f.id ? '#' + f.id + ' ' : '') + (f.getAttribute('aria-label') || f.name || f.type || f.tagName));
      });
      out.checks = document.querySelectorAll('#app-main .dt-row-check').length;
      out.bulk = Array.prototype.filter.call(document.querySelectorAll('#app-main .dt-bulk'), shown).length;
      return out;
    })(%s)"""

    ROUTES = ["home", "patch", "table", "plan", "racks", "racks/rk-foh/elevation", "inventory", "schedules/cables", "schedules/ip",
              "devices", "devices/foh-cl5/overview", "devices/foh-cl5/ports", "rooms", "rooms/main/overview", "imports",
              "discovery", "history", "builds", "settings", "settings/networks", "settings/templates", "sop",
              "inventory?sel=device:foh-cl5&sec=inventory", "schedules/cables?sel=cable:c-0001", "patch?sel=port:rio-sl:analog-in-9"]

    @classmethod
    def setUpClass(cls) -> None:
        super(AcceptanceViewer, cls).setUpClass()
        from fathom import users

        users.add_user("admin1", "admin1-password-1", role="admin")
        users.add_user("viewer1", cls.PASSWORD, role="viewer")

    def signed_in(self, name: str, path: str, size: str = "d"):
        from fathom import users

        cookie = users.make_session(users.get_user(name))
        cm = self.open("/login", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        pg.command("Network.enable")
        pg.command("Network.setCookie", {"name": "fathom_session", "value": cookie, "url": self.base + "/", "httpOnly": True, "sameSite": "Lax"})
        pg.goto(path)
        return pg

    def test_viewer_role_read_only(self):
        pg = self.signed_in("viewer1", "/#/campus-demo/main/home")
        view_ready(pg, "home")
        found = {}
        for r in self.ROUTES:
            pg.goto(CAMPUS + r)
            view_ready(pg, route_view(r))
            if "sel=" in r:
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("!!document.querySelector('#app-inspector .ins-head')")
            pg.js("new Promise(function (r) { setTimeout(r, 200); })")
            c = pg.js(self.CONTROLS % q(self.ALLOWED_CONTROLS))
            writes = [b for b in c["buttons"] if self.WRITE_WORDS.match(b)]
            bad = {}
            if writes:
                bad["write buttons"] = sorted(set(writes))
            if c["fields"]:
                bad["editable fields"] = sorted(set(c["fields"]))[:10]
            if c["checks"] or c["bulk"]:
                bad["selection"] = {"row checks": c["checks"], "bulk bars": c["bulk"]}
            if r == "patch":
                hint = pg.js("(document.querySelector('.pv-hint') || {}).textContent || ''")
                if re.search(r"(?i)drag|re-patch|rename", hint):
                    bad["canvas hint"] = hint
            if bad:
                found[r] = bad
            if r in ("patch", "inventory", "settings"):
                pg.shot("qa-viewer-%s-d" % r)
        self.assertEqual(pg.js("window.__fathomErrors || []"), [])
        self.assertEqual(found, {}, "write actions rendered for a viewer")

    def test_viewer_device_notes_read_only(self):
        """The device drawer's standalone Notes editor (bound() outside fieldRow) is disabled for viewers."""
        pg = self.signed_in("viewer1", "/#/campus-demo/main/inventory?sel=device:foh-cl5&sec=inventory")
        view_ready(pg, "inventory")
        pg.wait_for(DRAWER_OPEN)
        pg.wait_for("!!document.querySelector(%s)" % q(self.NOTES))
        self.assertTrue(pg.js("(function (t) { return t.disabled || t.readOnly; })(document.querySelector(%s))" % q(self.NOTES)),
                        "viewer gets an enabled Notes textarea in the device drawer")

    def test_viewer_put_is_403(self):
        auth = "Basic " + base64.b64encode(("viewer1:" + self.PASSWORD).encode()).decode()
        get = urllib.request.Request(self.base + "/api/v2/projects/" + PROJECT, headers={"Authorization": auth})
        with urllib.request.urlopen(get, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            doc = json.loads(resp.read().decode("utf-8"))
        body = json.dumps(doc.get("doc", doc)).encode("utf-8")
        put = urllib.request.Request(self.base + "/api/v2/projects/" + PROJECT, data=body, method="PUT",
                                     headers={"Authorization": auth, "Content-Type": "application/json", "X-Fathom": "1"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(put, timeout=10)
        self.assertEqual(cm.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
