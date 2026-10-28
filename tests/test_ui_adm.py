"""ADM: Imports, History, Builds and Settings in the app (docs/ui-audit.md B.3 ADM, B.8).

Settings tabs and the history revision live in the URL, every list is a shared DataTable whose
search/sort/filter state is in the hash, ``?hl=<id>`` highlights a row, and role-gated settings tabs
are hidden. Runs at the three ``SIZES``; skips without Chrome. ``FATHOM_UI_SHOTS`` collects
``<view>-<size>.png`` screenshots.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

P = "#/campus-demo/main/"
SIZES3 = ("d", "t", "m")
ALL_TABS = ["project", "rooms", "systems", "locations", "networks", "templates", "users", "invites", "backups", "sharing", "suggestions", "assistant", "offline", "trash"]
TRASH_ITEMS = {"items": [
    {"name": "chapel-2024", "trashed_at": "2026-10-27T09:12:00Z", "trashed_by": "admin", "rooms": 1, "devices": 18},
    {"name": "old-broadcast", "trashed_at": "2026-10-21T16:40:00Z", "trashed_by": "jordan", "rooms": 2, "devices": 41},
], "retention_days": 30}
# P2C: the invite and suggestion endpoints belong to the P2A backend; the UI is exercised against stubs.
INVITE_OLD = {"token": "inv-old0000000000", "role": "viewer", "projects": {}, "created_by": "admin", "created": "2026-10-20T10:00:00Z",
              "expires": "2026-10-27T10:00:00Z", "note": "front desk"}
INVITE_NEW = {"token": "inv-new0000000000", "role": "editor", "projects": {"campus-demo": "viewer"}, "created_by": "admin",
              "created": "2026-10-28T10:00:00Z", "expires": "2026-10-31T10:00:00Z", "note": "Jordan", "url": "/invite/inv-new0000000000"}
SUGGESTIONS = {"problems": [
    {"id": "pr-0000a001", "kind": "suggestion", "text": "Add a Dante name column to the patch table", "by": "jordan", "created": "2026-10-27T09:12:00Z",
     "status": "open", "device": "foh-cl5", "device_name": "FOH CL5", "via": "app"},
    {"id": "pr-0000a002", "kind": "suggestion", "text": "Link the power-up page from the lobby QR", "by": "sam", "created": "2026-10-21T16:40:00Z",
     "status": "resolved", "resolved": "2026-10-22T08:00:00Z", "resolved_by": "admin", "page": "power-up", "page_title": "Power up", "via": "app"},
    {"id": "pr-0000a003", "kind": "problem", "text": "Hum on the lectern mic", "by": "pat", "created": "2026-10-26T09:00:00Z", "status": "open", "via": "app"},
], "open": 2, "revision": 3}
SUGGESTIONS_ALL = {"items": [
    {"project": "sunday-demo", "id": "pr-0000b001", "kind": "suggestion", "text": "Rename the stage box", "by": "lee", "created": "2026-10-25T12:00:00Z", "status": "open"},
    {"project": "campus-demo", "id": "pr-0000a001", "kind": "suggestion", "text": "Add a Dante name column to the patch table", "by": "jordan",
     "created": "2026-10-27T09:12:00Z", "status": "open", "device": "foh-cl5", "device_name": "FOH CL5"},
]}


# P4C: the language-model endpoints belong to the P4A backend; Settings › Assistant is exercised against stubs.
LLM_PROVIDERS = {"providers": [
    {"id": "openai", "label": "OpenAI", "default_base_url": "https://api.openai.com/v1", "needs_key": True, "lists_models": True},
    {"id": "anthropic", "label": "Anthropic", "default_base_url": "https://api.anthropic.com", "needs_key": True, "lists_models": False},
    {"id": "xai", "label": "xAI Grok", "default_base_url": "https://api.x.ai/v1", "needs_key": True, "lists_models": True},
    {"id": "openai_compat", "label": "Local / OpenAI-compatible server", "default_base_url": "http://localhost:11434/v1", "needs_key": False, "lists_models": True,
     "presets": {"ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1", "vllm": "http://localhost:8000/v1", "llamacpp": "http://localhost:8080/v1"}},
]}
LLM_SETTINGS = {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api": "chat", "temperature": 0.2, "max_tokens": 700,
                "web_lookup": False, "daily_cap": 200, "api_key_set": True,
                "source": {"provider": "file", "base_url": "file", "model": "file", "api_key": "file", "api": "default", "temperature": "default"}}
# Records JSON request bodies (the harness intercept sees URLs, not bodies): window.__bodies = [{method, url, body}].
CAPTURE_BODIES = """(function () {
  var real = window.fetch;
  window.__bodies = [];
  window.fetch = function (u, o) {
    var s = String(u && u.url || u);
    if (s.indexOf('/api/') >= 0 && o && o.body && typeof o.body === 'string') window.__bodies.push({method: (o.method || 'GET').toUpperCase(), url: s, body: o.body});
    return real.apply(this, arguments);
  };
})();"""


def api_get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def seed_history(data: str) -> None:
    """Revision 1 in the history index (the sample ships without one) plus two edits (r2, r3)."""
    from fathom import history
    from fathom.project import apply_changes

    pdir = Path(data) / "projects" / "campus-demo"
    doc = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    if not history.has_history(pdir):
        history.record(pdir, int(doc.get("revision") or 1), [], doc, author="seed", summary="Sample project",
                       source="put", touched=set())
    rev = int(doc.get("revision") or 1)
    for i, name in enumerate(("Dante primary (edited)", "Dante primary")):
        res = apply_changes(pdir, [{"op": "merge", "coll": "networks", "id": "av-dante", "value": {"name": name}}],
                            base_revision=rev, author="tester", summary="Rename network %d" % (i + 1), source="changes")
        rev = res["revision"]


def import_dante_preset(base: str) -> None:
    """A Dante preset whose device the library knows (Yamaha Rio1608-D): the overlay gets a model suggestion."""
    preset = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><preset version=\"3.0.0\"><name>Stage</name>"
              "<device><name>Y004-Yamaha-Rio1608-STG</name><manufacturer_name>Yamaha Corporation</manufacturer_name>"
              "<model_name>Rio1608-D</model_name><ipv4_address>10.20.0.23</ipv4_address>"
              "<txchannel danteId=\"1\"><label>Stage 1</label></txchannel></device></preset>").encode("utf-8")
    boundary = "----fathomadm"
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"stage.xml\"\r\nContent-Type: text/xml\r\n\r\n" % boundary).encode()
            + preset + ("\r\n--%s--\r\n" % boundary).encode())
    req = urllib.request.Request(base + "/api/v2/projects/campus-demo/imports?kind=dante", data=body, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary, "X-Fathom": "1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 201, r.status


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Fathom": "1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode() or "{}")


def selected_tab(pg) -> str:
    return pg.js("(function () { var a = document.querySelector('.adm-tab[aria-selected=true]'); return a ? a.getAttribute('data-tab') : ''; })()")


def tabs(pg) -> list:
    return pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-tab'), function (a) { return a.getAttribute('data-tab'); })")


def set_value(pg, selector: str, value: str, event: str = "input") -> None:
    pg.wait_for("!!document.querySelector(%s)" % json.dumps(selector))
    pg.js("""(function (s, v, ev) {
      var el = document.querySelector(s); el.focus(); el.value = v;
      el.dispatchEvent(new Event(ev, {bubbles: true}));
      if (ev !== 'change') el.dispatchEvent(new Event('change', {bubbles: true}));
    })(%s, %s, %s)""" % (json.dumps(selector), json.dumps(value), json.dumps(event)))


class AdmUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(AdmUi, cls).setUpClass()
        seed_history(cls.server.data)
        import_dante_preset(cls.base)
        cls.build = post(cls.base, "/api/v2/projects/campus-demo/builds", {"pdf": False, "png": False})["build"]

    def revisions(self) -> list:
        with urllib.request.urlopen(self.base + "/api/v2/projects/campus-demo/history?limit=1000", timeout=30) as r:
            return [x["revision"] for x in json.loads(r.read().decode())["revisions"]]

    def view(self, pg, cls_name: str) -> None:
        pg.wait_for("!!document.querySelector('#app-main .adm.%s')" % cls_name)

    def rows(self, pg, scope: str = "#app-main") -> int:
        return pg.js("document.querySelectorAll(%s).length" % json.dumps(scope + " tr.dt-row"))

    # ------------------------------------------------------------------ settings

    def test_settings_tab_and_highlight_survive_reload_at_three_sizes(self):
        for size in SIZES3:
            with self.subTest(size=size), self.open(P + "settings/networks?hl=av-dante", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.view(pg, "adm-settings")
                pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=\"av-dante\"]')")
                self.assertEqual(selected_tab(pg), "networks")
                self.assertEqual(pg.js("document.querySelector('.adm-panel').getAttribute('data-tab')"), "networks")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("settings-" + size)
                pg.reload()
                self.view(pg, "adm-settings")
                pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=\"av-dante\"]')")
                self.assertEqual(selected_tab(pg), "networks")
                self.assertIn("/settings/networks", pg.hash)
                self.assertIn("hl=av-dante", pg.hash)
                self.assertLessEqual(pg.page_hscroll(), 0)

    def test_tab_click_writes_the_url_and_back_returns(self):
        with self.open(P + "settings", "d") as pg:
            self.view(pg, "adm-settings")
            self.assertEqual(selected_tab(pg), "project")
            self.assertEqual(tabs(pg), ALL_TABS)
            pg.click(".adm-tab[data-tab=rooms]")
            pg.wait_for("location.hash.indexOf('/settings/rooms') > 0")
            pg.wait_for("document.querySelector('.adm-panel').getAttribute('data-tab') === 'rooms'")
            self.assertEqual(selected_tab(pg), "rooms")
            self.assertEqual(pg.js("document.querySelectorAll('.adm-panel .dt-table').length"), 2)
            pg.js("history.back()")
            pg.wait_for("document.querySelector('.adm-panel').getAttribute('data-tab') === 'project'")
            self.assertEqual(selected_tab(pg), "project")

    def test_tab_keyboard_moves_focus(self):
        with self.open(P + "settings/systems", "d") as pg:
            self.view(pg, "adm-settings")
            pg.js("document.querySelector('.adm-tab[data-tab=systems]').focus()")
            pg.press("ArrowRight")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-tab')"), "locations")
            pg.press("Home")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-tab')"), "project")
            pg.press("Enter")
            pg.wait_for("location.hash.indexOf('/settings/project') > 0")

    def test_unknown_tab_falls_back_to_project(self):
        with self.open(P + "settings/bogus", "d") as pg:
            self.view(pg, "adm-settings")
            self.assertEqual(selected_tab(pg), "project")
            pg.wait_for("/\\/settings$/.test(location.hash.split('?')[0])")

    def test_settings_card_grid_is_one_column_at_sm(self):
        expect = {"d": 2, "t": 2, "m": 1}
        for size in SIZES3:
            with self.subTest(size=size), self.open(P + "settings/project", size) as pg:
                self.view(pg, "adm-settings")
                n = pg.js("getComputedStyle(document.querySelector('.adm-grid')).gridTemplateColumns.split(' ').length")
                self.assertEqual(n, expect[size])
                self.assertEqual(pg.js("document.querySelectorAll('.adm-grid > .adm-card[data-card=about], .adm-grid > .adm-card[data-card=preferences]').length"), 2)
                self.assertLessEqual(pg.page_hscroll(), 0)
            with self.subTest(size=size, tab="backups"), self.open(P + "settings/backups", size) as pg:
                self.view(pg, "adm-settings")
                n = pg.js("getComputedStyle(document.querySelector('.adm-grid')).gridTemplateColumns.split(' ').length")
                self.assertEqual(n, expect[size])
                self.assertLessEqual(pg.page_hscroll(), 0)

    def test_table_search_is_in_the_url_and_survives_reload(self):
        with self.open(P + "settings/networks", "d") as pg:
            self.view(pg, "adm-settings")
            pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 5")
            set_value(pg, ".adm-panel .dt-search", "sacn")
            pg.wait_for("location.hash.indexOf('q=sacn') > 0")
            pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 1")
            pg.reload()
            self.view(pg, "adm-settings")
            pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 1")
            self.assertEqual(pg.js("document.querySelector('.adm-panel .dt-search').value"), "sacn")
            self.assertEqual(selected_tab(pg), "networks")

    def test_inline_edit_still_commits(self):
        with self.open(P + "settings/networks", "d") as pg:
            self.view(pg, "adm-settings")
            sel = "tr.dt-row[data-id=mgmt] td[data-col=vlan] input"
            set_value(pg, sel, "99", "change")
            pg.js("document.activeElement.blur()")
            pg.wait_for("document.querySelector(%s).value === '99'" % json.dumps(sel))
            pg.reload()
            self.view(pg, "adm-settings")
            pg.wait_for("!!document.querySelector(%s) && document.querySelector(%s).value === '99'" % (json.dumps(sel), json.dumps(sel)))

    def test_every_list_is_a_datatable(self):
        cases = [("imports", "adm-imports"), ("history", "adm-history"), ("builds", "adm-builds")]
        cases += [("settings/" + t, "adm-settings") for t in ALL_TABS]
        for path, cls_name in cases:
            with self.subTest(path=path), self.open(P + path, "d") as pg:
                self.view(pg, cls_name)
                pg.wait_for("!document.querySelector('#app-main [aria-busy=true]')")
                self.assertEqual(pg.js("document.querySelectorAll('#app-main table:not(.dt-table)').length"), 0)
                self.assertEqual(pg.js("document.querySelectorAll('#app-main .adm-table').length"), 0)
                if path not in ("settings/project", "settings/offline", "settings/assistant"):
                    self.assertGreaterEqual(pg.js("document.querySelectorAll('#app-main .dt-table').length"), 1)
                self.assertEqual(pg.smoke["errors"], [])

    # --------------------------------------------------------------------- trash

    def test_trash_empty_state_names_the_retention(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/trash", size, intercepts=[("/api/v2/trash*", 200, {"items": [], "retention_days": 30}, "GET")]) as pg:
                self.view(pg, "adm-settings")
                self.assertEqual(selected_tab(pg), "trash")
                pg.wait_for("!!document.querySelector('.adm-panel .fb-empty')")
                text = pg.js("document.querySelector('.adm-panel .fb-empty').textContent")
                self.assertIn("Nothing in the trash.", text)
                self.assertIn("Deleted projects are kept for 30 days.", text)
                self.assertEqual(self.rows(pg), 0)
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.smoke["errors"], [])
                pg.shot("adm-trash-empty-%s" % size)

    def test_trash_lists_projects_with_restore_and_purge(self):
        with self.open(P + "settings/trash", "d", intercepts=[("/api/v2/trash*", 200, TRASH_ITEMS, "GET")]) as pg:
            self.view(pg, "adm-settings")
            pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 2")
            names = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel tr.dt-row td[data-col=name]'), function (td) { return td.textContent; })")
            self.assertEqual(sorted(names), ["chapel-2024", "old-broadcast"])
            cols = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
            self.assertEqual(cols, ["name", "trashed_at", "trashed_by", "rooms", "devices", "actions"])
            self.assertEqual(pg.js("document.querySelector('.adm-panel tr.dt-row[data-trash=chapel-2024] td[data-col=devices]').textContent"), "18")
            self.assertEqual(pg.js("document.querySelector('.adm-panel tr.dt-row[data-trash=old-broadcast] td[data-col=trashed_by]').textContent"), "jordan")
            acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel tr.dt-row[data-trash=chapel-2024] .adm-acts button'), function (b) { return [b.getAttribute('data-act'), b.textContent]; })")
            self.assertEqual(acts, [["restore", "Restore"], ["purge", "Delete permanently"]])
            pg.shot("adm-trash-d")

            # Delete permanently asks first; declining calls nothing
            purge = pg.intercept("/api/v2/trash/chapel-2024", 200, {"ok": True}, "DELETE")
            pg.click(".adm-panel tr.dt-row[data-trash=chapel-2024] .adm-acts button[data-act=purge]")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            body = pg.js("document.querySelector('.app-dialog .body').textContent")
            self.assertIn("chapel-2024", body)
            self.assertIn("for good", body)
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self.assertEqual(purge["hits"], 0)
            pg.click(".adm-panel tr.dt-row[data-trash=chapel-2024] .adm-acts button[data-act=purge]")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            pg.click(".app-dialog footer button:last-child")
            pg.wait_for("!document.querySelector('.app-dialog')")
            pg.wait_for("document.querySelectorAll('.app-toast').length > 0")
            self.assertEqual(purge["hits"], 1, "DELETE /api/v2/trash/<name> once the admin confirms")

            # Restore posts straight away
            restore = pg.intercept("/api/v2/trash/old-broadcast/restore", 200, {"ok": True, "project": "old-broadcast"}, "POST")
            pg.click(".adm-panel tr.dt-row[data-trash=old-broadcast] .adm-acts button[data-act=restore]")
            pg.wait_for("document.querySelectorAll('.app-toast').length > 1")
            self.assertEqual(restore["hits"], 1)
            self.assertFalse(pg.js("!!document.querySelector('.app-dialog')"), "restore needs no confirm")
            self.assertEqual(pg.smoke["errors"], [])

    def test_trash_list_failure_shows_retry(self):
        with self.open(P + "settings/trash", "d", intercepts=[("/api/v2/trash*", 500, {"error": "boom"}, "GET")]) as pg:
            self.view(pg, "adm-settings")
            pg.wait_for("!!document.querySelector('.adm-panel .fb-error .fb-retry')")
            pg.clear_intercepts()
            pg.intercept("/api/v2/trash*", 200, TRASH_ITEMS, "GET")
            pg.click(".adm-panel .fb-error .fb-retry")
            pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 2")

    def test_project_delete_is_move_to_trash(self):
        with self.open(P + "settings/project", "d") as pg:
            self.view(pg, "adm-settings")
            btn = "[data-card=danger] button[data-act=trash-project]"
            pg.wait_for("!!document.querySelector(%s)" % json.dumps(btn))
            self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(btn)), "Move to trash")
            self.assertIn("Settings \u203a Trash", pg.js("document.querySelector('[data-card=danger] p').textContent"))
            pg.click(btn)
            pg.wait_for("!!document.querySelector('.app-dialog')")
            text = pg.js("document.querySelector('.app-dialog').textContent")
            self.assertIn("move it to the trash", text)
            self.assertIn("restored from Settings", text)
            self.assertEqual(pg.js("document.querySelector('.app-dialog footer button:last-child').textContent"), "Move to trash")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")

    # ----------------------------------------------------------- lock editing (P2C)

    def test_lock_card_toggles_settings_locked(self):
        """The Lock editing card commits one settings.locked op; the server doc flips with it."""
        card = "[data-card=lock]"
        btn = card + " button[data-act=lock-toggle]"
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/project", size) as pg:
                self.view(pg, "adm-settings")
                pg.wait_for("!!document.querySelector(%s)" % json.dumps(btn))
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('data-locked')" % json.dumps(card + " .adm-lock-status")), "false")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(btn)), "Lock editing")
                self.assertIn("Builds, files and procedures are unaffected.", pg.js("document.querySelector(%s).textContent" % json.dumps(card + " .adm-lock-hint")))
                pg.click(btn)
                pg.wait_for("document.querySelector(%s).getAttribute('data-locked') === 'true'" % json.dumps(card + " .adm-lock-status"))
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(btn)), "Unlock editing")
                self.assertIn("Locked", pg.js("document.querySelector(%s).textContent" % json.dumps(card + " .adm-lock-status")))
                pg.wait_for("fetch('/api/v2/projects/campus-demo').then(function (r) { return r.json(); }).then(function (d) { return d.doc.settings.locked === true; })")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("adm-lock-%s" % size)
                pg.click(btn)
                pg.wait_for("document.querySelector(%s).getAttribute('data-locked') === 'false'" % json.dumps(card + " .adm-lock-status"))
                pg.wait_for("fetch('/api/v2/projects/campus-demo').then(function (r) { return r.json(); }).then(function (d) { return d.doc.settings.locked === false; })")
                self.assertEqual(pg.smoke["errors"], [])

    # ---------------------------------------------------------------- invites (P2C)

    def test_invites_tab_without_the_endpoint_is_empty(self):
        with self.open(P + "settings/invites", "d", intercepts=[("/api/v2/invites*", 404, {"error": "not found"}, "GET")]) as pg:
            self.view(pg, "adm-settings")
            self.assertEqual(selected_tab(pg), "invites")
            pg.wait_for("!!document.querySelector('.adm-panel .fb-empty')")
            self.assertIn("No open invites.", pg.js("document.querySelector('.adm-panel .fb-empty').textContent"))
            self.assertFalse(pg.js("!!document.querySelector('.adm-panel .fb-error')"), "a missing endpoint is an empty list, not an error")
            self.assertEqual(pg.smoke["errors"], [])

    def test_invites_form_creates_a_link_and_lists_open_invites(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/invites", size, intercepts=[
                ("/api/v2/invites*", 200, {"invites": [INVITE_OLD], "accept_url": "/invite/"}, "GET"),
            ]) as pg:
                self.view(pg, "adm-settings")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 1")
                cols = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
                self.assertEqual(cols, ["role", "projects", "created_by", "expires", "note", "actions"])
                row = ".adm-panel tr.dt-row[data-invite=%s]" % INVITE_OLD["token"]
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(row + " td[data-col=note]")), "front desk")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(row + " td[data-col=projects]")), "\u2014")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(row + " td[data-col=actions] button[data-act=revoke]")), "Revoke")
                # the form: role, per-project rows, expiry, note
                self.assertEqual(pg.js("document.querySelector('#adm-inv-role').value"), "editor")
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('#adm-inv-ttl option'), function (o) { return o.textContent; })"), ["24 hours", "72 hours", "7 days"])
                self.assertEqual(pg.js("document.querySelectorAll('.adm-inv-form .adm-pr-row').length"), 0)
                set_value(pg, "#adm-inv-role", "admin", "change")
                self.assertTrue(pg.js("document.querySelector('.adm-inv-form .adm-pr').hidden"))
                self.assertEqual(pg.js("document.querySelector('.adm-inv-form .adm-access-admin').textContent"), "Admins have full access everywhere.")
                set_value(pg, "#adm-inv-role", "editor", "change")
                self.assertFalse(pg.js("document.querySelector('.adm-inv-form .adm-pr').hidden"))
                pg.click(".adm-inv-form .adm-pr-add")
                pg.wait_for("document.querySelectorAll('.adm-inv-form .adm-pr-row').length === 1")
                opts = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-inv-form .adm-pr-proj option'), function (o) { return o.value; })")
                self.assertIn("campus-demo", opts)
                self.assertIn("sunday-demo", opts)
                set_value(pg, ".adm-inv-form .adm-pr-proj", "campus-demo", "change")
                set_value(pg, ".adm-inv-form .adm-pr-role", "viewer", "change")
                set_value(pg, "#adm-inv-note", "Jordan")
                pg.clear_intercepts()
                pg.intercept("/api/v2/invites*", 200, {"invites": [INVITE_OLD, INVITE_NEW], "accept_url": "/invite/"}, "GET")
                created = pg.intercept("/api/v2/invites", 201, INVITE_NEW, "POST")
                pg.click(".adm-inv-form button[data-act=create-invite]")
                pg.wait_for("!!document.querySelector('.adm-inv-out .adm-inv-url')")
                self.assertEqual(created["hits"], 1)
                url = pg.js("document.querySelector('.adm-inv-out .adm-inv-url').value")
                self.assertTrue(url.startswith("http"), url)
                self.assertTrue(url.endswith("/invite/" + INVITE_NEW["token"]), url)
                self.assertTrue(pg.js("document.querySelector('.adm-inv-out .adm-inv-url').readOnly"))
                self.assertIn("Send this link yourself", pg.js("document.querySelector('.adm-inv-out .adm-inv-hint').textContent"))
                self.assertIn("works once", pg.js("document.querySelector('.adm-inv-out .adm-inv-hint').textContent"))
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 2")
                self.assertEqual(pg.js("document.querySelectorAll('.adm-panel tr.dt-hl[data-invite=%s]').length" % INVITE_NEW["token"]), 1)
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(".adm-panel tr.dt-row[data-invite=%s] td[data-col=projects]" % INVITE_NEW["token"])), "campus-demo: viewer")
                pg.click(".adm-inv-out button[data-act=copy-invite]")
                pg.wait_for("document.querySelectorAll('.app-toast').length > 1")
                if size == "m":
                    self.assertLessEqual(pg.offscreen(".adm-inv-out button[data-act=copy-invite]", "x"), 0)
                    self.assertTrue(pg.js("!!document.querySelector('.adm-panel .dt-root.dt-cards')"), "cards at sm")
                    h = pg.js("document.querySelector('.adm-inv-form button[data-act=create-invite]').getBoundingClientRect().height")
                    self.assertGreaterEqual(h, 44)
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("adm-invites-%s" % size)
                # Revoke asks first, then DELETEs the token
                revoke = pg.intercept("/api/v2/invites/" + INVITE_OLD["token"], 204, "", "DELETE")
                pg.click(row + " td[data-col=actions] button[data-act=revoke]")
                pg.wait_for("!!document.querySelector('.app-dialog')")
                self.assertIn("front desk", pg.js("document.querySelector('.app-dialog').textContent"))
                pg.click(".app-dialog footer button:last-child")
                pg.wait_for("!document.querySelector('.app-dialog')")
                deadline = 30
                while revoke["hits"] < 1 and deadline > 0:
                    pg.js("new Promise(function (r) { setTimeout(r, 100); })")
                    deadline -= 1
                self.assertEqual(revoke["hits"], 1)
                self.assertEqual(pg.smoke["errors"], [])

    # ------------------------------------------------------------ suggestions (P2C)

    def test_suggestions_empty_state(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/suggestions", size, intercepts=[("/api/v2/projects/campus-demo/problems*", 200, {"problems": [], "open": 0}, "GET")]) as pg:
                self.view(pg, "adm-settings")
                self.assertEqual(selected_tab(pg), "suggestions")
                pg.wait_for("!!document.querySelector('.adm-panel .fb-empty')")
                text = pg.js("document.querySelector('.adm-panel .fb-empty').textContent")
                self.assertIn("No suggestions yet.", text)
                self.assertIn("Anyone can send one from the user menu.", text)
                self.assertFalse(pg.js("document.querySelector('#adm-sug-all').checked"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.smoke["errors"], [])

    def test_suggestions_rows_resolve_and_all_projects(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/suggestions", size, intercepts=[
                ("/api/v2/projects/campus-demo/problems*", 200, SUGGESTIONS, "GET"),
                ("/api/v2/suggestions*", 200, SUGGESTIONS_ALL, "GET"),
            ]) as pg:
                self.view(pg, "adm-settings")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 2", 20)
                ids = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel tr.dt-row'), function (tr) { return tr.getAttribute('data-suggestion'); })")
                self.assertEqual(sorted(ids), ["pr-0000a001", "pr-0000a002"], "only kind=suggestion rows are shown")
                cols = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
                self.assertEqual(cols, ["text", "project", "by", "created", "about", "status", "actions"])
                r1 = ".adm-panel tr.dt-row[data-suggestion=pr-0000a001]"
                r2 = ".adm-panel tr.dt-row[data-suggestion=pr-0000a002]"
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r1 + " td[data-col=by]")), "jordan")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r1 + " a.adm-sug-about[data-device=foh-cl5]")), "FOH CL5")
                self.assertIn("/campus-demo/*/devices/foh-cl5", pg.js("document.querySelector(%s).getAttribute('href')" % json.dumps(r1 + " a.adm-sug-about")))
                self.assertIn("page=power-up", pg.js("document.querySelector(%s).getAttribute('href')" % json.dumps(r2 + " a.adm-sug-about[data-page=power-up]")))
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r1 + " td[data-col=status]")), "Open")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r2 + " td[data-col=status]")), "Resolved")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r1 + " button[data-act=resolve]")), "Resolve")
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % json.dumps(r2 + " button[data-act=reopen]")), "Reopen")
                self.assertIn("1 open", pg.js("document.querySelector('.adm-sug-summary').textContent"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                if size == "m":
                    self.assertTrue(pg.js("!!document.querySelector('.adm-panel .dt-root.dt-cards')"), "cards at sm")
                pg.shot("adm-suggestions-%s" % size)
                patched = pg.intercept("/api/v2/projects/campus-demo/problems/pr-0000a001", 200, {"problem": dict(SUGGESTIONS["problems"][0], status="resolved")}, "PATCH")
                pg.click(r1 + " button[data-act=resolve]")
                pg.wait_for("document.querySelectorAll('.app-toast').length > 0")
                self.assertEqual(patched["hits"], 1, "Resolve reuses PATCH …/problems/<pid>")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 2", 20)
                # All projects switches the source
                pg.click(".adm-sug-all", force=True)
                pg.wait_for("document.querySelector('#adm-sug-all').checked")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row[data-project=sunday-demo]').length === 1", 20)
                self.assertEqual(pg.js("document.querySelectorAll('.adm-panel tr.dt-row').length"), 2)
                self.assertEqual(pg.js("document.querySelector('.adm-panel tr.dt-row[data-project=sunday-demo] td[data-col=project]').textContent"), "sunday-demo")
                self.assertEqual(pg.smoke["errors"], [])

    # ------------------------------------------------- Settings › Assistant (P4C)

    def llm_page(self, size: str, settings: dict = None, providers: dict = None, capture: bool = False):
        """Settings › Assistant against stubbed P4A endpoints; ``capture`` records request bodies in window.__bodies."""
        cm = self.open("/healthz", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        if capture:
            pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": CAPTURE_BODIES})
        pg.intercept("/api/v2/llm/providers*", 200, providers or LLM_PROVIDERS, "GET")
        pg.intercept("/api/v2/llm/settings*", 200, settings or LLM_SETTINGS, "GET")
        pg.goto("/" + P + "settings/assistant")
        self.view(pg, "adm-settings")
        pg.wait_for("!!document.querySelector('#adm-llm-provider')")
        return pg

    def test_assistant_tab_renders_providers_and_prefills_the_base_url(self):
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.llm_page(size)
                self.assertEqual(selected_tab(pg), "assistant")
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('#adm-llm-provider option'), function (o) { return o.textContent; })"),
                                 ["OpenAI", "Anthropic", "xAI Grok", "Local / OpenAI-compatible server"])
                self.assertEqual(pg.js("document.querySelector('#adm-llm-provider').value"), "openai")
                self.assertEqual(pg.js("document.querySelector('#adm-llm-url').value"), "https://api.openai.com/v1")
                self.assertEqual(pg.js("document.querySelector('#adm-llm-key').placeholder"), "Stored")
                self.assertFalse(pg.js("document.querySelector('#adm-llm-api').closest('.field').hidden"), "the API select shows for OpenAI")
                self.assertTrue(pg.js("document.querySelector('.adm-llm-presets').hidden"))
                # switching the provider replaces a base URL that still equals the previous default
                set_value(pg, "#adm-llm-provider", "anthropic", "change")
                self.assertEqual(pg.js("document.querySelector('#adm-llm-url').value"), "https://api.anthropic.com")
                self.assertTrue(pg.js("document.querySelector('#adm-llm-api').closest('.field').hidden"), "the API select is OpenAI only")
                self.assertTrue(pg.js("document.querySelector('[data-act=fetch-models]').disabled"), "Fetch models is off when the provider does not list models")
                # an edited URL is kept
                set_value(pg, "#adm-llm-url", "https://proxy.example.org/v1")
                set_value(pg, "#adm-llm-provider", "xai", "change")
                self.assertEqual(pg.js("document.querySelector('#adm-llm-url').value"), "https://proxy.example.org/v1")
                # the local provider shows preset chips that fill the URL
                set_value(pg, "#adm-llm-provider", "openai_compat", "change")
                self.assertFalse(pg.js("document.querySelector('.adm-llm-presets').hidden"))
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-llm-preset'), function (b) { return b.textContent; })"), ["Ollama", "LM Studio", "vLLM", "llama.cpp"])
                pg.click(".adm-llm-preset[data-preset=lmstudio]")
                self.assertEqual(pg.js("document.querySelector('#adm-llm-url').value"), "http://localhost:1234/v1")
                self.assertFalse(pg.js("document.querySelector('[data-act=fetch-models]').disabled"))
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    self.assertGreaterEqual(pg.rect(".adm-llm-preset[data-preset=lmstudio]")["height"], 44)
                    self.assertGreaterEqual(pg.rect("[data-act=save]")["height"], 44)
                pg.shot("settings-assistant-" + size)
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_assistant_fetch_models_fills_the_datalist(self):
        pg = self.llm_page("d")
        models = pg.intercept("/api/v2/llm/models", 200, {"models": ["gpt-4o-mini", "gpt-4.1", "o4-mini"]}, "POST")
        pg.click("[data-act=fetch-models]")
        pg.wait_for("document.querySelectorAll('#adm-llm-models option').length === 3")
        self.assertEqual(models["hits"], 1)
        self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('#adm-llm-models option'), function (o) { return o.value; })"), ["gpt-4o-mini", "gpt-4.1", "o4-mini"])
        self.assertEqual(pg.js("document.querySelector('#adm-llm-model').value"), "gpt-4o-mini", "the stored model stays")
        pg.clear_intercepts()
        pg.intercept("/api/v2/llm/models", 502, {"error": "upstream: 401 Unauthorized", "code": "upstream"}, "POST")
        pg.click("[data-act=fetch-models]")
        pg.wait_for("!!document.querySelector('.adm-llm-models-err .fb-error')")
        self.assertIn("401 Unauthorized", pg.js("document.querySelector('.adm-llm-models-err').textContent"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_assistant_test_connection_shows_ok_and_errors(self):
        pg = self.llm_page("d")
        pg.intercept("/api/v2/llm/test", 200, {"ok": True, "model": "gpt-4o-mini", "latency_ms": 420, "detail": ""}, "POST")
        pg.click("[data-act=test]")
        pg.wait_for("document.querySelector('.adm-llm-test-out').getAttribute('data-ok') === 'true'")
        self.assertEqual(pg.js("document.querySelector('.adm-llm-test-out').textContent"), "OK \u00b7 gpt-4o-mini \u00b7 420 ms")
        self.assertFalse(pg.js("document.querySelector('[data-act=test]').disabled"))
        pg.clear_intercepts()
        pg.intercept("/api/v2/llm/test", 200, {"ok": False, "model": "gpt-4o-mini", "latency_ms": 12, "detail": "401 Unauthorized (key sk-***)"}, "POST")
        pg.click("[data-act=test]")
        pg.wait_for("document.querySelector('.adm-llm-test-out').getAttribute('data-ok') === 'false'")
        self.assertEqual(pg.js("document.querySelector('.adm-llm-test-out').textContent"), "Failed \u00b7 401 Unauthorized (key sk-***)")
        pg.clear_intercepts()
        pg.intercept("/api/v2/llm/test", 502, {"error": "upstream: connection refused", "code": "upstream"}, "POST")
        pg.click("[data-act=test]")
        pg.wait_for("document.querySelector('.adm-llm-test-out').textContent.indexOf('connection refused') > 0")
        self.assertTrue(pg.js("document.querySelector('.adm-llm-test-out').classList.contains('warn')"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_assistant_save_sends_the_key_only_when_typed(self):
        pg = self.llm_page("d", capture=True)
        saved = pg.intercept("/api/v2/llm/settings", 200, dict(LLM_SETTINGS, model="gpt-4.1"), "PUT")
        set_value(pg, "#adm-llm-model", "gpt-4.1")
        set_value(pg, "#adm-llm-max", "900")
        pg.click("#adm-llm-web", force=True)
        pg.click("[data-act=save]")
        pg.wait_for("document.querySelector('.adm-llm-saved').textContent === 'Saved'")
        self.assertEqual(saved["hits"], 1)
        body = pg.js("JSON.parse(window.__bodies.filter(function (b) { return b.method === 'PUT'; }).pop().body)")
        self.assertNotIn("api_key", body, "an untouched key field sends no api_key")
        self.assertNotIn("clear_api_key", body)
        self.assertEqual(body["model"], "gpt-4.1")
        self.assertEqual(body["max_tokens"], 900)
        self.assertEqual(body["web_lookup"], True)
        self.assertEqual(body["api"], "chat")
        self.assertEqual(body["provider"], "openai")
        # a typed key travels once and the field empties again
        set_value(pg, "#adm-llm-key", "sk-new-secret")
        pg.click("[data-act=save]")
        pg.wait_for("window.__bodies.filter(function (b) { return b.method === 'PUT'; }).length === 2")
        body = pg.js("JSON.parse(window.__bodies.filter(function (b) { return b.method === 'PUT'; }).pop().body)")
        self.assertEqual(body["api_key"], "sk-new-secret")
        pg.wait_for("document.querySelector('#adm-llm-key').value === ''")
        # Clear key removes the stored key
        pg.click("[data-act=clear-key]")
        self.assertEqual(pg.js("document.querySelector('#adm-llm-key').placeholder"), "Paste the API key")
        pg.click("[data-act=save]")
        pg.wait_for("window.__bodies.filter(function (b) { return b.method === 'PUT'; }).length === 3")
        body = pg.js("JSON.parse(window.__bodies.filter(function (b) { return b.method === 'PUT'; }).pop().body)")
        self.assertEqual(body.get("clear_api_key"), True)
        self.assertNotIn("api_key", body)
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_assistant_env_sourced_fields_are_disabled(self):
        env = dict(LLM_SETTINGS, source={"provider": "env", "base_url": "env", "api_key": "env", "model": "file"})
        pg = self.llm_page("m", settings=env, capture=True)
        for sel in ("#adm-llm-provider", "#adm-llm-url", "#adm-llm-key"):
            self.assertTrue(pg.js("document.querySelector(%s).disabled" % json.dumps(sel)), sel)
        self.assertFalse(pg.js("document.querySelector('#adm-llm-model').disabled"))
        self.assertEqual(pg.js("document.querySelector('.adm-llm-env[data-env=base_url]').textContent"), "Set by environment (FATHOM_LLM_URL)")
        self.assertEqual(pg.js("document.querySelector('.adm-llm-env[data-env=api_key]').textContent"), "Set by environment (FATHOM_LLM_KEY)")
        self.assertTrue(pg.js("document.querySelector('[data-act=clear-key]').hidden"), "no Clear key for an env key")
        pg.intercept("/api/v2/llm/settings", 200, env, "PUT")
        pg.click("[data-act=save]")
        pg.wait_for("window.__bodies.filter(function (b) { return b.method === 'PUT'; }).length === 1")
        body = pg.js("JSON.parse(window.__bodies.filter(function (b) { return b.method === 'PUT'; }).pop().body)")
        for k in ("provider", "base_url", "api_key", "clear_api_key"):
            self.assertNotIn(k, body, "env-sourced fields are not sent")
        self.assertEqual(body["model"], "gpt-4o-mini")
        self.assertLessEqual(pg.page_hscroll(), 0)
        pg.shot("settings-assistant-env-m")

    def test_assistant_tab_without_the_endpoints_shows_a_note(self):
        with self.open(P + "settings/assistant", "d", intercepts=[("/api/v2/llm/providers*", 404, {"error": "not found"}, "GET"),
                                                                 ("/api/v2/llm/settings*", 404, {"error": "not found"}, "GET")]) as pg:
            self.view(pg, "adm-settings")
            pg.wait_for("!!document.querySelector('[data-card=llm-missing]')")
            self.assertIn("no language-model settings", pg.js("document.querySelector('.adm-llm-missing').textContent"))
            self.assertFalse(pg.js("!!document.querySelector('#adm-llm-provider')"))
            self.assertEqual(pg.smoke["errors"], [])

    # ------------------------------------------------------------------- history

    def test_history_revision_is_in_the_url(self):
        revs = self.revisions()
        for size in SIZES3:
            with self.subTest(size=size), self.open(P + "history/1", size) as pg:
                self.view(pg, "adm-history")
                pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=\"1\"]')")
                pg.wait_for("/r1 vs r%d/.test(document.querySelector('.adm-diff').textContent)" % max(revs))
                self.assertFalse(pg.js("document.querySelector('.adm-diff').classList.contains('hidden')"))
                self.assertEqual(self.rows(pg), len(revs))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("history-" + size)
                if size == "d":
                    pg.click("tr.dt-row[data-id=\"2\"] td[data-col=summary]")
                    pg.wait_for("/\\/history\\/2$/.test(location.hash.split('?')[0])")
                    pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=\"2\"]')")
                    self.assertEqual(pg.js("document.querySelectorAll('tr.dt-hl').length"), 1)
                    pg.reload()
                    self.view(pg, "adm-history")
                    pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=\"2\"]')")

    def test_history_user_filter_and_actions(self):
        revs = self.revisions()
        with self.open(P + "history", "d") as pg:
            self.view(pg, "adm-history")
            pg.wait_for("document.querySelectorAll('#app-main tr.dt-row').length === %d" % len(revs))
            self.assertIn(1, revs)
            self.assertTrue(pg.js("!!document.querySelector('.dt-filter[data-col=author]')"))
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('tr.dt-row[data-id=\"1\"] .adm-acts button'), function (b) { return b.textContent; })")
            self.assertEqual(labels, ["View", "Diff", "Restore"])

    # -------------------------------------------------------------------- builds

    def test_builds_list_and_delete_confirm(self):
        for size in SIZES3:
            with self.subTest(size=size), self.open(P + "builds?hl=" + self.build, size) as pg:
                self.view(pg, "adm-builds")
                pg.wait_for("!!document.querySelector('tr.dt-hl[data-id=%s]')" % json.dumps(self.build))
                self.assertTrue(pg.js("!!document.querySelector('#bld-go')"))
                self.assertIn("index.html", pg.js("document.querySelector('tr.dt-row td[data-col=outputs] a.chip').getAttribute('href')"))
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("builds-" + size)
                if size == "d":
                    pg.click("tr.dt-row[data-id=%s] .adm-acts button.danger" % json.dumps(self.build))
                    pg.wait_for("!!document.querySelector('.app-dialog')")
                    self.assertIn("Delete build " + self.build + "?", pg.js("document.querySelector('.app-dialog').textContent"))
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.app-dialog')")
                    self.assertEqual(self.rows(pg), 1)

    # ------------------------------------------------------------------- imports

    def test_imports_at_three_sizes_and_no_inner_scroll_on_a_phone(self):
        for size in SIZES3:
            with self.subTest(size=size), self.open(P + "imports", size) as pg:
                self.assertEqual(pg.smoke["errors"], [])
                self.view(pg, "adm-imports")
                pg.wait_for("document.querySelectorAll('[data-table=\"imports.registered\"] tr.dt-row').length > 0")
                pg.wait_for("document.querySelectorAll('[data-table=\"imports.overlay\"] tr.dt-row').length > 0", 30)
                self.assertLessEqual(pg.page_hscroll(), 0)
                if size in ("m", "t"):
                    wide = pg.js("""(function () {
                      var out = [];
                      Array.prototype.forEach.call(document.querySelectorAll('#app-main *'), function (el) {
                        if (el.closest('.dt-scroll')) return;
                        var closed = el.closest('details:not([open])');
                        if (closed && !el.closest('summary')) return;
                        var s = getComputedStyle(el);
                        if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1) out.push(el.tagName + '.' + el.className);
                        var r = el.getBoundingClientRect();
                        if (r.width && r.right > innerWidth + 1 && s.position !== 'fixed') out.push('off:' + el.tagName + '.' + el.className);
                      });
                      return out.slice(0, 10);
                    })()""")
                    self.assertEqual(wide, [])
                pg.shot("imports-" + size)
                pg.js("document.querySelector('.adm-sec-head').scrollIntoView({block: 'start'})")
                pg.shot("imports-overlay-" + size)

    def test_imports_review_badge_jumps_to_a_suggestion(self):
        with self.open(P + "imports", "m") as pg:
            self.view(pg, "adm-imports")
            pg.wait_for("!!document.querySelector('.adm-sec-head .fb-review, .adm-ovl-review button, .adm-ovl-review a')", 30)
            pg.click(".adm-ovl-review > *")
            pg.wait_for("!!document.activeElement && !!document.activeElement.closest('.ms-suggest')")
            self.assertEqual(pg.js("document.querySelectorAll('[data-table=\"imports.overlay\"] tr.dt-hl').length"), 1)

    # ------------------------------------------------------------------- sharing

    def test_share_wizard_steps_advance_and_create_a_link(self):
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(P + "settings/sharing", size) as pg:
                self.view(pg, "adm-settings")
                pg.wait_for("!document.querySelector('.adm-panel [aria-busy=true]')")
                before = self.rows(pg, ".adm-panel")
                pg.click(".adm-new-share")
                pg.wait_for("!!document.querySelector('.wz[data-wizard=share][data-step=scope]')")
                set_value(pg, ".wz input[name=label]", "Volunteers " + size)
                pg.click(".wz label.adm-radio:nth-of-type(2)")
                self.assertTrue(pg.js("document.querySelector('.wz input[name=scope][value=sop]').checked"))
                pg.click(".wz .wz-next")
                pg.wait_for("!!document.querySelector('.wz[data-step=expiry]')")
                set_value(pg, ".wz select[name=expiry]", "date", "change")
                pg.wait_for("!document.querySelector('.wz input[name=date]').closest('.wz-field').hidden")
                set_value(pg, ".wz input[name=date]", "2000-01-01")
                pg.click(".wz .wz-next")
                self.assertEqual(pg.js("document.querySelector('.wz').getAttribute('data-step')"), "expiry")
                set_value(pg, ".wz select[name=expiry]", "7", "change")
                pg.click(".wz .wz-next")
                pg.wait_for("!!document.querySelector('.wz[data-step=review]')")
                review = pg.js("document.querySelector('.wz-review').textContent")
                self.assertIn("procedures", review)
                self.assertIn("7 days", review)
                pg.click(".wz .wz-back")
                pg.wait_for("!!document.querySelector('.wz[data-step=expiry]')")
                pg.click(".wz .wz-next")
                pg.wait_for("!!document.querySelector('.wz[data-step=review]')")
                pg.click(".wz .wz-next")
                pg.wait_for("!!document.querySelector('.wz[data-step=result] .adm-share-url')")
                url = pg.js("document.querySelector('.adm-share-url').value")
                self.assertIn("/s/", url)
                self.assertIn("share=", pg.js("document.querySelector('.adm-share-qr').getAttribute('href')"))
                if size == "m":
                    self.assertLessEqual(pg.offscreen(".wz .adm-share-row button", "x"), 0)
                pg.shot("share-wizard-" + size)
                pg.click(".wz .wz-next")
                pg.wait_for("!document.querySelector('.wz')")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === %d" % (before + 1))
                self.assertEqual(pg.js("document.querySelectorAll('.adm-panel tr.dt-hl').length"), 1)


class AdmRoles(UiCase):
    """Login on: viewers see no users, backups or sharing tabs; editors no users or backups."""

    @classmethod
    def setUpClass(cls) -> None:
        super(AdmRoles, cls).setUpClass()
        from fathom import users

        for name, role in (("admin1", "admin"), ("editor1", "editor"), ("viewer1", "viewer")):
            users.add_user(name, name + "-password-1", role=role)
        # P2C: an editor who is only a viewer in campus-demo
        users.add_user("sam", "sam-password-1", role="editor", projects={"campus-demo": "viewer"})

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

    def test_viewer_sees_no_admin_tabs_or_write_controls(self):
        pg = self.signed_in("viewer1", "/#/campus-demo/main/settings/users")
        pg.wait_for("!!document.querySelector('#app-main .adm-settings')")
        self.assertEqual([t for t in tabs(pg) if t in ("users", "backups", "sharing")], [])
        self.assertEqual(selected_tab(pg), "project")
        pg.wait_for("location.hash.indexOf('/settings/users') < 0")
        pg.goto("#/campus-demo/main/settings/networks")
        pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 5")
        self.assertEqual(pg.js("document.querySelectorAll('.adm-panel .dt-table input, .adm-panel .dt-table select, .adm-addrow').length"), 0)
        pg.goto("#/campus-demo/main/builds")
        pg.wait_for("!!document.querySelector('#app-main .adm-builds')")
        self.assertFalse(pg.js("!!document.querySelector('#bld-go')"))
        pg.goto("#/campus-demo/main/history")
        pg.wait_for("!!document.querySelector('#app-main .adm-history')")
        self.assertEqual(pg.js("Array.prototype.filter.call(document.querySelectorAll('#app-main .adm-acts button'), function (b) { return b.textContent === 'Restore'; }).length"), 0)
        pg.goto("#/campus-demo/main/imports")
        pg.wait_for("!!document.querySelector('#app-main .adm-imports')")
        self.assertEqual(pg.js("document.querySelectorAll('#app-main .adm-card input[type=file]').length"), 0)

    def test_editor_sees_sharing_but_not_users_or_backups(self):
        pg = self.signed_in("editor1", "/#/campus-demo/main/settings/sharing")
        pg.wait_for("!!document.querySelector('#app-main .adm-settings')")
        got = tabs(pg)
        self.assertIn("sharing", got)
        self.assertNotIn("users", got)
        self.assertNotIn("backups", got)
        self.assertEqual(selected_tab(pg), "sharing")
        self.assertTrue(pg.js("!!document.querySelector('.adm-new-share')"))

    def test_admin_sees_every_tab(self):
        pg = self.signed_in("admin1", "/#/campus-demo/main/settings/users", "m")
        pg.wait_for("!!document.querySelector('#app-main .adm-settings')")
        self.assertEqual(tabs(pg), ALL_TABS)
        self.assertEqual(selected_tab(pg), "users")
        pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 4")
        self.assertLessEqual(pg.page_hscroll(), 0)

    # ---------------------------------------------------- per-project access (P2C)

    def test_user_access_rows_and_patch(self):
        """The Projects column counts overrides; the Access editor lists them and PATCHes the whole map."""
        from fathom import users

        for size, new_role in (("d", "editor"), ("m", "viewer")):
            with self.subTest(size=size):
                pg = self.signed_in("admin1", "/#/campus-demo/main/settings/users", size)
                pg.wait_for("!!document.querySelector('#app-main .adm-settings')")
                pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 4")
                cols = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
                self.assertEqual(cols, ["username", "role", "projects", "disabled", "created", "actions"])
                self.assertEqual(pg.js("document.querySelector('.adm-panel tr.dt-row[data-user=sam] td[data-col=projects]').textContent"), "1 override")
                self.assertEqual(pg.js("document.querySelector('.adm-panel tr.dt-row[data-user=admin1] td[data-col=projects]').textContent"), "\u2014")
                acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.adm-panel tr.dt-row[data-user=sam] .adm-acts button'), function (b) { return b.textContent; })")
                self.assertEqual(acts, ["Access", "Reset password", "Remove"])
                if size == "m":
                    self.assertTrue(pg.js("!!document.querySelector('.adm-panel .dt-root.dt-cards')"), "cards at sm")
                pg.click(".adm-panel tr.dt-row[data-user=sam] button[data-act=access]")
                pg.wait_for("!!document.querySelector('.app-dialog .adm-access[data-user=sam]')")
                self.assertEqual(pg.js("document.querySelectorAll('.app-dialog .adm-pr-row').length"), 1)
                self.assertEqual(pg.js("document.querySelector('.app-dialog .adm-pr-proj').value"), "campus-demo")
                self.assertEqual(pg.js("document.querySelector('.app-dialog .adm-pr-role').value"), users.get_user("sam")["projects"]["campus-demo"])
                self.assertFalse(pg.js("!!document.querySelector('.app-dialog .adm-pr-hint:not([hidden])')"))
                self.assertLessEqual(pg.offscreen(".app-dialog .adm-pr-row select", "x"), 0)
                pg.shot("adm-user-access-%s" % size)
                # a second row for the same project is refused; Save stays in the dialog
                pg.click(".app-dialog .adm-pr-add")
                pg.wait_for("document.querySelectorAll('.app-dialog .adm-pr-row').length === 2")
                set_value(pg, ".app-dialog .adm-pr-row:nth-child(2) .adm-pr-proj", "campus-demo", "change")
                pg.click(".app-dialog footer button.primary")
                self.assertTrue(pg.js("!!document.querySelector('.app-dialog')"))
                self.assertEqual(pg.js("document.querySelectorAll('.app-dialog .adm-pr-row.adm-pr-dup').length"), 2)
                self.assertIn("listed twice", pg.js("document.querySelector('.app-dialog .adm-pr-err').textContent"))
                # a different project is fine; the saved map carries both rows
                set_value(pg, ".app-dialog .adm-pr-row:nth-child(2) .adm-pr-proj", "sunday-demo", "change")
                set_value(pg, ".app-dialog .adm-pr-row:nth-child(2) .adm-pr-role", "editor", "change")
                self.assertEqual(pg.js("document.querySelectorAll('.app-dialog .adm-pr-row.adm-pr-dup').length"), 0)
                set_value(pg, ".app-dialog .adm-pr-row:nth-child(1) .adm-pr-role", new_role, "change")
                pg.click(".app-dialog footer button.primary")
                pg.wait_for("!document.querySelector('.app-dialog')")
                pg.wait_for("document.querySelector('.adm-panel tr.dt-row[data-user=sam] td[data-col=projects]').textContent === '2 overrides'")
                self.assertEqual(users.get_user("sam")["projects"], {"campus-demo": new_role, "sunday-demo": "editor"})
                # removing a row drops it from the map
                pg.click(".adm-panel tr.dt-row[data-user=sam] button[data-act=access]")
                pg.wait_for("document.querySelectorAll('.app-dialog .adm-pr-row').length === 2")
                pg.click(".app-dialog .adm-pr-row:nth-child(2) .adm-pr-rm")
                pg.wait_for("document.querySelectorAll('.app-dialog .adm-pr-row').length === 1")
                pg.click(".app-dialog footer button.primary")
                pg.wait_for("!document.querySelector('.app-dialog')")
                pg.wait_for("document.querySelector('.adm-panel tr.dt-row[data-user=sam] td[data-col=projects]').textContent === '1 override'")
                self.assertEqual(users.get_user("sam")["projects"], {"campus-demo": new_role})
                # admins have nothing to override
                pg.click(".adm-panel tr.dt-row[data-user=admin1] button[data-act=access]")
                pg.wait_for("!!document.querySelector('.app-dialog .adm-access[data-user=admin1]')")
                self.assertEqual(pg.js("document.querySelector('.app-dialog .adm-access-admin').textContent"), "Admins have full access everywhere.")
                self.assertEqual(pg.js("document.querySelectorAll('.app-dialog .adm-pr-row, .app-dialog .adm-pr-add').length"), 0)
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.app-dialog footer button'), function (b) { return b.textContent; })"), ["Close"])
                pg.press("Escape")
                pg.wait_for("!document.querySelector('.app-dialog')")
                self.assertEqual(pg.smoke["errors"], [])

    def test_editor_and_viewer_see_no_invites_or_suggestions(self):
        for name in ("editor1", "viewer1"):
            pg = self.signed_in(name, "/#/campus-demo/main/settings/invites")
            pg.wait_for("!!document.querySelector('#app-main .adm-settings')")
            self.assertEqual([t for t in tabs(pg) if t in ("invites", "suggestions")], [])
            self.assertEqual(selected_tab(pg), "project")
            pg.wait_for("location.hash.indexOf('/settings/invites') < 0")
            pg.wait_for("!!document.querySelector('[data-card=lock] .adm-lock-status')")
            has_toggle = pg.js("!!document.querySelector('[data-card=lock] button[data-act=lock-toggle]')")
            self.assertEqual(has_toggle, name == "editor1", "any editor may lock; viewers only see the status")
