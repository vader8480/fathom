"""FEEDBACK: the feedback harness ``/static/dev/feedback.html`` in headless Chrome (docs/ui-audit.md B.2 FEEDBACK).

Checks every state at d, t and m (skeleton ARIA, empty, error with Retry, offline, stale and review badges,
target sizes, no horizontal page scroll), the bell (count, ``aria-label``, keyboard-operable menu, Mark all
read, picking a notice), the stale badge turning stale and refreshing, ``confirmScope`` through the app's
confirm dialog, and ``prefers-reduced-motion``. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/feedback.html"
DOT = "\u00b7"


def q(s: str) -> str:
    return json.dumps(s)


class FeedbackHarnessUi(UiCase):
    def visible(self, pg, sel):
        return pg.js("""(function (s) {
          var e = document.querySelector(s); if (!e) return false;
          for (var p = e; p; p = p.parentElement) if (p.hidden) return false;
          var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0;
        })(%s)""" % q(sel))

    def text(self, pg, sel):
        return pg.js("(function (e) { return e ? e.textContent : null; })(document.querySelector(%s))" % q(sel))

    def active(self, pg):
        return pg.js("(function (a) { return {text: a.textContent, id: a.id, role: a.getAttribute('role'), cls: a.className}; })(document.activeElement)")

    def test_states_at_three_sizes(self) -> None:
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll")
                for kind in ("table", "cards", "page", "list"):
                    sk = "#fb-h-skel-%s .fb-skeleton" % kind
                    self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-busy')" % q(sk)), "true", kind)
                    self.assertEqual(pg.js("document.querySelector(%s).getAttribute('data-kind')" % q(sk)), kind)
                    self.assertEqual(pg.js("document.querySelector(%s + ' > .fb-skel').getAttribute('aria-hidden')" % q(sk)), "true")
                    self.assertTrue(self.visible(pg, sk + " .fb-skel-bar"), kind)
                self.assertEqual(pg.js("document.querySelectorAll('#fb-h-skel-table .fb-skel-row').length"), 6, "head + 5 rows")
                self.assertEqual(self.text(pg, "#fb-h-empty .fb-empty-title"), "No devices in Main Auditorium yet.")
                self.assertEqual(self.text(pg, "#fb-h-empty .fb-empty-action"), "Add gear")
                self.assertIsNone(pg.rect("#fb-h-empty-plain .fb-empty-action"), "no action for viewers")
                self.assertEqual(pg.js("document.querySelector('#fb-h-error .fb-error').getAttribute('role')"), "alert")
                self.assertIn("Overlay could not be built", self.text(pg, "#fb-h-error .fb-error-msg"))
                self.assertEqual(self.text(pg, "#fb-h-error .fb-retry"), "Retry")
                self.assertEqual(pg.js("document.querySelector('#fb-h-offline .fb-error').dataset.kind"), "offline")
                self.assertIsNone(pg.rect("#fb-h-error-plain .fb-retry"), "no Retry without a callback")
                self.assertIsNone(pg.rect("#fb-h-error-compact .fb-error-title"), "compact has no title")
                self.assertEqual(self.text(pg, "#fb-h-review .fb-review-label"), "3 to review")
                self.assertEqual(pg.js("document.querySelector('#fb-h-review .fb-review').getAttribute('aria-label')"), "3 to review")
                self.assertIsNone(pg.rect("#fb-h-review-zero .fb-review"), "count 0 is not rendered")
                self.assertTrue(self.visible(pg, "#fb-h-stale-rev .fb-stale"))
                self.assertEqual(self.text(pg, "#fb-h-stale-rev .fb-stale-text"), "Stale %s updated 4 min ago" % DOT)
                self.assertEqual(pg.js("document.querySelector('#fb-h-stale-rev .fb-stale').dataset.reason"), "revision")
                self.assertFalse(self.visible(pg, "#fb-h-stale-fresh .fb-stale"), "hidden while fresh")
                self.assertEqual(pg.js("document.querySelector('#fb-h-stale-age .fb-stale').dataset.reason"), "age")
                self.assertEqual(self.text(pg, "#fb-h-stale-run .fb-stale-text"), "Run 5 min ago")
                floor = 44 if size in ("t", "m") else 40
                for sel in ("#fb-h-error .fb-retry", "#fb-h-error-compact .fb-retry", "#fb-h-empty .fb-empty-action",
                            "#fb-h-review .fb-review", "#fb-h-stale-rev .fb-stale-refresh", "#fb-h-bell"):
                    r = pg.rect(sel)
                    self.assertGreaterEqual(round(r["height"]), floor, "%s height at %s" % (sel, size))
                self.assertGreaterEqual(round(pg.rect("#fb-h-bell")["width"]), floor)
                self.assertEqual(pg.offscreen(".fb-retry, .fb-empty-actions button, .fb-review, .fb-stale-refresh, #fb-h-bell", "x"), 0)
                pg.shot("feedback-" + size)

    def test_bell_count_and_keyboard_menu(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                self.assertEqual(self.text(pg, "#fb-h-bell-count"), "2")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-label')"), "Notifications, 2 unread")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-haspopup')"), "menu")
                pg.click("#fb-h-add-warn")
                pg.wait_for("document.getElementById('fb-h-bell-count').textContent === '3'")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-label')"), "Notifications, 3 unread")
                pg.js("__fb.notices.add({text: 'Twice'}); __fb.notices.add({text: 'Twice'}); 1")
                self.assertEqual(self.text(pg, "#fb-h-bell-count"), "4", "same text within 60 s is one notice")

                pg.js("document.getElementById('fb-h-bell').focus(); 1")
                pg.press("ArrowDown")
                pg.wait_for("!document.querySelector('.fb-bell-pop').hidden")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-expanded')"), "true")
                self.assertEqual(pg.js("document.querySelector('.fb-bell-pop ul').getAttribute('role')"), "menu")
                self.assertEqual(pg.js("document.querySelectorAll('ul.fb-notices [role=menuitem]').length"), 6, "5 notices + Mark all read")
                a = self.active(pg)
                self.assertEqual(a["role"], "menuitem")
                self.assertIn("Twice", a["text"], "newest first")
                pg.press("ArrowDown")
                self.assertIn("warn notice 1", self.active(pg)["text"])
                pg.press("End")
                self.assertEqual(self.active(pg)["text"], "Mark all read")
                pg.press("ArrowDown")
                self.assertIn("Twice", self.active(pg)["text"], "wraps to the first")
                pg.press("ArrowUp")
                self.assertEqual(self.active(pg)["text"], "Mark all read", "wraps to the last")
                pg.press("Home")
                self.assertIn("Twice", self.active(pg)["text"])
                self.assertEqual(pg.offscreen(".fb-bell-pop", "x"), 0, "menu fits the viewport")
                pg.press("Escape")
                pg.wait_for("document.querySelector('.fb-bell-pop').hidden")
                self.assertEqual(self.active(pg)["id"], "fb-h-bell", "focus returns to the bell")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-expanded')"), "false")

                pg.press("Enter")
                pg.wait_for("!document.querySelector('.fb-bell-pop').hidden")
                pg.press("End")
                pg.press("Enter")
                pg.wait_for("document.getElementById('fb-h-bell-count').hidden")
                self.assertEqual(pg.js("document.getElementById('fb-h-bell').getAttribute('aria-label')"), "Notifications")
                self.assertFalse(pg.js("!!document.querySelector('.fb-notice.fb-unread')"))
                self.assertEqual(self.active(pg)["text"], "Mark all read", "focus stays on the menu")
                self.assertEqual(pg.js("document.querySelector('.fb-markall').getAttribute('aria-disabled')"), "true")
                pg.shot("feedback-bell-" + size)
                pg.press("Escape")

                pg.click("#fb-h-add-err")
                pg.wait_for("document.getElementById('fb-h-bell-count').textContent === '1'")
                pg.click("#fb-h-bell")
                pg.wait_for("!document.querySelector('.fb-bell-pop').hidden")
                href = pg.js("document.querySelector('.fb-notice a').getAttribute('href')")
                pg.click(".fb-notice a")
                pg.wait_for("location.hash === %s" % q(href))
                pg.wait_for("document.querySelector('.fb-bell-pop').hidden")
                self.assertTrue(pg.js("document.getElementById('fb-h-bell-count').hidden"), "picked notice is read")

                pg.click("#fb-h-bell")
                pg.wait_for("!document.querySelector('.fb-bell-pop').hidden")
                pg.click(".h-bar strong")
                pg.wait_for("document.querySelector('.fb-bell-pop').hidden")
                self.assertEqual(pg.smoke.get("errors"), [])
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_stale_badge_turns_stale_announces_and_refreshes(self) -> None:
        with self.open(HARNESS, "d") as pg:
            self.assertFalse(self.visible(pg, "#fb-h-stale-fresh .fb-stale"))
            pg.click("#fb-h-bump")
            self.assertTrue(self.visible(pg, "#fb-h-stale-fresh .fb-stale"), "revision changed: badge shows")
            self.assertEqual(self.text(pg, "#fb-h-stale-fresh .fb-stale-text"), "Stale %s updated 2 min ago" % DOT)
            pg.wait_for("document.getElementById('fathom-live').textContent.indexOf('Stale') === 0")

            pg.click("#fb-h-stale-rev .fb-stale-refresh")
            self.assertEqual(self.text(pg, "#fb-h-stale-rev .fb-stale-refresh"), "Refreshing\u2026")
            self.assertTrue(pg.js("document.querySelector('#fb-h-stale-rev .fb-stale-refresh').disabled"))
            pg.wait_for("document.querySelector('#fb-h-stale-rev .fb-stale').hidden")
            self.assertEqual(pg.js("__fb.counts.refresh"), 1)
            self.assertEqual(self.text(pg, "#fb-h-stale-rev .fb-stale-refresh"), "Refresh")

            pg.js("__fb.offset = 20 * 60000; __fb.badges.rev.refresh(); __fb.badges.run.refresh(); 1")
            self.assertTrue(self.visible(pg, "#fb-h-stale-rev .fb-stale"), "20 min later the same revision is stale by age")
            self.assertEqual(pg.js("document.querySelector('#fb-h-stale-rev .fb-stale').dataset.reason"), "age")
            self.assertEqual(self.text(pg, "#fb-h-stale-run .fb-stale-text"), "Stale %s run 25 min ago" % DOT)

    def test_stale_badge_ticks_every_30s_and_stops_when_detached(self) -> None:
        with self.open(HARNESS, "d") as pg:
            r = pg.js("""(function () {
              var si = window.setInterval, ci = window.clearInterval, cap = null, cleared = [];
              window.setInterval = function (fn, ms) { var id = si(fn, ms); cap = {fn: fn, ms: ms, id: id}; return id; };
              window.clearInterval = function (id) { cleared.push(id); return ci(id); };
              var t = 0, b;
              try { b = __fb.api.staleBadge({fetchedAt: 0, fetchedRev: 1, currentRev: 1, now: function () { return t; }}); }
              finally { window.setInterval = si; window.clearInterval = ci; }
              document.body.appendChild(b);
              var out = {ms: cap && cap.ms, hidden0: b.hidden};
              t = 16 * 60000; cap.fn();
              out.hidden1 = b.hidden; out.text1 = b.querySelector('.fb-stale-text').textContent;
              b.remove();
              window.clearInterval = function (id) { cleared.push(id); return ci(id); };
              try { cap.fn(); } finally { window.clearInterval = ci; }
              out.stopped = cleared.indexOf(cap.id) >= 0;
              return out;
            })()""")
            self.assertEqual(r["ms"], 30000, "updates every 30 s")
            self.assertTrue(r["hidden0"])
            self.assertFalse(r["hidden1"], "a tick re-evaluates the age")
            self.assertEqual(r["text1"], "Stale %s updated 16 min ago" % DOT)
            self.assertTrue(r["stopped"], "a detached badge clears its timer")

    def test_retry_and_actions_call_back(self) -> None:
        with self.open(HARNESS, "t") as pg:
            pg.click("#fb-h-error .fb-retry")
            self.assertEqual(pg.js("__fb.counts.retry"), 1)
            self.assertEqual(self.text(pg, "#fb-h-error .fb-retry"), "Retrying\u2026")
            pg.click("#fb-h-error .fb-retry", force=True)
            self.assertEqual(pg.js("__fb.counts.retry"), 1, "disabled while the retry is pending")
            pg.wait_for("document.querySelector('#fb-h-error .fb-retry').textContent === 'Retry'")
            self.assertEqual(self.text(pg, "#fb-h-retry-count"), "retries: 1")
            pg.click("#fb-h-offline .fb-retry")
            pg.wait_for("__fb.counts.retry === 2")
            pg.click("#fb-h-empty .fb-empty-action")
            pg.click("#fb-h-empty .fb-empty-secondary")
            pg.click("#fb-h-review .fb-review")
            self.assertEqual(pg.js("[__fb.counts.emptyAction, __fb.counts.emptySecondary, __fb.counts.review]"), [1, 1, 1])

    def test_confirm_scope_dialog(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                pg.click("#fb-h-confirm")
                pg.wait_for("!!document.querySelector('.app-dialog')")
                self.assertEqual(self.text(pg, ".app-dialog .body"), "Delete 12 cables in Main Auditorium?")
                ok = pg.js("(function (b) { return {text: b.textContent, danger: b.classList.contains('danger')}; })"
                           "(document.querySelector('.app-dialog footer button:last-child'))")
                self.assertEqual(ok, {"text": "Delete 12 cables", "danger": True})
                pg.shot("feedback-confirm-" + size)
                pg.click(".app-dialog footer button:last-child")
                pg.wait_for("document.getElementById('fb-h-confirm-result').textContent === 'true'")

                pg.click("#fb-h-confirm-one")
                pg.wait_for("!!document.querySelector('.app-dialog')")
                self.assertEqual(self.text(pg, ".app-dialog .body"), "Restore revision 12?\nThis creates revision 43.")
                pg.press("Escape")
                pg.wait_for("document.getElementById('fb-h-confirm-result').textContent === 'false'")
                self.assertFalse(pg.js("!!document.querySelector('.app-dialog')"))

    def test_reduced_motion_stops_the_shimmer(self) -> None:
        with self.open(HARNESS, "d") as pg:
            anim = "getComputedStyle(document.querySelector('.fb-skel-bar')).animationName"
            self.assertEqual(pg.js(anim), "fb-shimmer")
            pg.command("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
            pg.wait_for("matchMedia('(prefers-reduced-motion: reduce)').matches")
            self.assertEqual(pg.js(anim), "none")


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
