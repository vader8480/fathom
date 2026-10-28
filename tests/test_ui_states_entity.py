"""ST-ENTITY: loading, empty, not-found and review states of the device page, room page and inspector
(docs/ui-audit.md B.5 ST-ENTITY, D5, D7).

The class server gets two throwaway projects next to the samples: ``empty-demo`` (blank template; room
``main`` with nothing in it, room ``store`` holding the bare device ``bare-box``, room ``annex`` for the
Add rack write) and ``roomless-demo`` (no rooms). The viewer role is forced by rewriting the project GET
through request interception, as ``test_ui_ins`` does; problem reports and duplicate suspects for the
inspector badges are injected the same way, and the duplicates request is failed to reach the inline
error. Skips without Chrome (set ``FATHOM_CHROME``); ``$FATHOM_UI_SHOTS`` collects screenshots.
"""
from __future__ import annotations

import json
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

E = "#/empty-demo/"
C = "#/campus-demo/main/"

DRAWER_OPEN = ("(function () { var el = document.getElementById('app-inspector'); var r = el.getBoundingClientRect();"
               " return el.classList.contains('dr-open') && r.width > 0 && r.height > 0; })()")

# Records the page skeletons as they are inserted (installed before the app's scripts run).
SKELETON_SPY = """(function () {
  window.__skel = [];
  new MutationObserver(function (ms) {
    ms.forEach(function (m) {
      m.addedNodes.forEach(function (n) {
        if (n.nodeType !== 1 || !n.classList || !(n.classList.contains('pd-skeleton') || n.classList.contains('pr-skeleton'))) return;
        var v = n.closest('.app-view');
        window.__skel.push({cls: n.className, kind: n.getAttribute('data-kind'), busy: n.getAttribute('aria-busy'),
                            view: v ? v.getAttribute('data-view') : ''});
      });
    });
  }).observe(document, {childList: true, subtree: true});
})();"""

EMPTY = """(function (scope) {
  var box = document.querySelector(scope + ' .fb-empty');
  if (!box) return null;
  var r = box.getBoundingClientRect();
  return {title: (box.querySelector('.fb-empty-title') || {}).textContent || '',
          text: (box.querySelector('.fb-empty-text') || {}).textContent || '',
          actions: [].map.call(box.querySelectorAll('.fb-empty-actions > *'), function (a) { return a.textContent; }),
          visible: r.width > 0 && r.height > 0};
})(%s)"""

SECTION_IN_VIEW = """(function (key) {
  var host = document.getElementById('app-inspector');
  var d = host.querySelector('.ins > details[data-section="' + key + '"]');
  if (!d || !d.open) return false;
  var s = d.querySelector('summary').getBoundingClientRect(), hr = host.getBoundingClientRect();
  var nav = host.querySelector('.ins-index'), top = nav ? nav.getBoundingClientRect().bottom : hr.top;
  return s.top >= top - 2 && s.bottom <= Math.min(hr.bottom, innerHeight) + 1;
})(%s)"""

# The badge click scrolls the drawer smoothly; wait for it to stop before the next click.
SCROLL_SETTLED = ("new Promise(function (res) { var el = document.getElementById('app-inspector'), a = el.scrollTop;"
                  " setTimeout(function () { res(el.scrollTop === a); }, 200); })")

DUPLICATES = {"revision": 1, "min_score": 0.5, "total": 3, "duplicates": [
    {"devices": [{"id": "foh-cl5", "name": "FOH CL5"}, {"id": "cl5-%d" % i, "name": "CL5 copy %d" % i, "manufacturer": "Yamaha", "model": "CL5"}],
     "score": 0.8, "confidence": "high", "suggested_survivor": "foh-cl5",
     "reasons": [{"text": "Same model", "weight": 0.4}]} for i in (1, 2, 3)]}


def q(s: str) -> str:
    return json.dumps(s)


class EntityStatesUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(EntityStatesUi, cls).setUpClass()
        cls.api("POST", "/api/v2/projects", {"name": "empty-demo", "template": "blank"})
        rev = cls.api("GET", "/api/v2/projects/empty-demo")["revision"]
        rooms = [{"op": "put", "coll": "rooms", "id": rid, "value": {"id": rid, "venue": "main", "name": name}}
                 for rid, name in (("store", "Store room"), ("annex", "Annex"))]
        device = {"op": "put", "coll": "devices", "id": "bare-box",
                  "value": {"id": "bare-box", "name": "Bare Box", "kind": "other", "room": "store"}}
        cls.api("POST", "/api/v2/projects/empty-demo/changes", {"base_revision": rev, "ops": rooms + [device]})
        cls.api("POST", "/api/v2/projects", {"name": "roomless-demo", "template": "blank"})
        got = cls.api("GET", "/api/v2/projects/roomless-demo")
        doc = got["doc"]
        doc["rooms"], doc["venues"] = [], []
        cls.api("PUT", "/api/v2/projects/roomless-demo", {"doc": doc, "base_revision": got["revision"]})

    @classmethod
    def api(cls, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cls.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Fathom": "1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode() or "null")

    def as_viewer(self, project: str):
        body = self.api("GET", "/api/v2/projects/" + project)
        body["role"] = "viewer"
        return [("/api/v2/projects/" + project, 200, body, "GET")]

    def no_errors(self, pg) -> None:
        self.assertEqual(pg.smoke["errors"], [])
        self.assertEqual(pg.js("window.__fathomErrors || []"), [])

    def empty(self, pg, scope: str):
        return pg.wait_for(EMPTY % q(scope))

    # ------------------------------------------------------------ skeleton

    def test_first_render_shows_a_page_skeleton_then_the_content(self):
        cases = ((C + "devices/foh-cl5/ports", "devices", ".pd-body tr.dt-row"),
                 (C + "rooms/main/overview", "rooms", ".pr-card"),
                 (C + "devices", "devices", ".pd-landing tr.dt-row"))
        for url, view, content in cases:
            with self.subTest(url=url), self.open(url, "m") as pg:
                pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": SKELETON_SPY})
                pg.reload()
                pg.wait_for("!!document.querySelector(%s)" % q(content))
                seen = pg.js("window.__skel")
                self.assertEqual(len(seen), 1, seen)
                self.assertEqual(seen[0]["view"], view)
                self.assertEqual(seen[0]["busy"], "true")
                self.assertEqual(seen[0]["kind"], "table" if url.endswith("/devices") else "page")
                self.assertEqual(pg.js("document.querySelectorAll('.app-view .fb-skeleton, .app-view [aria-busy=true]').length"), 0,
                                 "the skeleton is replaced, not left behind")
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.no_errors(pg)

    # ------------------------------------------------------------ device page

    def test_device_tabs_empty_copy_and_actions(self):
        want = {
            "ports": ("Bare Box has no ports yet.", ["Add ports"]),
            "cables": ("No cables connected to Bare Box.", ["Open in patch view"]),
            "network": ("No interfaces on Bare Box.", ["Add interface"]),
            "inventory": ("No inventory details for Bare Box.", ["Add inventory details"]),
            "procedures": ("No procedures mention Bare Box yet.", ["New procedure"]),
            "files": ("No photos or documents for Bare Box.", ["Upload files"]),
        }
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(E + "store/devices/bare-box/ports", size) as pg:
                for tab, (title, actions) in want.items():
                    pg.goto(E + "store/devices/bare-box/" + tab)
                    pg.wait_for("!!document.querySelector('.eh-tab[data-tab=%s][aria-selected=true]')" % tab)
                    st = self.empty(pg, ".pd-body[data-tab=%s]" % tab)
                    self.assertEqual(st["title"], title, tab)
                    self.assertEqual(st["actions"], actions, tab)
                    self.assertTrue(st["visible"], tab)
                    self.assertLessEqual(pg.page_hscroll(), 0, "%s at %s scrolls horizontally" % (tab, size))
                    pg.shot("st-device-%s-%s" % (tab, size))
                pg.goto(E + "store/devices/bare-box/network")
                self.assertEqual(self.empty(pg, ".pd-body[data-tab=network]")["text"], "Add one in the inspector\u2019s Network section.")
                pg.click(".pd-body .fb-empty-action")
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("location.hash.indexOf('sec=net') > 0")
                self.assertTrue(pg.hash.startswith(E + "store/devices/bare-box/network?"), pg.hash)
                pg.wait_for(SECTION_IN_VIEW % q("net"))
                pg.press("Escape")
                pg.goto(E + "store/devices/bare-box/procedures")
                self.empty(pg, ".pd-body[data-tab=procedures]")
                self.assertEqual(pg.js("document.querySelector('.pd-body .fb-empty-action').getAttribute('href')"),
                                 E + "store/sop?new=1&device=bare-box")
                pg.goto(E + "store/devices/bare-box/cables")
                self.empty(pg, ".pd-body[data-tab=cables]")
                pg.click(".pd-body .fb-empty-action")
                pg.wait_for("location.hash.indexOf('/patch?') > 0")
                self.assertIn("sel=device:bare-box", pg.hash)
                self.assertEqual("drawer=0" in pg.hash, size != "d", "the canvas stays clear below lg")
                self.no_errors(pg)

    def test_device_landing_empty(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(E + "main/devices", size) as pg:
                st = self.empty(pg, ".pd-landing")
                self.assertEqual(st["title"], "No devices in Main room yet.")
                self.assertEqual(st["actions"], ["Add device", "Bulk add"])
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("st-device-landing-" + size)
                self.no_errors(pg)

    def test_unknown_device_inline_error_and_back_link(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(C + "devices/no-such-box/ports", size) as pg:
                pg.wait_for("!!document.querySelector('.pd-notfound.fb-error[role=alert]')")
                self.assertIn("Device \u201cno-such-box\u201d not found", pg.js("document.querySelector('.pd-notfound').textContent"))
                self.assertFalse(pg.js("!!document.querySelector('header.eh')"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("st-device-notfound-" + size)
                pg.click("a.pd-back")
                pg.wait_for("location.hash === %s" % q(C + "devices"))
                pg.wait_for("document.querySelectorAll('.pd-landing tr.dt-row').length === 49")
                self.no_errors(pg)

    # ------------------------------------------------------------ room page

    def test_room_tabs_empty_copy_and_actions(self):
        want = {
            "devices": ("No devices in Main room yet.", ["Add device", "Bulk add"]),
            "cables": ("No cables in Main room yet.", ["Open patch view"]),
            "racks": ("No racks in Main room.", ["Add rack"]),
            "plans": ("No floor plan for Main room.", ["Upload a plan"]),
            "procedures": ("No procedures apply to Main room yet.", ["New procedure"]),
        }
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(E + "main/rooms/main/overview", size) as pg:
                for tab, (title, actions) in want.items():
                    pg.goto(E + "main/rooms/main/" + tab)
                    st = self.empty(pg, ".pr-panel[data-tab=%s]" % tab)
                    self.assertEqual(st["title"], title, tab)
                    self.assertEqual(st["actions"], actions, tab)
                    self.assertLessEqual(pg.page_hscroll(), 0, "%s at %s scrolls horizontally" % (tab, size))
                    pg.shot("st-room-%s-%s" % (tab, size))
                self.assertEqual(pg.js("document.querySelector('.pr-panel .fb-empty-action').getAttribute('href')"), E + "main/sop?new=1")
                self.no_errors(pg)

    def test_add_rack_from_the_empty_racks_tab(self):
        with self.open(E + "annex/rooms/annex/racks", "d") as pg:
            st = self.empty(pg, ".pr-panel[data-tab=racks]")
            self.assertEqual(st["title"], "No racks in Annex.")
            pg.click(".pr-panel .fb-empty-action")
            pg.wait_for("!!document.querySelector('.app-dialog input')")
            pg.js("(function (i) { i.value = 'Floor rack'; i.dispatchEvent(new Event('input', {bubbles: true})); })(document.querySelector('.app-dialog input'))")
            pg.click(".app-dialog button.primary")
            pg.wait_for("location.hash.indexOf('/racks/rk-floor-rack') > 0")
            self.assertTrue(pg.hash.startswith(E + "annex/racks/rk-floor-rack"), pg.hash)
            self.no_errors(pg)

    def test_rooms_landing_empty(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open("#/roomless-demo/*/rooms", size) as pg:
                st = self.empty(pg, ".pr-landing")
                self.assertEqual(st["title"], "No rooms yet.")
                self.assertEqual(st["actions"], ["Add a room", "Import a spreadsheet"])
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("st-rooms-landing-" + size)
                self.no_errors(pg)

    def test_unknown_room_inline_error_and_back_link(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(C + "rooms/nowhere/cables", size) as pg:
                pg.wait_for("!!document.querySelector('.pr-notfound .fb-error[role=alert]')")
                self.assertIn("Room \u201cnowhere\u201d not found", pg.js("document.querySelector('.pr-notfound').textContent"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("st-room-notfound-" + size)
                pg.click("a.pr-back")
                pg.wait_for("location.hash === %s" % q(C + "rooms"))
                pg.wait_for("document.querySelectorAll('.dt-root[data-table=rooms] tbody tr.dt-row').length === 3")
                self.no_errors(pg)

    # ------------------------------------------------------------ viewer

    def test_viewer_gets_no_write_actions(self):
        with self.open(E + "store/devices/bare-box/ports", "m", intercepts=self.as_viewer("empty-demo")) as pg:
            for tab in ("ports", "network", "inventory", "procedures", "files"):
                pg.goto(E + "store/devices/bare-box/" + tab)
                st = self.empty(pg, ".pd-body[data-tab=%s]" % tab)
                self.assertEqual(st["actions"], [], tab)
                self.assertTrue(st["text"], tab)
            pg.goto(E + "store/devices/bare-box/cables")
            self.assertEqual(self.empty(pg, ".pd-body[data-tab=cables]")["actions"], ["Open in patch view"], "navigation stays")
            pg.shot("st-device-viewer-m")
            pg.goto(E + "main/devices")
            self.assertEqual(self.empty(pg, ".pd-landing")["actions"], [])
            for tab in ("devices", "racks", "plans", "procedures"):
                pg.goto(E + "main/rooms/main/" + tab)
                st = self.empty(pg, ".pr-panel[data-tab=%s]" % tab)
                self.assertEqual(st["actions"], [], tab)
            pg.goto(E + "main/rooms/main/cables")
            self.assertEqual(self.empty(pg, ".pr-panel[data-tab=cables]")["actions"], ["Open patch view"])
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.no_errors(pg)

    # ------------------------------------------------------------ inspector

    def campus_with_reports(self):
        body = self.api("GET", "/api/v2/projects/campus-demo")
        body["doc"]["problems"] = [
            {"id": "pr-00000001", "device": "foh-cl5", "text": "Fader 3 sticks", "status": "open", "created": "2026-10-20T10:00:00Z", "via": "app"},
            {"id": "pr-00000002", "device": "foh-cl5", "text": "Scribble strip dark", "status": "open", "created": "2026-10-21T10:00:00Z", "via": "app"},
            {"id": "pr-00000003", "device": "foh-cl5", "text": "Old", "status": "resolved", "created": "2026-10-01T10:00:00Z", "via": "app"},
        ]
        return [("/api/v2/projects/campus-demo", 200, body, "GET")]

    def test_inspector_review_badges_jump_to_their_sections(self):
        for size in ("d", "t", "m"):
            rules = self.campus_with_reports() + [("/api/v2/projects/campus-demo/devices/duplicates*", 200, DUPLICATES, "GET")]
            with self.subTest(size=size), self.open(C + "patch?sel=device:foh-cl5", size, intercepts=rules) as pg:
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("!!document.querySelector('#app-inspector .ins-badges [data-badge=dups]')")
                badges = pg.js("[].map.call(document.querySelectorAll('#app-inspector .ins-head .ins-badges .fb-review'), function (b) {"
                               " return [b.getAttribute('data-badge'), b.querySelector('.fb-review-label').textContent]; })")
                self.assertEqual(badges, [["problems", "2 open problems"], ["dups", "3 possible duplicates"]])
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.offscreen("#app-inspector button", "x"), 0)
                pg.shot("st-ins-badges-" + size)
                pg.click("#app-inspector [data-badge=problems]")
                pg.wait_for("location.hash.indexOf('sec=problems') > 0")
                pg.wait_for(SECTION_IN_VIEW % q("problems"))
                self.assertEqual(pg.js("document.activeElement.parentElement.getAttribute('data-section')"), "problems")
                self.assertEqual(pg.js("document.querySelectorAll('#app-inspector .ins-problems li.open').length"), 2)
                pg.wait_for(SCROLL_SETTLED)
                pg.js("document.getElementById('app-inspector').scrollTop = 0; 1")
                pg.wait_for(SCROLL_SETTLED)
                pg.click("#app-inspector [data-badge=dups]")
                pg.wait_for("location.hash.indexOf('sec=dups') > 0")
                pg.wait_for(SECTION_IN_VIEW % q("dups"))
                pg.wait_for("document.querySelectorAll('#app-inspector [data-section=dups] .mg-hint').length === 3")
                self.no_errors(pg)
        with self.open(C + "patch?sel=device:rio-sl", "d") as pg:
            pg.wait_for(DRAWER_OPEN)
            pg.wait_for("!!document.querySelector('#app-inspector [data-section=dups] .mg-hints')")
            self.assertEqual(pg.js("document.querySelectorAll('#app-inspector .ins-badges > *').length"), 0, "no badge at 0")

    def test_inspector_duplicates_error_and_retry(self):
        rules = [("/api/v2/projects/campus-demo/devices/duplicates*", 500, {"error": "boom", "code": "internal"}, "GET")]
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(C + "patch?sel=device:foh-cl5&sec=dups", size, intercepts=rules) as pg:
                pg.wait_for(DRAWER_OPEN)
                pg.wait_for("!!document.querySelector('#app-inspector .ins-dups-error.fb-error[role=alert]')")
                self.assertIn("Could not check for duplicates: boom", pg.js("document.querySelector('#app-inspector .ins-dups-error').textContent"))
                self.assertFalse(pg.js("!!document.querySelector('#app-inspector [data-badge=dups]')"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("st-ins-dups-error-" + size)
                pg.rules = [r for r in pg.rules if "duplicates" not in r["glob"]]
                pg.intercept("/api/v2/projects/campus-demo/devices/duplicates*", 200, DUPLICATES, "GET")
                pg.click("#app-inspector .ins-dups-error .fb-retry")
                pg.wait_for("document.querySelectorAll('#app-inspector [data-section=dups] .mg-hint').length === 3")
                pg.wait_for("!!document.querySelector('#app-inspector [data-badge=dups]')")
                self.assertFalse(pg.js("!!document.querySelector('#app-inspector .ins-dups-error')"))
                self.no_errors(pg)


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
