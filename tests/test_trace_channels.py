"""Channel-level tracing (SPEC §6.9, console channels §4.3.17): Dante sub-channel nodes,
console channel links, ``indexed`` stage boxes, gap reporting, ``resolve_ref`` for
channels and the ``/trace`` route shape.

The synthetic doc reproduces Patrick's example end to end: Bass DI → Rio3224 analog in 6
→ Dante 6 "Bass 17" → CL5 Dante 17 "17 Bass" → CH 12 "Bass" → (DCA 1 BAND) → ST L/R →
Dante 63/64 → Rio1608 Dante 1/2 → analog out 1/2 → amp → PA. The API test runs the real
9-file CL5 export against campus-demo's Dante preset.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

try:
    from _helpers import call, fixture_path, get_app, install_campus, jbody, read_json, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fixture_path, get_app, install_campus, jbody, read_json, requires, temp_data_dir

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

CL5 = fixture_path("imports", "yamaha-cl5")
FILES = ("DCAName.csv", "InName.csv", "InPatch.csv", "MixName.csv", "MtxName.csv", "OutPatch.csv", "PortRackPatch.csv", "StMonoName.csv", "StName.csv")


def bass_doc():
    S = requires("schema")
    L = requires("library")
    doc = S.new_doc("T")

    def add(tid, did, name):
        t = L.get_template(tid)
        if t is None:
            raise unittest.SkipTest("template %s missing" % tid)
        d = L.instantiate(t, device_id=did, name=name)
        d["room"] = "main"
        doc["devices"].append(d)
        return d

    rio = add("yamaha-rio3224-d2", "rio-sl", "Rio3224 SL")
    rio["dante_name"] = "Y002"
    cl5 = add("yamaha-cl5", "foh", "FOH CL5")
    cl5["dante_name"] = "FOH-CL5"
    add("yamaha-rio1608-d2", "rio-foh", "Rio1608 FOH")["dante_name"] = "Y001"
    doc["devices"].append({"id": "bass-di", "name": "Bass DI", "kind": "source", "room": "main",
                           "ports": [{"id": "out", "name": "Out", "dir": "out", "medium": "analog"}]})
    doc["devices"].append({"id": "amp-1", "name": "d&b D80", "kind": "amp", "room": "main", "ports": [
        {"id": "in-1", "name": "In 1", "dir": "in", "medium": "analog"}, {"id": "in-2", "name": "In 2", "dir": "in", "medium": "analog"},
        {"id": "out-a", "name": "Out A", "dir": "out", "medium": "speaker"}, {"id": "out-b", "name": "Out B", "dir": "out", "medium": "speaker"}]})
    doc["devices"].append({"id": "pa-l", "name": "PA Left", "kind": "pa", "room": "main",
                           "ports": [{"id": "in", "name": "In", "dir": "in", "medium": "speaker"}]})
    doc["cables"] += [
        {"id": "c1", "from": {"device": "bass-di", "port": "out"}, "to": {"device": "rio-sl", "port": "analog-in-6"}, "medium": "analog", "tag": "A-006"},
        {"id": "c2", "from": {"device": "rio-foh", "port": "analog-out-1"}, "to": {"device": "amp-1", "port": "in-1"}, "medium": "analog"},
        {"id": "c3", "from": {"device": "rio-foh", "port": "analog-out-2"}, "to": {"device": "amp-1", "port": "in-2"}, "medium": "analog"},
        {"id": "c4", "from": {"device": "amp-1", "port": "out-a"}, "to": {"device": "pa-l", "port": "in"}, "medium": "speaker"},
        {"id": "c5", "from": {"device": "amp-1", "port": "out-b"}, "to": {"device": "pa-l"}, "medium": "speaker"},
    ]
    cl5["channels"] = [
        {"id": "in-12", "kind": "input", "index": 12, "name": "Bass", "source": "yamaha"},
        {"id": "in-13", "kind": "input", "index": 13, "name": "Gtr", "source": "yamaha"},
        {"id": "st-l", "kind": "stereo", "side": "L", "source": "yamaha"}, {"id": "st-r", "kind": "stereo", "side": "R", "source": "yamaha"},
        {"id": "dca-1", "kind": "dca", "index": 1, "name": "BAND", "source": "yamaha"},
        {"id": "mix-9", "kind": "mix", "index": 9, "name": "9 IEM", "source": "yamaha"},
        {"id": "fx-1", "kind": "rack", "rack": "FX", "index": 1, "source": "yamaha"},
    ]
    cl5["channel_links"] = [
        {"from": {"port": "dante-primary", "ch": 17}, "to": {"channel": "in-12"}, "kind": "input_patch", "source": "yamaha"},
        {"from": {"port": "dante-primary", "ch": 18}, "to": {"channel": "in-13"}, "kind": "input_patch", "source": "yamaha"},
        {"from": {"channel": "in-12"}, "to": {"channel": "st-l"}, "kind": "send", "source": "user"},
        {"from": {"channel": "in-12"}, "to": {"channel": "st-r"}, "kind": "send", "source": "user"},
        {"from": {"channel": "in-12"}, "to": {"channel": "dca-1"}, "kind": "dca", "source": "user"},
        {"from": {"channel": "st-l"}, "to": {"port": "dante-primary", "ch": 63}, "kind": "output_patch", "source": "yamaha"},
        {"from": {"channel": "st-r"}, "to": {"port": "dante-primary", "ch": 64}, "kind": "output_patch", "source": "yamaha"},
        {"from": {"channel": "mix-9"}, "to": {"port": "dante-primary", "ch": 10}, "kind": "output_patch", "source": "yamaha"},
        {"from": {"channel": "mix-9"}, "to": {"channel": "fx-1", "tag": "A"}, "kind": "insert_send", "insert": 1, "source": "yamaha"},
        {"from": {"channel": "st-l"}, "to": {"text": "REC 1"}, "kind": "output_patch", "source": "yamaha"},
    ]
    return S.normalize(doc)


OVERLAY = {
    "routes": [
        {"kind": "dante", "from": {"device": "rio-sl", "port": "dante-primary", "ch": 6}, "to": {"device": "foh", "port": "dante-primary", "ch": 17}, "label": "Bass 17", "medium": "dante"},
        {"kind": "dante", "from": {"device": "foh", "port": "dante-primary", "ch": 63}, "to": {"device": "rio-foh", "port": "dante-primary", "ch": 1}, "label": "Main L", "medium": "dante"},
        {"kind": "dante", "from": {"device": "foh", "port": "dante-primary", "ch": 64}, "to": {"device": "rio-foh", "port": "dante-primary", "ch": 2}, "label": "Main R", "medium": "dante"},
    ],
    "channel_labels": {
        "rio-sl": {"dante-primary": {"out": {"6": "Bass 17"}}},
        "foh": {"dante-primary": {"in": {"17": "17 Bass"}, "out": {"63": "Main L", "64": "Main R"}}},
        "rio-foh": {"dante-primary": {"in": {"1": "FOH/SIDE FILLS L", "2": "FOH/SIDE FILLS R"}}},
    },
}


class BassPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T = requires("trace")
        cls.doc = bass_doc()
        cls.g = cls.T.port_graph(cls.doc, OVERLAY)

    def texts(self, paths):
        return [self.T.path_text(self.doc, p, OVERLAY) for p in paths]

    def test_doc_is_valid(self):
        S = requires("schema")
        self.assertEqual([p for p in S.validate_doc(self.doc) if p["level"] == "error"], [])

    def test_end_to_end_downstream(self):
        T = self.T
        paths = T.downstream_paths(self.g, "bass-di:out")
        texts = self.texts(paths)
        self.assertIn("Bass DI · Out → Rio3224 SL · Analog In 6 → Dante Primary 6 “Bass 17” → FOH CL5 · Dante Primary 17 “17 Bass” → CH 12 · Bass (via DCA 1 · BAND) → ST L → Dante Primary 63 “Main L” → Rio1608 FOH · Dante Primary 1 “FOH/SIDE FILLS L” → Analog Out 1 → d&b D80 · In 1 → Out A → PA Left", texts)
        self.assertIn("Bass DI · Out → Rio3224 SL · Analog In 6 → Dante Primary 6 “Bass 17” → FOH CL5 · Dante Primary 17 “17 Bass” → CH 12 · Bass (via DCA 1 · BAND) → ST R → Dante Primary 64 “Main R” → Rio1608 FOH · Dante Primary 2 “FOH/SIDE FILLS R” → Analog Out 2 → d&b D80 · In 2 → Out A → PA Left", texts)
        self.assertFalse(any("Secondary" in t for t in texts), "the redundant Dante port is not wired as a second copy of every path")
        full = [p for p in paths if p["hops"][-1]["device"] == "pa-l"]
        self.assertEqual(len(full), 4, "L and R, each through Out A and Out B of the matrix-routed amp")
        p = full[0]
        self.assertNotIn("incomplete", p)
        kinds = [h.get("kind") for h in p["hops"]]
        self.assertEqual(kinds[:6], [None, None, "port_channel", "port_channel", "channel", "channel"], "plain port hops stay {device, port}")
        self.assertEqual(p["hops"][0], {"device": "bass-di", "port": "out"})
        self.assertEqual(p["hops"][2], {"device": "rio-sl", "port": "dante-primary", "kind": "port_channel", "ch": 6, "dir": "out", "name": "Bass 17"})
        self.assertEqual(p["hops"][3]["name"], "17 Bass", "both the transmitter's and the receiver's Dante names are shown (answer 4)")
        bass = p["hops"][4]
        self.assertEqual((bass["channel"], bass["channel_kind"], bass["title"], bass["name"]), ("in-12", "input", "CH 12 · Bass", "Bass"))
        self.assertEqual(bass["dca"], [{"channel": "dca-1", "title": "DCA 1 · BAND"}])
        self.assertEqual(p["via"][:9], ["", "cable:c1", "internal", "route:dante", "link:input_patch", "link:send", "link:output_patch", "route:dante", "internal"])
        self.assertEqual(p["cables"][0], "c1")

    def test_dca_as_hops_toggle(self):
        T = self.T
        p = T.port_paths(self.g, "bass-di:out", "pa-l")[0]
        q = T.with_dca_hops(p)
        self.assertEqual(len(q["hops"]), len(p["hops"]) + 1)
        dca = q["hops"][5]
        self.assertEqual((dca["kind"], dca["channel"], dca["control"]), ("dca", "dca-1", True))
        self.assertEqual(q["via"][5], "link:dca")
        self.assertIn("→ CH 12 · Bass → (via DCA 1 · BAND) → ST L →", T.path_text(self.doc, q, OVERLAY))
        self.assertIn("→ CH 12 · Bass (via DCA 1 · BAND) → ST L →", T.path_text(self.doc, p, OVERLAY), "without the toggle the DCA is an annotation")
        self.assertEqual([T.hop_ref(h) for h in p["hops"]][2:6], ["rio-sl:dante-primary#tx6", "foh:dante-primary#rx17", "foh:@in-12", "foh:@st-l"])

    def test_upstream_and_a_to_b(self):
        T = self.T
        up = self.texts(T.upstream_paths(self.g, "pa-l:in"))
        self.assertTrue(any(t.startswith("Bass DI · Out → Rio3224 SL · Analog In 6 → Dante Primary 6") and t.endswith("→ PA Left") for t in up))
        ab = T.port_paths(self.g, "bass-di:out", "pa-l")
        self.assertEqual(len(ab), 4, "A→B: L and R, each through amp Out A (to the PA port) and Out B (device-level cable)")
        self.assertEqual(ab, sorted(ab, key=lambda p: (len(p["hops"]), [T.hop_ref(h) for h in p["hops"]])), "deterministic order")
        stranded = T.upstream_paths(self.g, "rio-sl:dante-primary#6")
        self.assertEqual(len(stranded), 1, "'Dante 6' arriving at the Rio has no transmitter: a single-hop result that says why, no invented path")
        self.assertEqual((len(stranded[0]["hops"]), stranded[0]["incomplete"]), (1, "no Dante transmitter recorded for Rio3224 SL · Dante Primary 6"))
        self.assertEqual(T.downstream_paths(self.g, "pa-l:in"), [], "plain port dead ends stay empty as before")

    def test_gaps(self):
        T = self.T
        mix9 = T.downstream_paths(self.g, "foh:@mix-9")
        texts = self.texts(mix9)
        self.assertIn("FOH CL5 · MIX 9 · 9 IEM → Dante Primary 10 ⚠ no Dante subscriber recorded for FOH CL5 · Dante Primary 10", texts)
        self.assertIn("FOH CL5 · MIX 9 · 9 IEM → FX 1 A ⚠ FX 1 A return is not patched anywhere", texts)
        gtr = T.downstream_paths(self.g, "foh:@in-13")
        self.assertEqual(self.texts(gtr), ["FOH CL5 · CH 13 · Gtr ⚠ no sends recorded for CH 13 · Gtr"], "no send is assumed (answer 1)")
        self.assertEqual(gtr[0]["incomplete"], "no sends recorded for CH 13 · Gtr")
        self.assertEqual(self.texts(T.upstream_paths(self.g, "foh:@in-13")), ["FOH CL5 · Dante Primary 18 → CH 13 · Gtr ⚠ no Dante transmitter recorded for FOH CL5 · Dante Primary 18"])
        rec = [t for t in self.texts(T.downstream_paths(self.g, "foh:@st-l")) if "REC" in t]
        self.assertEqual(rec, ["FOH CL5 · ST L → REC 1"], "an unmapped console port is shown as text and is a natural end")
        g2 = T.port_graph(self.doc, None)
        self.assertEqual(self.texts(T.downstream_paths(g2, "bass-di:out")), ["Bass DI · Out → Rio3224 SL · Analog In 6 → Dante Primary 6 ⚠ no Dante subscriber recorded for Rio3224 SL · Dante Primary 6"],
                         "without a Dante import the indexed stage box stops at its transmit channel")
        self.assertEqual(self.texts(T.upstream_paths(g2, "amp-1:in-1")), ["Rio1608 FOH · Dante Primary 1 → Analog Out 1 → d&b D80 ⚠ no Dante transmitter recorded for Rio1608 FOH · Dante Primary 1"])

    def test_indexed_routing(self):
        T = self.T
        rio = next(d for d in self.doc["devices"] if d["id"] == "rio-sl")
        self.assertEqual(T.routing_mode(rio), "indexed", "the template's routing reaches the device")
        self.assertTrue(self.g.has_node("rio-sl:dante-primary#tx32"))
        self.assertFalse(self.g.has_node("rio-sl:dante-primary#tx33"), "32 analog ins → TX 1–32 only")
        outs = {e.dst for e in self.g.edges_out("rio-sl:dante-primary#rx17")}
        self.assertEqual(outs, {"rio-sl:aes-out-1-2"}, "RX 17 → AES out 1/2 (analog out 1–16 take RX 1–16)")
        self.assertEqual({e.dst for e in self.g.edges_out("rio-sl:dante-primary#rx24")}, {"rio-sl:aes-out-7-8"})
        self.assertFalse(self.g.has_node("rio-sl:dante-primary#rx25"))
        self.assertEqual({e.dst for e in self.g.edges_out("rio-sl:analog-in-1")}, {"rio-sl:dante-primary#tx1"})
        self.assertEqual([e.kind for e in self.g.edges_out("foh:dante-primary")], ["route"], "a console with channel links gets no generic matrix edges (the port-level Dante route stays)")
        self.assertFalse(any(e.kind == "internal" for e in self.g.edges_in("foh:omni-out-1")))
        self.assertEqual([e.kind for e in self.g.edges_in("rio-sl:analog-out-1")], ["internal"])

    def test_discipline_filter_and_state(self):
        T = self.T
        gv = T.port_graph(self.doc, OVERLAY, discipline="video")
        self.assertFalse(any(T.parse_ref(n)["channel"] for n in gv.nodes), "console channels are audio only")
        ga = T.port_graph(self.doc, OVERLAY, discipline="audio")
        self.assertTrue(ga.has_node("foh:@in-12"))
        self.assertTrue(T.port_paths(ga, "bass-di:out", "pa-l"))

    def test_resolve_ref(self):
        T = self.T
        doc = self.doc
        self.assertEqual(T.resolve_ref(doc, "FOH CL5 · CH 12"), ("foh", "@in-12"))
        self.assertEqual(T.resolve_ref(doc, "foh:Bass"), ("foh", "@in-12"))
        self.assertEqual(T.resolve_ref(doc, "foh:in-12"), ("foh", "@in-12"))
        self.assertEqual(T.resolve_ref(doc, "FOH CL5 · MIX 9"), ("foh", "@mix-9"))
        self.assertEqual(T.resolve_ref(doc, "FOH CL5 · ST L"), ("foh", "@st-l"))
        self.assertEqual(T.resolve_ref(doc, "Rio3224 SL · Dante 6"), ("rio-sl", "dante-primary#6"))
        self.assertEqual(T.resolve_ref(doc, "rio-sl:dante-primary#tx6"), ("rio-sl", "dante-primary#tx6"))
        self.assertEqual(T.resolve_ref(doc, "FOH CL5 · Dante Primary 17"), ("foh", "dante-primary#17"))
        self.assertEqual(T.resolve_ref(doc, "foh:omni-in-1"), ("foh", "omni-in-1"), "plain ports still resolve")
        self.assertEqual(T.resolve_ref(doc, "Rio3224 SL · Analog In 6"), ("rio-sl", "analog-in-6"))
        self.assertEqual(T.resolve_ref(doc, "Rio3224 SL · Dante Primary"), ("rio-sl", "dante-primary"))
        self.assertIsNone(T.resolve_ref(doc, "FOH CL5 · CH 99"))
        start = T.resolve_ref(doc, "Rio3224 SL · Dante 6")
        down = T.downstream_paths(self.g, "%s:%s" % start)
        self.assertTrue(down and down[0]["hops"][0] == {"device": "rio-sl", "port": "dante-primary", "kind": "port_channel", "ch": 6, "dir": "out", "name": "Bass 17"}, "an undirected sub-channel ref leaves on TX when tracing downstream")
        self.assertEqual(T.parse_ref("foh:dante-primary#rx17"), {"device": "foh", "port": "dante-primary", "ch": 17, "dir": "in", "channel": None, "tag": None, "text": None})
        self.assertEqual(T.split_ref("foh:dante-primary#rx17"), ("foh", "dante-primary"))
        self.assertEqual(T.split_ref("foh:@in-12"), ("foh", None))

    def test_device_level_starts_include_sub_channels(self):
        T = self.T
        down = T.downstream_paths(self.g, "rio-sl")
        self.assertTrue(any(p["hops"][0].get("ch") == 6 for p in down), "downstream of the Rio includes its transmit channels")
        up = T.upstream_paths(self.g, "foh")
        self.assertTrue(any(p["hops"][-1].get("ch") == 17 for p in up))


class TraceApi(unittest.TestCase):
    """campus-demo + the real CL5 export: the drum kick reaches CH 16 of the console through Dante 9."""

    def setUp(self):
        requires("plugins")
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.pdir = install_campus(self.data, "campus")
        dest = self.pdir / "exports" / "yamaha" / "cl5"
        dest.mkdir(parents=True)
        for f in FILES:
            shutil.copy(str(CL5 / f), str(dest / f))
        doc = read_json(self.pdir / "project.json")
        doc["imports"] = [i for i in doc["imports"] if i["kind"] != "yamaha"]
        doc["imports"].append({"id": "imp-cl5", "kind": "yamaha", "path": "exports/yamaha/cl5", "room": "main", "device": "foh-cl5", "label": "CL5 console export"})
        (self.pdir / "project.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    def test_kick_to_console_channel(self):
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=drum-mics:drum-kick-in")
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual(j["from"], "drum-mics:drum-kick-in")
        hit = [p for p in j["paths"] if any(h.get("kind") == "channel" for h in p["hops"])]
        self.assertTrue(hit, [p["text"] for p in j["paths"]][:5])
        p = hit[0]
        self.assertIn("→ Dante Primary 9 “Kick In” → FOH CL5 · Dante Primary 9 “Kick In” → CH 16 · DrumTalk", p["text"], "RIO-SL TX 9 and the console's DANTE 9 join on the number; both Dante names decorate")
        self.assertTrue(p["text"].startswith("Drum mics · Kick In → Stage Rack SL · Kick In →"), p["text"])
        self.assertTrue(p["incomplete"].startswith("no sends recorded for CH 16"), p["incomplete"])
        ch = next(h for h in p["hops"] if h.get("kind") == "channel")
        self.assertEqual(ch["channel"], "in-16")
        self.assertTrue(ch["label"].startswith("CH 16"))
        self.assertIn("route:dante", p["via"])
        self.assertIn("link:input_patch", p["via"])

    def test_named_channel_endpoints_and_dca_param(self):
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=FOH-CL5%20%C2%B7%20Kick%20In&direction=up")
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual(j["from"], "foh-cl5:@in-17", "the console name resolves to the channel (CH 17 'Kick In' in the export)")
        texts = [p["text"] for p in j["paths"]]
        self.assertTrue(any("Dante Primary 1 “Vox 1” → CH 17 · Kick In" in t for t in texts), texts)
        self.assertTrue(any(t.startswith("Vocal mic 1 · Mic Out → Stage Rack SL") for t in texts), "the mic cabled into the Rio is the source (the fixture export and the campus preset disagree on names; the numbers decide)")
        loop = [p for p in j["paths"] if "PRFX 6 A → CH 17 · Kick In" in p["text"]]
        self.assertTrue(loop, "the insert return from PRFX 6A is followed too")
        self.assertNotIn("incomplete", loop[0], "an insert loop (send and return on the same channel) is a natural end, not a gap")
        self.assertEqual(loop[0]["hops"][0]["tag"], "A")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:MIX%201&dca=1")
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual(j["from"], "foh-cl5:@mix-1")
        self.assertTrue(any("Dante Primary 1 “Main L”" in p["text"] for p in j["paths"]), "the Dante preset's TX name decorates the console's DANTE 1 output: numbers join, labels decorate")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:CH%20999")
        self.assertEqual(st, 400)

    def test_node_refs_round_trip_and_device_names(self):
        """The API accepts the node refs it returns (``dev:@ch``, ``dev:@rack.A``, ``dev:~text``) and names every hop's device (§5.8)."""
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:%40in-17&direction=up")
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual(j["from"], "foh-cl5:@in-17")
        for p in j["paths"]:
            for h in p["hops"]:
                self.assertTrue(h.get("device_name"), h)
        hop = next(h for p in j["paths"] for h in p["hops"] if h["device"] == "foh-cl5")
        self.assertEqual(hop["device_name"], "FOH CL5")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:%40prfx-6.A")
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(jbody(b)["from"], "foh-cl5:@prfx-6.A")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:%40nope-1")
        self.assertEqual(st, 400, "unknown channel ids are rejected")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:~REC%201&direction=up")
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(jbody(b)["from"], "foh-cl5:~REC 1")


if __name__ == "__main__":
    unittest.main()
