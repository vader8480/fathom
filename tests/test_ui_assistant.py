"""AST: the Helper panel's P4C additions (docs/SPEC.md §6.8 assistant UI).

Model status line and used-tools row, the "Proposed changes" card (Yes posts to ``…/assistant/apply``,
No hides it, viewers get no buttons, expired proposals say so), attachments and pasted manual text for
the next question, and voice input through ``speech.js``. The P4B answer fields and the apply route are
stubbed with request interception; request bodies are recorded by a ``fetch`` wrapper installed before
the app loads because the harness intercept sees URLs only. Runs at d and m; skips without Chrome.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

P = "#/campus-demo/main/"
ASK = "/api/v2/projects/campus-demo/assistant"
APPLY = "/api/v2/projects/campus-demo/assistant/apply"
OPS = [{"op": "merge", "coll": "networks", "id": "av-dante", "value": {"note": "stream feed"}}]
ANSWER = {
    "summary": "The **livestream encoder** gets its audio from the console's **Matrix 3** output.",
    "paths": [], "checks": [{"n": 1, "text": "Check that **Matrix 3** is unmuted."}], "notes": [], "confidence": "medium",
    "llm": {"used": True, "provider": "openai", "model": "gpt-4o-mini"},
    "used_tools": [{"name": "search", "args_summary": "livestream"}, {"name": "trace", "args_summary": "encoder"}],
    "proposal": {"id": "prop-1", "summary": ["Add a note to **Dante primary**: stream feed"], "ops": OPS, "applicable": True, "problems": [],
                 "expires": "2099-01-01T00:00:00Z"},
}
PLAIN = {"summary": "No model here.", "paths": [], "checks": [], "notes": [], "confidence": "low", "llm": {"used": False, "reason": "no model configured"}}
CAPTURE = """(function () {
  var real = window.fetch;
  window.__bodies = [];
  window.fetch = function (u, o) {
    var s = String(u && u.url || u);
    if (s.indexOf('/api/') >= 0 && o && o.body && typeof o.body === 'string') window.__bodies.push({method: (o.method || 'GET').toUpperCase(), url: s, body: o.body});
    return real.apply(this, arguments);
  };
})();"""
# Headless Chrome ships webkitSpeechRecognition; this removes both constructors to model Firefox.
NO_SR = "window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined;"
# A SpeechRecognition stub: records start/stop, exposes the instance as window.__sr so a test can feed results.
SR_STUB = """(function () {
  function SR() { window.__sr = this; this.lang = ''; this.started = 0; }
  SR.prototype.start = function () { this.started++; window.__srStarted = (window.__srStarted || 0) + 1; };
  SR.prototype.stop = function () { window.__srStopped = (window.__srStopped || 0) + 1; if (this.onend) this.onend(); };
  window.SpeechRecognition = SR;
})();"""


def q(s: str) -> str:
    return json.dumps(s)


class AssistantUi(UiCase):
    def panel(self, size: str, answer: dict = None, scripts=(), path: str = "patch"):
        """The patch view with the Helper open; ``…/assistant`` answers ``answer`` (default ANSWER)."""
        cm = self.open("/healthz", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        for src in scripts:
            pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": src})
        pg.intercept(ASK, 200, ANSWER if answer is None else answer, "POST")
        pg.goto("/" + P + path)
        pg.press("Control+j")
        pg.wait_for("document.getElementById('app-assistant').classList.contains('open') && !!document.querySelector('#app-assistant .ast-form input')")
        # the panel slides in (transform transition); clicks wait for it to settle
        pg.wait_for("getComputedStyle(document.getElementById('app-assistant')).transform === 'none'")
        pg.wait_for("!!document.querySelector('#app-assistant .ast-form[data-voice]')")
        return pg

    def ask(self, pg, text: str) -> None:
        pg.js("document.querySelector('#app-assistant .ast-form input').value = %s" % q(text))
        pg.js("document.querySelector('#app-assistant .ast-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")

    def text(self, pg, sel: str) -> str:
        return pg.js("(function () { var e = document.querySelector(%s); return e ? e.textContent.trim() : ''; })()" % q(sel))

    def bodies(self, pg, path: str) -> list:
        return pg.js("window.__bodies.filter(function (b) { return b.url.indexOf(%s) >= 0; }).map(function (b) { return JSON.parse(b.body); })" % q(path))

    # ------------------------------------------------------------ status line

    def test_status_line_and_used_tools(self):
        pg = self.panel("d", PLAIN)
        self.assertEqual(self.text(pg, ".ast-status-llm"), "Deterministic mode (no model configured)")
        self.assertTrue(pg.js("document.querySelector('.ast-tools').hidden"))
        self.ask(pg, "What feeds the Main projector?")
        pg.wait_for("!!document.querySelector('.ast-a')")
        self.assertEqual(self.text(pg, ".ast-status-llm"), "Deterministic mode (no model configured)")
        self.assertEqual(pg.js("document.querySelector('.ast-status-llm').getAttribute('data-llm')"), "off")
        pg.clear_intercepts()
        pg.intercept(ASK, 200, ANSWER, "POST")
        self.ask(pg, "House sound is fine, but the livestream has no audio.")
        pg.wait_for("document.querySelector('.ast-status-llm').getAttribute('data-llm') === 'on'")
        self.assertEqual(self.text(pg, ".ast-status-llm"), "openai \u00b7 gpt-4o-mini")
        self.assertFalse(pg.js("document.querySelector('.ast-tools').hidden"))
        self.assertFalse(pg.js("document.querySelector('.ast-tools').open"), "the tools row is collapsed by default")
        self.assertEqual(self.text(pg, ".ast-tools summary"), "Used: search, trace")
        self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.ast-tool'), function (c) { return c.getAttribute('data-tool'); })"), ["search", "trace"])
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ------------------------------------------------------------ proposal card

    def test_proposal_card_yes_applies_and_no_hides(self):
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.panel(size, scripts=[CAPTURE])
                applied = pg.intercept(APPLY, 200, {"revision": 99, "applied": 1, "summary": "Note on Dante primary"}, "POST")
                self.ask(pg, "House sound is fine, but the livestream has no audio.")
                pg.wait_for("!!document.querySelector('.ast-proposal[data-proposal=prop-1]')")
                self.assertEqual(self.text(pg, ".ast-proposal h4"), "Proposed changes")
                self.assertEqual(pg.js("document.querySelectorAll('.ast-proposal-summary li').length"), 1)
                self.assertEqual(pg.js("document.querySelector('.ast-proposal-summary li strong').textContent"), "Dante primary")
                self.assertFalse(pg.js("document.querySelector('#ast-proposal-yes').disabled"))
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    self.assertGreaterEqual(pg.rect("#ast-proposal-yes")["height"], 44)
                pg.shot("ast-proposal-" + size)
                pg.click("#ast-proposal-no")
                pg.wait_for("!document.querySelector('.ast-proposal')")
                self.assertEqual(applied["hits"], 0, "No sends nothing")
                # ask again: Yes posts the proposal at the store's revision and the card reports the new revision
                self.ask(pg, "House sound is fine, but the livestream has no audio.")
                pg.wait_for("document.querySelectorAll('.ast-proposal').length === 1")
                pg.click("#ast-proposal-yes")
                pg.wait_for("document.querySelector('.ast-proposal').getAttribute('data-state') === 'applied'")
                self.assertEqual(applied["hits"], 1)
                body = self.bodies(pg, APPLY)[-1]
                self.assertEqual(body["id"], "prop-1")
                self.assertEqual(body["proposal"]["ops"], OPS)
                self.assertIsInstance(body["base_revision"], int)
                self.assertGreaterEqual(body["base_revision"], 1)
                self.assertIn("revision 99", self.text(pg, ".ast-proposal-done"))
                toast = pg.wait_for("(function () { var t = document.querySelector('.app-toast.ok'); return t ? t.textContent : ''; })()")
                self.assertIn("Applied", toast)
                self.assertTrue(pg.js("!!document.querySelector('.app-toast .ast-undo')"), "the toast offers Undo")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_proposal_apply_locked_shows_the_lock_message(self):
        pg = self.panel("d")
        pg.intercept(APPLY, 423, {"error": "editing is locked", "code": "locked"}, "POST")
        self.ask(pg, "House sound is fine, but the livestream has no audio.")
        pg.wait_for("!!document.querySelector('#ast-proposal-yes')")
        pg.click("#ast-proposal-yes")
        pg.wait_for("!!document.querySelector('.ast-proposal-err')")
        self.assertIn("locked", self.text(pg, ".ast-proposal-err"))
        self.assertTrue(pg.js("!!document.querySelector('#ast-proposal-yes')"), "the card stays so the user can retry later")

    def test_proposal_states_expired_and_not_applicable(self):
        expired = json.loads(json.dumps(ANSWER))
        expired["proposal"]["expires"] = "2001-01-01T00:00:00Z"
        pg = self.panel("d", expired)
        self.ask(pg, "House sound is fine, but the livestream has no audio.")
        pg.wait_for("document.querySelector('.ast-proposal') && document.querySelector('.ast-proposal').getAttribute('data-state') === 'expired'")
        self.assertEqual(self.text(pg, ".ast-proposal-hint"), "Proposal expired \u2014 ask again")
        self.assertFalse(pg.js("!!document.querySelector('#ast-proposal-yes')"))
        blocked = json.loads(json.dumps(ANSWER))
        blocked["proposal"].update({"applicable": False, "problems": ["Device Foo was not found"]})
        pg.clear_intercepts()
        pg.intercept(ASK, 200, blocked, "POST")
        self.ask(pg, "Again please")
        pg.wait_for("document.querySelectorAll('.ast-proposal').length === 2")
        self.assertTrue(pg.js("document.querySelector('#ast-proposal-yes').disabled"))
        self.assertIn("Device Foo was not found", self.text(pg, ".ast-proposal-problem"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_deterministic_suggestion_card_still_commits(self):
        sugg = dict(PLAIN, suggestion={"text": "Add a note to Dante primary", "ops": OPS})
        pg = self.panel("d", sugg)
        self.ask(pg, "Where is the ULXD4D?")
        pg.wait_for("!!document.querySelector('#ast-suggest-yes')")
        self.assertEqual(self.text(pg, ".ast-suggest h4"), "Update the map?")
        pg.click("#ast-suggest-yes")
        pg.wait_for("document.querySelector('.ast-suggest h4').textContent === 'Map updated'")
        pg.wait_for("!!document.querySelector('.app-toast')")
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ------------------------------------------------------- attachments, manual text

    def test_attach_picker_sets_chips_and_the_request_body(self):
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.panel(size, PLAIN, scripts=[CAPTURE])
                pg.click(".ast-attach")
                pg.wait_for("document.querySelectorAll('.app-dialog .ast-pick-row').length > 1")
                self.assertEqual(self.text(pg, ".app-dialog header h2"), "Attach files")
                ids = pg.js("Array.prototype.map.call(document.querySelectorAll('.app-dialog .ast-pick-row'), function (r) { return r.getAttribute('data-att'); }).slice(0, 2)")
                self.assertEqual(len(ids), 2)
                self.assertTrue(pg.js("!!document.querySelector('.app-dialog .ast-pick-kind[data-kind]')"), "kind chips")
                if size == "m":
                    self.assertGreaterEqual(pg.rect(".app-dialog .ast-pick-row")["height"], 44)
                    pg.shot("ast-attach-m")
                for i in ids:
                    pg.click(".app-dialog .ast-pick-row[data-att=%s] input" % json.dumps(i), force=True)
                pg.click(".app-dialog footer button.primary")
                pg.wait_for("!document.querySelector('.app-dialog')")
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.ast-attached .ast-att'), function (c) { return c.getAttribute('data-att'); })"), ids)
                # one chip removed with its ×
                pg.click(".ast-attached .ast-att[data-att=%s] .ast-chip-x" % json.dumps(ids[1]), force=True)
                pg.wait_for("document.querySelectorAll('.ast-attached .ast-att').length === 1")
                # manual text sheet
                pg.click(".ast-manual")
                pg.wait_for("!!document.querySelector('#ast-manual-text')")
                pg.js("(function () { var t = document.querySelector('#ast-manual-text'); t.value = 'Page 12: Matrix 3 feeds the encoder.'; t.dispatchEvent(new Event('input', {bubbles: true})); })()")
                self.assertIn("KB of 20 KB", self.text(pg, ".ast-manual-count"))
                pg.click(".app-dialog footer button.primary")
                pg.wait_for("!!document.querySelector('.ast-manual-chip')")
                self.ask(pg, "What does the manual say about Matrix 3?")
                pg.wait_for("!!document.querySelector('.ast-a')")
                body = self.bodies(pg, ASK)[-1]
                self.assertEqual(body["question"], "What does the manual say about Matrix 3?")
                self.assertEqual(body["attachments"], [ids[0]])
                self.assertEqual(body["history"][-1], {"role": "user", "text": "What does the manual say about Matrix 3?", "attachments": [ids[0]]})
                self.assertEqual(body["manual_text"], "Page 12: Matrix 3 feeds the encoder.")
                # consumed by that question: the chips are gone, the question bubble shows what went with it
                self.assertEqual(pg.js("document.querySelectorAll('.ast-attached .chip').length"), 0)
                self.assertEqual(pg.js("document.querySelectorAll('.ast-q .ast-q-att').length"), 1)
                # the next question carries the earlier turn's attachments in history only
                self.ask(pg, "And the encoder?")
                pg.wait_for("document.querySelectorAll('.ast-a').length === 2")
                body = self.bodies(pg, ASK)[-1]
                self.assertNotIn("attachments", body)
                self.assertNotIn("manual_text", body)
                self.assertEqual(body["history"][0]["attachments"], [ids[0]])
                self.assertEqual(body["history"][-1]["role"], "assistant")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    # ------------------------------------------------------------------ voice

    def test_mic_hidden_without_speech_recognition(self):
        pg = self.panel("d", PLAIN, scripts=[NO_SR])
        self.assertFalse(pg.js("!!(window.SpeechRecognition || window.webkitSpeechRecognition)"), "no SpeechRecognition constructor")
        self.assertEqual(pg.js("document.querySelector('.ast-form').getAttribute('data-voice')"), "none")
        self.assertFalse(pg.js("!!document.querySelector('.ast-mic')"))
        self.assertTrue(pg.js("!!document.querySelector('.ast-form button[type=submit]')"))

    def test_mic_listens_fills_the_composer_and_reports_errors(self):
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.panel(size, PLAIN, scripts=[SR_STUB])
                pg.wait_for("!!document.querySelector('.ast-mic')")
                self.assertEqual(pg.js("document.querySelector('.ast-mic').getAttribute('aria-pressed')"), "false")
                pg.click(".ast-mic")
                pg.wait_for("document.querySelector('.ast-mic').classList.contains('listening')")
                self.assertEqual(pg.js("window.__srStarted"), 1)
                self.assertTrue(pg.js("!!window.__sr.lang"), "language comes from navigator.language")
                self.assertEqual(pg.js("window.__sr.interimResults"), True)
                self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), "Listening\u2026")
                pg.js("window.__sr.onresult({resultIndex: 0, results: [[{transcript: 'what feeds the'}]]})")
                self.assertEqual(pg.js("document.querySelector('.ast-form input').value"), "what feeds the")
                pg.js("(function () { var r = [[{transcript: 'what feeds the lobby screen'}]]; r[0].isFinal = true; window.__sr.onresult({resultIndex: 0, results: r}); })()")
                self.assertEqual(pg.js("document.querySelector('.ast-form input').value"), "what feeds the lobby screen")
                if size == "m":
                    self.assertGreaterEqual(pg.rect(".ast-mic")["height"], 44)
                pg.shot("ast-mic-" + size)
                # second press stops; the final text stays
                pg.click(".ast-mic")
                pg.wait_for("!document.querySelector('.ast-mic').classList.contains('listening')")
                self.assertEqual(pg.js("window.__srStopped"), 1)
                self.assertEqual(pg.js("document.querySelector('.ast-form input').value"), "what feeds the lobby screen")
                # a denied microphone shows an inline hint
                pg.click(".ast-mic")
                pg.wait_for("document.querySelector('.ast-mic').classList.contains('listening')")
                pg.js("window.__sr.onerror({error: 'not-allowed'}); window.__sr.onend()")
                pg.wait_for("!document.querySelector('.ast-mic').classList.contains('listening')")
                self.assertIn("Microphone access was denied", self.text(pg, ".ast-voice-hint"))
                self.assertEqual(pg.js("window.__fathomErrors"), [])


DRAFT_TEXT = "X32 with an S16 stage box, 2 ULXD4D wireless, 2 K12.2 on stands, ATEM Mini"
DRAFT_PLACEHOLDER = "Describe the room: e.g. X32 with an S16 stage box, 4 ULXD wireless, 2 K12.2 on stands, ATEM Mini, QuickQ 10"


class AssistantDraft(UiCase):
    """P6B (§6.9.5b, FR-AST-15..17): the Ask | Draft a room toggle, the room select, the Draft card and Apply.

    Own server (own temp data): the draft flow runs against the real ``…/assistant`` route and really applies to campus-demo.
    """

    def panel(self, size: str, scripts=(), path: str = "patch", open_panel: bool = True):
        cm = self.open("/healthz", size, ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        for src in scripts:
            pg.command("Page.addScriptToEvaluateOnNewDocument", {"source": src})
        pg.goto("/" + P + path)
        if open_panel:
            pg.press("Control+j")
            self.wait_panel(pg)
        return pg

    def wait_panel(self, pg) -> None:
        pg.wait_for("document.getElementById('app-assistant').classList.contains('open') && !!document.querySelector('#app-assistant .ast-form input')")
        pg.wait_for("getComputedStyle(document.getElementById('app-assistant')).transform === 'none'")
        pg.wait_for("!!document.querySelector('#app-assistant .ast-form[data-voice]')")

    def ask(self, pg, text: str) -> None:
        pg.js("document.querySelector('#app-assistant .ast-form input').value = %s" % q(text))
        pg.js("document.querySelector('#app-assistant .ast-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")

    def text(self, pg, sel: str) -> str:
        return pg.js("(function () { var e = document.querySelector(%s); return e ? e.textContent.trim() : ''; })()" % q(sel))

    def bodies(self, pg, path: str) -> list:
        return pg.js("window.__bodies.filter(function (b) { return b.url.indexOf(%s) >= 0; }).map(function (b) { return JSON.parse(b.body); })" % q(path))

    def project_devices(self) -> dict:
        import urllib.request

        with urllib.request.urlopen(self.base + "/api/v2/projects/campus-demo") as r:
            doc = json.loads(r.read().decode())["doc"]
        return {d["id"]: d for d in doc["devices"]}, doc["cables"]

    def test_toggle_room_select_draft_card_and_apply(self):
        for size in ("d", "m"):
            with self.subTest(size=size):
                pg = self.panel(size, scripts=[CAPTURE])
                # Ask is the default; the room select is hidden
                self.assertEqual(pg.js("document.querySelector('.ast-mode-btn[data-mode=ask]').getAttribute('aria-checked')"), "true")
                self.assertTrue(pg.js("document.querySelector('.ast-room-wrap').hidden"))
                self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), "Ask about your system\u2026")
                pg.click(".ast-mode-btn[data-mode=draft]")
                pg.wait_for("document.querySelector('.ast-modes').getAttribute('data-mode') === 'draft'")
                self.assertEqual(pg.js("document.querySelector('.ast-mode-btn[data-mode=draft]').getAttribute('aria-checked')"), "true")
                self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), DRAFT_PLACEHOLDER)
                self.assertFalse(pg.js("document.querySelector('.ast-room-wrap').hidden"))
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.ast-room option'), function (o) { return o.value; })"), ["main", "chapel", "broadcast"])
                self.assertEqual(pg.js("document.querySelector('.ast-room').value"), "main", "defaults to the current room")
                self.assertTrue(pg.js("!!document.querySelector('.ast-draft-example')"), "the example description chip replaces the question chips")
                self.assertIn("Nothing is changed until you apply", self.text(pg, ".ast-intro-draft"))
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    self.assertGreaterEqual(pg.rect(".ast-mode-btn[data-mode=draft]")["height"], 44)
                    self.assertGreaterEqual(pg.rect(".ast-room")["height"], 44)
                    # full width under the toggle: the select spans the panel like the composer input
                    self.assertGreaterEqual(pg.rect(".ast-room-wrap")["width"], pg.rect(".ast-form input")["width"] * 0.9)
                    self.assertGreater(pg.rect(".ast-room-wrap")["y"], pg.rect(".ast-mode")["y"])
                pg.shot("draft-composer-" + size)
                # the mic (headless Chrome has webkitSpeechRecognition) restores the draft placeholder after listening
                pg.js("document.querySelector('.ast-room').value = 'chapel'; document.querySelector('.ast-room').dispatchEvent(new Event('change'))")
                self.ask(pg, DRAFT_TEXT)
                pg.wait_for("!!document.querySelector('.ast-draft')")
                body = self.bodies(pg, ASK)[-1]
                self.assertEqual((body["mode"], body["room"], body["question"]), ("draft", "chapel", DRAFT_TEXT))
                self.assertEqual(self.text(pg, ".ast-q .ast-q-draft"), "Draft a room \u00b7 Chapel")
                self.assertEqual(self.text(pg, ".ast-draft h4"), "Draft \u00b7 Chapel")
                chips = pg.js("Array.prototype.map.call(document.querySelectorAll('.ast-draft-chip'), function (c) { return c.textContent; })")
                self.assertEqual(chips, ["Behringer X32 console", "Stagebox / I/O rack", "Shure ULXD4D wireless receiver \u00d72", "QSC K12.2 speaker \u00d72",
                                         "Blackmagic Design ATEM Mini Pro video switcher"])
                self.assertFalse(pg.js("!!document.querySelector('.ast-draft-unknown')"))
                pg.wait_for("!!document.querySelector('#ast-proposal-yes')")
                self.assertEqual(self.text(pg, "#ast-proposal-yes"), "Apply")
                self.assertEqual(self.text(pg, "#ast-proposal-no"), "Not now")
                self.assertEqual(self.text(pg, ".ast-draft-hint"), "Nothing is changed until you apply.")
                self.assertEqual(pg.js("document.querySelectorAll('.ast-proposal-summary li').length"), 13, "7 devices + 6 cables")
                # the second pass (size m) drafts into a room that already has the first pass's devices, so names carry " 2"
                self.assertRegex(self.text(pg, ".ast-a .ast-notes"), r"Stage box( 2)? \u2192 X32( 2)?", "the skipped link is explained")
                if size == "m":
                    self.assertLessEqual(pg.page_hscroll(), 0)
                    self.assertGreaterEqual(pg.rect("#ast-proposal-yes")["height"], 44)
                pg.shot("draft-card-" + size)
                devs, cables = self.project_devices()
                self.assertNotIn("x32" if size == "d" else "x32-2", devs, "nothing is applied before Apply")
                pg.click("#ast-proposal-yes")
                pg.wait_for("document.querySelector('.ast-proposal').getAttribute('data-state') === 'applied'")
                pg.wait_for("!!document.querySelector('.app-toast.ok')")
                self.assertIn("Applied", self.text(pg, ".ast-proposal-done"))
                pg.shot("draft-applied-" + size)
                devs2, cables2 = self.project_devices()
                self.assertEqual(len(devs2) - len(devs), 7, "Apply adds the drafted devices")
                self.assertEqual(len(cables2) - len(cables), 6, "and the default patch")
                new = [d for d in devs2.values() if d["id"] not in devs]
                self.assertTrue(all(d["room"] == "chapel" for d in new), "all of them in the chosen room")
                self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_unknown_mentions_and_open_event(self):
        pg = self.panel("d", scripts=[CAPTURE], open_panel=False)
        self.assertFalse(pg.js("document.getElementById('app-assistant').classList.contains('open')"))
        # a view opens the Helper in Draft mode for a room (page-room.js dispatches this; the module may not be loaded yet)
        pg.js("import('/static/js/assistant-ui.js').then(function () { document.dispatchEvent(new CustomEvent('fathom:assistant-open', {detail: {mode: 'draft', room: 'broadcast'}})); })")
        self.wait_panel(pg)
        pg.wait_for("document.querySelector('.ast-modes') && document.querySelector('.ast-modes').getAttribute('data-mode') === 'draft'")
        self.assertEqual(pg.js("document.querySelector('.ast-room').value"), "broadcast")
        # nothing the drafter knows: the card lists the unknown mentions and there is no proposal
        self.ask(pg, "a frobnicator 9000 and three widgets")
        pg.wait_for("!!document.querySelector('.ast-draft')")
        self.assertEqual(pg.js("document.querySelector('.ast-draft').getAttribute('data-recognised')"), "0")
        self.assertEqual(self.text(pg, ".ast-draft-unknown"), "Couldn\u2019t place: frobnicator 9000, widgets")
        self.assertFalse(pg.js("!!document.querySelector('.ast-proposal')"))
        self.assertIn("couldn't recognise", self.text(pg, ".ast-a").lower().replace("\u2019", "'"))
        # remembered per session: close, reopen with the shortcut -> still Draft mode with that room; Ask restores the placeholder
        pg.press("Escape")
        pg.wait_for("!document.getElementById('app-assistant').classList.contains('open')")
        pg.press("Control+j")
        self.wait_panel(pg)
        self.assertEqual(pg.js("document.querySelector('.ast-modes').getAttribute('data-mode')"), "draft")
        self.assertEqual(pg.js("document.querySelector('.ast-room').value"), "broadcast")
        # the event with the panel already open just switches room
        pg.js("document.dispatchEvent(new CustomEvent('fathom:assistant-open', {detail: {mode: 'draft', room: 'Chapel'}}))")
        pg.wait_for("document.querySelector('.ast-room').value === 'chapel'")
        pg.click(".ast-mode-btn[data-mode=ask]")
        pg.wait_for("document.querySelector('.ast-modes').getAttribute('data-mode') === 'ask'")
        self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), "Ask about your system\u2026")
        self.assertTrue(pg.js("document.querySelector('.ast-room-wrap').hidden"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_mic_keeps_the_draft_placeholder(self):
        pg = self.panel("m", scripts=[SR_STUB])
        pg.wait_for("!!document.querySelector('.ast-mic')")
        pg.click(".ast-mode-btn[data-mode=draft]")
        pg.wait_for("document.querySelector('.ast-modes').getAttribute('data-mode') === 'draft'")
        pg.click(".ast-mic")
        pg.wait_for("document.querySelector('.ast-mic').classList.contains('listening')")
        self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), "Listening\u2026")
        pg.js("(function () { var r = [[{transcript: 'X32 and two K12.2'}]]; r[0].isFinal = true; window.__sr.onresult({resultIndex: 0, results: r}); })()")
        pg.click(".ast-mic")
        pg.wait_for("!document.querySelector('.ast-mic').classList.contains('listening')")
        self.assertEqual(pg.js("document.querySelector('.ast-form input').value"), "X32 and two K12.2")
        self.assertEqual(pg.js("document.querySelector('.ast-form input').placeholder"), DRAFT_PLACEHOLDER)
        self.assertEqual(pg.js("window.__fathomErrors"), [])


class AssistantRoles(UiCase):
    """A signed-in viewer sees the proposal card without buttons."""

    @classmethod
    def setUpClass(cls) -> None:
        super(AssistantRoles, cls).setUpClass()
        from fathom import users

        users.add_user("viewer2", "viewer2-password-1", role="viewer")

    def test_viewer_sees_the_proposal_without_buttons(self):
        from fathom import users

        cookie = users.make_session(users.get_user("viewer2"))
        cm = self.open("/login", "d", ready=False)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        pg.command("Network.enable")
        pg.command("Network.setCookie", {"name": "fathom_session", "value": cookie, "url": self.base + "/", "httpOnly": True, "sameSite": "Lax"})
        pg.intercept(ASK, 200, ANSWER, "POST")
        pg.goto("/" + P + "patch")
        pg.press("Control+j")
        pg.wait_for("!!document.querySelector('#app-assistant .ast-form input')")
        pg.js("document.querySelector('#app-assistant .ast-form input').value = 'House sound is fine, but the livestream has no audio.'")
        pg.js("document.querySelector('#app-assistant .ast-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")
        pg.wait_for("!!document.querySelector('.ast-proposal')")
        self.assertEqual(pg.js("document.querySelector('.ast-proposal').getAttribute('data-state')"), "readonly")
        self.assertFalse(pg.js("!!document.querySelector('#ast-proposal-yes')"))
        self.assertIn("Only editors can apply changes", pg.js("document.querySelector('.ast-proposal-hint').textContent"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])
