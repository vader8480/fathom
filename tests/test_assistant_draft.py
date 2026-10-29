"""Helper "Draft a room" mode (SPEC FR-AST-15..17, §5.10 ``Question.mode`` / ``Answer.draft``, §6.9.5b).

The deterministic drafter (``fathom.assistant_draft``) turns a free-text room description into ONE proposal of
``add_device`` + ``connect`` changes; the LLM path adds the ``draft_room`` tool and is replayed from
``tests/fixtures/assistant/draft-*.json``. Nothing is written except through ``POST …/assistant/apply``.
"""

from __future__ import annotations

import json
import socket
import unittest
from unittest import mock

try:
    from _helpers import FIXTURES, call, fr, get_app, install_campus, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import FIXTURES, call, fr, get_app, install_campus, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
FX = FIXTURES / "assistant"
CHURCH = "X32 with an S16 stage box, 4 ULXD wireless, 2 K12.2 on stands, ATEM Mini, QuickQ 10"
ASK = "/api/v2/projects/campus/assistant"


def _no_network(*a, **k):
    raise AssertionError("FR-AST-11: a socket / HTTP call was attempted")


class _Guard:
    def __enter__(self):
        self.p = [mock.patch("urllib.request.urlopen", _no_network), mock.patch("socket.create_connection", _no_network),
                  mock.patch.object(socket.socket, "connect", _no_network)]
        for p in self.p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.p:
            p.stop()
        return False


def _campus_doc(data):
    from fathom.project import read_doc

    pdir = install_campus(data, "campus")
    doc, _ = read_doc(pdir)
    return pdir, doc


def _api_doc(app, name="campus"):
    st, _, b = call(app, "GET", "/api/v2/projects/" + name)
    assert st == 200, b[:200]
    return jbody(b)


class Tokeniser(unittest.TestCase):
    """§6.9.5b: mentions split on commas / "and" / "with" / newlines; quantities in digits or words; units are not counts."""

    def setUp(self):
        self.D = requires("assistant_draft")

    def test_split_and_quantities(self):
        toks = self.D.tokenize(CHURCH)
        self.assertEqual([(t["text"], t["count"]) for t in toks],
                         [("X32", 1), ("S16 stage box", 1), ("ULXD wireless", 4), ("K12.2", 2), ("ATEM Mini", 1), ("QuickQ 10", 1)],
                         fr("FR-AST-15", "6.9.5b", "quantities stripped, 'on stands' dropped"))
        toks = self.D.tokenize("we have a 32 channel mixer and a 24 port PoE switch; two laptops\n- LA12X amp feeding 4 speakers + pair of subs & 3 pcs ULXD4 (x3)")
        self.assertEqual([(t["text"], t["count"]) for t in toks],
                         [("32 channel mixer", 1), ("24 port PoE switch", 1), ("laptops", 2), ("LA12X amp", 1), ("speakers", 4), ("subs", 2), ("ULXD4", 3)],
                         "'32 channel' and '24 port' are specs, not counts; word numbers, 'pcs' and '(x3)' are")
        self.assertEqual([(t["text"], t["count"]) for t in self.D.tokenize("4 × ULXD4D, 2x K12.2, SM58 ×6, K10.2 (2)")],
                         [("ULXD4D", 4), ("K12.2", 2), ("SM58", 6), ("K10.2", 2)])
        self.assertEqual(self.D.tokenize(""), [])
        self.assertEqual(self.D.tokenize("and, with, etc."), [], "filler alone is no mention")
        self.assertEqual(self.D.MAX_COUNT, 16)
        self.assertEqual(self.D.tokenize("16 SM58")[0]["count"], 16)
        self.assertEqual(self.D.tokenize("99 SM58")[0], {"text": "99 SM58", "count": 1}, "a number over the per-mention cap is part of the text, not a quantity")


class Resolution(unittest.TestCase):
    """§6.9.5b: library template, then preset, then bare kind; nothing is invented."""

    def setUp(self):
        self.D = requires("assistant_draft")

    def test_templates_presets_kinds_unknown(self):
        with temp_data_dir() as data:
            _, doc = _campus_doc(data)
            r = self.D.draft(doc, CHURCH, "chapel")
            rec = {x["text"]: x for x in r["recognised"]}
            self.assertEqual(rec["X32"]["template"], "behringer-x32", fr("FR-AST-15", "6.9.5b", "model → library template"))
            self.assertEqual((rec["ULXD wireless"]["template"], rec["ULXD wireless"]["count"], rec["ULXD wireless"]["kind"]), ("shure-ulxd4d", 4, "wireless_rx"))
            self.assertEqual(rec["K12.2"]["template"], "qsc-k12-2")
            self.assertEqual(rec["ATEM Mini"]["template"], "blackmagic-atem-mini-pro", "the closest library model")
            self.assertEqual(rec["S16 stage box"]["preset"], "generic-stagebox", "unknown model + role word → the role's preset")
            self.assertEqual(rec["QuickQ 10"]["preset"], "generic-lighting-console", "a known lighting desk brand → lighting console preset")
            self.assertEqual(r["unknown"], [])
            self.assertEqual(sum(1 for c in r["changes"] if c["action"] == "add_device"), 10)
            self.assertEqual([c["name"] for c in r["changes"] if c.get("template") == "shure-ulxd4d"], ["ULXD4D 1", "ULXD4D 2", "ULXD4D 3", "ULXD4D 4"], "numbered names")
            self.assertTrue(all(c["room"] == "chapel" for c in r["changes"] if c["action"] == "add_device"))
            self.assertEqual([c["name"] for c in r["changes"] if c.get("template") == "generic-lighting-console"], ["Lighting console 2"],
                             "names never collide with an existing device (the campus already has a 'Lighting console')")
            # hints from the LLM
            item = self.D.resolve_item(doc, {"text": "wireless", "model": "ULXD4D", "count": 2})
            self.assertEqual((item["template"], item["count"]), ("shure-ulxd4d", 2))
            item = self.D.resolve_item(doc, {"text": "speakers", "kind": "speaker", "count": 2})
            self.assertEqual((item["kind"], item.get("template"), item.get("preset"), item["ports"]), ("speaker", None, None, []), "bare kind: no ports")
            item = self.D.resolve_item(doc, {"text": "a lighting desk"})
            self.assertEqual(item["preset"], "generic-lighting-console")
            self.assertTrue([p for p in item["ports"] if p["medium"] == "dmx"], "preset ports are known")
            # unknown is never invented
            u = self.D.draft(doc, "a frobnicator 9000 and three widgets", "chapel")
            self.assertEqual(u, {"changes": [], "recognised": [], "unknown": ["frobnicator 9000", "widgets"], "note": ""},
                             fr("FR-AST-16", "6.9.5b", "unknown mentions are listed, not guessed"))
            self.assertEqual(self.D.resolve_item(doc, {"text": "Frobnicator 9000"}), {"unknown": "Frobnicator 9000", "count": 1})
            # rooms by id / name / code / unique substring
            self.assertEqual([self.D.resolve_room(doc, x) for x in ("chapel", "Chapel", "CH", "broad", "nope", "")], ["chapel", "chapel", "chapel", "broadcast", None, None])

    def test_default_links_use_existing_ports_only(self):
        E = requires("assistant_edits")
        with temp_data_dir() as data:
            _, doc = _campus_doc(data)
            r = self.D.draft(doc, CHURCH, "chapel")
            links = [c for c in r["changes"] if c["action"] == "connect"]
            self.assertEqual([(c["from"]["device"], c["to"]["device"], c["medium"]) for c in links],
                             [("ULXD4D 1", "X32", "analog")] * 2 + [("ULXD4D 2", "X32", "analog")] * 2 + [("ULXD4D 3", "X32", "analog")] * 2 + [("ULXD4D 4", "X32", "analog")] * 2
                             + [("X32", "K12.2 1", "analog"), ("X32", "K12.2 2", "analog")],
                             fr("FR-AST-15", "6.9.5b", "one link per receiver channel into the console; console → each speaker"))
            self.assertIn("Stage box \u2192 X32", r["note"], "the generic stage box has no AES50/Dante port: the link is skipped and explained, never forced")
            self.assertNotIn("ATEM", r["note"], "a device with nothing to feed is simply not linked")
            p = E.new_proposal(doc, r["changes"], note=self.D.DRAFT_NOTE, base_revision=doc["revision"])
            self.assertTrue(p["applicable"], p["problems"])
            self.assertEqual(len(p["ops"]), 20)
            self.assertEqual(p["note"], "Drafted from your description")
            self.assertIn("Patch **ULXD4D 1 · Analog Out 1** → **X32 · Mic In 1**", p["summary"][10])
            self.assertIn("Patch **ULXD4D 1 · Analog Out 2** → **X32 · Mic In 2**", p["summary"][11])
            self.assertIn("Patch **X32 · XLR Out 1** → **K12.2 1 · Input 1**", p["summary"][18])
            # every patched port exists on the template of the device it is on
            from fathom import library

            dev_ops = {o["value"]["id"]: o["value"] for o in p["ops"] if o.get("coll") == "devices"}
            cable_ops = [o["value"] for o in p["ops"] if o.get("coll") == "cables"]
            self.assertEqual((len(dev_ops), len(cable_ops)), (10, 10))
            port_ids = {}
            for did, dv in dev_ops.items():
                tid = dv.get("template") or dv.get("template_id")
                ports = dv.get("ports") or library.expand_port_groups(library.get_template(tid, doc).get("ports") or [])
                port_ids[did] = {x["id"] for x in ports}
            for c in cable_ops:
                for end in ("from", "to"):
                    self.assertIn(c[end]["device"], port_ids, "cables only between drafted devices")
                    self.assertIn(c[end]["port"], port_ids[c[end]["device"]], "%s: %s is a real port of %s" % (c["id"], c[end]["port"], c[end]["device"]))
            self.assertEqual(len({(c["to"]["device"], c["to"]["port"]) for c in cable_ops}), 10, "no input is used twice")
            self.assertEqual(len({(c["from"]["device"], c["from"]["port"]) for c in cable_ops}), 10, "no output is used twice")
            # audio-video-lighting chains
            r2 = self.D.draft(doc, "QuickQ 10, DMX node, 4 LED pars; ATEM Mini, 2 PTZ cameras, projector, laptop; LA12X amp, 2 K12.2", "main")
            trip = [(c["from"]["device"], c["to"]["device"], c["medium"]) for c in r2["changes"] if c["action"] == "connect"]
            self.assertIn(("Lighting console 2", "DMX node", "sacn"), trip, "lighting console → node over sACN")
            self.assertIn(("Camera 1", "ATEM Mini Pro", "hdmi"), trip, "cameras into the switcher")
            self.assertFalse([t for t in trip if "Laptop" in t], "a bare-kind laptop has no template ports, so nothing is patched to it")
            self.assertIn(("ATEM Mini Pro", "Projector", "hdmi"), trip)
            self.assertFalse([t for t in trip if t[0] == "Lighting console 2" and t[1].startswith("Fixture")], "with a node the desk does not drive fixtures directly")
            self.assertIn("Fixture", r2["note"], "bare-kind fixtures have no ports: listed in the note")
            self.assertTrue(E.new_proposal(doc, r2["changes"], base_revision=doc["revision"])["applicable"])

    def test_cap_40_changes(self):
        with temp_data_dir() as data:
            _, doc = _campus_doc(data)
            r = self.D.draft(doc, "16 ULXD4D, 16 K12.2, 16 SM58, X32", "chapel")
            self.assertEqual(len(r["changes"]), self.D.MAX_CHANGES, fr("FR-AST-15", "6.9.5b", "at most 40 changes"))
            self.assertEqual(self.D.MAX_CHANGES, 40)
            self.assertTrue(all(c["action"] == "add_device" for c in r["changes"]), "devices first, links fill what is left")
            self.assertIn("Only the first 40 changes are in this draft", r["note"])
            self.assertIn("Apply, then describe the rest", r["note"])
            self.assertEqual(sum(x["count"] for x in r["recognised"]), 49, "recognised still reports everything mentioned")


class ApiDeterministic(unittest.TestCase):
    """§5.10: ``mode: "draft"`` needs a room; the proposal goes through the normal confirm-before-edit apply."""

    def setUp(self):
        self.app = get_app()
        requires("assistant_draft")

    def test_room_required_and_mode_validation(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            st, _, b = call(self.app, "POST", ASK, {"question": CHURCH, "mode": "draft"}, JSON_H)
            self.assertEqual(st, 400, b[:200])
            self.assertEqual(jbody(b)["code"], "room_required", fr("FR-AST-16", "5.10", "draft without a room → 400 room_required"))
            st, _, b = call(self.app, "POST", ASK, {"question": CHURCH, "mode": "draft", "room": "attic"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (400, "room_required"), "an unknown room is the same error")
            st, _, b = call(self.app, "POST", ASK, {"question": CHURCH, "mode": "sketch", "room": "chapel"}, JSON_H)
            self.assertEqual(st, 400, "mode must be ask or draft")
            st, _, b = call(self.app, "POST", ASK, {"question": "where does the chapel wireless go?", "room": "chapel"}, JSON_H)
            self.assertEqual(st, 200)
            self.assertNotIn("draft", jbody(b), "ask mode (the default) is unchanged")
            st, _, b = call(self.app, "POST", ASK, {"question": "what is here?", "mode": "ask"}, JSON_H)
            self.assertEqual(st, 200, "ask needs no room")

    def test_draft_then_apply(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            before = _api_doc(self.app)
            rev0 = before["revision"]
            with _Guard():
                st, _, b = call(self.app, "POST", ASK, {"question": CHURCH, "mode": "draft", "room": "Chapel"}, JSON_H)
            self.assertEqual(st, 200, b[:400])
            a = jbody(b)
            self.assertEqual(a["llm"], {"used": False}, "no model configured → deterministic drafter, no socket")
            self.assertEqual(a["intent"]["type"], "draft")
            self.assertEqual(a["intent"]["room"], "chapel", "room resolved by name")
            d = a["draft"]
            self.assertEqual(sorted(d.keys()), ["note", "recognised", "unknown"], fr("FR-AST-16", "5.10", "Answer.draft"))
            self.assertEqual([x.get("template") or x.get("preset") for x in d["recognised"]],
                             ["behringer-x32", "generic-stagebox", "shure-ulxd4d", "qsc-k12-2", "blackmagic-atem-mini-pro", "generic-lighting-console"])
            self.assertEqual(d["unknown"], [])
            self.assertIn("Stage box \u2192 X32", d["note"])
            self.assertNotIn("suggestion", a)
            p = a["proposal"]
            self.assertRegex(p["id"], r"^pp-[0-9a-f]{8}$")
            self.assertEqual(p["note"], "Drafted from your description")
            self.assertTrue(p["applicable"], p["problems"])
            self.assertEqual(len(p["ops"]), 20)
            self.assertEqual(p["base_revision"], rev0)
            self.assertIn("Drafted **10 devices** and **10 connections** for **Chapel**", a["summary"])
            self.assertEqual(a["confidence"], "high")
            self.assertEqual(_api_doc(self.app)["revision"], rev0, fr("FR-AST-13", "5.10", "nothing changes before /apply"))
            st, _, b = call(self.app, "POST", ASK + "/apply", {"id": p["id"], "base_revision": rev0}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            self.assertEqual((jbody(b)["revision"], jbody(b)["applied"]), (rev0 + 1, 20))
            after = _api_doc(self.app)
            devs = {x["id"]: x for x in after["doc"]["devices"]}
            self.assertEqual(len(after["doc"]["devices"]) - len(before["doc"]["devices"]), 10)
            self.assertEqual(len(after["doc"]["cables"]) - len(before["doc"]["cables"]), 10)
            for did in ("x32", "stage-box", "ulxd4d-1", "ulxd4d-4", "k12-2-2", "atem-mini-pro", "lighting-console-2"):
                self.assertIn(did, devs, did)
                self.assertEqual(devs[did]["room"], "chapel")
            self.assertEqual(devs["x32"]["model"], "X32")
            new_cables = [c for c in after["doc"]["cables"] if c["from"]["device"] in ("ulxd4d-1", "x32")]
            self.assertTrue(all(c["from"]["port"] in ("analog-out-1", "analog-out-2", "xlr-out-1", "xlr-out-2") for c in new_cables), new_cables)
            port_ids = {p["id"] for p in devs["x32"]["ports"]}
            self.assertTrue(all(c["to"]["port"] in port_ids for c in after["doc"]["cables"] if c["to"]["device"] == "x32"), "patched to ports that exist on the X32")
            # a second draft into the same room does not collide with what was just applied
            st, _, b = call(self.app, "POST", ASK, {"question": "X32, 2 K12.2", "mode": "draft", "room": "chapel"}, JSON_H)
            names = [c["name"] for c in jbody(b)["proposal"]["changes"] if c["action"] == "add_device"]
            self.assertEqual(names, ["X32 2", "K12.2 3", "K12.2 4"])

    def test_unknown_only_has_no_proposal(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            st, _, b = call(self.app, "POST", ASK, {"question": "a frobnicator 9000 and three widgets", "mode": "draft", "room": "chapel"}, JSON_H)
            self.assertEqual(st, 200)
            a = jbody(b)
            self.assertNotIn("proposal", a)
            self.assertEqual(a["draft"], {"recognised": [], "unknown": ["frobnicator 9000", "widgets"], "note": ""})
            self.assertIn("couldn't recognise", a["summary"])
            self.assertEqual(a["confidence"], "low")


class ApiLlm(unittest.TestCase):
    """§6.9.6 + §6.9.5b: in draft mode the system prompt names the room, ``draft_room`` runs the same resolver and the model proposes."""

    def setUp(self):
        self.app = get_app()
        self.AT = requires("assistant_tools")
        self.D = requires("assistant_draft")

    def test_tool_registered_and_prompt_line(self):
        api = self.AT._Api(None)
        names = [t.name for t in self.AT.tool_specs(api, {})]
        self.assertIn("draft_room", names, fr("FR-AST-17", "6.9.6", "draft_room tool"))
        spec = [t for t in self.AT.tool_specs(api, {}) if t.name == "draft_room"][0]
        self.assertEqual(spec.parameters["type"], "object")
        self.assertIn("devices", spec.parameters["properties"])
        with temp_data_dir() as data:
            _, doc = _campus_doc(data)
            ctx = {"doc": doc, "overlay": None, "room": "chapel", "mode": "draft", "draft": {}}
            out = json.loads(self.AT.run_tool("draft_room", {"devices": [{"text": "X32"}, {"text": "2 K12.2"}, "frobnicator"], "room": "chapel"}, ctx))
            self.assertEqual([c["action"] for c in out["changes"]], ["add_device"] * 3 + ["connect"] * 2)
            self.assertEqual(out["unknown"], ["frobnicator"])
            self.assertEqual(ctx["draft"]["unknown"], ["frobnicator"], "the result is kept for Answer.draft")
            self.assertTrue(out.get("hint"), "the tool tells the model to pass the changes to propose_changes")
            msgs = self.AT.build_messages(api, doc, "X32 and two K12.2", None, dict(ctx, project="campus", role="editor"))
            self.assertIn("DRAFT MODE", msgs[0].content)
            self.assertIn('"chapel"', msgs[0].content)
            self.assertIn("Never add equipment the user did not mention", msgs[0].content)
            plain = self.AT.build_messages(api, doc, "X32 and two K12.2", None, {"doc": doc, "room": "chapel", "project": "campus", "role": "editor"})
            self.assertNotIn("DRAFT MODE", plain[0].content, "ask mode keeps the usual prompt")

    def test_fixture_church(self):
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "draft-church-basic.json")) as data:
            install_campus(data, "campus")
            rev0 = _api_doc(self.app)["revision"]
            with _Guard():
                st, _, b = call(self.app, "POST", ASK, {"question": "X32 with an S16 stage box, 2 ULXD4D wireless, 2 K12.2 on stands, ATEM Mini", "mode": "draft", "room": "chapel"}, JSON_H)
            self.assertEqual(st, 200, b[:400])
            a = jbody(b)
            self.assertTrue(a["llm"]["used"], a["llm"])
            self.assertEqual([t["name"] for t in a["llm"]["tools"]], ["draft_room", "propose_changes"], fr("FR-AST-17", "6.9.6", "draft_room then propose_changes"))
            self.assertIn("Draft for the Chapel", a["llm"]["text"])
            self.assertEqual([x.get("template") or x.get("preset") for x in a["draft"]["recognised"]],
                             ["behringer-x32", "generic-stagebox", "shure-ulxd4d", "qsc-k12-2", "blackmagic-atem-mini-pro"], "Answer.draft comes from the tool run")
            self.assertEqual(a["draft"]["unknown"], [])
            p = a["proposal"]
            self.assertEqual(p["note"], "Chapel draft: X32, stage box, 2 ULXD4D, 2 K12.2, ATEM Mini Pro")
            self.assertTrue(p["applicable"], p["problems"])
            self.assertEqual(len(p["ops"]), 13)
            self.assertEqual(_api_doc(self.app)["revision"], rev0)
            st, _, b = call(self.app, "POST", ASK + "/apply", {"id": p["id"], "base_revision": rev0}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b)["applied"], 13)
            devs = {x["id"] for x in _api_doc(self.app)["doc"]["devices"]}
            self.assertTrue({"x32", "stage-box", "ulxd4d-1", "ulxd4d-2", "k12-2-1", "k12-2-2", "atem-mini-pro"} <= devs)

    def test_fixture_unknown(self):
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "draft-unknown.json")) as data:
            install_campus(data, "campus")
            with _Guard():
                st, _, b = call(self.app, "POST", ASK, {"question": "a frobnicator 9000 and three widgets", "mode": "draft", "room": "chapel"}, JSON_H)
            self.assertEqual(st, 200, b[:400])
            a = jbody(b)
            self.assertTrue(a["llm"]["used"])
            self.assertEqual([t["name"] for t in a["llm"]["tools"]], ["draft_room"])
            self.assertNotIn("proposal", a, "the model proposed nothing and the deterministic fallback finds nothing either")
            self.assertEqual(a["draft"]["unknown"], ["frobnicator 9000", "widgets"])
            self.assertIn("could not place", a["llm"]["text"])

    def test_use_llm_false_is_deterministic(self):
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "draft-church-basic.json")) as data:
            install_campus(data, "campus")
            st, _, b = call(self.app, "POST", ASK, {"question": CHURCH, "mode": "draft", "room": "chapel", "use_llm": False}, JSON_H)
            a = jbody(b)
            self.assertEqual(a["llm"], {"used": False})
            self.assertEqual(a["proposal"]["note"], "Drafted from your description")


if __name__ == "__main__":
    unittest.main()
