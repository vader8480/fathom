"""Console internals (SPEC §4.3.17): ``devices[].channels`` / ``channel_links``,
the CL5 CSV contribution, the imports overlay and the apply route.

Data: the real CL5 export in ``tests/fixtures/imports/yamaha-cl5`` (9 section
files) and the campus-demo Dante preset. Expected values come from the export's
routing guide (``tests/test_yamaha_cl5.py``).
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

try:
    from _helpers import call, fixture_path, get_app, install_campus, jbody, read_json, requires, temp_data_dir, upload
except ImportError:  # pragma: no cover
    from tests._helpers import call, fixture_path, get_app, install_campus, jbody, read_json, requires, temp_data_dir, upload

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

CL5 = fixture_path("imports", "yamaha-cl5")
FILES = ("DCAName.csv", "InName.csv", "InPatch.csv", "MixName.csv", "MtxName.csv", "OutPatch.csv", "PortRackPatch.csv", "StMonoName.csv", "StName.csv")


def _console_device(device_id: str = "foh", name: str = "FOH CL5"):
    lib = requires("library")
    t = lib.get_template("yamaha-cl5")
    if t is None:
        raise unittest.SkipTest("yamaha-cl5 template missing")
    return lib.instantiate(t, device_id=device_id, name=name)


def _contribution():
    from fathom.console import console_contribution
    from fathom.parsers import parse_yamaha

    return console_contribution(parse_yamaha(CL5), _console_device())


def _links(contrib, **match):
    out = []
    for ln in contrib["links"]:
        ok = True
        for k, v in match.items():
            if k in ("from_channel", "to_channel"):
                ok = ok and ln[k[:-8]].get("channel") == v
            elif k in ("from_port", "to_port"):
                ok = ok and ln[k[:-5]].get("port") == v
            else:
                ok = ok and ln.get(k) == v
        if ok:
            out.append(ln)
    return out


class Ids(unittest.TestCase):
    def test_channel_ids_and_labels(self):
        from fathom.console import channel_id, channel_label, channel_title, endpoint_text

        self.assertEqual(channel_id("input", 12), "in-12")
        self.assertEqual(channel_id("stereo_input", 4, "L"), "stin-4-l")
        self.assertEqual(channel_id("stereo", None, "R"), "st-r")
        self.assertEqual(channel_id("mono"), "mono")
        self.assertEqual(channel_id("rack", 1, rack="FX"), "fx-1")
        self.assertEqual(channel_label({"kind": "input", "index": 12}), "CH 12")
        self.assertEqual(channel_label({"kind": "stereo_input", "index": 4, "side": "L"}), "ST IN 4 L")
        self.assertEqual(channel_label({"kind": "matrix", "index": 7}), "MATRIX 7")
        self.assertEqual(channel_label({"kind": "stereo", "side": "L"}), "ST L")
        self.assertEqual(channel_label({"kind": "rack", "rack": "PRFX", "index": 6}), "PRFX 6")
        self.assertEqual(channel_title({"kind": "input", "index": 12, "name": "Bass"}), "CH 12 · Bass")
        self.assertEqual(channel_title({"kind": "mix", "index": 9, "name": "MIX 9"}), "MIX 9", "a name equal to the label is not repeated")
        chans = {"fx-1": {"id": "fx-1", "kind": "rack", "rack": "FX", "index": 1}}
        ports = {"dante-primary": {"id": "dante-primary", "name": "Dante Primary"}}
        self.assertEqual(endpoint_text({"channel": "fx-1", "tag": "A"}, chans, ports), "FX 1 A")
        self.assertEqual(endpoint_text({"port": "dante-primary", "ch": 17}, chans, ports), "Dante Primary 17")
        self.assertEqual(endpoint_text({"text": "REC 1"}), "REC 1")


class Contribution(unittest.TestCase):
    """The CL5 export mapped onto the yamaha-cl5 library device (§4.11 ``channels``)."""

    @classmethod
    def setUpClass(cls):
        requires("parsers")
        cls.c = _contribution()
        cls.by_id = {ch["id"]: ch for ch in cls.c["channels"]}

    def test_channel_counts(self):
        from fathom.console import summary

        s = summary(self.c["channels"], self.c["links"])
        self.assertEqual(s["by_kind"]["input"], 72)
        self.assertEqual(s["by_kind"]["stereo_input"], 16, "8 stereo pairs = 16 L/R channels")
        self.assertEqual((s["by_kind"]["mix"], s["by_kind"]["matrix"]), (24, 8))
        self.assertEqual((s["by_kind"]["stereo"], s["by_kind"]["mono"], s["by_kind"]["dca"]), (2, 1, 16))
        self.assertTrue(s["by_kind"]["rack"] >= 20, "rack channels are created on demand from the patch edges")
        self.assertEqual(s["sends"], 0, "the CL5 CSV export has no send levels: nothing is assumed (Patrick, answer 1)")
        self.assertEqual(s["dca_members"], 0, "DCAName.csv carries names only")
        self.assertTrue(all(ch["source"] == "yamaha" for ch in self.c["channels"]))

    def test_names_colours_and_order(self):
        kick = self.by_id["in-17"]
        self.assertEqual((kick["kind"], kick["index"], kick["name"]), ("input", 17, "Kick In"))
        self.assertEqual(self.by_id["mix-9"]["name"], "9 IEM")
        self.assertEqual([self.by_id["dca-%d" % i]["name"] for i in (1, 2, 3)], ["CHOIR", "VOX", "BAND"])
        self.assertEqual(self.by_id["st-l"]["side"], "L")
        self.assertNotIn("index", self.by_id["mono"])
        kinds = [ch["kind"] for ch in self.c["channels"]]
        self.assertLess(kinds.index("mix"), kinds.index("matrix"))
        self.assertLess(kinds.index("matrix"), kinds.index("dca"))

    def test_input_patch_from_dante(self):
        ln = _links(self.c, kind="input_patch", to_channel="in-17")
        self.assertEqual(len(ln), 1)
        self.assertEqual(ln[0]["from"], {"port": "dante-primary", "ch": 1}, "DANTE 1 → CH 17 lands on sub-channel 1 of the console's Dante port")
        self.assertEqual(ln[0]["source"], "yamaha")

    def test_input_patch_from_rack(self):
        ln = _links(self.c, kind="input_patch", to_channel="stin-4-l")
        self.assertEqual(ln[0]["from"], {"channel": "fx-4", "tag": "A"}, "ST IN 4 L is fed by the FX 4 A return")
        self.assertEqual(self.by_id["fx-4"], {"id": "fx-4", "kind": "rack", "rack": "FX", "index": 4, "source": "yamaha"})

    def test_output_patches(self):
        mix9 = _links(self.c, kind="output_patch", from_channel="mix-9")
        self.assertEqual([ln["to"] for ln in mix9], [{"port": "dante-primary", "ch": 10}], "MIX 9 → DANTE 10")
        mtx7 = _links(self.c, from_channel="mtx-7")
        tos = {json.dumps(ln["to"], sort_keys=True): ln["kind"] for ln in mtx7}
        self.assertEqual(tos.get(json.dumps({"ch": 63, "port": "dante-primary"})), "output_patch")
        self.assertEqual(tos.get(json.dumps({"port": "omni-out-7"})), "output_patch", "OMNI 7 resolves to the 7th analog Omni out port")
        self.assertEqual(tos.get(json.dumps({"channel": "prfx-1", "tag": "A"})), "insert_send")
        ins = _links(self.c, kind="insert_send", from_channel="mtx-7")[0]
        self.assertEqual(ins["insert"], 1)
        ret = _links(self.c, kind="insert_return", to_channel="mtx-7")
        self.assertEqual(ret[0]["from"], {"channel": "prfx-1", "tag": "A"}, "the insert loop closes back onto MATRIX 7")

    def test_direct_out_to_slot(self):
        ln = _links(self.c, kind="direct_out", from_channel="in-67")
        self.assertEqual(ln[0]["to"], {"port": "my-slot-1", "ch": 9}, "DIR CH 67 → SLOT1 9")

    def test_unmapped_ports_stay_text(self):
        self.assertTrue(any(u.startswith("REC") for u in self.c["unmapped"]), "the recorder outputs have no device port")
        texts = [ln for ln in self.c["links"] if "text" in ln["to"]]
        self.assertTrue(texts and all(ln["to"]["text"].startswith("REC") for ln in texts))
        self.assertTrue(any("REC 1" in n for n in self.c["notes"]))

    def test_links_are_unique_and_well_formed(self):
        from fathom.vocab import CHANNEL_LINK_KINDS

        keys = [json.dumps({k: v for k, v in ln.items() if k != "source"}, sort_keys=True) for ln in self.c["links"]]
        self.assertEqual(len(keys), len(set(keys)))
        for ln in self.c["links"]:
            self.assertIn(ln["kind"], CHANNEL_LINK_KINDS)
            for end in ("from", "to"):
                ep = ln[end]
                self.assertTrue(("channel" in ep) ^ ("port" in ep) ^ ("text" in ep), ep)
                if "channel" in ep:
                    self.assertIn(ep["channel"], self.by_id)


class Validation(unittest.TestCase):
    def _doc(self, channels, links):
        s = requires("schema")
        doc = s.new_doc("T")
        dev = _console_device()
        dev["room"] = "main"
        dev["channels"] = channels
        dev["channel_links"] = links
        doc["devices"].append(dev)
        return s.normalize(doc)

    def _codes(self, doc):
        s = requires("schema")
        return {(p["level"], p["code"]) for p in s.validate_doc(doc)}

    def test_valid_set_has_no_problems(self):
        c = _contribution()
        doc = self._doc(c["channels"], c["links"])
        probs = [p for p in requires("schema").validate_doc(doc) if "channel" in p.get("path", "")]
        self.assertEqual(probs, [])
        self.assertFalse(requires("schema").is_v1_expressible(doc), "4.3.17: channels make a doc v2-only")

    def test_errors(self):
        codes = self._codes(self._doc(
            [{"id": "in-1", "kind": "input"}, {"id": "in-1", "kind": "input"}, {"id": "Bad Id", "kind": "mix"}, {"kind": "mix"}, {"id": "x-1"}],
            [{"from": {"channel": "nope"}, "to": {"channel": "in-1"}, "kind": "send"},
             {"from": {"port": "dante-primary", "ch": 0}, "to": {"channel": "in-1"}, "kind": "input_patch"},
             {"from": {"channel": "in-1"}, "to": {"channel": "in-1"}, "kind": "insert_send", "insert": 3},
             {"to": {"channel": "in-1"}, "kind": "send"},
             {"from": {}, "to": {"channel": "in-1"}, "kind": "send"},
             {"from": {"channel": "in-1"}, "to": {"channel": "in-1"}}],
        ))
        for code in ("duplicate_channel", "bad_id", "missing_field", "dangling_channel", "bad_enum"):
            self.assertIn(("error", code), codes, code)

    def test_warnings_keep_the_doc_usable(self):
        codes = self._codes(self._doc(
            [{"id": "in-1", "kind": "flux", "source": "martian"}],
            [{"from": {"port": "ghost-port", "ch": 2}, "to": {"channel": "in-1"}, "kind": "teleport", "source": "martian"}],
        ))
        self.assertIn(("warning", "unknown_channel_kind"), codes)
        self.assertIn(("warning", "unknown_link_kind"), codes)
        self.assertIn(("warning", "dangling_port"), codes)
        self.assertIn(("warning", "bad_enum"), codes)
        self.assertFalse(any(level == "error" for level, _ in codes), codes)

    def test_bad_types(self):
        s = requires("schema")
        doc = self._doc([], [])
        doc["devices"][0]["channels"] = "nope"
        doc["devices"][0]["channel_links"] = {"a": 1}
        codes = {(p["code"], p["path"].rsplit("/", 1)[-1]) for p in s.validate_doc(doc)}
        self.assertIn(("bad_type", "channels"), codes)
        self.assertIn(("bad_type", "channel_links"), codes)

    def test_json_schema_covers_channels(self):
        s = requires("schema")
        try:
            from test_model_v2 import js_validate
        except ImportError:  # pragma: no cover
            from tests.test_model_v2 import js_validate
        c = _contribution()
        doc = self._doc(c["channels"], c["links"])
        self.assertEqual(js_validate(s.JSON_SCHEMA, doc), [])
        dev_schema = s.JSON_SCHEMA["$defs"]["device"]["properties"] if "$defs" in s.JSON_SCHEMA and "device" in s.JSON_SCHEMA["$defs"] else None
        if dev_schema is not None:
            self.assertIn("channels", dev_schema)
            self.assertIn("channel_links", dev_schema)
        bad = self._doc([{"id": "in-1"}], [{"from": {"channel": "in-1"}, "kind": "send"}])
        self.assertTrue(js_validate(s.JSON_SCHEMA, bad), "required kind / to are enforced by the JSON Schema")

    def test_vocab_exposes_the_enums(self):
        from fathom.vocab import CHANNEL_KINDS, CHANNEL_LINK_KINDS, CHANNEL_SOURCES, ROUTING_MODES, as_dict

        self.assertIn("indexed", ROUTING_MODES)
        self.assertEqual(CHANNEL_KINDS["input"]["role"], "input")
        self.assertIn("dca", CHANNEL_KINDS)
        self.assertEqual(CHANNEL_LINK_KINDS[0], "input_patch")
        self.assertEqual(CHANNEL_SOURCES[0], "user")
        v = as_dict()
        self.assertEqual(set(v["channel_link_kinds"]), set(CHANNEL_LINK_KINDS))
        self.assertIn("input", v["channel_kinds"])


class MergeSets(unittest.TestCase):
    """User entries survive a re-apply; imported ones are replaced (§4.11)."""

    def test_user_channels_and_links_survive(self):
        from fathom.console import _merge_sets

        old_ch = [{"id": "in-1", "kind": "input", "name": "Kick (my name)", "source": "user"},
                  {"id": "in-2", "kind": "input", "name": "Old import", "source": "yamaha"},
                  {"id": "mix-99", "kind": "mix", "index": 99, "name": "Hand made", "source": "user"}]
        old_ln = [{"from": {"channel": "in-1"}, "to": {"channel": "st-l"}, "kind": "send", "source": "user"},
                  {"from": {"port": "dante-primary", "ch": 5}, "to": {"channel": "in-2"}, "kind": "input_patch", "source": "yamaha"}]
        new_ch = [{"id": "in-1", "kind": "input", "name": "Kick In", "color": "Red", "source": "yamaha"},
                  {"id": "st-l", "kind": "stereo", "side": "L", "source": "yamaha"}]
        new_ln = [{"from": {"port": "dante-primary", "ch": 1}, "to": {"channel": "in-1"}, "kind": "input_patch", "source": "yamaha"},
                  {"from": {"channel": "in-1"}, "to": {"channel": "st-l"}, "kind": "send", "source": "yamaha"}]
        chans, links = _merge_sets(old_ch, old_ln, new_ch, new_ln)
        by = {c["id"]: c for c in chans}
        self.assertEqual(set(by), {"in-1", "st-l", "mix-99"}, "the stale imported in-2 is gone, the hand-made mix-99 stays")
        self.assertEqual((by["in-1"]["name"], by["in-1"]["color"], by["in-1"]["source"]), ("Kick (my name)", "Red", "user"), "user name wins, imported colour fills")
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0]["source"], "user", "the user's send is kept once (the identical imported one is a duplicate)")
        self.assertEqual([c["id"] for c in chans], ["in-1", "mix-99", "st-l"], "sorted by kind / index")

    def test_csv_entries_survive_too(self):
        from fathom.console import MANUAL_SOURCES, _merge_sets

        self.assertEqual(MANUAL_SOURCES, ("user", "csv"))
        old_ln = [{"from": {"channel": "in-1"}, "to": {"channel": "mix-1"}, "kind": "send", "source": "csv"},
                  {"from": {"channel": "in-1"}, "to": {"channel": "mix-2"}, "kind": "send", "source": "yamaha"}]
        new_ch = [{"id": "in-1", "kind": "input", "source": "yamaha"}, {"id": "mix-1", "kind": "mix", "index": 1, "source": "yamaha"}]
        _, links = _merge_sets([], old_ln, new_ch, [])
        self.assertEqual([(ln["to"]["channel"], ln["source"]) for ln in links], [("mix-1", "csv")], "spreadsheet sends are hand-entered: kept; the stale import send goes")


class Typed(unittest.TestCase):
    """``console.resolve_channels`` / ``expand_ranges``: what people type in the CSV template (§5.7.4)."""

    def setUp(self):
        self.chans = _contribution()["channels"]

    def ids(self, text, hint=""):
        from fathom.console import resolve_channels

        return [c["id"] for c in resolve_channels(self.chans, text, hint)]

    def test_console_style_references(self):
        self.assertEqual(self.ids("CH 12"), ["in-12"])
        self.assertEqual(self.ids("12"), ["in-12"], "a bare number is an input channel")
        self.assertEqual(self.ids("in-12"), ["in-12"], "ids pass through")
        self.assertEqual(self.ids("ch12"), ["in-12"])
        self.assertEqual(self.ids("ST"), ["st-l", "st-r"], "the stereo bus means both sides")
        self.assertEqual(self.ids("ST L/R"), ["st-l", "st-r"])
        self.assertEqual(self.ids("Main"), ["st-l", "st-r"])
        self.assertEqual(self.ids("ST L"), ["st-l"])
        self.assertEqual(self.ids("MONO"), ["mono"])
        self.assertEqual(self.ids("MIX 1"), ["mix-1"])
        self.assertEqual(self.ids("AUX 1"), ["mix-1"], "aux falls back to mix when the console calls them mixes")
        self.assertEqual(self.ids("MATRIX 3"), ["mtx-3"])
        self.assertEqual(self.ids("MTX 3"), ["mtx-3"])
        self.assertEqual(self.ids("ST IN 2"), ["stin-2-l", "stin-2-r"])
        self.assertEqual(self.ids("DCA 1"), ["dca-1"])
        self.assertEqual(self.ids("1", "dca"), ["dca-1"], "a bare number in the dca column is a DCA")
        self.assertEqual(self.ids("Band", "dca"), ["dca-3"], "a DCA's name")
        self.assertEqual(self.ids("Choir", "dca"), [], "two DCAs are named Choir: ambiguous")
        self.assertEqual(self.ids("Kick In"), ["in-17"], "a channel's console name")
        self.assertEqual(self.ids("FX 1"), ["fx-1"])
        self.assertEqual(self.ids("PRFX 6"), ["prfx-6"])
        for bad in ("MIX", "nope", "CH 99", ""):
            self.assertEqual(self.ids(bad), [], bad)

    def test_ranges_and_separators(self):
        from fathom.console import expand_ranges

        self.assertEqual(expand_ranges("ST; MIX 1-3, DCA 2 | -MIX 4"), ["ST", "MIX 1", "MIX 2", "MIX 3", "DCA 2", "-MIX 4"])
        self.assertEqual(expand_ranges("1-3"), ["1", "2", "3"])
        self.assertEqual(expand_ranges(""), [])


class Overlay(unittest.TestCase):
    """campus-demo + the 9-file CL5 export: Dante routes carry ``ch``, labels and channels land in the overlay, apply persists them."""

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

    def _overlay(self):
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/overlay")
        self.assertEqual(st, 200, b[:300])
        return jbody(b)

    def test_overlay_routes_labels_and_channels(self):
        ov = self._overlay()
        dante = [r for r in ov["routes"] if r["kind"] == "dante" and r["to"]["device"] == "foh-cl5"]
        self.assertTrue(dante)
        vox = next(r for r in dante if r["label"] == "Vox 1")
        self.assertEqual((vox["from"]["device"], vox["from"]["port"], vox["to"]["port"], vox["to"]["ch"]), ("rio-sl", "dante-primary", "dante-primary", 1))
        self.assertIsInstance(vox["from"]["ch"], int, "TX channel number on the route (4.11)")
        labels = ov["channel_labels"]
        self.assertEqual(labels["foh-cl5"]["dante-primary"]["in"]["1"], "Vox 1")
        self.assertEqual(labels["rio-sl"]["dante-primary"]["out"][str(vox["from"]["ch"])], "Vox 1")
        sets = ov["channels"]["foh-cl5"]
        ids = {c["id"] for c in sets["channels"]}
        self.assertTrue({"in-17", "mix-9", "mtx-7", "st-l", "dca-3"} <= ids)
        kick = next(ln for ln in sets["links"] if ln["kind"] == "input_patch" and ln["to"] == {"channel": "in-17"})
        self.assertEqual(kick["from"], {"port": "dante-primary", "ch": 1}, "the import is mapped onto the campus console's own ports")
        self.assertNotIn("rio-sl", ov["channels"], "only the console the import is attached to gets channels")

    def test_channels_route_and_apply(self):
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/foh-cl5/channels")
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual((j["source"], j["pending"], j["device"]), ("overlay", True, "foh-cl5"))
        self.assertEqual(j["summary"]["by_kind"]["input"], 72)
        self.assertEqual(j["labels"]["dante-primary"]["in"]["1"], "Vox 1")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/nope/channels")
        self.assertEqual(st, 404)
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/rio-sl/channels")
        self.assertEqual(jbody(b)["source"], "none", "a stage box has no console channels")

        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/rio-sl/channels/apply", {}, {"X-Fathom": "1"})
        self.assertEqual(st, 404, b[:200])

        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/foh-cl5/channels/apply", {}, {"X-Fathom": "1"})
        self.assertEqual(st, 200, b[:300])
        res = jbody(b)
        self.assertTrue(res["changed"])
        self.assertEqual(res["summary"]["by_kind"]["input"], 72)
        doc = read_json(self.pdir / "project.json")
        dev = next(d for d in doc["devices"] if d["id"] == "foh-cl5")
        self.assertEqual(len(dev["channels"]), res["summary"]["channels"])
        self.assertEqual(len(dev["channel_links"]), res["summary"]["links"])
        self.assertEqual(doc["revision"], res["revision"])
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/history")
        self.assertEqual(st, 200)
        self.assertTrue(any("Apply console channels" in (e.get("summary") or "") for e in jbody(b)["revisions"]))

        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/foh-cl5/channels")
        j = jbody(b)
        self.assertEqual((j["source"], j["pending"]), ("device", False), "once applied the device is authoritative and nothing is pending")
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/foh-cl5/channels/apply", {}, {"X-Fathom": "1"})
        self.assertEqual(st, 200)
        self.assertFalse(jbody(b)["changed"], "re-apply is a no-op")

        # a user edit survives the next apply
        ops = [{"op": "merge", "coll": "devices", "id": "foh-cl5", "value": {"channels": [
            dict(c, name="Bass DI", source="user") if c["id"] == "in-17" else c for c in dev["channels"]]}}]
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": doc["revision"], "ops": ops, "summary": "rename"}, {"X-Fathom": "1"})
        self.assertEqual(st, 200, b[:300])
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/foh-cl5/channels")
        self.assertFalse(jbody(b)["pending"], "a user rename does not count as a pending import change")
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/foh-cl5/channels/apply", {}, {"X-Fathom": "1"})
        self.assertFalse(jbody(b)["changed"])
        doc = read_json(self.pdir / "project.json")
        dev = next(d for d in doc["devices"] if d["id"] == "foh-cl5")
        kick = next(c for c in dev["channels"] if c["id"] == "in-17")
        self.assertEqual((kick["name"], kick["source"]), ("Bass DI", "user"))
        self.assertEqual(requires("schema").validate_doc(doc) and [p for p in requires("schema").validate_doc(doc) if p["level"] == "error"], [])

    def test_public_device_page_lists_channels_with_trace_buttons(self):
        """§6.8.6 / §6.8.7: the viewer device page shows the console tables and trace buttons; builds (no API) get neither buttons nor the drawer."""
        st, h, b = call(self.app, "GET", "/p/campus/d/foh-cl5")
        self.assertEqual(st, 200, b[:300])
        html = b.decode("utf-8")
        self.assertIn("<h2>Console channels</h2>", html)
        self.assertIn("source: imported, not applied yet", html)
        self.assertIn("No sends are recorded", html)
        for title in ("Inputs", "Buses", "DCAs &amp; mute groups", "Racks"):
            self.assertIn(f"<summary>{title} ", html, title)
        self.assertIn('data-trace="foh-cl5:@in-17"', html)
        self.assertIn('data-trace-title="CH 17 · Kick In"', html)
        self.assertIn('data-trace="foh-cl5:dante-primary"', html, "ports get a trace button too")
        self.assertIn('data-trace="foh-cl5"', html, "and the whole device")
        self.assertIn("static/js/trace-ui.js", html)
        self.assertIn("static/css/trace.css", html)
        self.assertIn("Dante Primary 1 “Vox 1”", html, "the Dante receive name decorates the input patch")
        st, _, b = call(self.app, "GET", "/p/campus/d/rio-sl")
        self.assertEqual(st, 200)
        self.assertNotIn("<h2>Console channels</h2>", b.decode("utf-8"), "stage boxes have no console section")

        from fathom.render_html import render_device_page

        doc = read_json(self.pdir / "project.json")
        built = render_device_page(doc, "foh-cl5", project="campus", overlay=None, link_style="build")
        self.assertNotIn("data-trace=", built)
        self.assertNotIn("trace-ui.js", built)
        self.assertNotIn("<h2>Console channels</h2>", built, "nothing applied and no overlay → no section")
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/foh-cl5/channels/apply", {}, {"X-Fathom": "1"})
        self.assertEqual(st, 200, b[:300])
        doc = read_json(self.pdir / "project.json")
        built = render_device_page(doc, "foh-cl5", project="campus", overlay=None, link_style="build")
        self.assertIn("<h2>Console channels</h2>", built, "applied channels render in builds from the doc alone")
        self.assertIn("source: device", built)
        self.assertNotIn("data-trace=", built)

    def test_promote_copies_channels(self):
        requires("merge")
        from fathom import merge as M

        doc = read_json(self.pdir / "project.json")
        # pretend the console is an overlay-only device: promote_ops copies channels along
        ov = {"devices": [{"id": "foh-cl5", "name": "FOH-CL5", "kind": "console", "room": "main", "auto": True, "source": "dante", "ports": []}],
              "channels": {"foh-cl5": {"channels": [{"id": "in-1", "kind": "input", "index": 1, "source": "yamaha"}], "links": []}}}
        doc["devices"] = [d for d in doc["devices"] if d["id"] != "foh-cl5"]
        ops = M.promote_ops(doc, ov, ["foh-cl5"])
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["value"]["channels"][0]["id"], "in-1")
        self.assertEqual(ops[0]["value"]["channel_links"], [])

    def _preview(self, rows, name="sends.csv"):
        import csv
        import io

        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        st, _, b = upload(self.app, "/api/v2/projects/campus/imports/preview?kind=csv", [(name, buf.getvalue().encode("utf-8"), "text/csv")])
        self.assertEqual(st, 200, b[:300])
        return jbody(b)

    def test_console_csv_template_preview_apply(self):
        """§5.7.4 console table / FR-IMP-12: template → preview → apply; sends and DCA membership land as ``source: csv`` links the tracer follows."""
        import csv
        import io

        st, hd, b = call(self.app, "GET", "/api/v2/projects/campus/imports/templates/csv/console.csv")
        self.assertEqual(st, 200, b[:200])
        self.assertIn('filename="fathom-console-template.csv"', hd.get("Content-Disposition"))
        text = b.decode("utf-8")
        self.assertTrue(text.startswith("\ufeff"))
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
        self.assertEqual(rows[0], ["console", "channel", "name", "sends", "dca", "mute", "note"])
        self.assertEqual(rows[1][0], "FOH CL5", "the example names the project's console")
        st, _, b = upload(self.app, "/api/v2/projects/campus/imports/preview?room=main", [("fathom-console-template.csv", text.encode("utf-8"), "text/csv")])
        pv = jbody(b)
        self.assertEqual((st, pv["kind"], pv["errors"]), (200, "csv", []), "the unedited template auto-detects and previews cleanly")
        self.assertEqual(pv["summary"]["skip"], 0)
        self.assertEqual(len(pv["ops"]), 1)
        self.assertTrue(any("applied to the device together" in w for w in pv["warnings"]), "overlay-only channels are persisted by the same op")

        pv = self._preview([
            ["Console", "Channel", "Name", "Sends", "DCA", "Mute"],
            ["FOH CL5", "CH 12", "Bass", "ST; MIX 1-2", "Band", ""],          # stereo = both sides, a range, a DCA by name
            ["FOH CL5", "17", "", "ST L/R", "1; 3", ""],                        # bare number = CH 17
            ["FOH CL5", "MIX 1", "", "MATRIX 3; ST", "", ""],                   # a bus feeding a matrix
            ["FOH CL5", "Kick In", "", "-MIX 9", "", ""],                       # removing an absent send changes nothing
            ["FOH CL5", "DCA 1", "", "ST", "", ""],                             # error: a DCA is not a channel
            ["FOH CL5", "CH 99", "", "ST", "", ""],                             # error: no such channel
            ["FOH CL5", "CH 3", "", "MIX 77", "9", ""],                         # error: no such bus (the row is skipped whole)
            ["Nope", "CH 3", "", "ST", "", ""],                                 # error: no such console
        ])
        self.assertEqual([(e["row"], e["column"], e["value"]) for e in pv["errors"]],
                         [(6, "Channel", "DCA 1"), (7, "Channel", "CH 99"), (8, "Sends", "MIX 77"), (9, "Console", "Nope")],
                         "spreadsheet rows and the user's header text")
        self.assertEqual(pv["summary"], {"create": 3, "update": 0, "skip": 5})
        self.assertTrue(any(w.startswith("row 5: nothing to change") for w in pv["warnings"]), pv["warnings"])
        op = pv["ops"][0]
        self.assertEqual((op["op"], op["coll"], op["id"]), ("merge", "devices", "foh-cl5"))
        csv_links = [(ln["from"]["channel"], ln["to"]["channel"], ln["kind"]) for ln in op["value"]["channel_links"] if ln.get("source") == "csv"]
        self.assertEqual(csv_links, [("in-12", "st-l", "send"), ("in-12", "st-r", "send"), ("in-12", "mix-1", "send"), ("in-12", "mix-2", "send"),
                                     ("in-12", "dca-3", "dca"), ("in-17", "st-l", "send"), ("in-17", "st-r", "send"), ("in-17", "dca-1", "dca"),
                                     ("in-17", "dca-3", "dca"), ("mix-1", "mtx-3", "send"), ("mix-1", "st-l", "send"), ("mix-1", "st-r", "send")])
        self.assertEqual(len(op["value"]["channels"]), 72 + 16 + 24 + 8 + 2 + 1 + 16 + len([c for c in op["value"]["channels"] if c["kind"] == "rack"]),
                         "the whole imported set rides along (72 in, 8 st in pairs, 24 mix, 8 mtx, st l/r, mono, 16 dca + racks)")

        doc = read_json(self.pdir / "project.json")
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": doc["revision"], "ops": pv["ops"], "summary": "Import sends.csv"}, {"X-Fathom": "1"})
        self.assertEqual(st, 200, b[:300])
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/devices/foh-cl5/channels")
        j = jbody(b)
        self.assertEqual((j["source"], j["pending"], j["summary"]["sends"], j["summary"]["dca_members"]), ("device", False, 9, 3))
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/trace?from=foh-cl5:%40in-12&direction=down")
        self.assertEqual(st, 200, b[:300])
        hops = [(h["device"], h.get("channel")) for p in jbody(b)["paths"] for h in p["hops"]]
        self.assertIn(("foh-cl5", "st-l"), hops, "the tracer follows the spreadsheet send")
        self.assertIn(("foh-cl5", "mtx-3"), hops, "and the bus-to-matrix send")

        # the next import re-apply keeps the spreadsheet entries
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/devices/foh-cl5/channels/apply", {}, {"X-Fathom": "1"})
        self.assertEqual(st, 200, b[:300])
        self.assertFalse(jbody(b)["changed"], "nothing pending: csv links count as hand-entered")
        pv = self._preview([["console", "channel", "sends"], ["foh-cl5", "CH 12", "-MIX 2"]])
        self.assertEqual((pv["errors"], pv["summary"]), ([], {"create": 0, "update": 1, "skip": 0}), "a - entry removes a send; the console may be given by id")
        self.assertNotIn(("in-12", "mix-2"), [(ln["from"].get("channel"), ln["to"].get("channel")) for ln in pv["ops"][0]["value"]["channel_links"]])
        problems = [p for p in requires("schema").validate_doc(read_json(self.pdir / "project.json")) if p["level"] == "error"]
        self.assertEqual(problems, [])

    def test_build_report_tables_and_csv(self):
        """§5.9: the build gets a *Console channels* report section (per console, same tables as the device page) and ``console-channels.csv``."""
        import csv
        import io

        export = requires("export")
        run = Path(export.build_doc(str(self.pdir), run_dir=self.data / "runs" / "r1", discovery=False))
        self.assertTrue((run / "console-channels.csv").is_file())
        rows = list(csv.DictReader(io.StringIO((run / "console-channels.csv").read_text(encoding="utf-8"))))
        self.assertEqual(list(rows[0]), ["Console", "Group", "Channel", "Name", "Fed by", "Goes to", "DCA / mute", "Members", "Source"])
        kick = next(r for r in rows if r["Channel"] == "CH 17")
        self.assertEqual((kick["Console"], kick["Group"], kick["Name"]), ("FOH CL5", "Inputs", "Kick In"))
        self.assertTrue(kick["Fed by"].startswith("Dante Primary 1 “Vox 1”"), kick["Fed by"])
        self.assertEqual(kick["Source"], "imported, not applied yet")
        self.assertTrue(any(r["Group"] == "DCAs & mute groups" and r["Channel"] == "DCA 3" and r["Name"] == "BAND" for r in rows))
        self.assertTrue(any(r["Group"] == "Buses" and r["Channel"] == "MIX 9" and "Dante Primary" in r["Goes to"] for r in rows), "bus output patches")
        report = (run / "report.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Console channels</h2>", report)
        self.assertIn('id="console-foh-cl5"', report)
        self.assertIn("<h3>FOH CL5", report)
        self.assertIn("console-channels.csv", report)
        self.assertIn("No sends are recorded", report)
        self.assertNotIn("data-trace=", report, "no trace buttons in a static report")
        self.assertEqual(report.count('<article class="console-report"'), 1, "one block per console with channels")

    def test_binary_console_file_is_explained(self):
        """A .CLF (CL Editor console file) is proprietary and binary: the upload is refused with a note pointing at CSV export + template."""
        import os

        blob = b"CL [OSX, 5.8.1.27]\x00" + os.urandom(2048)
        st, _, b = upload(self.app, "/api/v2/projects/campus/imports?kind=auto&room=main&device=foh-cl5", [("show.clf", blob, "application/octet-stream")])
        self.assertEqual(st, 422, b[:300])
        msg = jbody(b).get("error") or b.decode("utf-8", "replace")
        self.assertIn("show.clf is a .CLF console file", msg)
        self.assertIn("console CSV template", msg)
        self.assertEqual(sorted(p.name for p in (self.pdir / "exports" / "yamaha").rglob("*.clf")), [], "the file is not kept")
        from fathom.parsers import detect_kind, parse_yamaha

        folder = self.pdir / "exports" / "yamaha" / "cl5"
        (folder / "session.CLF").write_bytes(blob)
        self.assertEqual(detect_kind(folder / "session.CLF"), "yamaha")
        data = parse_yamaha(folder)
        self.assertFalse(data.fatal, "a folder that also has the CSVs still parses")
        self.assertEqual(len(data.inputs), 88, "72 mono + 8 stereo pairs")
        self.assertTrue(any(".CLF console file" in n for n in data.notes))


class TemplateRouting(unittest.TestCase):
    def test_stage_boxes_are_indexed_and_instantiate_carries_routing(self):
        lib = requires("library")
        for tid in ("yamaha-rio3224-d", "yamaha-rio3224-d2", "yamaha-rio1608-d", "yamaha-rio1608-d2", "yamaha-ri8-d", "yamaha-ro8-d", "yamaha-tio1608-d", "focusrite-rednet-a16r-mkii", "focusrite-rednet-mp8r", "focusrite-rednet-am2"):
            t = lib.get_template(tid)
            self.assertIsNotNone(t, tid)
            self.assertEqual(t["routing"], "indexed", tid)
            self.assertEqual(lib.validate_template(t), [], tid)
            dev = lib.instantiate(t, device_id="sb", name="SB")
            self.assertEqual(dev["routing"], {"mode": "indexed"}, "4.4.5: template routing reaches the device")
        cl5 = lib.get_template("yamaha-cl5")
        self.assertNotIn("routing", lib.instantiate(cl5, device_id="c", name="C"), "templates without routing leave the kind default")
        self.assertEqual(lib.template_from_device({"id": "x", "name": "X", "kind": "stage_io", "routing": {"mode": "indexed"}, "ports": []}, "x-t")["routing"], "indexed")


if __name__ == "__main__":
    unittest.main()
