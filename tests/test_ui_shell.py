"""SHELL: app shell layout, sections, nav memory, drawer and selection bar (docs/ui-audit.md B.2 SHELL, D1-D6).

Runs against the real app on a ``tests/_ui.py`` server (``sunday-demo`` fixture and ``campus-demo``
sample). Skips without Chrome; set ``FATHOM_CHROME=/usr/bin/google-chrome-stable``. With
``FATHOM_UI_SHOTS`` set it writes ``home``, ``patch`` and ``schedules`` screenshots at d, t and m.
"""
from __future__ import annotations

import json
import time
import unittest
import urllib.error
import urllib.request

try:
    from _ui import UiCase
    from test_frontend_smoke import VIEWS
except ImportError:  # pragma: no cover
    from tests._ui import UiCase
    from tests.test_frontend_smoke import VIEWS

CAMPUS = "#/campus-demo/main/"
SUNDAY = "#/sunday-demo/main/"
SHOT_VIEWS = ("home", "patch", "schedules")
LIGHT_BG = "rgb(246, 247, 251)"  # --bg of html[data-theme=light]
DARK_BG = "rgb(11, 16, 32)"


def api(base: str, method: str, path: str, body=None):
    """JSON call against the test server (mutations carry the X-Fathom CSRF header)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"X-Fathom": "1", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else None


def set_lock(base: str, project: str, locked: bool, by: str = "sam"):
    """settings.locked through the ops pipeline (P2A's server fills locked_by / locked_at; here the test does)."""
    cur = api(base, "GET", "/api/v2/projects/%s" % project)
    value = {"locked": locked}
    if locked:
        value["locked_by"] = by
        value["locked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return api(base, "POST", "/api/v2/projects/%s/changes" % project,
               {"base_revision": cur["revision"], "ops": [{"op": "root", "key": "settings", "value": value}], "summary": "lock"})

VISIBLE = """(function (sel) {
  return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }).length;
})(%s)"""

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")


def visible(pg, selector: str) -> int:
    return int(pg.js(VISIBLE % json.dumps(selector)))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading');
    })(%s)""" % json.dumps(view), timeout)


class ShellUi(UiCase):
    def test_sections_and_tab_bar(self):
        for size in ("d", "t"):
            with self.subTest(size=size), self.open(CAMPUS + "patch", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(visible(pg, "#app-views .app-sec"), 7, "7 section buttons (home is #app-home)")
                self.assertEqual(visible(pg, "#app-tabbar button"), 0)
                cur = pg.js("document.querySelector('#app-views .app-sec[aria-current=page]').getAttribute('data-section')")
                self.assertEqual(cur, "patch")
                self.assertEqual(pg.js("document.querySelectorAll('#app-subnav a.app-subtab[data-view][href]').length"), 3)
                self.assertTrue(visible(pg, "#app-subnav"))
                if size == "d":
                    self.assertEqual(visible(pg, "#app-views .app-sec .app-sec-label"), 7, "labels visible at d")
                    self.assertTrue(visible(pg, "#app-home"), "brand links home at lg")
        with self.open(CAMPUS + "sop", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            tabs = pg.js("""Array.prototype.map.call(document.querySelectorAll('#app-tabbar button[data-tab]'), function (b) {
              var r = b.getBoundingClientRect(); return {key: b.getAttribute('data-tab'), w: r.width, h: r.height, label: b.getAttribute('aria-label')};
            })""")
            self.assertEqual(len(tabs), 8)
            self.assertEqual([t["key"] for t in tabs], ["home", "patch", "rooms", "devices", "schedules", "sop", "data", "settings"])
            for t in tabs:
                self.assertGreaterEqual(t["w"], 40, t)
                self.assertGreaterEqual(t["h"], 40, t)
                self.assertTrue(t["label"], t)
            self.assertEqual(visible(pg, "#app-views"), 0, "#app-views hidden at m")
            self.assertEqual(visible(pg, "#app-subnav"), 0, "SOPs has one view: no subnav")
            self.assertEqual(pg.js("document.querySelector('#app-tabbar [aria-current=page]').getAttribute('data-tab')"), "sop")
            pg.click("#app-tabbar [data-tab=home]")
            view_ready(pg, "home")
            self.assertEqual(pg.js("location.hash"), CAMPUS + "home")

    def test_nav_memory(self):
        with self.open(CAMPUS + "schedules?q=drum", "d") as pg:
            view_ready(pg, "schedules")
            pg.goto(CAMPUS + "patch")
            view_ready(pg, "patch")
            pg.click("#app-views [data-section=schedules]")
            pg.wait_for("location.hash.indexOf('/schedules') > 0")
            view_ready(pg, "schedules")
            self.assertEqual(pg.js("location.hash"), CAMPUS + "schedules?q=drum", "remembered hash")
            pg.click("#app-views [data-section=schedules]")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "schedules"))
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "schedules?q=drum"))
            pg.js("history.back(); 1")
            pg.wait_for("location.hash === %s" % json.dumps(CAMPUS + "patch"))
            view_ready(pg, "patch")
            stored = json.loads(pg.js("sessionStorage.getItem('fathom.ui.nav')"))
            self.assertEqual(stored["campus-demo"]["patch"], CAMPUS + "patch")

    def test_section_menu_lists_views(self):
        with self.open(CAMPUS + "patch", "d") as pg:
            pg.js("document.querySelector('#app-views [data-section=rooms]').focus(); 1")
            pg.press("ArrowDown")
            pg.wait_for("!document.querySelector('#app-views [data-section=rooms] + .app-sec-menu').hidden")
            views = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-views [data-section=rooms] + .app-sec-menu [data-view]'), function (b) { return b.getAttribute('data-view'); })")
            self.assertEqual(views, ["rooms", "plan", "racks"])
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-view')"), "rooms")
            pg.press("ArrowDown")
            pg.press("Enter")
            pg.wait_for("location.hash.indexOf('/plan') > 0")
            view_ready(pg, "plan")
            self.assertTrue(pg.js("document.querySelector('#app-views [data-section=rooms] + .app-sec-menu').hidden"))

    def test_banner_precedes_header(self):
        with self.open(SUNDAY + "patch", "d") as pg:
            order = pg.js("""(function () {
              var ids = Array.prototype.map.call(document.getElementById('app').children, function (c) { return c.id; });
              return ids;
            })()""")
            self.assertEqual(order, ["app-banner", "app-top", "app-lock", "app-views", "app-subnav", "app-body", "app-selbar", "app-tabbar"])
            self.assertTrue(pg.js("document.getElementById('app-lock').hidden"), "no lock banner on an unlocked project")

    def test_deep_link_opens_drawer(self):
        for size in ("m", "d"):
            with self.subTest(size=size), self.open(SUNDAY + "patch?sel=device:atem-mini", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('ATEM Mini') >= 0")
                self.assertTrue(pg.wait_for(DRAWER_OPEN))
                self.assertEqual(visible(pg, "#app-selbar"), 0)

    def test_drawer_closed_shows_selection_bar(self):
        with self.open(SUNDAY + "patch?sel=device:atem-mini&drawer=0", "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))
            self.assertIn("ATEM Mini", pg.js("document.querySelector('#app-selbar .app-selbar-title').textContent"))
            bar = pg.rect("#app-selbar")
            tabbar = pg.rect("#app-tabbar")
            self.assertLessEqual(bar["bottom"], tabbar["top"] + 1, "selection bar sits above the tab bar")
            pg.click("#app-selbar .app-selbar-open")
            pg.wait_for(DRAWER_OPEN)
            pg.wait_for("document.getElementById('app-inspector').textContent.indexOf('ATEM Mini') >= 0")
            self.assertNotIn("drawer=0", pg.js("location.hash"))
            self.assertIn("sel=device:atem-mini", pg.js("location.hash"))
            # opening pushed a history entry: Back closes the drawer and keeps the selection
            pg.js("history.back(); 1")
            pg.wait_for("location.hash.indexOf('drawer=0') > 0")
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))
            pg.click("#app-selbar .app-selbar-close")
            pg.wait_for("document.getElementById('app-selbar').hidden")
            self.assertNotIn("sel=", pg.js("location.hash"))

    def test_canvas_selection_below_lg_keeps_drawer_closed(self):
        with self.open(SUNDAY + "patch", "t") as pg:
            pg.wait_for("!!document.querySelector('.pv-card[data-device=atem-mini]')")
            pg.click(".pv-card[data-device=atem-mini] .pv-title")
            sel = pg.wait_for("(location.hash.match(/sel=([^&]*)/) || [])[1]")
            self.assertTrue(sel.startswith("device:atem-mini") or sel.startswith("port:atem-mini"), sel)
            self.assertIn("drawer=0", pg.js("location.hash"))
            pg.wait_for("!document.getElementById('app-selbar').hidden")
            self.assertFalse(pg.js(DRAWER_OPEN))

    def test_no_page_hscroll_on_any_view(self):
        for size in ("m", "t"):
            with self.subTest(size=size), self.open(CAMPUS + "home", size) as pg:
                for i, v in enumerate(VIEWS):
                    with self.subTest(view=v):
                        if i or v != "home":
                            pg.goto(CAMPUS + v)
                        view_ready(pg, v)
                        self.assertLessEqual(pg.page_hscroll(), 0, "%s at %s scrolls horizontally" % (v, size))
                        if v in SHOT_VIEWS:
                            pg.shot("%s-%s" % (v, size))
                self.assertEqual(pg.js("window.__fathomErrors"), [])
        with self.open(CAMPUS + "home", "d") as pg:
            for v in SHOT_VIEWS:
                if v != "home":
                    pg.goto(CAMPUS + v)
                view_ready(pg, v)
                pg.shot("%s-d" % v)

    def test_search_palette_keyboard(self):
        with self.open(SUNDAY + "patch", "d") as pg:
            pg.press("Meta+k")
            pg.wait_for("!!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-palette-input")
            pg.press("Escape")
            pg.wait_for("!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-search")
            pg.click("#app-search")
            pg.wait_for("!!document.getElementById('app-palette')")

    def test_legacy_project_url_lands_on_home(self):
        with self.open("/?p=sunday-demo", "d") as pg:
            view_ready(pg, "home")
            self.assertTrue(pg.js("location.hash").startswith("#/sunday-demo/"))
            self.assertEqual(pg.js("location.hash").split("?")[0].split("/")[3], "home")

    def test_empty_view_canonicalizes_to_home_and_keeps_selection(self):
        with self.open("#/sunday-demo/main?sel=device:atem-mini", "d") as pg:
            view_ready(pg, "home")
            self.assertEqual(pg.js("location.hash"), SUNDAY + "home?sel=device:atem-mini")
            pg.wait_for(DRAWER_OPEN)

    def test_phone_user_menu_holds_header_actions(self):
        with self.open(CAMPUS + "patch", "m") as pg:
            for ident in ("app-undo", "app-redo", "app-assistant-btn", "app-project"):
                self.assertEqual(visible(pg, "#" + ident), 0, "#%s hidden at sm" % ident)
            for ident in ("app-room", "app-search", "app-notify", "app-save", "app-user"):
                self.assertEqual(visible(pg, "#" + ident), 1, "#%s shown at sm" % ident)
            pg.click("#app-user")
            pg.wait_for("!!document.querySelector('.app-menu')")
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('.app-menu button'), function (b) { return b.textContent; })")
            for want in ("Undo", "Redo", "Helper", "campus-demo", "sunday-demo", "New project\u2026"):
                self.assertTrue(any(l.startswith(want) for l in labels), "%r not in user menu %r" % (want, labels))
            self.assertLessEqual(pg.page_hscroll(), 0)

    # ---- Phase 2 (P2B): theme, lock banner, suggestions (FR-UX-15, 17, 18)

    def test_theme_cycles_and_persists(self):
        with self.open(CAMPUS + "home", "d") as pg:
            self.assertEqual(pg.js("document.documentElement.getAttribute('data-theme')"), "dark", "dark is the default")
            self.assertEqual(pg.js("getComputedStyle(document.body).backgroundColor"), DARK_BG)
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-theme')")
            self.assertTrue(pg.js("document.getElementById('app-menu-theme').textContent").startswith("Theme: Dark"))
            pg.click("#app-menu-theme")
            pg.wait_for("document.documentElement.getAttribute('data-theme') === 'light'")
            self.assertEqual(pg.js("getComputedStyle(document.body).backgroundColor"), LIGHT_BG)
            self.assertEqual(pg.js("localStorage.getItem('fathom.ui.theme')"), "light")
            self.assertEqual(pg.js("document.querySelector('meta[name=theme-color]').getAttribute('content')"), "#f6f7fb")
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-theme')")
            self.assertTrue(pg.js("document.getElementById('app-menu-theme').textContent").startswith("Theme: Light"))
            pg.click("#app-menu-theme")
            pg.wait_for("document.documentElement.getAttribute('data-theme') === 'system'")
            self.assertEqual(pg.js("localStorage.getItem('fathom.ui.theme')"), "system")
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-theme')")
            pg.click("#app-menu-theme")
            pg.wait_for("document.documentElement.getAttribute('data-theme') === 'dark'")
            self.assertEqual(pg.js("getComputedStyle(document.body).backgroundColor"), DARK_BG)
            # persists across a reload
            pg.js("localStorage.setItem('fathom.ui.theme', 'light'); 1")
            pg.reload()
            view_ready(pg, "home")
            self.assertEqual(pg.js("document.documentElement.getAttribute('data-theme')"), "light")
            self.assertEqual(pg.js("getComputedStyle(document.body).backgroundColor"), LIGHT_BG)
            self.assertEqual(pg.smoke["errors"], [])

    def test_theme_query_override_renders_light_without_hscroll(self):
        for size, view in (("m", "inventory"), ("m", "home"), ("d", "inventory")):
            with self.subTest(size=size, view=view), self.open("/?theme=light" + CAMPUS + view, size) as pg:
                view_ready(pg, view)
                self.assertEqual(pg.js("document.documentElement.getAttribute('data-theme')"), "light")
                self.assertEqual(pg.js("getComputedStyle(document.body).backgroundColor"), LIGHT_BG)
                self.assertIsNone(pg.js("localStorage.getItem('fathom.ui.theme')"), "?theme= is not persisted")
                self.assertLessEqual(pg.page_hscroll(), 0, "%s at %s scrolls horizontally in light mode" % (view, size))
                self.assertEqual(pg.smoke["errors"], [])
                pg.shot("light-%s-%s" % (view, size))

    def test_locked_project_shows_banner_and_viewer_mode(self):
        name = "lock-demo"
        try:
            api(self.base, "POST", "/api/v2/projects", {"name": name, "template": "campus-demo", "org": "Lock"})
        except urllib.error.HTTPError as e:  # already there from an earlier run of this class
            if e.code != 409:
                raise
        set_lock(self.base, name, True, by="sam")
        doc = api(self.base, "GET", "/api/v2/projects/" + name)["doc"]
        self.assertIs(doc["settings"]["locked"], True, "normalize keeps settings.locked")
        try:
            with self.open("#/%s/main/inventory" % name, "d") as pg:
                view_ready(pg, "inventory")
                pg.wait_for("!document.getElementById('app-lock').hidden")
                text = pg.js("document.getElementById('app-lock').textContent")
                self.assertIn("Editing is locked", text)
                self.assertIn("sam", text)
                self.assertIn("just now", text)
                self.assertTrue(pg.js("!!document.getElementById('app-unlock')"), "editors get Unlock")
                self.assertTrue(pg.js("document.querySelector('#app-save').getAttribute('aria-label')").startswith("Locked"))
                self.assertTrue(pg.js("document.getElementById('app-undo').disabled"))
                pg.wait_for("document.getElementById('inv-bulk-add') && document.getElementById('inv-bulk-add').hidden", 5)
                self.assertEqual(pg.js("document.querySelectorAll('#app-banner .small').length"), 0, "no second read-only banner for editors")
                pg.click("#app-user")
                pg.wait_for("!!document.querySelector('.app-menu')")
                self.assertFalse(pg.js("!!document.getElementById('app-menu-lock')"), "no Lock editing while locked")
                self.assertFalse(pg.js("document.getElementById('app-menu-suggest').disabled"), "suggestions stay open to everyone")
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.app-menu')")
                # Unlock: one op through the pipeline; the view comes back editable
                pg.click("#app-unlock")
                pg.wait_for("document.getElementById('app-lock').hidden")
                pg.wait_for("document.querySelector('#app-save').getAttribute('data-state') === 'saved'", 10)
                pg.wait_for("document.getElementById('inv-bulk-add') && !document.getElementById('inv-bulk-add').hidden", 5)
                self.assertTrue(pg.js("document.querySelector('#app-save').getAttribute('aria-label')").startswith("Saved"))
                doc = api(self.base, "GET", "/api/v2/projects/" + name)["doc"]
                self.assertIs(doc["settings"].get("locked"), False)
                pg.click("#app-user")
                pg.wait_for("!!document.getElementById('app-menu-lock')")
                pg.click("#app-menu-lock")
                pg.wait_for("!document.getElementById('app-lock').hidden")
                pg.wait_for("document.querySelector('#app-save').getAttribute('data-state') === 'saved'", 10)
                doc = api(self.base, "GET", "/api/v2/projects/" + name)["doc"]
                self.assertIs(doc["settings"].get("locked"), True)
                pg.shot("lock-banner-d")
                self.assertEqual(pg.js("window.__fathomErrors"), [])
            with self.open("#/%s/main/patch" % name, "m") as pg:
                pg.wait_for("!document.getElementById('app-lock').hidden")
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertGreaterEqual(pg.rect("#app-unlock")["height"], 44, "44 px Unlock on touch")
                pg.shot("lock-banner-m")
        finally:
            set_lock(self.base, name, False)

    def test_locked_change_flush_drops_ops_and_reloads(self):
        name = "lock-demo"
        try:
            api(self.base, "POST", "/api/v2/projects", {"name": name, "template": "campus-demo", "org": "Lock"})
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
        set_lock(self.base, name, False)
        try:
            with self.open("#/%s/main/settings" % name, "d") as pg:
                view_ready(pg, "settings")
                self.assertTrue(pg.js("document.getElementById('app-lock').hidden"))
                rule = pg.intercept("/api/v2/projects/%s/changes" % name, 423,
                                    {"error": "locked", "code": "locked", "details": {"locked_by": "sam", "locked_at": "2026-01-01T00:00:00Z"}}, method="POST")
                set_lock(self.base, name, True, by="sam")  # what the resync will read back
                edited = pg.js("""(function () {
                  var lab = Array.prototype.filter.call(document.querySelectorAll('[data-card=preferences] label'), function (l) { return l.textContent === 'Currency'; })[0];
                  if (!lab) return false;
                  var inp = document.getElementById(lab.htmlFor); inp.value = 'EUR'; inp.dispatchEvent(new Event('change', {bubbles: true})); return true;
                })()""")
                self.assertTrue(edited, "settings Currency field found")
                pg.wait_for("Array.prototype.some.call(document.querySelectorAll('.app-toast'), function (t) { return t.textContent.indexOf('Someone locked editing') >= 0; })", 10)
                self.assertGreaterEqual(rule["hits"], 1)
                pg.wait_for("!document.getElementById('app-lock').hidden", 10)
                self.assertIn("sam", pg.js("document.getElementById('app-lock').textContent"))
                pg.wait_for("document.querySelector('#app-save').getAttribute('aria-label').indexOf('pending') < 0", 10)
                self.assertTrue(pg.js("document.querySelector('#app-save').getAttribute('aria-label')").startswith("Locked"))
                self.assertIsNone(pg.js("localStorage.getItem('fathom.pending.%s')" % name), "queued ops dropped")
                self.assertEqual(pg.js("window.__fathomErrors"), [])
        finally:
            set_lock(self.base, name, False)

    def test_suggest_improvement_dialog_posts(self):
        text = "Suggestion from the shell test %d" % int(time.time())
        with self.open(CAMPUS + "inventory", "m") as pg:
            view_ready(pg, "inventory")
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-suggest')")
            pg.click("#app-menu-suggest")
            pg.wait_for("!!document.getElementById('imv-text')")
            self.assertEqual(pg.js("document.querySelector('.app-dialog h2').textContent"), "Suggest an improvement")
            about = pg.js("document.getElementById('imv-about').textContent")
            self.assertIn("campus-demo", about)
            self.assertIn("Inventory", about)
            self.assertIn("Main Auditorium", about)
            dlg = pg.rect(".app-dialog")
            self.assertGreaterEqual(dlg["width"], 380, "full-width sheet at 390 px")
            send = pg.rect(".app-dialog footer button.primary")
            self.assertGreaterEqual(send["height"], 44)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("suggest-m")
            # empty text is refused
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("Array.prototype.some.call(document.querySelectorAll('.app-toast'), function (t) { return t.textContent.indexOf('Describe the improvement') >= 0; })")
            self.assertTrue(pg.js("!!document.getElementById('imv-text')"), "dialog stays open")
            pg.js("var t = document.getElementById('imv-text'); t.value = %s; t.dispatchEvent(new Event('input')); document.getElementById('imv-name').value = 'Pat'; 1" % json.dumps(text))
            self.assertEqual(pg.js("document.getElementById('imv-count').textContent"), "%d / 2000" % len(text))
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("Array.prototype.some.call(document.querySelectorAll('.app-toast'), function (t) { return t.textContent.indexOf('Thanks') >= 0; })", 10)
            self.assertFalse(pg.js("!!document.getElementById('imv-text')"))
            self.assertEqual(pg.js("window.__fathomErrors"), [])
        probs = api(self.base, "GET", "/api/v2/projects/campus-demo/problems")["problems"]
        mine = [p for p in probs if p.get("text") == text]
        self.assertEqual(len(mine), 1, "the suggestion reached the problems list")
        if "kind" in mine[0]:  # P2A's server keeps the kind; main ignores it
            self.assertEqual(mine[0]["kind"], "suggestion")
        with self.open(CAMPUS + "home", "d", intercepts=[("/api/v2/projects/campus-demo/problems", 404, {"error": "not found", "code": "not_found"}, "POST")]) as pg:
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-suggest')")
            pg.click("#app-menu-suggest")
            pg.wait_for("!!document.getElementById('imv-text')")
            pg.shot("suggest-d")
            pg.js("var t = document.getElementById('imv-text'); t.value = 'x'; t.dispatchEvent(new Event('input')); 1")
            pg.click(".app-dialog footer button.primary")
            pg.wait_for("Array.prototype.some.call(document.querySelectorAll('.app-toast.err'), function (t) { return t.textContent.indexOf('not found') >= 0; })", 10)


if __name__ == "__main__":
    unittest.main()
