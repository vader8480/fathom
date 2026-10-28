"""Data model v2 (SPEC §4): schema, migration, flow adapter, ops, validation, history storage."""

from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from _helpers import (FIXTURES, RRC_DIR, fr, install_project, load_fixture, read_json, requires, rrc_dict,
                          sunday_doc, temp_data_dir, uniq)
except ImportError:  # pragma: no cover - run as a package
    from tests._helpers import (FIXTURES, RRC_DIR, fr, install_project, load_fixture, read_json, requires, rrc_dict,
                                sunday_doc, temp_data_dir, uniq)


COLLECTIONS = ["venues", "rooms", "systems", "locations", "racks", "networks", "devices", "cables", "bundles",
               "floorplans", "attachments", "templates", "imports", "pages", "problems"]


def codes(problems, level=None):
    return [p["code"] for p in problems if level is None or p["level"] == level]


def strip_ports(d):
    d = copy.deepcopy(d)
    for n in d.get("nodes", []):
        n.pop("ports", None)
    return d


def first_diff(a, b, path=""):
    """Human-readable first difference between two JSON values."""
    if type(a) != type(b):
        return "%s: %r != %r" % (path, a, b)
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return "%s/%s: only in %s" % (path, k, "left" if k in a else "right")
            r = first_diff(a[k], b[k], path + "/" + str(k))
            if r:
                return r
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s: len %d != %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            r = first_diff(x, y, "%s[%d]" % (path, i))
            if r:
                return r
        return ""
    return "" if a == b else "%s: %r != %r" % (path, a, b)


def minimal_doc(schema, **extra):
    doc = schema.new_doc("T1")
    doc.update(copy.deepcopy(extra))
    return doc


def dev(id, kind="other", ports=None, **kw):
    d = {"id": id, "name": id.upper(), "kind": kind, "room": "main", "ports": ports or []}
    d.update(kw)
    return d


def port(id, dir, medium="analog", **kw):
    p = {"id": id, "name": id, "dir": dir, "medium": medium}
    p.update(kw)
    return p


# ------------------------------------------------------------------ tiny JSON-schema subset validator (§4.12)


def js_validate(schema_doc, value, node=None, path="$", errs=None):
    errs = [] if errs is None else errs
    node = schema_doc if node is None else node
    if not isinstance(node, dict):
        return errs
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            target = schema_doc
            for part in ref[2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            js_validate(schema_doc, value, target, path, errs)
    t = node.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for ty in types:
            if ty == "object" and isinstance(value, dict):
                ok = True
            elif ty == "array" and isinstance(value, list):
                ok = True
            elif ty == "string" and isinstance(value, str):
                ok = True
            elif ty == "integer" and isinstance(value, int) and not isinstance(value, bool):
                ok = True
            elif ty == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                ok = True
            elif ty == "boolean" and isinstance(value, bool):
                ok = True
            elif ty == "null" and value is None:
                ok = True
        if not ok:
            errs.append("%s: type %s expected, got %r" % (path, t, type(value).__name__))
            return errs
    if "enum" in node and value not in node["enum"]:
        errs.append("%s: %r not in enum" % (path, value))
    if "pattern" in node and isinstance(value, str) and not re.search(node["pattern"], value):
        errs.append("%s: %r fails pattern" % (path, value))
    if isinstance(value, dict):
        for k in node.get("required", []):
            if k not in value:
                errs.append("%s: missing required %s" % (path, k))
        for k, sub in node.get("properties", {}).items():
            if k in value:
                js_validate(schema_doc, value[k], sub, path + "." + k, errs)
    if isinstance(value, list) and isinstance(node.get("items"), dict):
        for i, item in enumerate(value):
            js_validate(schema_doc, item, node["items"], "%s[%d]" % (path, i), errs)
    return errs


# ================================================================== vocabulary (Appendix A)

A1 = [
    ("source", "audio", "#2fd4b4", "none"), ("stage_io", "audio", "#4ea8ff", "matrix"), ("computer", "audio", "#a98bff", "matrix"),
    ("console", "audio", "#7c5cff", "matrix"), ("iem", "audio", "#f06aa8", "matrix"), ("pa", "audio", "#ff9548", "matrix"),
    ("network", "network", "#7b86ff", "matrix"), ("video", "video", "#c084fc", "matrix"), ("other", "other", "#9aa3b5", "matrix"),
    ("mic", "audio", "#2fd4b4", "none"), ("wireless_rx", "audio", "#38bdf8", "matrix"), ("processor", "audio", "#60a5fa", "matrix"),
    ("amp", "audio", "#fb923c", "matrix"), ("speaker", "audio", "#fdba74", "passthrough"), ("recorder", "audio", "#a78bfa", "matrix"),
    ("intercom", "audio", "#f472b6", "matrix"), ("camera", "video", "#34d399", "matrix"), ("video_source", "video", "#2dd4bf", "matrix"),
    ("video_switcher", "video", "#22c55e", "matrix"), ("video_router", "video", "#10b981", "matrix"), ("converter", "video", "#86efac", "matrix"),
    ("encoder", "video", "#4ade80", "matrix"), ("stream", "network", "#fb923c", "none"), ("display", "video", "#a3e635", "passthrough"),
    ("projector", "video", "#bef264", "none"), ("lighting_console", "lighting", "#fbbf24", "matrix"), ("dmx_node", "lighting", "#f59e0b", "matrix"),
    ("dimmer", "lighting", "#eab308", "matrix"), ("fixture", "lighting", "#fde047", "passthrough"), ("switch", "network", "#fb923c", "matrix"),
    ("control", "control", "#c084fc", "matrix"), ("touch_panel", "control", "#d8b4fe", "none"), ("power", "power", "#f87171", "matrix"),
    ("patch_panel", "other", "#94a3b8", "passthrough"), ("container", "other", "#8b94a6", "none"),
]

# v0.2 MEDIA (identical to the first 14 rows of Appendix A.2).
V1_MEDIA = {
    "dante": ("Dante · Cat6", "#7b86ff", "", 1.6, False), "analog": ("Analog · XLR", "#aab3c5", "", 1.4, True),
    "aes3": ("AES3 · 110 Ω", "#2dd4ee", "7 4", 1.5, True), "aes50": ("AES50 · Cat5e", "#5ac8fa", "2 4", 1.6, False),
    "madi": ("MADI", "#fbbf24", "10 4", 1.5, True), "avb": ("AVB / Milan", "#34d399", "6 3 2 3", 1.5, False),
    "speaker": ("Speaker · NL4/NL8", "#ff9548", "", 1.8, True), "iem_wired": ("Wired IEM", "#f472b6", "1.5 4", 1.6, True),
    "iem_wireless": ("Wireless IEM", "#e879f9", "1.5 6", 1.6, True), "rf": ("RF · wireless mic", "#f0abfc", "1.5 6", 1.6, True),
    "usb": ("USB", "#cbd5e1", "4 3", 1.2, True), "video": ("SDI / HDMI", "#c084fc", "", 1.2, True),
    "network": ("Control · IP", "#94a3b8", "3 3", 1.0, False), "other": ("Other", "#9aa3b5", "", 1.2, True),
}
NEW_MEDIA = ["aes67", "qlan", "snake", "adat", "speaker_70v", "intercom", "sdi", "hdmi", "displayport", "hdbaset", "fiber", "ndi",
             "st2110", "dmx", "rdm", "sacn", "artnet", "rs232", "rs422", "ir", "gpio", "osc", "midi", "timecode", "sync", "power", "power_dc"]


class Vocab(unittest.TestCase):
    def setUp(self):
        self.vocab = requires("vocab")

    def test_vocab_kinds(self):
        K = self.vocab.KINDS
        self.assertEqual(len(K), 35, fr("FR-VOC-01", "A.1", "len(KINDS)"))
        self.assertEqual(sorted(K), sorted(k for k, *_ in A1), fr("FR-VOC-01", "A.1", "kind keys"))
        for key, disc, color, routing in A1:
            self.assertEqual(K[key]["discipline"], disc, fr("FR-VOC-01", "A.1", key))
            self.assertEqual(K[key]["color"].lower(), color, fr("FR-VOC-01", "A.1", key + " color"))
            self.assertEqual(K[key]["routing"], routing, fr("FR-VOC-01", "A.1", key + " routing"))
            for f in ("label", "side", "legacy"):
                self.assertIn(f, K[key], fr("FR-VOC-01", "A.1", key + "." + f))
        self.assertEqual(K["network"]["label"], "Network", fr("FR-VOC-01", "A.1", "v1 network label becomes Network"))
        model = requires("model")
        for key in ("source", "stage_io", "computer", "console", "iem", "pa", "network", "video", "other"):
            self.assertIn(key, model.KINDS, fr("FR-VOC-01", "7.4.1", "model.KINDS re-export"))
            self.assertEqual(model.KINDS[key]["color"], K[key]["color"])

    def test_vocab_media_v1_subset(self):
        M = self.vocab.MEDIA
        self.assertEqual(len(M), 41, fr("FR-VOC-02", "A.2", "len(MEDIA)"))
        for key, (label, color, dash, width, arrow) in V1_MEDIA.items():
            m = M[key]
            self.assertEqual(m["label"], label, fr("FR-VOC-02", "A.2", key))
            self.assertEqual(m["color"].lower(), color, fr("FR-VOC-02", "A.2", key))
            self.assertEqual(m["dash"] or "", dash, fr("FR-VOC-02", "A.2", key))
            self.assertAlmostEqual(float(m["width"]), width, msg=fr("FR-VOC-02", "A.2", key))
            self.assertIs(bool(m["arrow"]), arrow, fr("FR-VOC-02", "A.2", key))
        for key in NEW_MEDIA:
            self.assertIn(key, M, fr("FR-VOC-02", "A.2", key))
        for key, m in M.items():
            for f in ("label", "color", "dash", "width", "arrow", "discipline", "carries", "ip", "connector", "short"):
                self.assertIn(f, m, fr("FR-VOC-02", "A.2", "%s.%s" % (key, f)))
        self.assertEqual(set(M["usb"]["carries"]), {"audio", "video", "control"})
        self.assertEqual(M["sdi"]["short"], "SDI")
        self.assertTrue(M["dante"]["ip"])
        self.assertFalse(M["analog"]["ip"])

    def test_vocab_disciplines(self):
        d = self.vocab.as_dict()["disciplines"]
        exp = {"audio": ("#4ea8ff", "A"), "video": ("#34d399", "V"), "lighting": ("#fbbf24", "L"), "network": ("#fb923c", "N"),
               "control": ("#c084fc", "C"), "power": ("#f87171", "P"), "other": ("#9aa3b5", "X")}
        self.assertEqual(len(d), 7, fr("FR-VOC-03", "A.3"))
        for k, (color, letter) in exp.items():
            self.assertEqual(d[k]["color"].lower(), color, fr("FR-VOC-03", "A.3", k))
            self.assertEqual(d[k]["letter"], letter, fr("FR-VOC-03", "A.3", k))

    def test_vocab_as_dict_and_enums(self):
        d = self.vocab.as_dict()
        for k in ("kinds", "media", "disciplines", "brands", "connectors", "statuses", "room_kinds", "port_dirs"):
            self.assertIn(k, d, fr("FR-VOC-04", "7.4.2", k))
        self.assertEqual(tuple(self.vocab.STATUSES), ("installed", "planned", "spare", "retired"))
        self.assertEqual(set(self.vocab.NETWORK_MEDIA), {"dante", "avb", "aes67", "aes50", "madi", "snake", "network", "qlan"})
        self.assertEqual(set(self.vocab.SOURCE_KINDS), {"mic", "source", "video_source", "camera", "computer", "lighting_console", "touch_panel"})
        for b in ("ma", "etc", "chauvet", "martin", "samsung", "decimator", "whirlwind", "electro-voice", "yamaha", "shure"):
            self.assertIn(b, self.vocab.BRANDS, "A.6 brand %s" % b)
        self.assertEqual(self.vocab.kind_discipline("video_switcher"), "video")
        self.assertIn("lighting", self.vocab.medium_carries("sacn"))
        json.dumps(d)  # JSON-serializable for /api/v2/meta


# ================================================================== schema basics


class SchemaBasics(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def test_constants(self):
        s = self.schema
        self.assertEqual(s.SCHEMA_VERSION, 2)
        self.assertEqual(list(s.COLLECTIONS), COLLECTIONS, fr("FR-ROOM-01", "4.1", "collection names/order"))
        self.assertEqual(tuple(s.ROOTS), ("meta", "settings", "media"))
        self.assertTrue(issubclass(s.SchemaError, ValueError))

    def test_new_doc_shape(self):
        s = self.schema
        model = requires("model")
        from fathom.project import blank_project_dict

        d = s.new_doc(org="Hillside")
        self.assertEqual(list(d)[0], "fathom", "4.3.1 fathom is written first")
        self.assertEqual(d["fathom"], 2)
        self.assertEqual(d["revision"], 0)
        self.assertEqual(d["meta"]["org"], "Hillside")
        self.assertEqual(d["meta"]["system"], "Audio system")
        self.assertEqual(d["meta"]["title"], "Signal flow, mic to speaker")
        self.assertEqual(d["meta"]["intro"], model.DEFAULT_INTRO)
        self.assertEqual(d["meta"]["footnote"], model.DEFAULT_FOOTNOTE)
        self.assertEqual(d["settings"], {"default_room": "main", "units": "metric", "cable_tag_pattern": "{D}-{n:03}", "currency": "USD", "autosave": True}, "4.12")
        self.assertEqual(d["venues"], [{"id": "main", "name": "Hillside"}])
        room = d["rooms"][0]
        self.assertEqual({k: room[k] for k in ("id", "venue", "name", "code", "kind")},
                         {"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "auditorium"})
        self.assertEqual(room["flow"]["spine"], {"label": "Dante network", "show": True})
        self.assertEqual(room["flow"]["columns"], model.DEFAULT_COLUMNS)
        self.assertEqual(room["flow"]["groups"], blank_project_dict()["groups"])
        self.assertEqual(room["flow"]["options"], {"auto_dante_nodes": True, "auto_sources": True, "dante_counts": False, "appendix": True})
        for c in COLLECTIONS:
            self.assertIn(c, d, "4.3.1 collections always written")
            if c not in ("venues", "rooms"):
                self.assertEqual(d[c], [])
        self.assertEqual(self.schema.errors(self.schema.validate_doc(d)), [])

    def test_doc_version_and_load_any(self):
        s = self.schema
        self.assertEqual(s.doc_version({"fathom": 2}), 2)
        self.assertEqual(s.doc_version({"fathom": 1}), 1)
        self.assertEqual(s.doc_version({"signalflow": 1}), 1)
        self.assertEqual(s.doc_version({"nodes": []}), 1)
        self.assertEqual(s.doc_version({"links": [], "meta": {}}), 1)
        self.assertEqual(s.doc_version({}), 0)
        with self.assertRaises(s.SchemaError, msg="4.6.1 version > 2") as cm:
            s.load_any({"fathom": 3, "meta": {}})
        self.assertIn("newer", str(cm.exception))
        blank = s.load_any({})
        self.assertEqual(blank["fathom"], 2)
        for c in COLLECTIONS:
            self.assertIn(c, blank)
        v2 = s.load_any(sunday_doc())
        self.assertEqual(v2["fathom"], 2)
        self.assertEqual(len(v2["devices"]), 12)

    def test_normalize(self):
        s = self.schema
        doc = sunday_doc()
        doc["devices"][0]["note"] = None
        doc["devices"][0]["tags"] = []
        doc["devices"][0]["x_custom"] = "keep me"
        doc["devices"][0]["inventory"] = {}
        doc["devices"].append({"id": "auto-1", "name": "Auto", "kind": "iem", "room": "main", "auto": True, "source": "dante", "ports": []})
        doc["devices"][1]["ports"].append({"id": "ovl", "name": "Ovl", "dir": "io", "medium": "dante", "auto": True})
        doc["cables"].append({"id": "auto-c", "from": {"device": "atem-mini"}, "to": {"device": "restream"}, "medium": "usb", "auto": True})
        del doc["bundles"]
        n = s.normalize(doc)
        self.assertEqual(n["fathom"], 2)
        self.assertEqual(list(n)[0], "fathom")
        present = [k for k in n if k in COLLECTIONS]
        self.assertEqual(present, COLLECTIONS, "4.1 collections in order, all present")
        ids = [d["id"] for d in n["devices"]]
        self.assertNotIn("auto-1", ids, "4.4.1 auto devices stripped")
        self.assertNotIn("ovl", [p["id"] for p in n["devices"][1]["ports"]], "4.4.1 auto ports stripped")
        self.assertNotIn("auto-c", [c["id"] for c in n["cables"]])
        d0 = n["devices"][0]
        self.assertNotIn("note", d0, "4.4.1 null dropped")
        self.assertNotIn("tags", d0, "4.4.1 empty array dropped")
        self.assertNotIn("inventory", d0, "4.4.1 empty object dropped")
        self.assertEqual(d0["x_custom"], "keep me", "4.1 unknown fields preserved")
        self.assertEqual(n["devices"][-1]["ports"], [], "4.4.1 ports always written")
        self.assertEqual(s.normalize(n), n, "4.4.1 idempotent")
        self.assertEqual(ids, [d["id"] for d in sunday_doc()["devices"]], "4.4.1 order preserved")
        self.assertIsNot(n, doc)

    def test_json_schema_subset(self):
        s = self.schema
        js = s.JSON_SCHEMA
        self.assertIsInstance(js, dict)
        self.assertIn("2020-12", js.get("$schema", ""), "4.12 JSON Schema 2020-12")
        json.dumps(js)
        self.assertEqual(js_validate(js, sunday_doc()), [], "4.12 fixture validates against JSON_SCHEMA")
        bad = sunday_doc()
        bad["devices"][0]["ports"] = "nope"
        self.assertTrue(js_validate(js, bad), "4.12 ports must be an array")
        self.assertEqual(js_validate(js, s.new_doc("X")), [])
        campus = Path(RRC_DIR).parent / "campus-demo" / "project.json"
        if campus.exists():
            self.assertEqual(js_validate(js, read_json(campus)), [], "4.12 campus-demo validates against JSON_SCHEMA")

    def test_discipline_of(self):
        s = self.schema
        self.assertEqual(s.discipline_of({"kind": "video_switcher"}), "video")
        self.assertEqual(s.discipline_of({"kind": "console", "discipline": "video"}), "video")
        self.assertEqual(s.discipline_of({"kind": "laser-thing"}), "other")


# ================================================================== port expansion + ops vectors


class Vectors(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def test_port_expansion_vectors(self):
        cases = load_fixture("port-expansion.json")
        self.assertGreaterEqual(len(cases), 8)
        for c in cases:
            with self.subTest(case=c["name"]):
                got = self.schema.expand_port_groups(copy.deepcopy(c["input"]), v1=c["v1"])
                self.assertEqual(got, c["expected"], fr("FR-PORT-03", "4.4.3", c["name"] + " " + first_diff(got, c["expected"])))

    def test_ops_vectors_apply(self):
        cases = load_fixture("ops-vectors.json")
        self.assertGreaterEqual(len(cases), 10)
        for c in cases:
            with self.subTest(case=c["name"]):
                before = copy.deepcopy(c["doc"])
                if c.get("error"):
                    with self.assertRaises(self.schema.SchemaError, msg=fr("FR-HIST-05", "4.9", c["name"])) as cm:
                        self.schema.apply_ops(c["doc"], c["ops"])
                    self.assertIn(c["error"], "%s %s" % (getattr(cm.exception, "code", ""), cm.exception))
                else:
                    new, touched = self.schema.apply_ops(c["doc"], c["ops"])
                    self.assertEqual(new, c["expected"], fr("FR-HIST-05", "4.9", c["name"] + " " + first_diff(new, c["expected"])))
                    self.assertEqual(sorted(touched), c["touched"], fr("FR-HIST-05", "4.9", c["name"] + " touched"))
                    self.assertEqual(sorted(self.schema.touched_refs(c["ops"])), c["touched"])
                self.assertEqual(c["doc"], before, "4.9 apply_ops is pure (input not mutated)")

    def test_ops_invert_roundtrip(self):
        s = self.schema
        for c in load_fixture("ops-vectors.json"):
            if c.get("error"):
                continue
            with self.subTest(case=c["name"]):
                inv = s.invert_ops(c["doc"], c["ops"])
                new, _ = s.apply_ops(c["doc"], c["ops"])
                back, _ = s.apply_ops(new, inv)
                self.assertEqual(back, c["doc"], fr("FR-PV-08", "4.9 inverse", c["name"] + " " + first_diff(back, c["doc"])))

    def test_diff_docs_roundtrip(self):
        s = self.schema
        for c in load_fixture("ops-vectors.json"):
            if c.get("error"):
                continue
            with self.subTest(case=c["name"]):
                ops = s.diff_docs(c["doc"], c["expected"])
                for op in ops:
                    self.assertIn(op["op"], ("put", "del", "root", "move"), "4.9 diff_docs op types")
                    if op["op"] == "root":
                        self.assertTrue(op.get("replace"), "4.9 diff_docs root ops use replace:true")
                got, _ = s.apply_ops(c["doc"], ops)
                self.assertEqual(got, c["expected"], fr("FR-HIST-04", "4.9 diff_docs", c["name"] + " " + first_diff(got, c["expected"])))
        fx = sunday_doc()
        self.assertEqual(s.diff_docs(fx, copy.deepcopy(fx)), [])
        b = copy.deepcopy(fx)
        b["devices"][5]["name"] = "ATEM"
        ops = s.diff_docs(fx, b)
        self.assertEqual(sorted(s.touched_refs(ops)), ["devices/atem-mini"], "4.9 diff_docs touches only changed entities")

    def test_merge_patch_rfc7396(self):
        mp = self.schema.merge_patch
        cases = [
            ({"a": "b"}, {"a": "c"}, {"a": "c"}), ({"a": "b"}, {"b": "c"}, {"a": "b", "b": "c"}),
            ({"a": "b"}, {"a": None}, {}), ({"a": "b", "b": "c"}, {"a": None}, {"b": "c"}),
            ({"a": ["b"]}, {"a": "c"}, {"a": "c"}), ({"a": "c"}, {"a": ["b"]}, {"a": ["b"]}),
            ({"a": {"b": "c"}}, {"a": {"b": "d", "c": None}}, {"a": {"b": "d"}}), ({"a": [{"b": "c"}]}, {"a": [1]}, {"a": [1]}),
            (["a", "b"], ["c", "d"], ["c", "d"]), ({"a": "b"}, ["c"], ["c"]), ({"a": "foo"}, None, None),
            ({"a": "foo"}, "bar", "bar"), ({"e": None}, {"a": 1}, {"e": None, "a": 1}), ([1, 2], {"a": "b", "c": None}, {"a": "b"}),
            ({}, {"a": {"bb": {"ccc": None}}}, {"a": {"bb": {}}}),
        ]
        for target, patch, expected in cases:
            t0 = copy.deepcopy(target)
            self.assertEqual(mp(target, patch), expected, "RFC 7396 %r + %r" % (target, patch))
            self.assertEqual(target, t0, "merge_patch must not mutate its target")


# ================================================================== validation (§4.7)


class Validation(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def v(self, doc):
        probs = self.schema.validate_doc(doc)
        for p in probs:
            for k in ("level", "code", "ref", "path", "message"):
                self.assertIn(k, p, "4.7 Problem shape")
            self.assertIn(p["level"], ("error", "warning"))
        return probs

    def test_fixture_validates_clean(self):
        probs = self.v(sunday_doc())
        self.assertEqual(probs, [], fr("FR-ROOM-01", "Appendix B", "validate_doc(fixture) must be [] (no errors, no warnings): %s" % probs))

    def test_room_collections_validate(self):
        s = self.schema
        self.assertEqual(s.errors(self.v(sunday_doc())), [], fr("FR-ROOM-01", "3.1"))
        project = requires("project")
        with temp_data_dir() as data:
            name = uniq("rooms")
            pdir = install_project(data, name, doc=sunday_doc())
            doc, _ = project.load_doc(name)
            room = {"id": "chapel", "venue": "hillside", "name": "Chapel", "code": "CHPL", "kind": "chapel"}
            res = project.apply_changes(pdir, [{"op": "put", "coll": "rooms", "id": "chapel", "value": room}],
                                        base_revision=doc["revision"], author="t1", summary="add room")
            self.assertGreater(res["revision"], doc["revision"])
            self.assertEqual(sorted(res["touched"]), ["rooms/chapel"])
            again, _ = project.load_doc(name)
            self.assertIn("chapel", [r["id"] for r in again["rooms"]], fr("FR-ROOM-01", "3.1", "room op returned by next load"))
            self.assertEqual(again["revision"], res["revision"])
        bad = sunday_doc()
        bad["rooms"][0]["venue"] = "nowhere"
        self.assertIn("dangling_ref", codes(self.v(bad), "error"), fr("FR-ROOM-01", "4.7", "room.venue dangling"))
        bad = sunday_doc()
        bad["systems"][0]["room"] = "nowhere"
        self.assertIn("dangling_ref", codes(self.v(bad), "error"), "4.7 system.room dangling")

    def test_port_validation(self):
        doc = minimal_doc(self.schema, devices=[dev("a", ports=[port("p", "in"), port("p", "out")])])
        probs = self.v(doc)
        self.assertIn("duplicate_port", codes(probs, "error"), fr("FR-PORT-01", "4.7", "duplicate_port"))
        doc = minimal_doc(self.schema, devices=[dev("a", ports=[port("p", "sideways")])])
        probs = self.v(doc)
        self.assertIn("bad_enum", codes(probs, "error"), fr("FR-PORT-01", "4.7", "bad dir -> bad_enum"))
        hit = [p for p in probs if p["code"] == "bad_enum"][0]
        self.assertEqual(hit["ref"], "devices/a")

    def test_device_level_cable(self):
        s = self.schema
        v1 = {"fathom": 1, "nodes": [{"id": "a", "label": "A", "kind": "source"}, {"id": "b", "label": "B", "kind": "console"}],
              "links": [{"from": "a", "to": "b", "medium": "analog"}]}
        doc = s.migrate(v1)
        self.assertEqual(len(doc["cables"]), 1)
        c = doc["cables"][0]
        self.assertEqual(c["from"], {"device": "a"}, fr("FR-PORT-02", "4.6.5", "device-level from endpoint"))
        self.assertEqual(c["to"], {"device": "b"}, fr("FR-PORT-02", "4.6.5", "device-level to endpoint"))
        self.assertEqual(s.errors(self.v(doc)), [], fr("FR-PORT-02", "4.3.10"))
        native = minimal_doc(s, devices=[dev("x", ports=[port("o", "out")]), dev("y")],
                             cables=[{"id": "c-1", "from": {"device": "x", "port": "o"}, "to": {"device": "y"}, "medium": "analog"}])
        self.assertEqual(s.errors(self.v(native)), [])

    def test_port_overuse_warning(self):
        doc = minimal_doc(self.schema,
                          devices=[dev("a", ports=[port("o1", "out"), port("o2", "out")]), dev("b", ports=[port("i1", "in")])],
                          cables=[{"id": "c-1", "from": {"device": "a", "port": "o1"}, "to": {"device": "b", "port": "i1"}, "medium": "analog"},
                                  {"id": "c-2", "from": {"device": "a", "port": "o2"}, "to": {"device": "b", "port": "i1"}, "medium": "analog"}])
        probs = self.v(doc)
        self.assertIn("port_overuse", codes(probs, "warning"), fr("FR-PORT-04", "4.4.4", "port_overuse"))
        self.assertEqual(self.schema.errors(probs), [])
        doc["devices"][1]["ports"][0]["channels"] = 2
        self.assertNotIn("port_overuse", codes(self.v(doc)), "4.4.4 overuse only when >= channels cables")

    def test_unknown_values_are_warnings(self):
        doc = minimal_doc(self.schema, devices=[dev("a", kind="laser-cannon", ports=[port("o", "out", medium="laser")]), dev("b")],
                          cables=[{"id": "c-1", "from": {"device": "a", "port": "o"}, "to": {"device": "b"}, "medium": "laser"}])
        probs = self.v(doc)
        self.assertEqual(self.schema.errors(probs), [], fr("FR-VOC-07", "4.7", "unknown kind/medium never errors"))
        self.assertIn("unknown_medium", codes(probs, "warning"), fr("FR-VOC-07", "4.7"))
        self.assertIn("unknown_kind", codes(probs, "warning"), fr("FR-VOC-07", "4.7"))

    def test_error_codes(self):
        s = self.schema
        mk = lambda **kw: minimal_doc(s, **kw)  # noqa: E731
        cases = [
            ("bad_id", mk(devices=[dev("ok"), dict(dev("x"), id="bad id")])),
            ("duplicate_id", mk(devices=[dev("a"), dev("a")])),
            ("missing_field", mk(devices=[{"id": "a", "kind": "other", "room": "main", "ports": []}])),
            ("bad_type", mk(devices=[dict(dev("a"), ports="none")])),
            ("dangling_ref", mk(devices=[dev("a")], cables=[{"id": "c-1", "from": {"device": "a"}, "to": {"device": "ghost"}, "medium": "analog"}])),
            ("bad_enum", mk(devices=[dict(dev("a"), status="broken")])),
        ]
        for code, doc in cases:
            with self.subTest(code=code):
                self.assertIn(code, codes(self.v(doc), "error"), "4.7 %s is an error" % code)
        doc = sunday_doc()
        doc["rooms"][0].setdefault("flow", {})["extra_cards"] = [{"id": "atem-mini", "device": "atem-mini"}]
        self.assertIn("duplicate_id", codes(self.v(doc), "error"), "4.7 devices and extra cards share an id space")
        doc = sunday_doc()
        doc["rooms"][0]["flow"]["extra_cards"] = [{"id": "ghost-card", "device": "nope"}]
        self.assertIn("dangling_ref", codes(self.v(doc), "error"), "4.7 extra_card.device dangling")

    def test_warning_codes(self):
        s = self.schema
        base = lambda: minimal_doc(s, devices=[dev("a", ports=[port("i", "in"), port("o", "out")]), dev("b", ports=[port("i", "in"), port("o", "out")])])  # noqa: E731
        d = base()
        d["cables"] = [{"id": "c-1", "from": {"device": "a", "port": "nope"}, "to": {"device": "b", "port": "i"}, "medium": "analog"}]
        self.assertIn("dangling_port", codes(self.v(d), "warning"), "4.7 dangling_port is a warning")
        self.assertEqual(s.errors(self.v(d)), [])
        d = base()
        d["cables"] = [{"id": "c-1", "from": {"device": "a", "port": "i"}, "to": {"device": "b", "port": "o"}, "medium": "analog"}]
        self.assertIn("bad_direction", codes(self.v(d), "warning"), "4.7 bad_direction")
        d = base()
        d["cables"] = [{"id": "c-1", "tag": "A-001", "from": {"device": "a", "port": "o"}, "to": {"device": "b", "port": "i"}, "medium": "analog"},
                       {"id": "c-2", "tag": "A-001", "from": {"device": "b", "port": "o"}, "to": {"device": "a", "port": "i"}, "medium": "analog"}]
        self.assertIn("tag_duplicate", codes(self.v(d), "warning"), "4.7 tag_duplicate")
        d = base()
        d["devices"][0]["inventory"] = {"purchase_date": "04/02/2023"}
        self.assertIn("bad_date", codes(self.v(d), "warning"), "4.7 bad_date")
        d = base()
        d["devices"][0]["ports"][1]["medium"] = "hdmi"
        d["devices"][1]["ports"][0]["medium"] = "sdi"
        d["cables"] = [{"id": "c-1", "from": {"device": "a", "port": "o"}, "to": {"device": "b", "port": "i"}, "medium": "hdmi"}]
        self.assertIn("medium_mismatch", codes(self.v(d), "warning"), "4.4.4 hdmi->sdi carries intersect -> medium_mismatch")
        d["devices"][1]["ports"][0]["medium"] = "dmx"
        self.assertIn("medium_incompatible", codes(self.v(d), "warning"), "4.4.4 hdmi->dmx disjoint -> medium_incompatible")

    def test_marker_out_of_bounds(self):
        d = sunday_doc()
        d["attachments"] = [{"id": "att-000000000001", "name": "p.png", "file": "files/att-000000000001/p.png", "mime": "image/png"}]
        d["floorplans"] = [{"id": "fp-main", "name": "Main", "room": "main",
                            "source": {"attachment": "att-000000000001", "kind": "png", "page": 0},
                            "image": {"attachment": "att-000000000001", "kind": "png", "width": 100, "height": 100},
                            "markers": [{"device": "atem-mini", "x": 1.5, "y": 0.5}]}]
        probs = self.v(d)
        self.assertIn("marker_out_of_bounds", codes(probs, "warning"), "4.7 marker_out_of_bounds")
        d["floorplans"][0]["markers"] = [{"device": "ghost", "x": 0.5, "y": 0.5}]
        self.assertIn("dangling_ref", codes(self.v(d), "error"), "4.7 marker.device dangling")

    def test_network_validation(self):
        requires("network")
        d = sunday_doc()
        d["devices"][1]["interfaces"][0]["ip"] = "10.20.0.999"
        self.assertIn("bad_ip", codes(self.v(d), "warning"), fr("FR-NET-01", "4.7", "bad_ip"))
        d = sunday_doc()
        d["networks"][0]["subnet"] = "10.20.0.0/33"
        self.assertIn("bad_subnet", codes(self.v(d), "warning"), fr("FR-NET-01", "4.7", "bad_subnet"))
        self.assertEqual(self.schema.errors(self.v(d)), [])

    def test_dmx_range_warning(self):
        requires("dmx")
        d = sunday_doc()
        d["devices"].append({"id": "par-1", "name": "Par 1", "kind": "fixture", "room": "main", "ports": [],
                             "dmx": {"universe": 70000, "address": 1, "footprint": 8}})
        probs = self.v(d)
        self.assertIn("dmx_range", codes(probs, "warning"), fr("FR-DMX-01", "4.7", "universe > 63999"))
        self.assertEqual(self.schema.errors(probs), [])


# ================================================================== migration (§4.6)


class Migration(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.doc = self.schema.migrate(rrc_dict())
        self.devices = {d["id"]: d for d in self.doc["devices"]}

    def ports(self, dev_id):
        return {p["id"]: p for p in self.devices[dev_id]["ports"]}

    def test_migrate_rrc_valid(self):
        errs = self.schema.errors(self.schema.validate_doc(self.doc))
        self.assertEqual(errs, [], fr("FR-MIG-01", "4.6", "RRC migrates with 0 errors"))
        self.assertEqual(self.doc["fathom"], 2)
        self.assertEqual(self.schema.doc_version(self.doc), 2)
        self.assertEqual(self.doc["settings"]["default_room"], "main")
        self.assertEqual(self.doc["venues"], [{"id": "main", "name": rrc_dict()["meta"]["org"]}], "4.6.2 venue")
        sysm = self.doc["systems"]
        self.assertEqual(sysm, [{"id": "main-audio", "room": "main", "discipline": "audio", "name": rrc_dict()["meta"].get("system") or "Audio system"}])
        room = self.doc["rooms"][0]
        self.assertEqual({k: room[k] for k in ("id", "venue", "name", "code", "kind")},
                         {"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "other"})
        v1 = rrc_dict()
        self.assertEqual(room["flow"]["columns"], v1["columns"], "4.6.2 columns")
        self.assertEqual(room["flow"]["spine"], v1["spine"], "4.6.2 spine")
        self.assertEqual(room["flow"]["options"], v1["options"], "4.6.2 options verbatim")
        self.assertEqual(self.doc["meta"], v1["meta"], "4.6.2 meta verbatim")
        imps = self.doc["imports"]
        self.assertEqual([i["id"] for i in imps], ["imp-0001", "imp-0002", "imp-0003"])
        self.assertEqual(imps[0]["device"], "foh")
        self.assertEqual(imps[0]["room"], "main")
        self.assertEqual(imps[1]["path"], "exports/dante/rrc-littleton-preset.xml")
        n_nodes = len([n for n in v1["nodes"] if not n.get("ref")])
        self.assertEqual(len(self.doc["devices"]), n_nodes, "4.6.3 one device per non-ref node")

    def test_migration_bundles_drums_neve1(self):
        b1 = [b for b in self.doc["bundles"] if b["id"] == "b-0001"]
        self.assertTrue(b1, fr("FR-MIG-07", "4.6.5", "bundle b-0001"))
        members = [c for c in self.doc["cables"] if c.get("bundle") == "b-0001"]
        self.assertEqual(len(members), 8, fr("FR-MIG-07", "4.6.5"))
        for i, c in enumerate(members, 1):
            self.assertEqual(c["from"], {"device": "drums", "port": "kit-mics-%d" % i}, fr("FR-MIG-07", "4.6.4"))
            self.assertEqual(c["to"], {"device": "neve1", "port": "mic-line-in-%d" % i}, fr("FR-MIG-07", "4.6.4"))
        self.assertEqual([c["id"] for c in self.doc["cables"][:8]], ["c-%04d" % i for i in range(1, 9)])

    def test_migration_appendix_g(self):
        d = self.devices["drums"]
        self.assertEqual({k: v for k, v in d.items() if k != "ports"},
                         {"id": "drums", "name": "Drums", "kind": "source", "room": "main", "system": "main-audio",
                          "sub": "8 → Neve #1 · 4 + TB → #2", "count": 12, "suffix": "+ TB",
                          "flow": {"group": "A", "column": "sources", "seq": 0}}, fr("FR-MIG-01", "Appendix G", "drums device"))
        dp = self.ports("drums")
        self.assertEqual(dp["kit-mics-1"], {"id": "kit-mics-1", "name": "kit mics 1", "dir": "out", "medium": "analog", "group": "kit mics", "index": 1, "origin": "link"}, "Appendix G kit-mics-1")
        for i in range(1, 6):
            self.assertIn("oh-l-r-ride-perc-tb-%d" % i, dp, "Appendix G opaque side with 5 ports")
        self.assertEqual(dp["oh-l-r-ride-perc-tb-1"]["name"], "OH L/R, ride, perc, TB 1")
        n = self.devices["neve1"]
        self.assertEqual({k: v for k, v in n.items() if k != "ports"},
                         {"id": "neve1", "name": "1073OPX #1", "kind": "stage_io", "room": "main", "system": "main-audio",
                          "sub": "8 of 8 · drums", "brand": "neve", "dante": True, "dante_name": "1073OPX-1",
                          "flow": {"group": "A", "column": "stage_io", "seq": 6}}, "Appendix G neve1 device")
        npt = self.ports("neve1")
        self.assertEqual(npt["mic-line-in-1"], {"id": "mic-line-in-1", "name": "Mic/line in 1", "dir": "in", "medium": "analog", "group": "Mic/line in", "index": 1, "origin": "declared"})
        self.assertEqual(npt["dante-tx"], {"id": "dante-tx", "name": "Dante tx", "dir": "out", "medium": "dante", "group": "Dante tx", "index": 1, "channels": 8, "origin": "declared"})
        r = self.devices["rio3224"]
        self.assertEqual(r["lines"], ["stage box", "15 of 32 in used", "outputs: see G · PA & zones"])
        self.assertEqual(r["flow"], {"group": "A", "column": "stage_io", "seq": 8})
        rp = self.ports("rio3224")
        self.assertEqual(rp["aes-ebu-out-1-2"], {"id": "aes-ebu-out-1-2", "name": "AES/EBU out 1/2", "dir": "out", "medium": "aes3", "group": "AES/EBU out", "index": 1, "origin": "declared"})
        for pid in ["mic-line-in-%d" % i for i in range(1, 33)] + ["line-out-%d" % i for i in range(1, 17)] + ["aes-ebu-out-3-4", "aes-ebu-out-5-6", "aes-ebu-out-7-8"]:
            self.assertIn(pid, rp, "Appendix G rio3224 port %s" % pid)
        extra = self.doc["rooms"][0]["flow"]["extra_cards"]
        card = [e for e in extra if e["id"] == "rio3224-out"]
        self.assertEqual(card, [{"id": "rio3224-out", "device": "rio3224", "seq": 28, "name": "Rio3224", "sub": "stage box · AES + line outs",
                                 "kind": "stage_io", "brand": "yamaha", "group": "G", "column": "mix", "dante": True}], "Appendix G extra card")
        b = [x for x in self.doc["bundles"] if x["id"] == "b-0001"][0]
        self.assertEqual(b, {"id": "b-0001", "kind": "link", "medium": "analog", "count": 8, "from_text": "kit mics 1-8", "to_text": "in 1-8",
                             "signal": "kick in/out, snare top/bottom, hi-hat, toms", "flow": {"seq": 0}}, "Appendix G bundle")
        cab = {c["id"]: c for c in self.doc["cables"]}
        self.assertEqual(cab["c-0001"], {"id": "c-0001", "from": {"device": "drums", "port": "kit-mics-1"}, "to": {"device": "neve1", "port": "mic-line-in-1"},
                                         "medium": "analog", "bundle": "b-0001", "flow": {"seq": 0}}, "Appendix G c-0001")
        self.assertEqual(cab["c-0050"], {"id": "c-0050", "from": {"device": "rio3224", "port": "aes-ebu-out-1-2"}, "to": {"device": "la7-1", "port": "aes-in-a"},
                                         "medium": "aes3", "label": "AES · L/R", "count": 2, "from_text": "AES out 1/2", "to_text": "AES in A",
                                         "signal": "Main L/R", "flow": {"seq": 15, "from_card": "rio3224-out"}}, "Appendix G c-0050")
        la = self.ports("la7-1")["aes-in-a"]
        self.assertEqual({k: la.get(k) for k in ("id", "name", "dir", "medium", "channels", "origin")},
                         {"id": "aes-in-a", "name": "AES in A", "dir": "in", "medium": "aes3", "channels": 2, "origin": "link"}, "Appendix G la7-1 generated port")

    def test_migration_empty_side_allocation(self):
        crowd_cables = [c for c in self.doc["cables"] if c["from"]["device"] == "crowd"]
        to_rio = [c["from"].get("port") for c in crowd_cables if c["to"]["device"] == "rio3224"]
        to_1608 = [c["from"].get("port") for c in crowd_cables if c["to"]["device"] == "rio1608"]
        self.assertEqual(to_rio, ["out-%d" % i for i in range(1, 7)], fr("FR-MIG-07", "4.6.4 empty side"))
        self.assertEqual(to_1608, ["out-%d" % i for i in range(7, 11)], fr("FR-MIG-07", "4.6.4 empty side"))
        rio_ins = [c["to"]["port"] for c in crowd_cables if c["to"]["device"] == "rio3224"]
        self.assertEqual(rio_ins, ["mic-line-in-%d" % i for i in range(10, 16)], "4.6.4 'in 10-15' resolves to the declared group")

    def test_parse_port_text(self):
        ppt = self.schema.parse_port_text
        self.assertEqual(ppt("in 1-8"), ("range", "in", 1, 8))
        self.assertEqual(ppt("Omni out 1-8")[:1] + ppt("Omni out 1-8")[2:], ("range", 1, 8))
        self.assertEqual(ppt("in 5"), ("index", "in", 5, 5))
        self.assertEqual(ppt("line out 1")[0], "index")
        self.assertEqual(ppt("AES out 1/2")[0], "opaque")
        self.assertEqual(ppt("kit mics")[0], "opaque")
        self.assertEqual(ppt("AES50 A")[0], "opaque")
        self.assertEqual(ppt("OH L/R, ride, perc, TB")[0], "opaque")

    def test_id_remap_alias(self):
        s = self.schema
        v1 = {"fathom": 1, "nodes": [{"id": "FOH Console", "label": "FOH", "kind": "console"}, {"id": "spk", "label": "S", "kind": "pa"}],
              "links": [{"from": "FOH Console", "to": "spk", "medium": "analog"}]}
        doc = s.migrate(v1)
        ids = [d["id"] for d in doc["devices"]]
        self.assertIn("foh-console", ids, "4.6.3 invalid id -> slug")
        foh = [d for d in doc["devices"] if d["id"] == "foh-console"][0]
        self.assertIn("FOH Console", foh.get("aliases", []), "4.6.3 old id kept as alias")
        self.assertEqual(doc["cables"][0]["from"]["device"], "foh-console", "4.6.3 references remapped")

    def test_load_signalflow_v1(self):
        project = requires("project")
        with temp_data_dir() as data:
            name = uniq("sf")
            pdir = install_project(data, name, src_dir=RRC_DIR)
            d = read_json(pdir / "project.json")
            d.pop("fathom", None)
            d["signalflow"] = 1
            (pdir / "project.json").write_text(json.dumps(d), encoding="utf-8")
            before = (pdir / "project.json").read_bytes()
            doc, ddir = project.load_doc(name)
            self.assertEqual(doc["fathom"], 2, fr("FR-MIG-02", "4.6.1"))
            self.assertEqual(len(doc["devices"]), len(self.doc["devices"]), fr("FR-MIG-02", "4.6"))
            _, _, ver = project.load_doc_info(name)
            self.assertEqual(ver, 1, fr("FR-MIG-02", "7.4.1 load_doc_info source version"))
            self.assertEqual((pdir / "project.json").read_bytes(), before, fr("FR-MIG-02", "2.3 item 1", "load must not write"))
            self.assertFalse((pdir / "project.v1.json").exists())
            # v1 loader still works on it
            p, _ = project.load_project(name)
            self.assertTrue(p.nodes)

    def test_v1_backup_written_once(self):
        project = requires("project")
        with temp_data_dir() as data:
            name = uniq("bk")
            pdir = install_project(data, name, src_dir=RRC_DIR)
            original = (pdir / "project.json").read_bytes()
            doc, ddir = project.load_doc(name)
            doc["meta"]["description"] = "first v2 write"
            res = project.save_doc(doc, ddir, base_revision=doc.get("revision", 0), author="t1", summary="first")
            self.assertIn("revision", res)
            backup = pdir / "project.v1.json"
            self.assertTrue(backup.exists(), fr("FR-MIG-04", "2.3 item 1", "project.v1.json written on first v2 save"))
            self.assertEqual(backup.read_bytes(), original, fr("FR-MIG-04", "4.10", "backup is the original file"))
            saved = read_json(pdir / "project.json")
            self.assertEqual(saved.get("fathom"), 2, "saved as v2")
            doc2, _ = project.load_doc(name)
            doc2["meta"]["description"] = "second write"
            project.save_doc(doc2, ddir, base_revision=doc2["revision"], author="t1")
            self.assertEqual(backup.read_bytes(), original, fr("FR-MIG-04", "4.10", "never overwritten afterwards"))
            entries = (pdir / "history" / "index.jsonl").read_text().strip().splitlines()
            first = json.loads(entries[0])
            self.assertEqual(first["revision"], 1)
            self.assertEqual(first["source"], "migrate", "4.10 first write of a migrated v1 file records rev 1 source migrate")
            self.assertTrue((pdir / "history" / "snap" / "000001.json").exists(), "4.10 snapshot at revision 1")


# ================================================================== flow adapter & identity (§4.6.6–4.6.8)


class FlowIdentity(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        from fathom.layout import compute_layout
        from fathom.merge import apply_imports
        from fathom.model import project_from_dict

        self.compute_layout = compute_layout
        self.apply_imports = apply_imports
        self.project_from_dict = project_from_dict

    def _identity(self, v1, project_dir, label):
        p1 = self.project_from_dict(copy.deepcopy(v1))
        p2 = self.schema.flow_project(self.schema.migrate(copy.deepcopy(v1)))
        self.apply_imports(p1, project_dir)
        self.apply_imports(p2, project_dir)
        d1, d2 = strip_ports(p1.to_dict()), strip_ports(p2.to_dict())
        self.assertEqual(d1, d2, fr("FR-MIG-03", "4.6.8", "%s to_dict differs: %s" % (label, first_diff(d1, d2))))
        l1, l2 = self.compute_layout(p1), self.compute_layout(p2)
        self.assertEqual(sorted(l1.cards), sorted(l2.cards), fr("FR-MIG-03", "4.6.8", label + " card ids"))
        for cid in l1.cards:
            b1, b2 = l1.cards[cid].box, l2.cards[cid].box
            self.assertEqual(tuple(round(v, 2) for v in (b1.x, b1.y, b1.w, b1.h)), tuple(round(v, 2) for v in (b2.x, b2.y, b2.w, b2.h)),
                             fr("FR-MIG-03", "4.6.8", "%s box of %s" % (label, cid)))
        self.assertEqual(len(l1.links), len(l2.links), fr("FR-MIG-03", "4.6.8", label + " link count"))

    def test_rrc_layout_identity(self):
        tmp = Path(tempfile.mkdtemp(prefix="fathom-t1-"))
        try:
            pdir = tmp / "rrc"
            shutil.copytree(str(RRC_DIR), str(pdir))
            self._identity(rrc_dict(), pdir, "RRC")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_blank_and_extra_identity(self):
        from fathom.project import blank_project_dict

        tmp = Path(tempfile.mkdtemp(prefix="fathom-t1-"))
        try:
            self._identity(blank_project_dict("Blank Org"), tmp, "blank_project_dict")
            self._identity(load_fixture("v1-extra.json"), tmp, "tests/fixtures/v1-extra.json")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_flow_project_rooms_and_state(self):
        s = self.schema
        fx = sunday_doc()
        p = s.flow_project(fx)
        ids = {n.id for n in p.nodes}
        self.assertIn("atem-mini", ids)
        self.assertNotIn("spare-ulxd4d", ids, "4.6.6 only devices of the room")
        self.assertEqual(p.meta.system, "Main Auditorium")
        fx["devices"][5]["status"] = "planned"
        self.assertNotIn("atem-mini", {n.id for n in s.flow_project(fx, state="as_built").nodes}, fr("FR-PLN-01", "4.4.6", "as_built hides planned"))
        self.assertIn("atem-mini", {n.id for n in s.flow_project(fx, state="planned").nodes})
        fx2 = sunday_doc()
        fx2["rooms"].append({"id": "chapel", "venue": "hillside", "name": "Chapel"})
        fx2["devices"][5]["room"] = "chapel"
        main = s.flow_project(fx2, "main")
        ext = [n for n in main.nodes if n.id == "atem-mini"]
        self.assertTrue(ext and ext[0].auto, "4.6.6 cross-room device becomes an auto external node")
        chapel = s.flow_project(fx2, "chapel")
        self.assertEqual(chapel.meta.system, "Chapel", "4.6.6 non-default room system = room name")
        self.assertIn("atem-mini", {n.id for n in chapel.nodes})

    def test_v1_expressible_and_to_v1_dict(self):
        s = self.schema
        rrc = s.migrate(rrc_dict())
        self.assertTrue(s.is_v1_expressible(rrc), fr("FR-MIG-06", "4.6.7", "migrated RRC is v1-expressible"))
        self.assertFalse(s.is_v1_expressible(sunday_doc()), fr("FR-MIG-06", "4.6.7", "fixture has racks/networks"))
        v1 = s.to_v1_dict(rrc)
        self.assertEqual(strip_ports(self.project_from_dict(v1).to_dict()), strip_ports(self.project_from_dict(rrc_dict()).to_dict()),
                         fr("FR-MIG-06", "5.12", "to_v1_dict round trip"))
        neve = [n for n in v1["nodes"] if n["id"] == "neve1"][0]
        counts = sorted(int(g.get("count") or len(g.get("labels") or [])) for g in neve.get("ports", []))
        self.assertEqual(counts, [8, 8], "4.6.6 declared ports rebuilt as v1 groups")
        again = s.migrate(v1)
        self.assertEqual(len(again["cables"]), len(rrc["cables"]))
        tweaked = copy.deepcopy(rrc)
        tweaked["devices"][0]["inventory"] = {"serial": "x"}
        self.assertFalse(s.is_v1_expressible(tweaked), "4.6.7 inventory is not v1")
        tweaked = copy.deepcopy(rrc)
        tweaked["cables"][0]["tag"] = "A-001"
        self.assertFalse(s.is_v1_expressible(tweaked), "4.6.7 cable tag is not v1")


# ================================================================== storage & history (§4.10)


class Storage(unittest.TestCase):
    def setUp(self):
        self.project = requires("project")
        requires("history")

    def test_history_snapshots_every_25(self):
        history = requires("history")
        with temp_data_dir() as data:
            name = uniq("hist")
            pdir = install_project(data, name, doc=sunday_doc())
            doc, _ = self.project.load_doc(name)
            rev = doc["revision"]
            revs = []
            for i in range(27):
                res = self.project.apply_changes(pdir, [{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "n%d" % i}}],
                                                 base_revision=rev, author="t1", summary="edit %d" % i)
                self.assertEqual(res["rebased"], False)
                if revs:
                    self.assertEqual(res["revision"], rev + 1, fr("FR-HIST-01", "4.10", "each write creates N+1"))
                rev = res["revision"]
                revs.append(rev)
            self.assertEqual(revs, list(range(revs[0], revs[0] + 27)), fr("FR-HIST-01", "4.10", "one revision per write"))
            hdir = pdir / "history"
            self.assertTrue((hdir / "snap" / "000001.json").exists(), fr("FR-HIST-08", "4.10", "snapshot at revision 1"))
            for r in range(2, rev + 1):
                snap = (hdir / "snap" / ("%06d.json" % r)).exists()
                self.assertEqual(snap, r % 25 == 0, fr("FR-HIST-08", "4.10", "snapshot iff rev %% 25 == 0 (rev %d)" % r))
            for r in revs:
                self.assertTrue((hdir / "ops" / ("%06d.json" % r)).exists(), fr("FR-HIST-08", "4.10", "ops file for rev %d" % r))
            lines = [json.loads(x) for x in (hdir / "index.jsonl").read_text().strip().splitlines()]
            self.assertEqual([x["revision"] for x in lines], list(range(1, rev + 1)), "4.10 index has one line per revision")
            for x in lines:
                for k in ("revision", "time", "author", "summary", "source", "touched", "ops", "snapshot"):
                    self.assertIn(k, x, "4.10 index line field %s" % k)
                self.assertTrue(x["time"].endswith("Z"))
            self.assertEqual(lines[-1]["touched"], ["devices/atem-mini"])
            self.assertEqual(lines[-1]["source"], "changes")
            self.assertTrue(lines[24]["snapshot"])
            mid = history.get_revision_doc(pdir, 10)
            self.assertEqual([d for d in mid["devices"] if d["id"] == "atem-mini"][0]["note"], "n%d" % (10 - revs[0]), "4.10 snapshot + replay")
            self.assertEqual(history.touched_since(pdir, rev - 1), {"devices/atem-mini"})
            self.assertEqual(history.touched_since(pdir, rev), set())
            listed = history.list_revisions(pdir, limit=5)
            self.assertEqual([x["revision"] for x in listed], list(range(rev, rev - 5, -1)), "newest first")
            with self.assertRaises(KeyError):
                history.get_revision_doc(pdir, rev + 50)

    def test_save_doc_rejects_errors_and_returns_shape(self):
        with temp_data_dir() as data:
            name = uniq("val")
            pdir = install_project(data, name, doc=sunday_doc())
            doc, _ = self.project.load_doc(name)
            bad = copy.deepcopy(doc)
            bad["devices"].append(copy.deepcopy(bad["devices"][0]))
            with self.assertRaises(self.project.ValidationError) as cm:
                self.project.save_doc(bad, pdir, base_revision=doc["revision"], author="t1")
            self.assertIn("duplicate_id", [p["code"] for p in cm.exception.problems])
            good = copy.deepcopy(doc)
            good["devices"][0]["note"] = "ok"
            res = self.project.save_doc(good, pdir, base_revision=doc["revision"], author="t1")
            for k in ("revision", "rebased", "problems", "touched"):
                self.assertIn(k, res, "7.4.1 save_doc result")
            with self.assertRaises(self.project.ConflictError):
                self.project.save_doc(good, pdir, base_revision=res["revision"] + 5, author="t1")
            stored = read_json(pdir / "project.json")
            self.assertEqual(stored["revision"], res["revision"])
            self.assertFalse(list(pdir.glob("*.tmp")), "atomic replace leaves no tmp files")

    def test_new_project_writes_v2(self):
        with temp_data_dir():
            name = uniq("np")
            pdir = self.project.new_project(name, template="blank", org="Hillside")
            d = read_json(Path(pdir) / "project.json")
            self.assertEqual(d["fathom"], 2, "4.12 new_project(blank) writes schema.new_doc")
            self.assertEqual(d["venues"][0]["name"], "Hillside")


if __name__ == "__main__":
    unittest.main()
