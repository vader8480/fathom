"""Assistant, tracing, search, checklists, LLM bridge (SPEC §3.16–3.18, §5.10–5.11, §6.9, Appendix F)."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

try:
    from _helpers import fr, install_project, install_sunday, requires, sunday_doc, temp_data_dir, temp_env, uniq
except ImportError:  # pragma: no cover
    from tests._helpers import fr, install_project, install_sunday, requires, sunday_doc, temp_data_dir, temp_env, uniq

Q_LIVESTREAM = "House sound is fine, but the livestream has no audio."
EXPECTED_HOPS = [{"device": "audio-rack-1", "port": "analog-out-4", "label": "Audio Rack 1 · Stream"},
                 {"device": "atem-mini", "port": "analog-in-1", "label": "ATEM Mini · Stream"},
                 {"device": "atem-mini", "port": "usb-out-1", "label": "USB Stream Out"},
                 {"device": "restream", "port": "usb-in-1", "label": "Restream"}]
EXPECTED_CHECKS = [
    {"n": 1, "text": "Confirm the **Stream** output is up on Audio Rack 1 — it feeds ATEM Mini separately from Main Speakers - L/R.",
     "device": "audio-rack-1", "port": "analog-out-4", "source": "kinds:stage_io/output-up"},
    {"n": 2, "text": "On the ATEM Mini's Audio tab, make sure the **Stream** input is set to ON, not AFV (inputs default to audio-follow-video).",
     "device": "atem-mini", "port": "analog-in-1", "source": "template:blackmagic-atem-mini-pro/audio-on"},
    {"n": 3, "text": "Check levels on the ATEM Mini's Program meter before it reaches Restream.", "device": "atem-mini", "port": "usb-out-1",
     "source": "kinds:video_switcher/program-meter"},
]
NOTE = "Stream feed: Audio Rack 1 → ATEM Mini · check Audio tab"
A1_KINDS = ["source", "stage_io", "computer", "console", "iem", "pa", "network", "video", "other", "mic", "wireless_rx", "processor", "amp",
            "speaker", "recorder", "intercom", "camera", "video_source", "video_switcher", "video_router", "converter", "encoder", "stream",
            "display", "projector", "lighting_console", "dmx_node", "dimmer", "fixture", "switch", "control", "touch_panel", "power", "patch_panel"]


def node_targets(edges, node=None):
    """Normalize PortGraph edge listings to the set of *other* endpoint refs (strings, tuples, dicts or objects)."""
    keys = ("dst", "to", "target", "node", "src", "from", "source")
    out = set()
    for e in edges or []:
        if isinstance(e, str):
            cands = [e]
        elif isinstance(e, (tuple, list)):
            cands = [x for x in e if isinstance(x, str) and ":" in x]
        elif isinstance(e, dict):
            cands = [e[k] for k in keys if isinstance(e.get(k), str) and ":" in e[k]]
        else:
            cands = [getattr(e, k) for k in keys if isinstance(getattr(e, k, None), str) and ":" in getattr(e, k)]
        other = [c for c in cands if c != node] or cands[:1]
        if other:
            out.add(other[0])
    return out


def hop_refs(paths):
    return {"%s:%s" % (h["device"], h.get("port") or "*") for p in paths for h in p["hops"]}


class Assistant(unittest.TestCase):
    def setUp(self):
        self.assistant = requires("assistant")
        requires("llm")

    def answer(self, q, doc=None, **kw):
        kw.setdefault("room", "main")
        kw.setdefault("base_revision", 1)
        with temp_env(FATHOM_LLM_URL=None, FATHOM_LLM_MODEL=None, FATHOM_LLM_API_KEY=None):
            return self.assistant.answer(doc or sunday_doc(), q, **kw)

    def test_livestream_no_audio(self):
        a = self.answer(Q_LIVESTREAM)
        self.assertEqual(a["question"], Q_LIVESTREAM)
        self.assertEqual(a["paths"][0]["text"], "Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream", fr("FR-AST-02", "3.16"))
        self.assertGreaterEqual(len(a["checks"]), 3, fr("FR-AST-02", "3.16"))
        self.assertIn("Audio Rack 1", a["checks"][0]["text"], fr("FR-AST-02", "3.16"))
        self.assertIn("Stream", a["checks"][0]["text"], fr("FR-AST-02", "3.16"))
        it = a["intent"]
        self.assertEqual(it["symptom"], "no_audio", fr("FR-AST-02", "3.16"))
        self.assertEqual(it["targets"], ["restream"], fr("FR-AST-02", "3.16"))
        self.assertEqual(it["working"], ["main-speakers", "sub-x2"], fr("FR-AST-02", "3.16"))
        self.assertEqual((it["type"], it["discipline"], it["room"]), ("troubleshoot", "audio", "main"), fr("FR-AST-02", "5.10"))

    def test_answer_structure_5_10(self):
        a = self.answer(Q_LIVESTREAM)
        for k in ("question", "intent", "summary", "paths", "branch", "suspects", "checks", "notes", "suggestion", "confidence", "unresolved", "llm"):
            self.assertIn(k, a, fr("FR-AST-02", "5.10", k))
        self.assertEqual(a["summary"], "Your stream audio takes its own path: **Audio Rack 1 · Stream** → **ATEM Mini · Stream** → USB Stream Out → Restream.",
                         fr("FR-AST-02", "5.10 / 6.9.5 step 10", "summary"))
        p0 = a["paths"][0]
        self.assertEqual(p0["hops"], EXPECTED_HOPS, fr("FR-AST-02", "5.10", "paths[0].hops"))
        self.assertEqual(p0["cables"], ["c-0011", "c-0015"], fr("FR-AST-02", "5.10"))
        self.assertEqual(p0["role"], "suspect")
        self.assertTrue(all(p["role"] == "context" for p in a["paths"][1:]) and len(a["paths"]) <= 3, "6.9.5 up to 2 context paths")
        self.assertEqual(a["branch"], {"device": "audio-rack-1", "reason": "Shared with Main Speakers - L/R, which works"}, fr("FR-AST-02", "5.10", "branch"))
        self.assertEqual(a["suspects"], [{"device": h["device"], "port": h["port"]} for h in EXPECTED_HOPS], fr("FR-AST-02", "5.10", "suspects"))
        self.assertEqual(a["checks"][:3], EXPECTED_CHECKS, fr("FR-AST-02", "F.6 / 5.10", "the first three checks exactly"))
        self.assertLessEqual(len(a["checks"]), 8, "5.10 checks <= 8")
        self.assertEqual([c["n"] for c in a["checks"]], list(range(1, len(a["checks"]) + 1)), "5.10 numbered from 1")
        self.assertEqual(len({c["source"] for c in a["checks"]}), len(a["checks"]), "6.9.5 de-duplicated by check id")
        self.assertTrue([n for n in a["notes"] if "ATEM Mini" in n and "Stage Box 1" in n and "not patched" in n], fr("FR-AST-02", "6.9.5 step 8 (ii)", "note about the unpatched HDMI source: %s" % a["notes"]))
        self.assertEqual(a["confidence"], "high", "5.10 target + working resolved and one suspect path")
        self.assertEqual(a["unresolved"], [])
        self.assertEqual(a["llm"], {"used": False}, "5.10 llm not configured")
        self.assertNotIn("<", a["summary"], "5.10 summary uses **bold** only")
        json.dumps(a)

    def test_suggestion_ops(self):
        schema = requires("schema")
        doc = sunday_doc()
        a = self.answer(Q_LIVESTREAM, doc=doc)
        s = a["suggestion"]
        self.assertEqual(s["text"], 'Add note "%s" to ATEM Mini · Stream' % NOTE, fr("FR-AST-03", "5.10"))
        self.assertEqual(s["base_revision"], 1)
        self.assertEqual(len(s["ops"]), 1)
        op = s["ops"][0]
        self.assertEqual((op["op"], op["coll"], op["id"], list(op["value"])), ("merge", "devices", "atem-mini", ["ports"]), fr("FR-AST-03", "6.9.5 step 11"))
        new, touched = schema.apply_ops(doc, s["ops"])
        ports = {p["id"]: p for p in [d for d in new["devices"] if d["id"] == "atem-mini"][0]["ports"]}
        self.assertEqual(ports["analog-in-1"].get("note"), NOTE, fr("FR-AST-03", "3.16", "Yes sets the note"))
        old = {p["id"]: p for p in [d for d in doc["devices"] if d["id"] == "atem-mini"][0]["ports"]}
        for pid in old:
            if pid != "analog-in-1":
                self.assertEqual(ports[pid], old[pid], "other ports unchanged")
        self.assertEqual(len(ports), len(old), "full ports array kept")
        again = self.answer(Q_LIVESTREAM, doc=new)
        self.assertIsNone(again["suggestion"], fr("FR-AST-03", "6.9.5 step 11", "skip if the port note already contains the text"))
        withnote = copy.deepcopy(doc)
        [p for p in [d for d in withnote["devices"] if d["id"] == "atem-mini"][0]["ports"] if p["id"] == "analog-in-1"][0]["note"] = "old"
        s2 = self.answer(Q_LIVESTREAM, doc=withnote)["suggestion"]
        new2, _ = schema.apply_ops(withnote, s2["ops"])
        p2 = [p for p in [d for d in new2["devices"] if d["id"] == "atem-mini"][0]["ports"] if p["id"] == "analog-in-1"][0]
        self.assertEqual(p2["note"], "old; " + NOTE, "6.9.5 step 11 appends with '; '")

    def test_parse_intent_cases(self):
        pi = self.assistant.parse_intent
        doc = sunday_doc()
        cases = [
            ("How does the sound board get to the subs?", {"type": "trace"}),
            ("What feeds Samsung TV - 1?", {"type": "trace"}),
            ("trace the restream", {"type": "trace"}),
            ("Where is the spare ULXD4D?", {"type": "locate"}),
            ("which rack is the shure wireless in", {"type": "locate"}),
            ("What is on Audio Rack 1 input 3?", {"type": "describe"}),
            ("The TV has no picture", {"type": "troubleshoot", "symptom": "no_video", "discipline": "video"}),
            ("there's a hum in the main speakers", {"type": "troubleshoot", "symptom": "noise", "discipline": "audio"}),
            ("the screen is flickering", {"type": "troubleshoot", "symptom": "flicker"}),
            ("lights not responding", {"type": "troubleshoot", "symptom": "lighting_no_response", "discipline": "lighting"}),
            ("the switcher is offline", {"type": "troubleshoot", "symptom": "no_network"}),
            ("something is weird with the ATEM", {"type": "troubleshoot", "symptom": "general"}),
        ]
        for q, exp in cases:
            with self.subTest(q=q):
                it = pi(doc, q, room="main")
                for k, v in exp.items():
                    self.assertEqual(it.get(k), v, fr("FR-AST-02", "6.9.5", "%s: %s" % (q, k)))
        it = pi(doc, "What feeds Samsung TV - 1?", room="main")
        self.assertIn("samsung-tv-1", it["targets"], "6.9.5 search hit target")
        it = pi(doc, "the livestream has no audio", room="main")
        self.assertEqual(it["targets"], ["restream"], "6.9.5 'livestream' role phrase never matches Audio Rack 1")
        self.assertNotIn("audio-rack-1", it.get("working", []) + it["targets"])
        it = pi(doc, "The Sound Board has no audio but the subs are fine", room="main")
        self.assertIn("sound-board", it["targets"], "F.2 exact device-name hit beats the 'board' role phrase")
        self.assertEqual(it["working"], ["sub-x2"], "F.2 subs role with name_contains 'sub'")

    def test_trace_question_tv(self):
        a = self.answer("What feeds Samsung TV - 1?")
        self.assertEqual(a["intent"]["type"], "trace", fr("FR-AST-04", "3.16"))
        self.assertEqual(a["checks"], [], fr("FR-AST-04", "3.16", "trace answers carry no checks"))
        through = [p for p in a["paths"] if {"video-converter", "atem-mini"} <= {h["device"] for h in p["hops"]}]
        self.assertTrue(through, fr("FR-AST-04", "3.16", "path through video-converter and atem-mini"))
        a2 = self.answer("how does the sound board get to the subs")
        self.assertEqual(a2["intent"]["type"], "trace")
        self.assertTrue(a2["paths"], "trace A->B returns paths")
        self.assertTrue([p for p in a2["paths"] if p["hops"][-1]["device"] == "sub-x2"])

    def test_locate_spare(self):
        a = self.answer("Where is the spare ULXD4D?")
        self.assertEqual(a["intent"]["type"], "locate", fr("FR-AST-05", "3.16"))
        self.assertIn("ULXD4D", json.dumps(a["summary"]), fr("FR-AST-05", "3.16"))
        b = self.answer("What is on Audio Rack 1 input 3?")
        self.assertEqual(b["intent"]["type"], "describe")
        self.assertIn("Wireless 1", json.dumps(b, ensure_ascii=False), fr("FR-AST-05", "3.16", "port label 'Wireless 1'"))
        c = self.answer("which rack is the shure wireless in")
        self.assertIn("FOH rack", json.dumps(c, ensure_ascii=False), fr("FR-AST-05", "3.16", "rack named in the answer"))

    def test_unresolved_suggestions(self):
        a = self.answer("projector 2 has no picture")
        self.assertTrue(a["unresolved"], fr("FR-AST-08", "3.16"))
        self.assertIn("projector 2", json.dumps(a["unresolved"]).lower(), fr("FR-AST-08", "3.16", "names the unresolved phrase"))
        self.assertEqual(a["confidence"], "low")
        self.assertLessEqual(len(json.dumps(a["unresolved"])) > 0, True)

    def test_passthrough_routing(self):
        trace = requires("trace")
        g = trace.port_graph(sunday_doc())
        paths = trace.upstream_paths(g, "stage-box-1:hdmi-out-1")
        sb = {h["port"] for p in paths for h in p["hops"] if h["device"] == "stage-box-1"}
        self.assertEqual(sb, {"hdmi-in-1", "hdmi-out-1"}, fr("FR-PORT-05", "3.3", "passthrough reaches only hdmi-in-1"))
        down = trace.downstream_paths(g, "main-speakers:analog-in-1")
        self.assertIn("main-speakers:thru-1", hop_refs(down), "4.4.5 passthrough idx pairing Analog In 1 -> Thru 1")
        self.assertNotIn("main-speakers:thru-2", hop_refs(down))

    def test_port_graph_edges(self):
        trace = requires("trace")
        g = trace.port_graph(sunday_doc())
        out = lambda n: node_targets(g.edges_out(n), n)  # noqa: E731
        inn = lambda n: node_targets(g.edges_in(n), n)  # noqa: E731
        self.assertIn("atem-mini:analog-in-1", out("audio-rack-1:analog-out-4"), fr("FR-TRC-01", "6.9.3", "cable edge from -> to"))
        self.assertNotIn("audio-rack-1:analog-out-4", out("atem-mini:analog-in-1"), "6.9.3 one-way for in/out ports")
        self.assertIn("audio-rack-1:dsnake", out("sound-board:slink"), fr("FR-TRC-01", "6.9.3", "bidirectional cable"))
        self.assertIn("sound-board:slink", out("audio-rack-1:dsnake"), fr("FR-TRC-01", "6.9.3", "bidirectional cable both ways"))
        self.assertIn("atem-mini:usb-out-1", out("atem-mini:analog-in-1"), fr("FR-TRC-01", "4.4.5", "matrix internal edge"))
        self.assertEqual(out("restream:usb-in-1"), set(), fr("FR-TRC-01", "4.4.5", "stream kind routing none"))
        self.assertNotIn("stage-box-1:hdmi-out-1", out("stage-box-1:analog-in-1"), "4.4.5 passthrough needs the same medium")
        self.assertIn("audio-rack-1:analog-out-4", inn("atem-mini:analog-in-1"))
        ov = {"routes": [{"kind": "dante", "from": {"device": "audio-rack-1", "port": "dsnake"}, "to": {"device": "restream"}, "medium": "network"}]}
        g2 = trace.port_graph(sunday_doc(), overlay=ov)
        self.assertIn("restream:*", node_targets(g2.edges_out("audio-rack-1:dsnake"), "audio-rack-1:dsnake"), fr("FR-TRC-01", "6.9.3", "overlay route edge, device-level when the port is missing"))
        d = sunday_doc()
        d["cables"].append({"id": "c-dev", "from": {"device": "restream"}, "to": {"device": "samsung-tv-1", "port": "hdmi-in-1"}, "medium": "network"})
        g3 = trace.port_graph(d)
        self.assertIn("samsung-tv-1:hdmi-in-1", node_targets(g3.edges_out("restream:*"), "restream:*"), "6.9.1 device-level virtual node dev:*")
        d = sunday_doc()
        d["devices"][5]["status"] = "planned"
        g4 = trace.port_graph(d, state="as_built")
        self.assertNotIn("atem-mini:analog-in-1", out_of(g4, "audio-rack-1:analog-out-4"), "6.9.3 excluded devices contribute no nodes")

    def test_discipline_filter_video(self):
        trace = requires("trace")
        g = trace.port_graph(sunday_doc(), discipline="video")
        refs = hop_refs(trace.upstream_paths(g, "samsung-tv-1:sdi-in-1"))
        self.assertIn("atem-mini:hdmi-in-1", refs, fr("FR-TRC-02", "3.17"))
        self.assertNotIn("atem-mini:analog-in-1", refs, fr("FR-TRC-02", "3.17"))
        ga = trace.port_graph(sunday_doc(), discipline="audio")
        down = trace.downstream_paths(ga, "audio-rack-1:analog-out-4")
        cables = set(c for p in down for c in p["cables"])
        self.assertEqual(cables, {"c-0011", "c-0013", "c-0014", "c-0015"}, fr("FR-TRC-05", "3.17", "downstream audio from analog-out-4"))

    def test_path_text_rule(self):
        trace = requires("trace")
        doc = sunday_doc()
        path = {"hops": [{"device": h["device"], "port": h["port"]} for h in EXPECTED_HOPS], "cables": ["c-0011", "c-0015"]}
        self.assertEqual(trace.path_text(doc, path), "Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream", fr("FR-TRC-03", "6.9.4"))
        self.assertEqual(trace.hop_labels(doc, path), [h["label"] for h in EXPECTED_HOPS])
        g = trace.port_graph(doc, discipline="audio")
        ps = trace.port_paths(g, "audio-rack-1:analog-out-4", "restream:usb-in-1")
        self.assertTrue(ps, fr("FR-TRC-03", "3.17", "A->B search"))
        self.assertEqual(ps[0]["hops"], path["hops"])
        self.assertEqual(ps[0]["cables"], path["cables"])
        up = trace.upstream_paths(g, "restream:usb-in-1")
        self.assertEqual(up, trace.upstream_paths(g, "restream:usb-in-1"), "6.9.4 deterministic")
        lens = [len(p["hops"]) for p in up]
        self.assertEqual(lens, sorted(lens), "6.9.4 shortest first")
        self.assertLessEqual(len(trace.upstream_paths(g, "restream:usb-in-1", limit=1)), 1, "limit respected")
        self.assertEqual(trace.resolve_ref(doc, "atem-mini:usb-out-1"), ("atem-mini", "usb-out-1"))
        self.assertEqual(trace.resolve_ref(doc, "ATEM Mini"), ("atem-mini", None))
        self.assertIsNone(trace.resolve_ref(doc, "no such thing at all"))

    def test_search_ip(self):
        search = requires("search")
        hits = search.search(sunday_doc(), "10.20.0.40")
        iface = [h for h in hits if h["kind"] == "interface"]
        self.assertTrue(iface, fr("FR-SRCH-01", "3.18"))
        self.assertEqual((iface[0]["id"], iface[0]["device"]), ("atem-mini/primary", "atem-mini"), fr("FR-SRCH-01", "5.11", "interface id <device>/<interface>"))
        idx = search.build_index(sunday_doc())
        self.assertEqual(search.search(idx, "10.20.0.40")[0]["id"], "atem-mini/primary")
        for q, kind, ident in (("SQ5-004211", "device", "sound-board"), ("HC-0012", "device", "sound-board"), ("A-003", "cable", "c-0005"),
                               ("Wireless 1", "port", None), ("FOH rack", "rack", "rk-foh"), ("Main Auditorium", "room", "main")):
            hs = search.search(sunday_doc(), q)
            self.assertTrue([h for h in hs if h["kind"] == kind and (ident is None or h["id"] == ident)], fr("FR-SRCH-01", "3.18", "%r finds %s %s" % (q, kind, ident)))
        port = [h for h in search.search(sunday_doc(), "USB Stream Out") if h["kind"] == "port"][0]
        self.assertEqual((port["id"], port["device"], port["port"]), ("atem-mini:usb-out-1", "atem-mini", "usb-out-1"), "5.11 port id <device>:<port>")

    def test_search_ranking(self):
        search = requires("search")
        doc = sunday_doc()
        hits = search.search(doc, "atem")
        self.assertEqual((hits[0]["kind"], hits[0]["id"]), ("device", "atem-mini"), fr("FR-SRCH-04", "3.18", "'atem' ranks ATEM Mini first"))
        score = lambda q, ident: max([h["score"] for h in search.search(doc, q, limit=50) if h["id"] == ident] or [0])  # noqa: E731
        self.assertEqual(score("ATEM Mini", "atem-mini"), 100, fr("FR-SRCH-04", "3.18", "exact 100"))
        self.assertEqual(score("Audio R", "audio-rack-1"), 80, fr("FR-SRCH-04", "3.18", "prefix 80"))
        self.assertEqual(score("Rack", "audio-rack-1"), 60, fr("FR-SRCH-04", "3.18", "token 60"))
        self.assertEqual(score("udio Ra", "audio-rack-1"), 40, fr("FR-SRCH-04", "3.18", "substring 40"))
        self.assertEqual(score("Restrem", "restream"), 25, fr("FR-SRCH-04", "3.18", "fuzzy edit distance 1 on tokens >= 4 chars"))
        rk = search.search(doc, "rack", limit=50)
        top = [h for h in rk if h["score"] == rk[0]["score"]]
        order = ["device", "port", "cable", "interface", "room", "rack", "floorplan", "attachment"]
        self.assertEqual([h["kind"] for h in top], sorted([h["kind"] for h in top], key=order.index), "3.18 ties by kind order")
        self.assertLessEqual(len(search.search(doc, "a", limit=5)), 5)
        self.assertTrue(all(h["kind"] == "cable" for h in search.search(doc, "A-00", kinds=["cable"])))

    def test_checklists_seed_and_coverage(self):
        cl = self.assistant.load_checklists(refresh=True)
        blob = json.dumps(cl)
        kinds = self._kinds_map(cl)
        for k in A1_KINDS:
            self.assertGreaterEqual(len(kinds.get(k, [])), 2, fr("FR-AST-02", "F.3", "at least 2 checks for kind %s" % k))
        stage = {c["id"] for c in kinds["stage_io"]}
        self.assertTrue({"output-up", "input-gain", "link-lights"} <= stage, "F.3 seed checks")
        for s in ("no_audio", "no_video", "noise", "feedback", "dropout", "latency", "flicker", "wrong_source", "lighting_no_response", "no_network", "no_power"):
            self.assertIn('"%s"' % s, blob, "F.1 symptom %s" % s)
        self.assertIn("livestream", blob, "F.2 role phrases")

    def _kinds_map(self, cl):
        if "kinds" in cl and isinstance(cl["kinds"], dict) and "kinds" in cl["kinds"]:
            return cl["kinds"]["kinds"]
        return cl.get("kinds", {})

    def test_extra_checklist_dir(self):
        with temp_data_dir() as data:
            ext = data / "checklists"
            ext.mkdir()
            (ext / "kinds.json").write_text(json.dumps({"version": 1, "kinds": {"video_switcher": [
                {"id": "program-meter", "symptoms": ["no_audio"], "when": {"port_dir": "out"}, "text": "T1 EXTRA: check {device} program audio for {next_device}."}]}}))
            with temp_env(FATHOM_CHECKLISTS=str(ext)):
                self.assistant.load_checklists(refresh=True)
                try:
                    a = self.answer(Q_LIVESTREAM)
                finally:
                    pass
            self.assistant.load_checklists(refresh=True)
        texts = [c["text"] for c in a["checks"]]
        self.assertIn("T1 EXTRA: check ATEM Mini program audio for Restream.", texts, fr("FR-EXT-03", "F (same id replaces)", "extra checklist dir changes the checks: %s" % texts))
        self.assertNotIn(EXPECTED_CHECKS[2]["text"], texts)

    def test_llm_stub_and_unconfigured(self):
        llm = requires("llm")
        with temp_env(FATHOM_LLM_URL=None, FATHOM_LLM_MODEL=None, FATHOM_LLM_API_KEY=None):
            self.assertFalse(llm.configured(), fr("FR-AST-07", "6.9.6", "configured() false by default"))

            def no_socket(*a, **k):
                raise AssertionError("FR-AST-07: urlopen called while the LLM is not configured")

            with mock.patch("urllib.request.urlopen", no_socket):
                a = self.assistant.answer(sunday_doc(), Q_LIVESTREAM, room="main", use_llm=True, base_revision=1)
            self.assertEqual(a["llm"], {"used": False}, fr("FR-AST-07", "3.16", "not configured -> used false, no socket"))
            baseline = {k: v for k, v in a.items() if k != "llm"}

        seen = []

        class Handler(BaseHTTPRequestHandler):
            mode = "ok"

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(self.rfile.read(n).decode())})
                if Handler.mode == "fail":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"boom")
                    return
                body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "Check the ATEM audio mixer. (stub)"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            url = "http://127.0.0.1:%d/v1" % srv.server_address[1]
            with temp_env(FATHOM_LLM_URL=url, FATHOM_LLM_MODEL="stub-model", FATHOM_LLM_API_KEY="sk-t1-stub", FATHOM_LLM_TIMEOUT="5"):
                self.assertTrue(llm.configured())
                info = llm.info()
                self.assertEqual(info.get("model"), "stub-model")
                self.assertNotIn("sk-t1-stub", json.dumps(info), "6.9.6 info() has no key")
                a = self.assistant.answer(sunday_doc(), Q_LIVESTREAM, room="main", use_llm=True, base_revision=1)
                self.assertTrue(a["llm"]["used"], fr("FR-AST-07", "3.16", "stub server -> used true: %s" % a["llm"]))
                self.assertTrue(a["llm"]["text"], fr("FR-AST-07", "3.16", "llm.text non-empty"))
                self.assertEqual(a["llm"].get("model"), "stub-model")
                self.assertEqual({k: v for k, v in a.items() if k != "llm"}, baseline, "6.9.6 deterministic fields unchanged")
                req = seen[-1]
                self.assertEqual(req["path"], "/v1/chat/completions", "6.9.6 POST <url>/chat/completions")
                self.assertEqual(req["auth"], "Bearer sk-t1-stub")
                self.assertEqual(req["body"]["model"], "stub-model")
                self.assertIs(req["body"]["stream"], False)
                self.assertEqual(req["body"]["messages"][0]["role"], "system")
                self.assertTrue(req["body"]["messages"][0]["content"].startswith("You are Fathom's AV/lighting troubleshooting assistant."))
                self.assertIn("SYSTEM DATA (JSON):", req["body"]["messages"][-1]["content"] if req["body"]["messages"][-1]["role"] == "user" else
                              json.dumps(req["body"]["messages"]))
                n_before = len(seen)
                a_off = self.assistant.answer(sunday_doc(), Q_LIVESTREAM, room="main", use_llm=False, base_revision=1)
                self.assertEqual(a_off["llm"]["used"], False)
                d = sunday_doc()
                d["settings"]["assistant"] = {"llm": False}
                self.assistant.answer(d, Q_LIVESTREAM, room="main", use_llm=True, base_revision=1)
                self.assertEqual(len(seen), n_before, "6.9.6 use_llm false / settings.assistant.llm false -> no request")
                Handler.mode = "fail"
                a_err = self.assistant.answer(sunday_doc(), Q_LIVESTREAM, room="main", use_llm=True, base_revision=1)
                self.assertFalse(a_err["llm"]["used"], fr("FR-AST-07", "3.16", "failure never fails the request"))
                self.assertTrue(a_err["llm"].get("error"), "llm.error set")
                self.assertEqual(a_err["paths"], baseline["paths"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_cli_ask(self):
        cli = requires("cli")
        with temp_data_dir() as data:
            pdir = install_sunday(data, "sunday")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["ask", str(pdir), Q_LIVESTREAM, "--room", "main", "--no-llm"])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
            text = out.getvalue()
            self.assertIn("Audio Rack 1", text, fr("FR-AST-09", "3.16", "prints the summary/path"))
            self.assertIn("Restream", text)
            self.assertRegex(text, r"(?m)^\s*1[.)]", fr("FR-AST-09", "3.16", "numbered checks"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["ask", str(pdir), Q_LIVESTREAM, "--json", "--no-llm"])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
            j = json.loads(out.getvalue())
            self.assertEqual(j["paths"][0]["text"], "Audio Rack 1 · Stream → ATEM Mini · Stream → USB Stream Out → Restream")

    def test_cli_trace_port(self):
        cli = requires("cli")
        with temp_data_dir() as data:
            pdir = install_sunday(data, "sunday")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["trace", str(pdir), "audio-rack-1:analog-out-4", "--discipline", "audio"])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
            self.assertIn("Restream", out.getvalue(), fr("FR-TRC-04", "3.17", "port-level CLI prints hops"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["trace", str(pdir), "restream:usb-in-1", "--up"])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
            self.assertIn("ATEM Mini", out.getvalue(), fr("FR-TRC-04", "3.17", "--up"))


def out_of(g, n):
    try:
        return node_targets(g.edges_out(n), n)
    except Exception:
        return set()


if __name__ == "__main__":
    unittest.main()
