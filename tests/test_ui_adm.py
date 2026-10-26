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
ALL_TABS = ["project", "rooms", "systems", "locations", "networks", "templates", "users", "backups", "sharing", "offline"]


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
                if path not in ("settings/project", "settings/offline"):
                    self.assertGreaterEqual(pg.js("document.querySelectorAll('#app-main .dt-table').length"), 1)
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
        pg.wait_for("document.querySelectorAll('.adm-panel tr.dt-row').length === 3")
        self.assertLessEqual(pg.page_hscroll(), 0)
