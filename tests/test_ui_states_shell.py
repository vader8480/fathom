"""ST-SHELL: loading, empty and error states for the app shell, Home and SOP (docs/ui-audit.md B.2, B.3).

Holds a request to see each skeleton and then its replacement; fails one to see the error card or
``inlineError`` and its Retry; opens a blank project for the empty copy. Also covers Esc on an explorer
page (the explorer's hidden backdrop must not swallow it), a deep-linked device being selected once,
and the bell notices for restored offline edits, a failed overlay refresh and a finished build.
Skips without Chrome; with ``FATHOM_UI_SHOTS`` set it writes ``st-<state>-<size>`` screenshots.
"""
from __future__ import annotations

import fnmatch
import json
import time
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

SUNDAY = "#/sunday-demo/main/"
CAMPUS = "#/campus-demo/main/"
EMPTY = "st-empty"
EMPTY_HASH = "#/%s/main/" % EMPTY
SIZES = ("d", "t", "m")

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

VISIBLE = """(function (sel) {
  return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }).length;
})(%s)"""

SELECTION_HOOK = """(function () {
  window.__stSel = [];
  var orig = EventTarget.prototype.dispatchEvent;
  EventTarget.prototype.dispatchEvent = function (ev) {
    if (ev && ev.type === 'selection') { try { window.__stSel.push(JSON.stringify(ev.detail)); } catch (e) { window.__stSel.push('?'); } }
    return orig.call(this, ev);
  };
})();"""


def visible(pg, selector: str) -> int:
    return int(pg.js(VISIBLE % json.dumps(selector)))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading');
    })(%s)""" % json.dumps(view), timeout)


def notices(pg, project: str):
    raw = pg.js("sessionStorage.getItem(%s)" % json.dumps("fathom.ui.notices." + project))
    return [n.get("text", "") for n in json.loads(raw or "[]")]


class Hold(object):
    """Keep matching requests paused (CDP Fetch) until ``release()``; other requests pass through.

    ``pattern`` is a URL glob like ``UiPage.intercept``'s; requests are only paused, never answered,
    so the page sees exactly the server's response once released.
    """

    def __init__(self, pg, pattern: str, method=None) -> None:
        self.pg = pg
        self.glob = "*" + pattern if pattern.startswith("/") else pattern
        self.method = method
        self.held = []
        self.active = True
        self._orig = pg._event
        pg._event = self._event
        pg.command("Network.enable")
        pg.command("Network.setBypassServiceWorker", {"bypass": True})
        pg.command("Fetch.enable", {"patterns": [{"urlPattern": self.glob, "requestStage": "Request"}]
                                    + [{"urlPattern": r["glob"], "requestStage": "Request"} for r in pg.rules]})

    def _event(self, msg) -> None:
        if self.active and msg.get("method") == "Fetch.requestPaused":
            req = msg["params"].get("request") or {}
            if (self.method is None or req.get("method") == self.method) and fnmatch.fnmatchcase(req.get("url", ""), self.glob):
                self.pg.events.append(msg)
                self.held.append(msg["params"]["requestId"])
                return
        self._orig(msg)

    def wait(self, timeout: float = 15.0) -> None:
        t0 = time.time()
        while not self.held:
            if time.time() - t0 > timeout:
                raise AssertionError("no request matched %s" % self.glob)
            self.pg.js("1")  # lets the page session read pending events
            time.sleep(0.05)

    def release(self) -> None:
        self.active = False
        self.pg._event = self._orig
        for rid in self.held:
            self.pg.command("Fetch.continueRequest", {"requestId": rid})
        self.held = []
        if not self.pg.rules:
            self.pg.command("Fetch.disable")


class StatesShellUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(StatesShellUi, cls).setUpClass()
        cls.api("POST", "/api/v2/projects", {"name": EMPTY, "template": "blank"})

    @classmethod
    def api(cls, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(cls.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def no_hscroll(self, pg, what: str) -> None:
        self.assertLessEqual(pg.page_hscroll(), 0, "%s scrolls horizontally at %s" % (what, pg.size))

    # ------------------------------------------------------------ skeletons

    def test_view_skeleton_until_module_loads(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(SUNDAY + "home", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                hold = Hold(pg, "/static/js/views-admin.js*")
                pg.goto(SUNDAY + "imports")
                hold.wait()
                busy = pg.js("""(function () {
                  var s = document.querySelector('#app-main .app-loading.fb-skeleton');
                  return s && {kind: s.getAttribute('data-kind'), busy: s.getAttribute('aria-busy'), table: !!s.querySelector('.fb-skel-table')};
                })()""")
                self.assertEqual(busy, {"kind": "table", "busy": "true", "table": True}, "imports loads behind a table skeleton")
                self.assertEqual(pg.js("""Array.prototype.filter.call(document.querySelectorAll('#app-main *'), function (e) {
                  return !e.children.length && /Loading/.test(e.textContent) && !e.classList.contains('fb-sr');
                }).length"""), 0, "no visible Loading placeholder, only the skeleton's screen-reader label")
                self.no_hscroll(pg, "view skeleton")
                pg.shot("st-view-skeleton-" + size)
                hold.release()
                view_ready(pg, "imports")
                self.assertFalse(pg.js("!!document.querySelector('#app-main .app-loading')"), "skeleton replaced by the view")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_project_skeleton_until_project_loads(self):
        with self.open("/static/sw.js", "d", ready=False) as pg:
            hold = Hold(pg, "/api/v2/projects/sunday-demo", "GET")
            pg.command("Page.navigate", {"url": self.server.url(SUNDAY + "patch")})
            hold.wait()
            kind = pg.wait_for("(document.querySelector('#app-main .app-loading.fb-skeleton') || {getAttribute: function () { return ''; }}).getAttribute('data-kind')")
            self.assertEqual(kind, "cards", "patch is a canvas view: card skeleton")
            hold.release()
            view_ready(pg, "patch")
            self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ---------------------------------------------------------- error + Retry

    def test_view_error_card_retry_remounts(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(SUNDAY + "home", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.intercept("/static/js/views-admin.js*", 500, "nope")
                pg.goto(SUNDAY + "imports")
                pg.wait_for("!!document.querySelector('#app-main .app-error-card[role=alert][data-error-view] .app-retry')")
                self.assertFalse(pg.js("!!document.querySelector('#app-main .app-loading')"))
                self.no_hscroll(pg, "view error card")
                pg.shot("st-view-error-" + size)
                pg.clear_intercepts()
                pg.click("#app-main .app-retry")
                view_ready(pg, "imports")
                self.assertFalse(pg.js("!!document.querySelector('#app-main .app-error-card')"), "Retry remounted the view")
                self.assertEqual(pg.hash, SUNDAY + "imports")

    def test_project_load_error_retry(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(SUNDAY + "patch", size, ready=False,
                                                    intercepts=[("/api/v2/projects/sunday-demo", 500, {"error": "boom"}, "GET")]) as pg:
                pg.wait_for("!!document.querySelector('#app-main .app-error-card .app-retry')")
                self.no_hscroll(pg, "project error card")
                pg.shot("st-project-error-" + size)
                pg.clear_intercepts()
                pg.click("#app-main .app-retry")
                view_ready(pg, "patch")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_projects_list_error_retry(self):
        for size in SIZES:
            with self.subTest(size=size), self.open("/", size, intercepts=[("/api/v2/projects", 500, {"error": "boom"}, "GET")]) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for("!!document.querySelector('#app-main .app-projects-error .fb-error[role=alert] .fb-retry')")
                self.assertIn("Projects could not be loaded", pg.js("document.getElementById('app-main').textContent"))
                self.no_hscroll(pg, "projects error")
                pg.shot("st-projects-error-" + size)
                pg.clear_intercepts()
                pg.click("#app-main .fb-retry")
                view_ready(pg, "home")
                self.assertTrue(pg.hash.startswith("#/"), pg.hash)

    def test_home_projects_section_error_skeleton_retry(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(CAMPUS + "home", size, intercepts=[("/api/v2/projects", 500, {"error": "boom"}, "GET")]) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg, "home")
                pg.wait_for("!!document.querySelector('.hm-projects .fb-error .fb-retry')")
                self.assertEqual(pg.js("document.querySelectorAll('.hm-project').length"), 0)
                self.no_hscroll(pg, "home projects error")
                pg.shot("st-home-projects-error-" + size)
                pg.clear_intercepts()
                hold = Hold(pg, "/api/v2/projects", "GET")
                pg.click(".hm-projects .fb-retry")
                hold.wait()
                pg.wait_for("!!document.querySelector('.hm-projects .fb-skeleton[data-kind=cards]')")
                self.no_hscroll(pg, "home projects skeleton")
                pg.shot("st-home-projects-skeleton-" + size)
                hold.release()
                pg.wait_for("document.querySelectorAll('.hm-projects .hm-project').length >= 2")
                self.assertFalse(pg.js("!!document.querySelector('.hm-projects .fb-error, .hm-projects .fb-skeleton')"))
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ----------------------------------------------------------------- empty

    def test_empty_project_home(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY_HASH + "home", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg, "home")
                st = pg.wait_for("""(function () {
                  var s = document.querySelector('.hm-start'); if (!s) return null;
                  return {title: s.querySelector('.fb-empty-title').textContent, text: s.querySelector('.fb-empty-text').textContent,
                          links: Array.prototype.map.call(s.querySelectorAll('a[href]'), function (a) { return [a.textContent, a.getAttribute('href')]; })};
                })()""")
                self.assertEqual(st["title"], "Nothing here yet")
                self.assertTrue(st["text"].startswith("Add a room, then add gear in Patch."), st["text"])
                self.assertEqual([l[0] for l in st["links"]], ["Add gear in Patch", "Add a room"])
                self.assertIn("/patch", st["links"][0][1])
                self.assertIn("/settings/rooms", st["links"][1][1])
                self.no_hscroll(pg, "empty home")
                pg.shot("st-home-empty-" + size)
                if size == "d":
                    pg.click(".hm-start a.fb-empty-action")
                    view_ready(pg, "patch")
        with self.open(SUNDAY + "home", "d") as pg:
            view_ready(pg, "home")
            self.assertFalse(pg.js("!!document.querySelector('.hm-start')"), "a documented project has no start card")

    def test_sop_landing_empty(self):
        for size in ("d", "t"):
            with self.subTest(size=size), self.open(EMPTY_HASH + "sop", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for("!!document.querySelector('.sop-landing-empty .fb-empty')")
                self.assertEqual(pg.js("document.querySelector('.sop-landing-empty .fb-empty-title').textContent"), "No procedures yet.")
                self.assertEqual(pg.js("document.querySelector('.sop-landing-empty .fb-empty-action').textContent"), "New page")
                self.no_hscroll(pg, "SOP landing empty")
                pg.shot("st-sop-landing-empty-" + size)
                if size == "d":
                    pg.click(".sop-landing-empty .fb-empty-action")
                    pg.wait_for("/[?&]new=1/.test(location.hash)")
        with self.open(EMPTY_HASH + "sop", "m") as pg:
            pg.wait_for("!!document.querySelector('.sop-empty')")
            self.no_hscroll(pg, "SOP empty tree")
            pg.shot("st-sop-landing-empty-m")

    def test_sop_problems_empty(self):
        for size in SIZES:
            with self.subTest(size=size), self.open(EMPTY_HASH + "sop?problems=1", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                text = pg.wait_for("(document.querySelector('.sop-problems .dt-empty:not([hidden]) .dt-empty-text') || {}).textContent")
                self.assertTrue(text.startswith("No problem reports."), text)
                self.no_hscroll(pg, "SOP problems empty")
                pg.shot("st-sop-problems-empty-" + size)

    def test_sop_page_skeleton_and_error_retry(self):
        page_api = "/api/v2/projects/campus-demo/pages/power-up"
        for size in SIZES:
            with self.subTest(size=size), self.open(CAMPUS + "sop", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                hold = Hold(pg, page_api, "GET")
                pg.goto(CAMPUS + "sop?page=power-up")
                hold.wait()
                kind = pg.wait_for("(document.querySelector('.sop-loading.fb-skeleton') || {getAttribute: function () { return ''; }}).getAttribute('data-kind')")
                self.assertEqual(kind, "page")
                self.no_hscroll(pg, "SOP page skeleton")
                pg.shot("st-sop-page-skeleton-" + size)
                hold.release()
                pg.wait_for("!!document.getElementById('sop-report')")
                self.assertFalse(pg.js("!!document.querySelector('.sop-loading')"))

                pg.goto(CAMPUS + "sop")
                pg.intercept(page_api, 500, {"error": "boom"}, "GET")
                pg.goto(CAMPUS + "sop?page=power-up")
                pg.wait_for("!!document.querySelector('.sop-load-error .fb-error[role=alert] .fb-retry')")
                self.assertTrue(visible(pg, ".sop-main .sop-back"), "back to the procedures list stays")
                self.assertIn("Could not load this page", pg.js("document.querySelector('.sop-load-error h2').textContent"))
                self.no_hscroll(pg, "SOP page error")
                pg.shot("st-sop-page-error-" + size)
                pg.clear_intercepts()
                pg.click(".sop-load-error .fb-retry")
                pg.wait_for("!!document.getElementById('sop-report')")
                self.assertFalse(pg.js("!!document.querySelector('.sop-load-error')"))

    # ------------------------------------------------------------ keys, selection

    def test_esc_on_explorer_page(self):
        page = SUNDAY + "devices/atem-mini?sel=device:atem-mini"
        with self.open(page, "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.assertTrue(pg.js("!!document.querySelector('.ex-backdrop[hidden]')"), "explorer page with its hidden backdrop")
            pg.press("Meta+j")
            pg.wait_for("document.getElementById('app-assistant').classList.contains('open')")
            pg.js("document.activeElement && document.activeElement.blur(); 1")
            pg.press("Escape")
            pg.wait_for("!document.getElementById('app-assistant').classList.contains('open')", 3)
        for size in ("t", "m"):
            with self.subTest(size=size), self.open(page, size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                pg.wait_for(DRAWER_OPEN)
                pg.press("Escape")
                pg.wait_for("!(%s)" % DRAWER_OPEN, 3)
                self.assertNotIn("sel=", pg.hash)

    def test_deep_linked_device_selected_once(self):
        for view in ("patch", "plan"):
            with self.subTest(view=view), self.open("/static/sw.js", "d", ready=False) as pg:
                pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": SELECTION_HOOK})
                pg.navigate(self.server.url(SUNDAY + view + "?sel=device:atem-mini"))
                self.assertEqual(pg.smoke["errors"], [])
                view_ready(pg, view)
                pg.wait_for(DRAWER_OPEN)
                time.sleep(0.5)
                sels = [json.loads(s) for s in pg.js("window.__stSel")]
                self.assertEqual(len(sels), 1, sels)
                self.assertEqual(sels[0].get("id"), "atem-mini")

    # ------------------------------------------------------------------ bell

    def test_bell_notice_restored_offline_edits(self):
        with self.open("/static/sw.js", "d", ready=False) as pg:
            pending = {"project": "sunday-demo", "items": [{"label": "Offline edits", "ops": [
                {"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"notes": "restored by ST-SHELL"}}]}]}
            pg.js("localStorage.setItem('fathom.pending.sunday-demo', %s); 1" % json.dumps(json.dumps(pending)))
            pg.navigate(self.server.url(SUNDAY + "home"))
            self.assertEqual(pg.smoke["errors"], [])
            pg.wait_for("(sessionStorage.getItem('fathom.ui.notices.sunday-demo') || '').indexOf('Saved 1 queued change') >= 0")
            self.assertEqual(notices(pg, "sunday-demo").count("Saved 1 queued change"), 1)
            pg.wait_for("!localStorage.getItem('fathom.pending.sunday-demo')")
        doc = self.api("GET", "/api/v2/projects/sunday-demo")["doc"]
        dev = [d for d in doc["devices"] if d["id"] == "atem-mini"][0]
        self.assertEqual(dev.get("notes"), "restored by ST-SHELL")

    def test_bell_notice_overlay_refresh_failed(self):
        with self.open(SUNDAY + "home", "d", intercepts=[("/api/v2/projects/sunday-demo/overlay*", 500, {"error": "boom"}, "GET")]) as pg:
            view_ready(pg, "home")
            pg.wait_for("(sessionStorage.getItem('fathom.ui.notices.sunday-demo') || '').indexOf('Imported data could not be refreshed') >= 0")
            pg.wait_for("document.getElementById('app-notify-count').textContent.trim() === '1'")

    def test_bell_notice_build_finished(self):
        with self.open(SUNDAY + "builds", "d", intercepts=[
                ("/api/v2/projects/sunday-demo/builds", 200, {"build": "b-st-shell", "files": ["a.svg", "b.svg"]}, "POST")]) as pg:
            self.assertEqual(pg.smoke["errors"], [])
            view_ready(pg, "builds")
            pg.click("#bld-go")
            pg.wait_for("(sessionStorage.getItem('fathom.ui.notices.sunday-demo') || '').indexOf('Build b-st-shell finished (2 files)') >= 0")
            self.assertEqual(sum(1 for t in notices(pg, "sunday-demo") if t.startswith("Build ")), 1)
