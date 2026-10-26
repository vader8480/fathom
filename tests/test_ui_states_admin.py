"""ST-ADMIN: loading, empty, error, confirm, freshness and review states of the admin and discovery views
(docs/ui-audit.md B.5, row ST-ADMIN).

Each state is forced with request interception (``UiPage.intercept``) or by holding a request open with a
``fetch`` wrapper installed before the app loads, then asserted: the copy, the actions an admin gets (and a
viewer does not), Retry re-requesting, the ``confirmScope`` wording with real names and numbers, and no
horizontal page scroll at ``m``. With ``FATHOM_UI_SHOTS`` set every state is also captured at d, t and m as
``st-admin-<state>-<size>.png``. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

ROOT = Path(__file__).resolve().parent.parent
P = "#/campus-demo/main/"
SHOTS = bool(os.environ.get("FATHOM_UI_SHOTS"))
# Every state is asserted at m; the other sizes only run when screenshots are wanted.
STATE_SIZES = ("d", "t", "m") if SHOTS else ("m",)
BOOM = {"error": "boom"}
DANTE_PRESET = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><preset version=\"3.0.0\"><name>Stage</name>"
                "<device><name>Y004-Yamaha-Rio1608-STG</name><manufacturer_name>Yamaha Corporation</manufacturer_name>"
                "<model_name>Rio1608-D</model_name><ipv4_address>10.20.0.23</ipv4_address>"
                "<txchannel danteId=\"1\"><label>Stage 1</label></txchannel></device></preset>")
LOADED = "(document.querySelectorAll('#app-main tr.dt-row').length > 0 || !!document.querySelector('#app-main .dt-empty:not([hidden])'))"
DISC_ENV = {"FATHOM_DISCOVERY_FIXTURES": str(ROOT / "tests" / "fixtures" / "discovery"), "FATHOM_DISCOVERY_FIXTURE_DELAY": "0.1"}


def q(s: str) -> str:
    return json.dumps(s)


def api(base: str, method: str, path: str, body=None, raw: bytes = b"", ctype: str = "application/json"):
    data = json.dumps(body).encode() if body is not None else (raw or None)
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": ctype, "X-Fathom": "1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode()
        return json.loads(text) if text else {}


def seed_history(data: str) -> None:
    """Revision 1 in the history index (the sample ships without one) plus two edits."""
    from fathom import history
    from fathom.project import apply_changes

    pdir = Path(data) / "projects" / "campus-demo"
    doc = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    if not history.has_history(pdir):
        history.record(pdir, int(doc.get("revision") or 1), [], doc, author="seed", summary="Sample project",
                       source="put", touched=set())
    rev = int(doc.get("revision") or 1)
    for i, name in enumerate(("Dante primary (edited)", "Dante primary")):
        rev = apply_changes(pdir, [{"op": "merge", "coll": "networks", "id": "av-dante", "value": {"name": name}}],
                            base_revision=rev, author="tester", summary="Rename network %d" % (i + 1), source="changes")["revision"]


def upload_preset(base: str, project: str = "campus-demo") -> None:
    boundary = "----fathomst"
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"stage.xml\"\r\nContent-Type: text/xml\r\n\r\n" % boundary).encode()
            + DANTE_PRESET.encode() + ("\r\n--%s--\r\n" % boundary).encode())
    api(base, "POST", "/api/v2/projects/%s/imports?kind=dante" % project, raw=body, ctype="multipart/form-data; boundary=" + boundary)


# A fetch wrapper that parks matching requests until window.__release() (skeleton states).
HOLD = """(function () {
  var re = new RegExp(%s), real = window.fetch, held = [];
  window.__held = function () { return held.length; };
  window.__release = function () { var h = held; held = []; re = /^$/; h.forEach(function (f) { f(); }); };
  window.fetch = function (u, o) {
    var s = String(u && u.url || u);
    if (!re.test(s)) return real.apply(this, arguments);
    var self = this, args = arguments;
    return new Promise(function (res, rej) { held.push(function () { real.apply(self, args).then(res, rej); }); });
  };
})();"""


def each_size():
    """(size, is_last) over STATE_SIZES; destructive steps (a Retry that succeeds, a confirmed delete) run once, last."""
    return [(s, i == len(STATE_SIZES) - 1) for i, s in enumerate(STATE_SIZES)]


class StateMixin(object):
    def view(self, pg, cls_name: str, timeout: float = 20) -> None:
        pg.wait_for("!!document.querySelector('#app-main .%s')" % cls_name, timeout)

    def text(self, pg, selector: str) -> str:
        return pg.js("(function () { var e = document.querySelector(%s); return e ? e.textContent : ''; })()" % q(selector))

    def rows(self, pg, scope: str) -> int:
        return pg.js("document.querySelectorAll(%s).length" % q(scope + " tr.dt-row"))

    def no_hscroll(self, pg, what: str) -> None:
        self.assertLessEqual(pg.page_hscroll(), 0, "%s: no horizontal page scroll at %s" % (what, pg.size))
        self.assertEqual(pg.smoke["errors"], [], what)

    def dialog_text(self, pg) -> str:
        pg.wait_for("!!document.querySelector('.app-dialog')")
        return pg.js("document.querySelector('.app-dialog').textContent")

    def dismiss(self, pg) -> None:
        pg.press("Escape")
        pg.wait_for("!document.querySelector('.app-dialog')")

    def confirm(self, pg) -> None:
        pg.click(".app-dialog footer button:last-child")
        pg.wait_for("!document.querySelector('.app-dialog')")

    def held(self, path: str, size: str, pattern: str):
        """Open ``path`` with requests matching ``pattern`` (a JS regexp source) held open."""
        cm = self.open("/healthz", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": HOLD % q(pattern)})
        pg.goto(path)
        return pg

    def retry_clears(self, pg, err_sel: str, ok_expr: str, rule) -> None:
        """The inline error has Retry; once the server answers again Retry re-requests and recovers."""
        pg.wait_for("!!document.querySelector(%s)" % q(err_sel + " .fb-retry"), 20)
        self.assertEqual(self.text(pg, err_sel + " .fb-retry"), "Retry")
        self.assertIn("boom", self.text(pg, err_sel))
        hits = rule["hits"]
        self.assertGreaterEqual(hits, 1)
        pg.clear_intercepts()
        pg.click(err_sel + " .fb-retry")
        pg.wait_for(ok_expr, 30)
        self.assertFalse(pg.js("!!document.querySelector(%s)" % q(err_sel + " .fb-error")), "the error goes once Retry succeeds")


class AdminStates(StateMixin, UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        super(AdminStates, cls).setUpClass()
        seed_history(cls.server.data)
        upload_preset(cls.base)
        api(cls.base, "POST", "/api/v2/projects", {"name": "st-empty", "template": "blank"})
        cls.build = api(cls.base, "POST", "/api/v2/projects/campus-demo/builds", {"pdf": False, "png": False})["build"]
        cls.share = api(cls.base, "POST", "/api/v2/projects/campus-demo/shares", {"label": "Ushers", "scope": "all", "expires": ""})["share"]
        cls.backup = api(cls.base, "POST", "/api/v2/backups", {"label": "st-admin"})["backup"]

    def revisions(self) -> list:
        r = api(self.base, "GET", "/api/v2/projects/campus-demo/history?limit=1000")
        return [x["revision"] for x in r["revisions"]]

    # ------------------------------------------------------------------ skeletons

    def test_skeleton_until_the_list_loads(self):
        cases = [("history", "adm-history", "/history"), ("builds", "adm-builds", "/builds"),
                 ("settings/backups", "adm-settings", "/backups"), ("settings/sharing", "adm-settings", "/shares"),
                 ("imports", "adm-imports", "/overlay")]
        for path, cls_name, api_path in cases:
            for size in STATE_SIZES:
                with self.subTest(path=path, size=size):
                    pg = self.held("/" + P + path, size, api_path.replace("/", "\\/") + "(\\?|$)")
                    self.view(pg, cls_name)
                    pg.wait_for("!!document.querySelector('#app-main .adm-state > .fb-skeleton[aria-busy=true]')")
                    self.assertGreaterEqual(pg.js("window.__held()"), 1)
                    self.assertEqual(pg.js("document.querySelector('#app-main .adm-state > .fb-skeleton').getAttribute('data-kind')"), "table")
                    self.no_hscroll(pg, path + " skeleton")
                    pg.shot("st-admin-skeleton-%s-%s" % (path.replace("/", "-"), size))
                    pg.js("window.__release()")
                    pg.wait_for("!document.querySelector('#app-main .fb-skeleton') && " + LOADED, 20)

    # ------------------------------------------------------------------ load errors

    def test_load_failures_are_inline_with_retry(self):
        cases = [("history", "adm-history", "/api/v2/projects/campus-demo/history*", ".adm-history .adm-state"),
                 ("builds", "adm-builds", "/api/v2/projects/campus-demo/builds", ".adm-builds .adm-state"),
                 ("settings/backups", "adm-settings", "/api/v2/backups", ".adm-panel .adm-state"),
                 ("settings/sharing", "adm-settings", "/api/v2/projects/campus-demo/shares", ".adm-panel .adm-state"),
                 ("settings/users", "adm-settings", "/api/v2/users", ".adm-panel .adm-state"),
                 ("imports", "adm-imports", "/api/v2/projects/campus-demo/overlay", ".adm-imports .adm-state:not(:empty)")]
        for path, cls_name, pattern, err in cases:
            for size in STATE_SIZES:
                with self.subTest(path=path, size=size), self.open(P + path, size, intercepts=[(pattern, 500, BOOM, "GET")]) as pg:
                    self.view(pg, cls_name)
                    pg.wait_for("!!document.querySelector(%s)" % q(err + " .fb-error[role=alert]"), 20)
                    self.no_hscroll(pg, path + " error")
                    pg.shot("st-admin-error-%s-%s" % (path.replace("/", "-"), size))
                    ok = "!!document.querySelector('[data-table=\"imports.overlay\"] tr.dt-row')" if path == "imports" else LOADED
                    self.retry_clears(pg, err, ok, pg.rules[0])

    # ------------------------------------------------------------------ imports

    def test_overlay_stale_badge_refreshes(self):
        ovl = api(self.base, "GET", "/api/v2/projects/campus-demo/overlay")
        ovl["revision"] = 0
        for size in STATE_SIZES:
            with self.subTest(size=size), self.open(P + "imports", size, intercepts=[("/api/v2/projects/campus-demo/overlay", 200, ovl, "GET")]) as pg:
                self.view(pg, "adm-imports")
                pg.wait_for("!!document.querySelector('.adm-sec-head .fb-stale.fb-is-stale:not([hidden])')", 20)
                self.assertIn("Stale", self.text(pg, ".adm-sec-head .fb-stale"))
                self.assertEqual(pg.js("document.querySelector('.adm-sec-head .fb-stale').getAttribute('data-reason')"), "revision")
                self.no_hscroll(pg, "imports stale")
                pg.js("document.querySelector('.adm-sec-head').scrollIntoView({block: 'start'})")
                pg.shot("st-admin-imports-stale-%s" % size)
                pg.clear_intercepts()
                pg.click(".adm-sec-head .fb-stale-refresh")
                pg.wait_for("document.querySelector('.adm-sec-head .fb-stale').hidden", 20)

    def test_import_upload_failure_is_inline_and_retry_uploads(self):
        for size, last in each_size():
            with self.subTest(size=size), self.open(P + "imports", size, intercepts=[("/api/v2/projects/campus-demo/imports?*", 500, BOOM, "POST")]) as pg:
                self.view(pg, "adm-imports")
                card = ".adm-card[data-importer=dante]"
                pg.wait_for("!!document.querySelector(%s)" % q(card + " input[type=file]"))
                pg.js("""(function () {
                  var dt = new DataTransfer();
                  dt.items.add(new File([%s], 'stage.xml', {type: 'text/xml'}));
                  document.querySelector(%s).files = dt.files;
                })()""" % (q(DANTE_PRESET), q(card + " input[type=file]")))
                self.assertEqual(pg.js("document.querySelector(%s).files.length" % q(card + " input[type=file]")), 1)
                pg.click(card + " button.primary")
                out = card + " .imp-out"
                pg.wait_for("!!document.querySelector(%s)" % q(out + " .fb-error"), 20)
                self.assertIn("Could not import stage.xml", self.text(pg, out))
                self.no_hscroll(pg, "import upload error")
                pg.js("document.querySelector(%s).scrollIntoView({block: 'center'})" % q(out))
                pg.shot("st-admin-imports-upload-error-%s" % size)
                if last:
                    self.retry_clears(pg, out, "!!document.querySelector(%s)" % q(out + " .imp-sum"), pg.rules[0])

    def test_remove_import_confirms_scope(self):
        imp = api(self.base, "GET", "/api/v2/projects/campus-demo")
        imp = (imp.get("doc", imp).get("imports") or [])[0]
        sel = "[data-table=\"imports.registered\"] tr.dt-row[data-id=%s] .adm-acts button.danger" % q(imp["id"])
        for size, _ in each_size():
            with self.subTest(size=size), self.open(P + "imports", size) as pg:
                self.view(pg, "adm-imports")
                pg.wait_for("!!document.querySelector(%s)" % q(sel))
                pg.click(sel)
                text = self.dialog_text(pg)
                self.assertIn("Remove import " + imp["path"] + "?", text)
                self.assertIn("Remove + delete files", text)
                pg.shot("st-admin-imports-remove-confirm-%s" % size)
                self.dismiss(pg)
                self.assertTrue(pg.js("!!document.querySelector(%s)" % q(sel)), "cancel removes nothing")

    # ------------------------------------------------------------------ history

    def test_history_empty_copy(self):
        for size in STATE_SIZES:
            with self.subTest(size=size), self.open(P + "history", size, intercepts=[("/api/v2/projects/campus-demo/history*", 200, {"revisions": []}, "GET")]) as pg:
                self.view(pg, "adm-history")
                pg.wait_for("!!document.querySelector('.adm-history .dt-empty .fb-empty')", 20)
                text = self.text(pg, ".adm-history .fb-empty")
                self.assertIn("No revisions yet", text)
                self.assertIn("Every save creates one", text)
                self.no_hscroll(pg, "history empty")
                pg.shot("st-admin-history-empty-%s" % size)

    def test_history_restore_confirms_with_numbers_and_failure_retries(self):
        revs = self.revisions()
        latest = max(revs)
        restore = "(function () { return Array.prototype.filter.call(document.querySelectorAll('.adm-history tr.dt-row[data-id=\"1\"] .adm-acts button'), function (b) { return b.textContent === 'Restore'; })[0]; })()"
        for size, last in each_size():
            with self.subTest(size=size), self.open(P + "history", size, intercepts=[("/api/v2/projects/campus-demo/history/1/restore", 500, BOOM, "POST")]) as pg:
                self.view(pg, "adm-history")
                pg.wait_for("document.querySelectorAll('.adm-history tr.dt-row').length === %d" % len(revs), 20)
                pg.js(restore + ".click()")
                text = self.dialog_text(pg)
                self.assertIn("Restore revision 1?", text)
                self.assertIn("This creates revision %d." % (latest + 1), text)
                pg.shot("st-admin-history-restore-confirm-%s" % size)
                self.dismiss(pg)
                if not last:
                    continue
                pg.js(restore + ".click()")
                self.dialog_text(pg)
                self.confirm(pg)
                err = ".adm-history .adm-state"
                pg.wait_for("!!document.querySelector(%s)" % q(err + " .fb-error"), 20)
                self.assertIn("Could not restore revision 1", self.text(pg, err))
                self.no_hscroll(pg, "history restore error")
                self.retry_clears(pg, err, "document.querySelectorAll('.adm-history tr.dt-row').length === %d" % (len(revs) + 1), pg.rules[0])
        self.assertEqual(max(self.revisions()), latest + 1)

    # ------------------------------------------------------------------ builds

    def test_builds_empty_has_the_build_action(self):
        for size in STATE_SIZES:
            with self.subTest(size=size), self.open("#/st-empty//builds", size) as pg:
                self.view(pg, "adm-builds")
                pg.wait_for("!!document.querySelector('.adm-builds .dt-empty .fb-empty')", 20)
                text = self.text(pg, ".adm-builds .fb-empty")
                self.assertIn("No builds yet", text)
                self.assertIn("PDF/HTML pack", text)
                self.assertEqual(self.text(pg, ".adm-builds .fb-empty .fb-empty-action"), "Build package")
                self.no_hscroll(pg, "builds empty")
                pg.js("document.querySelector('.adm-builds .fb-empty').scrollIntoView({block: 'center'})")
                pg.shot("st-admin-builds-empty-%s" % size)

    def test_build_and_delete_failures_are_inline(self):
        for size, last in each_size():
            with self.subTest(size=size), self.open(P + "builds", size, intercepts=[("/api/v2/projects/campus-demo/builds", 500, BOOM, "POST")]) as pg:
                self.view(pg, "adm-builds")
                pg.wait_for("document.querySelectorAll('.adm-builds tr.dt-row').length > 0", 20)
                n = self.rows(pg, ".adm-builds")
                pg.click("#bld-go")
                pg.wait_for("!!document.querySelector('.adm-build-err .fb-error')", 30)
                self.assertIn("Build failed", self.text(pg, ".adm-build-err"))
                self.assertTrue(pg.js("!!document.querySelector('.adm-build-err .fb-retry')"))
                self.no_hscroll(pg, "build error")
                pg.shot("st-admin-builds-build-error-%s" % size)
                if not last:
                    continue
                pg.clear_intercepts()
                pg.intercept("/api/v2/projects/campus-demo/builds/*", 500, BOOM, "DELETE")
                pg.click("tr.dt-row[data-id=%s] .adm-acts button.danger" % q(self.build))
                self.assertIn("Delete build " + self.build + "?", self.dialog_text(pg))
                self.confirm(pg)
                self.retry_clears(pg, ".adm-builds .adm-state", "document.querySelectorAll('.adm-builds tr.dt-row').length === %d" % (n - 1), pg.rules[0])

    # ------------------------------------------------------------------ settings

    def test_share_revoke_confirms_and_failure_retries(self):
        tok = self.share["token"]
        for size, last in each_size():
            with self.subTest(size=size), self.open(P + "settings/sharing", size, intercepts=[("/api/v2/projects/campus-demo/shares/*", 500, BOOM, "DELETE")]) as pg:
                self.view(pg, "adm-settings")
                row = ".adm-panel tr.dt-row[data-id=%s]" % q(tok)
                pg.wait_for("!!document.querySelector(%s)" % q(row), 20)
                pg.click(row + " .adm-acts button.danger")
                text = self.dialog_text(pg)
                self.assertIn("Revoke share link \u201cUshers\u201d?", text)
                self.assertIn("loses access", text)
                pg.shot("st-admin-share-revoke-confirm-%s" % size)
                if not last:
                    self.dismiss(pg)
                    continue
                self.confirm(pg)
                self.retry_clears(pg, ".adm-panel .adm-state", "!document.querySelector(%s)" % q(row), pg.rules[0])

    def test_backup_delete_and_restore_confirm_scope(self):
        name = self.backup["name"]
        listed = [b for b in api(self.base, "GET", "/api/v2/backups")["backups"] if b["name"] == name][0]
        n = len(listed.get("projects") or [])
        for size, _ in each_size():
            with self.subTest(size=size), self.open(P + "settings/backups", size) as pg:
                self.view(pg, "adm-settings")
                row = ".adm-panel tr.dt-row[data-id=%s]" % q(name)
                pg.wait_for("!!document.querySelector(%s)" % q(row), 20)
                pg.click(row + " button[aria-label^=Delete]")
                self.assertIn("Delete backup " + name + "?", self.dialog_text(pg))
                pg.shot("st-admin-backup-delete-confirm-%s" % size)
                self.dismiss(pg)
                pg.js("Array.prototype.filter.call(document.querySelectorAll(%s), function (b) { return b.textContent === 'Restore'; })[0].click()" % q(row + " .adm-acts button"))
                text = self.dialog_text(pg)
                self.assertIn("Restore backup " + name + "?", text)
                self.assertIn("%d project%s" % (n, "" if n == 1 else "s"), text)
                self.assertIn("pre-restore", text)
                self.assertIn("Replace everything", text)
                pg.shot("st-admin-backup-restore-confirm-%s" % size)
                self.dismiss(pg)
                self.assertTrue(pg.js("!!document.querySelector(%s)" % q(row)))

    def test_settings_row_deletes_confirm_scope(self):
        for size, _ in each_size():
            with self.subTest(size=size), self.open(P + "settings/networks", size) as pg:
                self.view(pg, "adm-settings")
                pg.wait_for("!!document.querySelector('.adm-panel tr.dt-row[data-id=mgmt]')", 20)
                n = self.rows(pg, ".adm-panel")
                pg.click(".adm-panel tr.dt-row[data-id=mgmt] .adm-acts button.danger")
                text = self.dialog_text(pg)
                self.assertRegex(text, r"Delete network .+\?")
                pg.shot("st-admin-settings-row-delete-confirm-%s" % size)
                self.dismiss(pg)
                self.assertEqual(self.rows(pg, ".adm-panel"), n)


class DiscoveryStates(StateMixin, UiCase):
    rid = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls._old = {k: os.environ.get(k) for k in DISC_ENV}
        os.environ.update(DISC_ENV)
        super(DiscoveryStates, cls).setUpClass()
        api(cls.base, "POST", "/api/v2/projects", {"name": "st-norun", "template": "blank"})
        cls.rid = cls._run("campus-demo")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            super(DiscoveryStates, cls).tearDownClass()
        finally:
            for k, v in cls._old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @classmethod
    def _run(cls, project: str) -> str:
        base = "/api/v2/projects/%s/discovery/runs" % project
        rid = api(cls.base, "POST", base, {"window": 10})["run"]["id"]
        t0 = time.time()
        while time.time() - t0 < 60:
            if not api(cls.base, "GET", base + "/" + rid)["run"]["active"]:
                return rid
            time.sleep(0.1)
        raise AssertionError("discovery run %s did not finish" % rid)

    def tab(self, pg, name: str) -> None:
        pg.click("[data-disc-tab=%s]" % name)
        pg.wait_for("document.querySelector('.disc-tab-body').dataset.discTab === %s" % q(name))
        pg.wait_for("!document.querySelector('.disc-tab-body .fb-skeleton')", 20)

    def test_skeleton_per_tab_while_findings_load(self):
        for size in STATE_SIZES:
            with self.subTest(size=size):
                pg = self.held("/#/campus-demo/main/discovery/new?run=" + self.rid, size, "\\/findings(\\?|$)")
                pg.wait_for("!!document.querySelector('.disc-tab-body > .fb-skeleton[aria-busy=true]')", 20)
                self.assertEqual(pg.js("document.querySelector('.disc-tab-body').dataset.discTab"), "new")
                self.no_hscroll(pg, "discovery skeleton")
                pg.shot("st-admin-discovery-skeleton-%s" % size)
                pg.js("window.__release()")
                pg.wait_for("!!document.querySelector('.disc-tab-body .dt-table')", 20)

    def test_empty_copy_on_every_findings_tab(self):
        path = "/api/v2/projects/campus-demo/discovery/runs/%s/findings" % self.rid
        f = api(self.base, "GET", path)
        f.update({"entities": [], "rows": [], "connections": [], "networks": []})
        f["counts"] = dict(f.get("counts") or {}, new=0, matched=0, possible=0, connections=0, networks=0, unresolved=0, ignored=0)
        expect = {"new": ("No new devices in this run", "Start a run or pick another one"),
                  "matches": ("No matches in this run", "New devices"),
                  "connections": ("No connections in this run", "Sources"),
                  "networks": ("No networks in this run", "UniFi"),
                  "unresolved": ("Nothing unresolved in this run", "MAC address"),
                  "changes": ("Nothing to compare yet", "first completed run")}
        for size in STATE_SIZES:
            with self.subTest(size=size), self.open("#/campus-demo/main/discovery/new?run=" + self.rid, size, intercepts=[(path, 200, f, "GET")]) as pg:
                pg.wait_for("!!document.querySelector('.disc-tab-body .fb-empty')", 20)
                self.assertEqual(pg.js("document.querySelector('.disc-review').children.length"), 0, "no review badge at 0")
                for tab, words in expect.items():
                    self.tab(pg, tab)
                    pg.wait_for("!!document.querySelector('.disc-tab-body .fb-empty')", 20)
                    text = self.text(pg, ".disc-tab-body .fb-empty")
                    for w in words:
                        self.assertIn(w, text, "%s/%s" % (size, tab))
                    self.no_hscroll(pg, "discovery empty " + tab)
                    pg.shot("st-admin-discovery-empty-%s-%s" % (tab, size))

    def test_no_runs_offers_the_run_action(self):
        for size in STATE_SIZES:
            with self.subTest(size=size), self.open("#/st-norun//discovery", size) as pg:
                pg.wait_for("!!document.querySelector('.disc-findings .fb-empty')", 20)
                self.assertIn("No runs yet", self.text(pg, ".disc-findings .fb-empty"))
                self.assertEqual(self.text(pg, ".disc-findings .fb-empty-action"), "Run discovery")
                self.no_hscroll(pg, "discovery no runs")
                pg.shot("st-admin-discovery-no-runs-%s" % size)

    def test_run_start_failure_is_inline_and_retry_starts_it(self):
        before = len(api(self.base, "GET", "/api/v2/projects/st-norun/discovery/runs")["runs"])
        for size, last in each_size():
            with self.subTest(size=size), self.open("#/st-norun//discovery", size, intercepts=[("/api/v2/projects/st-norun/discovery/runs", 500, BOOM, "POST")]) as pg:
                pg.wait_for("!!document.querySelector('.disc-run-btn') && !document.querySelector('.disc-run-btn').disabled", 20)
                pg.click(".disc-run-btn")
                err = ".disc-run-err"
                pg.wait_for("!!document.querySelector(%s)" % q(err + " .fb-error"), 20)
                self.assertIn("Could not start the run", self.text(pg, err))
                self.no_hscroll(pg, "run start error")
                pg.shot("st-admin-discovery-start-error-%s" % size)
                if last:
                    self.retry_clears(pg, err, "!!document.querySelector('.disc-run .disc-run-id')", pg.rules[0])
        t0 = time.time()
        while time.time() - t0 < 30 and len(api(self.base, "GET", "/api/v2/projects/st-norun/discovery/runs")["runs"]) == before:
            time.sleep(0.2)
        self.assertEqual(len(api(self.base, "GET", "/api/v2/projects/st-norun/discovery/runs")["runs"]), before + 1)

    def test_source_save_and_test_failures_sit_beside_the_form(self):
        for size, last in each_size():
            with self.subTest(size=size), self.open("#/campus-demo/main/discovery/new?run=" + self.rid, size) as pg:
                pg.wait_for("!!document.querySelector('.disc-card .disc-card-acts')", 20)
                pg.js("document.querySelector('details.disc-sources').open = true")
                card = ".disc-card[data-probe]:not(.disc-install)"
                pid = pg.js("document.querySelector(%s).getAttribute('data-probe')" % q(card))
                card = ".disc-card[data-probe=%s]" % q(pid)
                out = card + " .disc-test-out"
                rule = pg.intercept("/api/v2/projects/campus-demo/discovery/settings", 500, BOOM, "PUT")
                pg.click(card + " .disc-card-acts button.primary")
                pg.wait_for("!!document.querySelector(%s)" % q(out + " .fb-error"), 20)
                self.assertIn("Could not save", self.text(pg, out))
                self.no_hscroll(pg, "source save error")
                pg.js("document.querySelector(%s).scrollIntoView({block: 'center'})" % q(out))
                pg.shot("st-admin-discovery-source-save-error-%s" % size)
                if last:
                    pg.js("document.querySelector(%s).__stale = 1" % q(card))
                    # A save that goes through re-renders the source cards.
                    self.retry_clears(pg, out, "!!document.querySelector(%s) && !document.querySelector(%s).__stale" % (q(card), q(card)), rule)
                    pg.js("document.querySelector('details.disc-sources').open = true")
                pg.clear_intercepts()
                rule = pg.intercept("/api/v2/projects/campus-demo/discovery/test", 500, BOOM, "POST")
                pg.click(card + " .disc-card-acts button:not(.primary)")
                pg.wait_for("!!document.querySelector(%s)" % q(out + " .fb-error .fb-retry"), 20)
                self.assertIn("Could not test", self.text(pg, out))
                self.assertEqual(rule["hits"], 1)
                pg.shot("st-admin-discovery-source-test-error-%s" % size)

    def test_promote_failure_is_inline_and_retry_promotes(self):
        for size, last in each_size():
            with self.subTest(size=size), self.open("#/campus-demo/main/discovery/new?run=" + self.rid, size,
                                                    intercepts=[("/api/v2/projects/campus-demo/discovery/runs/*/findings/promote", 500, BOOM, "POST")]) as pg:
                pg.wait_for("!!document.querySelector('.disc-tab-body tr.dt-row .disc-actions button.primary')", 20)
                n = self.rows(pg, ".disc-tab-body")
                pg.click(".disc-tab-body tr.dt-row .disc-actions button.primary")
                err = ".disc-act-err"
                pg.wait_for("!!document.querySelector(%s)" % q(err + " .fb-error"), 20)
                self.assertIn("Could not apply the change", self.text(pg, err))
                self.no_hscroll(pg, "promote error")
                pg.js("document.querySelector('.disc-act-err').scrollIntoView({block: 'center'})")
                pg.shot("st-admin-discovery-promote-error-%s" % size)
                if last:
                    self.retry_clears(pg, err, "document.querySelectorAll('.disc-tab-body tr.dt-row').length === %d" % (n - 1), pg.rules[0])


class RoleStates(StateMixin, UiCase):
    """Login on: an admin's user delete confirms; a viewer gets the states without any write action."""

    @classmethod
    def setUpClass(cls) -> None:
        super(RoleStates, cls).setUpClass()
        from fathom import users

        seed_history(cls.server.data)
        api(cls.base, "POST", "/api/v2/projects", {"name": "st-empty", "template": "blank"})
        for name, role in (("admin1", "admin"), ("viewer1", "viewer"), ("temp1", "editor")):
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

    def test_admin_user_remove_confirms_scope(self):
        for size, last in each_size():
            with self.subTest(size=size):
                pg = self.signed_in("admin1", "/" + P + "settings/users", size)
                row = ".adm-panel tr.dt-row[data-id=temp1]"
                pg.wait_for("!!document.querySelector(%s)" % q(row), 20)
                pg.js("Array.prototype.filter.call(document.querySelectorAll(%s), function (b) { return b.textContent === 'Remove'; })[0].click()" % q(row + " .adm-acts button"))
                text = self.dialog_text(pg)
                self.assertIn("Remove user temp1?", text)
                self.assertIn("Remove user", pg.js("document.querySelector('.app-dialog footer button:last-child').textContent"))
                pg.shot("st-admin-user-remove-confirm-%s" % size)
                if not last:
                    self.dismiss(pg)
                    continue
                self.confirm(pg)
                pg.wait_for("!document.querySelector(%s)" % q(row), 20)
                self.no_hscroll(pg, "user removed")

    def test_viewer_gets_states_without_write_actions(self):
        for size, last in each_size():
            with self.subTest(size=size):
                pg = self.signed_in("viewer1", "/#/st-empty//builds", size)
                pg.wait_for("!!document.querySelector('.adm-builds .fb-empty')", 20)
                self.assertIn("No builds yet", self.text(pg, ".adm-builds .fb-empty"))
                self.assertFalse(pg.js("!!document.querySelector('.adm-builds .fb-empty-action, #bld-go')"), "viewer: no Build action")
                self.no_hscroll(pg, "viewer builds empty")
                pg.shot("st-admin-viewer-builds-empty-%s" % size)
                pg.goto("#/st-empty//discovery")
                pg.wait_for("!!document.querySelector('.disc-findings .fb-empty')", 20)
                self.assertIn("has not been run", self.text(pg, ".disc-findings .fb-empty"))
                self.assertFalse(pg.js("!!document.querySelector('.disc-findings .fb-empty-action, .disc-run-btn')"), "viewer: no Run action")
                pg.shot("st-admin-viewer-discovery-no-runs-%s" % size)
                if not last:
                    continue
                pg.goto("#/campus-demo/main/history")
                pg.wait_for("document.querySelectorAll('.adm-history tr.dt-row').length > 0", 20)
                self.assertEqual(pg.js("Array.prototype.filter.call(document.querySelectorAll('.adm-history .adm-acts button'), function (b) { return b.textContent === 'Restore'; }).length"), 0)
                pg.goto("#/campus-demo/main/imports")
                pg.wait_for("!!document.querySelector('#app-main .adm-imports')", 20)
                self.assertEqual(pg.js("document.querySelectorAll('.adm-imports .adm-acts button.danger, .adm-imports .adm-card input[type=file], .adm-ovl .disc-actions button').length"), 0)


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
