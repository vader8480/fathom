"""WIZARD UI tests (docs/ui-audit.md B.2 WIZARD) on the dev harness ``/static/dev/wizard.html``.

The harness runs ``bulkAdd`` and ``openWizard`` on the ``sunday-demo`` fixture with a fake ctx whose
``commit`` records ``{label, ops}`` in ``window.__wz.commits`` instead of calling the API. Covered: the
step list advances with ``aria-current``; Next stays disabled on errors; inline errors are tied to their
field with ``aria-describedby``; Back keeps data; the preview DataTable marks invalid rows and only lets
valid rows be selected; review, one commit (one undo step) and the result link; Esc asks before
discarding; the focus trap; read-only; full screen at m with no horizontal page scroll at 390 px.
Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/wizard.html"


class WizardUi(UiCase):

    # ------------------------------------------------------------ helpers

    def _open(self, pg, kind):
        pg.click("#wz-h-" + kind)
        pg.wait_for("!!document.querySelector('.wz .wz-body') && document.querySelector('.wz').getAttribute('data-step')")
        pg.wait_for("document.querySelector('.wz').getAnimations().every(function (a) { return a.playState !== 'running'; })")

    def _step(self, pg):
        return pg.js("(function () { var li = document.querySelector('.wz-steps li[aria-current=step]');"
                     " return li ? li.getAttribute('data-step') : null; })()")

    def _wait_step(self, pg, key):
        pg.wait_for("(document.querySelector('.wz-steps li[aria-current=step]') || {}).getAttribute"
                    " && document.querySelector('.wz-steps li[aria-current=step]').getAttribute('data-step') === %s"
                    % json.dumps(key))

    def _next_disabled(self, pg):
        return pg.js("document.querySelector('.wz .wz-next').disabled")

    def _paste(self, pg, kind):
        pg.js("(function () { var ta = document.querySelector('.wz textarea[name=text]'); ta.focus();"
              " ta.value = window.__wz.samples[%s]; ta.dispatchEvent(new Event('input', {bubbles: true})); })()"
              % json.dumps(kind))

    def _next(self, pg, key):
        pg.wait_for("!document.querySelector('.wz .wz-next').disabled")
        pg.click(".wz .wz-next")
        self._wait_step(pg, key)

    # ------------------------------------------------------------ tests

    def test_bulk_add_devices_end_to_end(self):
        with self.open(HARNESS, "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self._open(pg, "devices")
            dlg = pg.js("""(function () { var w = document.querySelector('.wz');
              var t = document.getElementById(w.getAttribute('aria-labelledby'));
              return {role: w.getAttribute('role'), modal: w.getAttribute('aria-modal'), title: t && t.textContent,
                      steps: Array.prototype.map.call(document.querySelectorAll('ol.wz-steps > li'), function (li) { return li.getAttribute('data-step'); })}; })()""")
            self.assertEqual(dlg["role"], "dialog")
            self.assertEqual(dlg["modal"], "true")
            self.assertEqual(dlg["title"], "Bulk add devices")
            self.assertEqual(dlg["steps"], ["paste", "map", "preview", "review", "result"])
            self.assertEqual(self._step(pg), "paste")
            self.assertTrue(self._next_disabled(pg), "Next is disabled on an empty paste")

            self._paste(pg, "devices")
            self.assertIn("7 rows", pg.js("document.querySelector('.wz-paste-sum').textContent"))
            self.assertIn("tab-separated", pg.js("document.querySelector('.wz-paste-sum').textContent"))
            self._next(pg, "map")
            mapping = pg.js("Array.prototype.map.call(document.querySelectorAll('.wz-map select'), function (s) { return s.value; })")
            self.assertEqual(mapping, ["name", "room", "status", "kind", "manufacturer", "model", "serial"])

            # unmapping Name blocks Next and says why
            pg.js("(function () { var s = document.querySelector('.wz select[name=col-0]'); s.value = '';"
                  " s.dispatchEvent(new Event('change', {bubbles: true})); })()")
            self.assertTrue(self._next_disabled(pg))
            self.assertIn("Name", pg.js("document.querySelector('.wz .wz-errors').textContent"))
            pg.js("(function () { var s = document.querySelector('.wz select[name=col-0]'); s.value = 'name';"
                  " s.dispatchEvent(new Event('change', {bubbles: true})); })()")
            self.assertFalse(self._next_disabled(pg))

            self._next(pg, "preview")
            pg.wait_for("document.querySelectorAll('.wz .dt-root tbody tr[data-id]').length === 7")
            prev = pg.js("""(function () {
              var rows = Array.prototype.slice.call(document.querySelectorAll('.wz .dt-root tbody tr[data-id]'));
              return rows.map(function (tr) { var cb = tr.querySelector('input.wz-inc');
                return {id: tr.getAttribute('data-id'), bad: tr.classList.contains('wz-row-bad'), checked: cb.checked, disabled: cb.disabled}; }); })()""")
            bad = sorted(r["id"] for r in prev if r["bad"])
            self.assertEqual(bad, ["5", "6", "7"], "unknown room, blank name and bad status rows are flagged")
            for r in prev:
                self.assertEqual(r["disabled"], r["bad"], "only valid rows are selectable: %r" % r)
                self.assertEqual(r["checked"], not r["bad"])
            self.assertIn("4 of 7 rows selected", pg.js("document.querySelector('.wz-preview-sum').textContent"))
            self.assertIn("Unknown room", pg.js("document.querySelector('.wz tr[data-id=\"5\"]').textContent"))
            self.assertTrue(pg.js("document.querySelectorAll('.wz .dt-root th').length > 0 && "
                                  "Array.prototype.every.call(document.querySelectorAll('.wz .dt-root thead th'), function (th) { return th.getAttribute('scope') === 'col'; })"))

            # Back keeps the mapping and the pasted text
            pg.click(".wz .wz-back")
            self._wait_step(pg, "map")
            self.assertEqual(pg.js("document.querySelector('.wz select[name=col-0]').value"), "name")
            pg.click(".wz .wz-back")
            self._wait_step(pg, "paste")
            self.assertTrue(pg.js("document.querySelector('.wz textarea[name=text]').value === window.__wz.samples.devices"))
            self._next(pg, "map")
            self._next(pg, "preview")

            # deselecting every row blocks Next
            pg.click(".wz .wz-none")
            self.assertTrue(self._next_disabled(pg))
            self.assertIn("at least one valid row", pg.js("document.querySelector('.wz .wz-errors').textContent"))
            pg.click(".wz .wz-all")
            self.assertFalse(self._next_disabled(pg))

            self._next(pg, "review")
            self.assertEqual(pg.js("document.querySelector('.wz .wz-review-title').textContent"), "Add 4 devices to Main Auditorium")
            self.assertEqual(pg.js("document.querySelector('.wz .wz-next').textContent"), "Add 4 devices")
            self.assertEqual(pg.js("window.__wz.commits.length"), 0, "nothing is written before Submit")
            self._next(pg, "result")
            commits = pg.js("window.__wz.commits")
            self.assertEqual(len(commits), 1, "one commit = one undo step")
            self.assertEqual(commits[0]["label"], "Bulk add 4 devices")
            self.assertEqual([o["op"] + " " + o["coll"] for o in commits[0]["ops"]], ["put devices"] * 4)
            self.assertEqual(sorted(o["id"] for o in commits[0]["ops"]), ["choir-mic-l", "choir-mic-r", "confidence-monitor", "lectern-mic"])
            lectern = [o["value"] for o in commits[0]["ops"] if o["id"] == "lectern-mic"][0]
            self.assertEqual((lectern["room"], lectern["kind"], lectern["status"], lectern["inventory"]["serial"]), ("main", "mic", "planned", "SN-1001"))
            res = pg.js("""(function () { var a = document.querySelector('.wz .wz-result-link');
              return {text: document.querySelector('.wz .wz-result-text').textContent, href: a && a.getAttribute('href')}; })()""")
            self.assertIn("Added 4 devices to Main Auditorium.", res["text"])
            self.assertTrue(res["href"].startswith("#/sunday-demo/main/devices?hl=lectern-mic&f.id="), res["href"])
            self.assertEqual(pg.js("document.querySelector('.wz .wz-back').hidden"), True)
            self.assertEqual(pg.js("window.__wz.store.undoLabel"), "Bulk add 4 devices")

            pg.click(".wz .wz-next")
            pg.wait_for("!document.querySelector('.wz')")
            pg.wait_for("window.__wz.results.length === 1")
            self.assertEqual(pg.js("window.__wz.results[0].count"), 4)
            self.assertEqual(pg.js("document.activeElement && document.activeElement.id"), "wz-h-devices", "focus returns to the opener")
            pg.shot("wizard-devices-done-d")

    def test_bulk_add_cables(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg, "cables")
            self.assertEqual(pg.js("document.getElementById(document.querySelector('.wz').getAttribute('aria-labelledby')).textContent"), "Bulk add cables")
            self._paste(pg, "cables")
            self._next(pg, "map")
            self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.wz-map select'), function (s) { return s.value; })"),
                             ["from", "to", "tag", "type", "length_m"])
            self._next(pg, "preview")
            pg.wait_for("document.querySelectorAll('.wz .dt-root tbody tr[data-id]').length === 4")
            self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.wz tr.wz-row-bad'), function (tr) { return tr.getAttribute('data-id'); })"), ["4"])
            self.assertIn("Unknown device", pg.js("document.querySelector('.wz tr[data-id=\"4\"]').textContent"))
            self._next(pg, "review")
            self.assertEqual(pg.js("document.querySelector('.wz .wz-review-title').textContent"), "Add 3 cables in Main Auditorium")
            self._next(pg, "result")
            commits = pg.js("window.__wz.commits")
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0]["label"], "Bulk add 3 cables")
            ops = commits[0]["ops"]
            self.assertEqual([o["op"] + " " + o["coll"] for o in ops], ["put cables"] * 3)
            first = [o["value"] for o in ops if o["value"].get("tag") == "A-101"][0]
            self.assertEqual(first["from"], {"device": "main-speakers", "port": "thru-1"})
            self.assertEqual(first["to"], {"device": "audio-rack-1", "port": "analog-in-5"})
            href = pg.js("document.querySelector('.wz .wz-result-link').getAttribute('href')")
            self.assertTrue(href.startswith("#/sunday-demo/main/schedules/cables?hl="), href)

    def test_submit_failure_shows_inline_error_with_retry(self):
        with self.open(HARNESS + "?open=devices&step=review", "d") as pg:
            self._wait_step(pg, "review")
            pg.js("window.__wz.failNext = true")
            pg.click(".wz .wz-next")
            pg.wait_for("!!document.querySelector('.wz .fb-error[role=alert]')")
            self.assertIn("Nothing was added", pg.js("document.querySelector('.wz .fb-error').textContent"))
            self.assertEqual(self._step(pg), "review")
            self.assertEqual(pg.js("window.__wz.commits.length"), 0)
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.wz .fb-retry')"))
            pg.click(".wz .fb-retry")
            self._wait_step(pg, "result")
            self.assertEqual(pg.js("window.__wz.commits.length"), 1)

    def test_inline_errors_and_describedby(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg, "generic")
            self.assertTrue(self._next_disabled(pg))
            self.assertFalse(pg.js("!!document.querySelector('.wz .wz-err')"), "no error before the field is touched")
            pg.click(".wz input[name=label]")
            pg.command("Input.insertText", {"text": "x"})
            pg.press("Backspace")
            err = pg.js("""(function () { var i = document.querySelector('.wz input[name=label]'); var p = document.querySelector('.wz .wz-err');
              return {text: p && p.textContent, id: p && p.id, desc: i.getAttribute('aria-describedby'), invalid: i.getAttribute('aria-invalid')}; })()""")
            self.assertIn("Give the link a name", err["text"])
            self.assertIn(err["id"], (err["desc"] or "").split())
            self.assertEqual(err["invalid"], "true")
            self.assertTrue(self._next_disabled(pg))
            pg.command("Input.insertText", {"text": "Choir"})
            self.assertFalse(pg.js("!!document.querySelector('.wz .wz-err')"))
            self.assertIsNone(pg.js("document.querySelector('.wz input[name=label]').getAttribute('aria-describedby')"))
            self.assertFalse(self._next_disabled(pg))
            pg.press("Enter")
            self._wait_step(pg, "expiry")
            self.assertEqual(pg.js("document.querySelectorAll('.wz-steps li.wz-done').length"), 1)
            pg.click(".wz .wz-back")
            self._wait_step(pg, "name")
            self.assertEqual(pg.js("document.querySelector('.wz input[name=label]').value"), "Choir", "Back keeps data")

    def test_escape_asks_before_discarding(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg, "devices")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.wz')")  # nothing entered: closes at once
            self._open(pg, "devices")
            self._paste(pg, "devices")
            pg.press("Escape")
            pg.wait_for("!!document.querySelector('#app-dialog .app-dialog-backdrop')")
            self.assertIn("Discard", pg.js("document.querySelector('#app-dialog .app-dialog-backdrop').textContent"))
            self.assertTrue(pg.js("!!document.querySelector('.wz')"))
            pg.press("Escape")  # cancels the confirmation only
            pg.wait_for("!document.querySelector('#app-dialog .app-dialog-backdrop')")
            self.assertTrue(pg.js("!!document.querySelector('.wz')"))
            self.assertEqual(self._step(pg), "paste")
            pg.click(".wz .wz-close")
            pg.wait_for("!!document.querySelector('#app-dialog .app-dialog-backdrop')")
            pg.click("#app-dialog .app-dialog-backdrop footer button.danger")
            pg.wait_for("!document.querySelector('.wz')")
            pg.wait_for("window.__wz.results.length === 2")
            self.assertEqual(pg.js("window.__wz.results"), [None, None])
            self.assertEqual(pg.js("window.__wz.commits.length"), 0)

    def test_focus_trap(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg, "generic")
            pg.command("Input.insertText", {"text": "Choir"})
            for _ in range(6):
                pg.press("Tab")
                self.assertTrue(pg.js("document.querySelector('.wz').contains(document.activeElement)"), "Tab stays inside the wizard")
            pg.js("document.querySelector('.wz .wz-close').focus()")
            pg.press("Shift+Tab")
            self.assertTrue(pg.js("document.activeElement === document.querySelector('.wz .wz-next')"), "Shift+Tab from the first control wraps to the last")

    def test_read_only_store_opens_nothing(self):
        with self.open(HARNESS + "?readonly=1", "d") as pg:
            pg.click("#wz-h-devices")
            pg.wait_for("window.__wz.results.length === 1")
            self.assertIsNone(pg.js("window.__wz.results[0]"))
            self.assertFalse(pg.js("!!document.querySelector('.wz')"))

    def test_phone_full_screen_without_horizontal_scroll(self):
        with self.open(HARNESS, "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self._open(pg, "devices")
            box = pg.rect(".wz")
            self.assertEqual((round(box["left"]), round(box["top"])), (0, 0))
            self.assertEqual((round(box["width"]), round(box["height"])), (390, 844), "full screen at sm")
            labels = pg.js("Array.prototype.map.call(document.querySelectorAll('.wz-step-label'), function (s) { return getComputedStyle(s).display !== 'none'; })")
            self.assertEqual(labels, [True, False, False, False, False], "only the current step label shows at sm")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self._paste(pg, "devices")
            for key in ("map", "preview", "review"):
                self._next(pg, key)
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll on " + key)
                self.assertEqual(pg.offscreen(".wz .wz-foot button:not([hidden])", "x"), 0)
                for b in pg.js("Array.prototype.filter.call(document.querySelectorAll('.wz-foot button, .wz-close'), function (b) { return !b.hidden; })"
                               ".map(function (b) { var r = b.getBoundingClientRect(); return [r.width, r.height]; })"):
                    self.assertGreaterEqual(min(b), 44, "coarse-pointer targets are 44px")
                pg.shot("wizard-%s-m" % key)
            self._next(pg, "result")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertGreaterEqual(pg.rect(".wz .wz-result-link")["height"], 44)

    def test_tablet_dialog_fits(self):
        with self.open(HARNESS + "?open=cables&step=preview", "t") as pg:
            self._wait_step(pg, "preview")
            box = pg.rect(".wz")
            self.assertLess(box["width"], 820)
            self.assertGreaterEqual(box["left"], 0)
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("wizard-preview-t")
