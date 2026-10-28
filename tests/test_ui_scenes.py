"""SCN: the scene bar, its dialogs and the read-only scene preview (SPEC §6.4, §6.15; FR-SCN, P3B).

Drives the real app on a ``tests/_ui.py`` server. The server on this branch has no scene routes (they
are P3A's), so every ``/api/v2/projects/<n>/scenes…`` call is answered by the harness intercept with the
contract payloads; the scenes themselves are seeded into a project doc through ``PUT`` (``normalize``
keeps ``scenes[]`` and ``settings.scene``), so the chip and the live doc are real. Request bodies are
read through a ``fetch`` wrapper installed before the page boots. Skips without Chrome (set
``FATHOM_CHROME``). With ``FATHOM_UI_SHOTS`` set it writes bar, dialog and preview screenshots.
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

PROJECT = "scene-demo"
P = "#/%s/main/" % PROJECT
API = "/api/v2/projects/%s" % PROJECT
XMAS = "sc-aaaaaaaa"
EASTER = "sc-bbbbbbbb"

XMAS_DIFF = {"cables_added": 2, "cables_removed": 1, "cables_changed": 0, "devices_moved": 1, "markers_changed": 0}
XMAS_TEXT = "+2 cables \u00b7 \u22121 cable \u00b7 1 device moved"
NONE = {"cables_added": 0, "cables_removed": 0, "cables_changed": 0, "devices_moved": 0, "markers_changed": 0}

SCENE_ROWS = [
    {"id": XMAS, "name": "Christmas", "note": "Extra choir mics", "base": False, "created": "2026-10-01T00:00:00Z", "by": "sam",
     "updated": "2026-10-01T00:00:00Z", "data": {"cables": [], "bundles": [], "markers": {}, "devices": {}}},
    {"id": EASTER, "name": "Easter", "note": "", "base": False, "created": "2026-10-02T00:00:00Z", "by": "sam",
     "updated": "2026-10-02T00:00:00Z", "data": {"cables": [], "bundles": [], "markers": {}, "devices": {}}},
]


def scene_list(active: str = XMAS, scenes: bool = True, revision: int = 2):
    rows = [{"id": "base", "name": "Base", "note": "", "base": True, "active": active == "base", "created": "", "by": "", "updated": "",
             "diff": NONE, "text": "No differences"}]
    if scenes:
        rows.append({"id": XMAS, "name": "Christmas", "note": "Extra choir mics", "base": False, "active": active == XMAS, "created": "2026-10-01T00:00:00Z",
                     "by": "sam", "updated": "2026-10-01T00:00:00Z", "diff": XMAS_DIFF, "text": XMAS_TEXT})
        rows.append({"id": EASTER, "name": "Easter", "note": "", "base": False, "active": active == EASTER, "created": "2026-10-02T00:00:00Z",
                     "by": "sam", "updated": "2026-10-02T00:00:00Z", "diff": NONE, "text": "No differences"})
    return {"scenes": rows, "active": active, "revision": revision}


def xmas_diff(doc):
    cables = doc.get("cables") or []
    dev = (doc.get("devices") or [{"id": "x"}])[0]
    a, b, c = cables[0], cables[1], cables[2]
    return {
        "cables": {
            "added": [dict(a, tag="XM-01"), dict(b, tag="XM-02")],
            "removed": [c],
            "changed": [],
        },
        "bundles": {"added": [], "removed": [], "changed": []},
        "devices": {"moved": [{"id": dev["id"], "before": {"room": "main", "patch": {"x": 10, "y": 20}}, "after": {"room": "main", "patch": {"x": 300, "y": 20}}, "fields": ["patch"]}]},
        "markers": {"added": [], "removed": [], "moved": []},
        "summary": XMAS_DIFF, "text": XMAS_TEXT,
    }


# fetch wrapper (installed before boot): records scene requests so tests can read their bodies
RECORD_FETCH = """
(function () {
  var orig = window.fetch;
  window.__reqs = [];
  window.fetch = function (url, init) {
    var u = String(url);
    if (u.indexOf('/scenes') >= 0) window.__reqs.push({url: u, method: (init && init.method) || 'GET', body: init && typeof init.body === 'string' ? init.body : null});
    return orig.apply(this, arguments);
  };
})();
"""

VISIBLE = """(function (sel) {
  return Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }).length;
})(%s)"""

TOAST = "Array.prototype.some.call(document.querySelectorAll('.app-toast'), function (t) { return t.textContent.indexOf(%s) >= 0; })"
OPTIONS = "Array.prototype.map.call(document.querySelectorAll('#app-scene-select option'), function (o) { return o.textContent; })"
MENU_IDS = "Array.prototype.map.call(document.querySelectorAll('.app-scenes-menu button'), function (b) { return b.id; })"


def api(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"X-Fathom": "1", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else None


def visible(pg, selector: str) -> int:
    return int(pg.js(VISIBLE % json.dumps(selector)))


def view_ready(pg, view: str, timeout: float = 20.0) -> None:
    pg.wait_for("""(function (v) {
      var el = document.querySelector('#app-main > .app-view');
      return !!el && el.getAttribute('data-view') === v && !el.querySelector('.app-loading');
    })(%s)""" % json.dumps(view), timeout)


def bar_ready(pg) -> None:
    pg.wait_for("!document.getElementById('app-scenes').hidden && document.querySelectorAll('#app-scene-select option').length >= 1", 15)


class ScenesUi(UiCase):
    doc = None  # type: dict

    @classmethod
    def setUpClass(cls) -> None:
        super(ScenesUi, cls).setUpClass()
        try:
            api(cls.base, "POST", "/api/v2/projects", {"name": PROJECT, "template": "campus-demo", "org": "Scenes"})
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
        cur = api(cls.base, "GET", API)
        doc = cur["doc"]
        doc["scenes"] = copy.deepcopy(SCENE_ROWS)
        doc["settings"]["scene"] = XMAS
        api(cls.base, "PUT", API, {"doc": doc, "base_revision": cur["revision"], "summary": "seed scenes"})
        cls.doc = api(cls.base, "GET", API)["doc"]
        assert [s["id"] for s in cls.doc.get("scenes", [])] == [XMAS, EASTER], "normalize keeps scenes[]"
        assert cls.doc["settings"].get("scene") == XMAS, "normalize keeps settings.scene"

    # -------------------------------------------------------------- helpers

    def preview_doc(self, scene: str):
        """The /doc stub: the live project without any cables, so the patch view visibly changes."""
        d = copy.deepcopy(self.doc)
        d["cables"] = []
        d["bundles"] = []
        return {"doc": d, "scene": scene, "revision": 2}

    def stubs(self, active: str = XMAS, scenes: bool = True):
        return [
            (API + "/scenes", 200, scene_list(active, scenes), "GET"),
            (API + "/scenes/" + XMAS + "/diff*", 200, xmas_diff(self.doc), "GET"),
            (API + "/scenes/" + EASTER + "/diff*", 200, {"cables": {"added": [], "removed": [], "changed": []}, "bundles": {"added": [], "removed": [], "changed": []},
                                                        "devices": {"moved": []}, "markers": {"added": [], "removed": [], "moved": []}, "summary": NONE, "text": "No differences"}, "GET"),
            (API + "/scenes/" + EASTER + "/doc", 200, self.preview_doc(EASTER), "GET"),
            (API + "/scenes/base/doc", 200, self.preview_doc("base"), "GET"),
        ]

    def open_bar(self, path: str, size: str, intercepts=None, record: bool = False):
        """The app at ``path`` with the scene stubs; ``record`` installs the fetch recorder and reloads."""
        cm = self.open(path, size, intercepts=self.stubs() if intercepts is None else intercepts)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        if record:
            pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": RECORD_FETCH})
            pg.reload()
        return pg

    def open_menu(self, pg) -> list:
        pg.click("#app-scene-menu")
        pg.wait_for("!!document.querySelector('.app-scenes-menu')")
        return pg.js(MENU_IDS)

    def close_menu(self, pg) -> None:
        pg.press("Escape")
        pg.wait_for("!document.querySelector('.app-scenes-menu')")

    def select_scene(self, pg, sid: str) -> None:
        pg.js("var s = document.getElementById('app-scene-select'); s.value = %s; s.dispatchEvent(new Event('change', {bubbles: true})); 1" % json.dumps(sid))

    # ---------------------------------------------------------------- tests

    def test_bar_lists_base_and_scenes_with_diff_text(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.open_bar(P + "patch", size)
                view_ready(pg, "patch")
                bar_ready(pg)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js(OPTIONS), ["Base", "Christmas \u2014 " + XMAS_TEXT, "Easter \u2014 No differences"])
                self.assertEqual(pg.js("document.getElementById('app-scene-select').value"), XMAS, "the active scene is selected")
                self.assertEqual(pg.js("document.querySelector('.app-scene-chip').textContent"), "Scene Christmas")
                self.assertTrue(visible(pg, ".app-scene-chip"), "the tinted chip shows while a named scene is active")
                order = pg.js("Array.prototype.map.call(document.getElementById('app').children, function (c) { return c.id; })")
                self.assertEqual(order, ["app-banner", "app-top", "app-lock", "app-preview", "app-views", "app-subnav", "app-scenes", "app-body", "app-selbar", "app-tabbar"])
                sub = pg.rect("#app-subnav")
                bar = pg.rect("#app-scenes")
                self.assertGreaterEqual(bar["top"], sub["bottom"] - 1, "the bar sits under the sub-nav")
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.js("getComputedStyle(document.getElementById('app-scenes')).overflowX"), "auto", "the bar scrolls sideways instead of the page")
                if size == "m":
                    self.assertGreaterEqual(bar["height"], 44, "44 px bar under a coarse pointer")
                    self.assertGreaterEqual(pg.rect("#app-scene-select")["height"], 44)
                    self.assertGreaterEqual(pg.rect("#app-scene-menu")["height"], 44)
                    self.assertGreaterEqual(pg.rect("#app-scene-menu")["width"], 44)
                else:
                    self.assertAlmostEqual(bar["height"], 36, delta=1)
                pg.shot("scenes-bar-" + size)
                # the bar follows the user to the other listed views and leaves on the rest
                pg.goto(P + "table")
                view_ready(pg, "table")
                bar_ready(pg)
                pg.goto(P + "inventory")
                view_ready(pg, "inventory")
                pg.wait_for("document.getElementById('app-scenes').hidden")
                pg.goto(P + "plan")
                view_ready(pg, "plan")
                bar_ready(pg)
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_editor_menu_and_select_activates(self) -> None:
        pg = self.open_bar(P + "patch", "d", record=True)
        view_ready(pg, "patch")
        bar_ready(pg)
        ids = self.open_menu(pg)
        self.assertEqual(ids, ["app-scene-new", "app-scene-save", "app-scene-rename", "app-scene-delete", "app-scene-compare", "app-scene-preview"])
        self.assertEqual(pg.js("document.getElementById('app-scene-save').textContent"), "Save current state into Christmas")
        self.close_menu(pg)
        act = pg.intercept(API + "/scenes/" + EASTER + "/activate", 200, {"active": EASTER, "from": XMAS, "diff": {"summary": NONE, "text": "No differences"}, "revision": 3}, "POST")
        self.select_scene(pg, EASTER)
        pg.wait_for(TOAST % json.dumps("Switched to Easter"), 10)
        self.assertEqual(act["hits"], 1)
        reqs = pg.js("window.__reqs")
        posts = [r for r in reqs if r["method"] == "POST"]
        self.assertTrue(posts and posts[-1]["url"].endswith("/scenes/%s/activate" % EASTER), posts)
        self.assertTrue(any(r["method"] == "GET" and r["url"].endswith("/scenes") for r in reqs), "the list is re-read after the switch")
        # the rename dialog patches name + note
        self.open_menu(pg)
        pg.click("#app-scene-rename")
        pg.wait_for("!!document.getElementById('scn-name')")
        self.assertEqual(pg.js("document.getElementById('scn-name').value"), "Christmas")
        patched = pg.intercept(API + "/scenes/" + XMAS, 200, {"scene": dict(SCENE_ROWS[0], name="Xmas"), "revision": 4}, "PATCH")
        pg.js("document.getElementById('scn-name').value = 'Xmas'; document.getElementById('scn-note').value = 'choir'; 1")
        pg.click(".app-dialog footer button.primary")
        pg.wait_for(TOAST % json.dumps("Renamed to Xmas"), 10)
        self.assertEqual(patched["hits"], 1)
        body = json.loads([r for r in pg.js("window.__reqs") if r["method"] == "PATCH"][-1]["body"])
        self.assertEqual(body, {"name": "Xmas", "note": "choir"})
        # save current state into the active scene
        self.open_menu(pg)
        saved = pg.intercept(API + "/scenes/" + XMAS + "/save", 200, {"scene": SCENE_ROWS[0], "revision": 5}, "POST")
        pg.click("#app-scene-save")
        pg.wait_for(TOAST % json.dumps("Saved the current state into Christmas"), 10)
        self.assertEqual(saved["hits"], 1)
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_new_scene_dialog_posts_body(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.open_bar(P + "patch", size, record=True)
                view_ready(pg, "patch")
                bar_ready(pg)
                self.open_menu(pg)
                pg.click("#app-scene-new")
                pg.wait_for("!!document.getElementById('scn-name')")
                self.assertEqual(pg.js("document.querySelector('.app-dialog h2').textContent"), "New scene")
                self.assertTrue(pg.js("document.getElementById('scn-activate').checked"), "Switch to it now is on by default")
                froms = pg.js("Array.prototype.map.call(document.querySelectorAll('#scn-from option'), function (o) { return o.textContent; })")
                self.assertEqual(froms, ["Current state", "Copy of Base", "Copy of Christmas", "Copy of Easter"])
                if size == "m":
                    dlg = pg.rect(".app-dialog")
                    self.assertGreaterEqual(dlg["width"], 380, "full-width sheet at 390 px")
                    self.assertGreaterEqual(dlg["bottom"], pg.js("window.innerHeight") - 1, "docked at the bottom")
                    self.assertGreaterEqual(pg.rect(".app-dialog footer button.primary")["height"], 44)
                    self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("scenes-new-" + size)
                # empty name is refused and the dialog stays
                pg.click(".app-dialog footer button.primary")
                pg.wait_for(TOAST % json.dumps("Give the scene a name"))
                self.assertTrue(pg.js("!!document.getElementById('scn-name')"))
                created = pg.intercept(API + "/scenes", 201, {"scene": dict(SCENE_ROWS[1], id="sc-cccccccc", name="Summer"), "revision": 6}, "POST")
                pg.js("document.getElementById('scn-name').value = 'Summer'; document.getElementById('scn-note').value = 'Outdoor stage';"
                      "document.getElementById('scn-from').value = %s; document.getElementById('scn-activate').checked = false; 1" % json.dumps(EASTER))
                pg.click(".app-dialog footer button.primary")
                pg.wait_for(TOAST % json.dumps("Created scene Summer"), 10)
                self.assertEqual(created["hits"], 1)
                post = [r for r in pg.js("window.__reqs") if r["method"] == "POST"][-1]
                self.assertTrue(post["url"].endswith("/scenes"), post)
                self.assertEqual(json.loads(post["body"]), {"name": "Summer", "note": "Outdoor stage", "activate": False, "copy_from": EASTER})
                self.assertFalse(pg.js("!!document.getElementById('scn-name')"), "dialog closed")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_compare_dialog_shows_rows(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.open_bar(P + "patch", size)
                view_ready(pg, "patch")
                bar_ready(pg)
                self.open_menu(pg)
                pg.click("#app-scene-compare")
                pg.wait_for("!!document.querySelector('.scn-diff')", 10)
                self.assertEqual(pg.js("document.querySelector('.app-dialog h2').textContent"), "Compare Christmas with Base")
                self.assertEqual(pg.js("document.querySelector('.scn-diff-text').textContent"), XMAS_TEXT)
                self.assertEqual(pg.js("document.querySelectorAll('.scn-row.add').length"), 2)
                self.assertEqual(pg.js("document.querySelectorAll('.scn-row.del').length"), 1)
                heads = pg.js("Array.prototype.map.call(document.querySelectorAll('.scn-sec h4'), function (x) { return x.textContent; })")
                self.assertEqual(heads, ["Cables added (2)", "Cables removed (1)", "Devices moved (1)"])
                self.assertIn("XM-01", pg.js("document.querySelector('.scn-row.add .scn-tag').textContent"))
                dev = self.doc["devices"][0]
                self.assertIn(dev.get("name") or dev["id"], pg.js("document.querySelector('.scn-col:nth-child(2) .scn-tag').textContent"))
                self.assertIn("10,20 \u2192 300,20", pg.js("document.querySelector('.scn-col:nth-child(2) .scn-ends').textContent"))
                labels = pg.js("Array.prototype.map.call(document.querySelectorAll('.app-dialog footer button'), function (b) { return b.textContent; })")
                self.assertEqual(labels, ["Close"], "no Switch for the scene that is already active")
                cols = pg.js("Array.prototype.map.call(document.querySelectorAll('.scn-col'), function (c) { var r = c.getBoundingClientRect(); return [r.left, r.top]; })")
                if size == "m":
                    self.assertGreater(cols[1][1], cols[0][1], "columns stack at sm")
                    self.assertAlmostEqual(cols[1][0], cols[0][0], delta=1)
                    self.assertLessEqual(pg.page_hscroll(), 0)
                else:
                    self.assertGreater(cols[1][0], cols[0][0], "two columns side by side")
                pg.shot("scenes-compare-" + size)
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.app-dialog')")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_preview_banner_read_only_and_deep_link(self) -> None:
        pg = self.open_bar(P + "patch", "d")
        view_ready(pg, "patch")
        bar_ready(pg)
        wires = pg.wait_for("window.__pvStats && window.__pvStats.wires")
        self.assertGreater(wires, 0)
        self.open_menu(pg)
        pg.click("#app-scene-preview")
        pg.wait_for("!!document.getElementById('scn-pick')")
        picks = pg.js("Array.prototype.map.call(document.querySelectorAll('#scn-pick option'), function (o) { return o.value; })")
        self.assertEqual(picks, ["base", EASTER], "the active scene is not offered")
        pg.js("document.getElementById('scn-pick').value = %s; 1" % json.dumps(EASTER))
        pg.click(".app-dialog footer button.primary")
        pg.wait_for("!document.getElementById('app-preview').hidden", 10)
        text = pg.js("document.getElementById('app-preview').textContent")
        self.assertIn("Previewing scene Easter", text)
        self.assertIn("read-only", text)
        self.assertTrue(pg.js("!!document.getElementById('app-preview-switch')"), "editors may switch from the banner")
        pg.wait_for("window.__pvStats && window.__pvStats.wires === 0", 10)
        self.assertTrue(pg.js("document.querySelector('#app-save').getAttribute('aria-label')").startswith("Preview"))
        self.assertIn("scene=" + EASTER, pg.hash)
        self.assertEqual(pg.js("document.getElementById('app-scene-select').value"), EASTER)
        self.assertTrue(pg.js("document.querySelector('.app-scene-chip').hidden"), "no active chip while previewing")
        self.assertTrue(pg.js("document.getElementById('app-undo').disabled"))
        ids = self.open_menu(pg)
        self.assertEqual(ids, ["app-scene-compare", "app-scene-switch", "app-scene-exit"])
        self.close_menu(pg)
        pg.shot("scenes-preview-d")
        # the preview survives a move to another listed view and ends on any other
        pg.goto(P + "table")
        view_ready(pg, "table")
        self.assertFalse(pg.js("document.getElementById('app-preview').hidden"))
        self.assertIn("scene=" + EASTER, pg.hash)
        pg.goto(P + "inventory")
        view_ready(pg, "inventory")
        pg.wait_for("document.getElementById('app-preview').hidden")
        self.assertNotIn("scene=", pg.hash)
        # deep link enters the preview on load; Exit preview restores the live doc
        pg.goto(P + "patch?scene=" + EASTER)
        view_ready(pg, "patch")
        pg.wait_for("!document.getElementById('app-preview').hidden", 10)
        pg.wait_for("window.__pvStats && window.__pvStats.wires === 0", 10)
        pg.click("#app-preview-exit")
        pg.wait_for("document.getElementById('app-preview').hidden")
        pg.wait_for("window.__pvStats && window.__pvStats.wires > 0", 10)
        self.assertNotIn("scene=", pg.hash)
        self.assertTrue(pg.js("document.querySelector('#app-save').getAttribute('aria-label')").startswith("Saved"))
        self.assertEqual(pg.js("document.getElementById('app-scene-select').value"), XMAS)
        # Switch to this scene from the banner: activate + reload ends the preview
        pg.goto(P + "patch?scene=" + EASTER)
        pg.wait_for("!document.getElementById('app-preview').hidden", 10)
        act = pg.intercept(API + "/scenes/" + EASTER + "/activate", 200, {"active": EASTER, "from": XMAS, "diff": {"summary": NONE, "text": "No differences"}, "revision": 3}, "POST")
        pg.click("#app-preview-switch")
        pg.wait_for(TOAST % json.dumps("Switched to Easter"), 10)
        pg.wait_for("document.getElementById('app-preview').hidden", 10)
        self.assertEqual(act["hits"], 1)
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_preview_on_phone_deep_link(self) -> None:
        pg = self.open_bar(P + "patch?scene=" + EASTER, "m")
        view_ready(pg, "patch")
        pg.wait_for("!document.getElementById('app-preview').hidden", 10)
        bar_ready(pg)
        self.assertIn("Previewing scene Easter", pg.js("document.getElementById('app-preview').textContent"))
        self.assertGreaterEqual(pg.rect("#app-preview-exit")["height"], 44)
        self.assertGreaterEqual(pg.rect("#app-preview-switch")["height"], 44)
        self.assertLessEqual(pg.page_hscroll(), 0)
        self.assertEqual(pg.offscreen("#app-preview button", "x"), 0)
        pg.shot("scenes-preview-m")
        pg.click("#app-preview-exit")
        pg.wait_for("document.getElementById('app-preview').hidden")
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_viewer_gets_preview_only_and_no_bar_without_scenes(self) -> None:
        live = api(self.base, "GET", API)
        viewer = dict(live, role="viewer")
        pg = self.open_bar(P + "patch", "d", intercepts=[(API, 200, viewer, "GET")] + self.stubs(), record=True)
        view_ready(pg, "patch")
        bar_ready(pg)
        ids = self.open_menu(pg)
        self.assertEqual(ids, ["app-scene-compare", "app-scene-preview"], "viewers get Compare and Preview only")
        self.close_menu(pg)
        self.select_scene(pg, EASTER)
        pg.wait_for("!document.getElementById('app-preview').hidden", 10)
        self.assertFalse(pg.js("!!document.getElementById('app-preview-switch')"), "viewers cannot switch")
        self.assertTrue(pg.js("!!document.getElementById('app-preview-exit')"))
        self.assertFalse(any(r["method"] == "POST" for r in pg.js("window.__reqs")), "a viewer's select change previews, it never activates")
        # the compare dialog offers no switch to viewers
        self.open_menu(pg)
        pg.click("#app-scene-compare")
        pg.wait_for("!!document.querySelector('.scn-diff')", 10)
        labels = pg.js("Array.prototype.map.call(document.querySelectorAll('.app-dialog footer button'), function (b) { return b.textContent; })")
        self.assertEqual(labels, ["Close"])
        pg.press("Escape")
        self.assertEqual(pg.js("window.__fathomErrors"), [])
        # a viewer on a project without scenes sees no bar at all
        pg2 = self.open_bar(P + "patch", "d", intercepts=[(API, 200, viewer, "GET"), (API + "/scenes", 200, scene_list("base", scenes=False), "GET")])
        view_ready(pg2, "patch")
        pg2.wait_for("!!document.getElementById('app-scenes')")
        pg2.js("new Promise(function (r) { setTimeout(r, 700); })")
        self.assertTrue(pg2.js("document.getElementById('app-scenes').hidden"))
        self.assertEqual(pg2.js("window.__fathomErrors"), [])
        # an editor on the same project still gets the bar (to create the first scene)
        pg3 = self.open_bar(P + "patch", "d", intercepts=[(API + "/scenes", 200, scene_list("base", scenes=False), "GET")])
        view_ready(pg3, "patch")
        bar_ready(pg3)
        self.assertEqual(pg3.js(OPTIONS), ["Base"])
        self.assertTrue(pg3.js("document.querySelector('.app-scene-chip').hidden"))
        ids = self.open_menu(pg3)
        self.assertEqual(ids, ["app-scene-new", "app-scene-compare", "app-scene-preview"])
        self.assertTrue(pg3.js("document.getElementById('app-scene-compare').disabled"))
        self.assertEqual(pg3.js("window.__fathomErrors"), [])

    def test_delete_scene_confirms_and_reloads(self) -> None:
        pg = self.open_bar(P + "patch", "d", record=True)
        view_ready(pg, "patch")
        bar_ready(pg)
        self.open_menu(pg)
        pg.click("#app-scene-delete")
        pg.wait_for("!!document.querySelector('.app-dialog')")
        self.assertIn('Delete scene "Christmas"?', pg.js("document.querySelector('.app-dialog .body').textContent"))
        pg.click(".app-dialog footer button:not(.danger)")  # Cancel
        pg.wait_for("!document.querySelector('.app-dialog')")
        self.assertFalse(any(r["method"] == "DELETE" for r in pg.js("window.__reqs")))
        self.open_menu(pg)
        pg.click("#app-scene-delete")
        pg.wait_for("!!document.querySelector('.app-dialog footer button.danger')")
        gone = pg.intercept(API + "/scenes/" + XMAS, 200, {"ok": True, "revision": 7, "active": "base"}, "DELETE")
        pg.click(".app-dialog footer button.danger")
        pg.wait_for(TOAST % json.dumps("Deleted scene Christmas"), 10)
        self.assertEqual(gone["hits"], 1)
        reqs = pg.js("window.__reqs")
        self.assertEqual(reqs[-1]["method"], "GET", reqs[-2:])
        self.assertTrue(reqs[-1]["url"].endswith("/scenes"), "the bar re-reads the list after the delete")
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_locked_server_shows_lock_toast(self) -> None:
        pg = self.open_bar(P + "patch", "d")
        view_ready(pg, "patch")
        bar_ready(pg)
        pg.intercept(API + "/scenes/" + EASTER + "/activate", 423, {"error": "locked", "code": "locked", "details": {"locked_by": "sam"}}, "POST")
        self.select_scene(pg, EASTER)
        pg.wait_for(TOAST % json.dumps("Editing is locked"), 10)
        self.assertEqual(pg.js("document.getElementById('app-scene-select').value"), XMAS, "the select falls back to the active scene")
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_server_without_scenes_hides_bar(self) -> None:
        with self.open("#/campus-demo/main/patch", "d") as pg:  # the real server: GET …/scenes is 404
            view_ready(pg, "patch")
            pg.wait_for("!!document.getElementById('app-scenes')")
            pg.js("new Promise(function (r) { setTimeout(r, 700); })")
            self.assertTrue(pg.js("document.getElementById('app-scenes').hidden"))
            self.assertTrue(pg.js("document.getElementById('app-preview').hidden"))
            self.assertEqual(pg.smoke["errors"], [])
            pg.click("#app-user")
            pg.wait_for("!!document.getElementById('app-menu-scenes')")
            self.assertFalse(pg.js("document.getElementById('app-menu-scenes').disabled"))
            pg.click("#app-menu-scenes")
            pg.wait_for(TOAST % json.dumps("Scenes need a server with scene support"), 10)
            self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_user_menu_scenes_opens_actions(self) -> None:
        pg = self.open_bar(P + "inventory", "d")
        view_ready(pg, "inventory")
        pg.click("#app-user")
        pg.wait_for("!!document.getElementById('app-menu-scenes')")
        pg.click("#app-menu-scenes")
        view_ready(pg, "patch")
        pg.wait_for("!!document.querySelector('.app-scenes-menu')", 10)
        self.assertIn("app-scene-new", pg.js(MENU_IDS))
        self.close_menu(pg)
        self.assertEqual(pg.js("window.__fathomErrors"), [])
