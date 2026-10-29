"""Rackula layout import (fathom.parsers.rackula) and the mini YAML reader/writer (fathom.parsers.mini_yaml)."""

from __future__ import annotations

import base64
import copy
import io
import json
import math
import unittest
import zipfile
import zlib

try:
    from _helpers import CAMPUS_DIR, fixture_path, read_json, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import CAMPUS_DIR, fixture_path, read_json, temp_data_dir

from fathom import schema
from fathom.parsers import mini_yaml, rackula

FIX = fixture_path("rackula")


def _text(name):
    return (FIX / name).read_text(encoding="utf-8")


def _zip_b64(name):
    return base64.b64encode((FIX / name).read_bytes()).decode("ascii")


# ---------------------------------------------------------------- lz-string encoder
# compressToEncodedURIComponent, written from the lz-string algorithm so the
# tests can make share links the way Rackula does.

_LZ_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"


def lz_compress_uri(text):
    units = [chr(int.from_bytes(text.encode("utf-16-le", "surrogatepass")[i:i + 2], "little"))
             for i in range(0, len(text.encode("utf-16-le", "surrogatepass")), 2)]
    out = []
    state = {"val": 0, "pos": 0}

    def write(value, nbits):
        for _ in range(nbits):
            state["val"] = (state["val"] << 1) | (value & 1)
            if state["pos"] == 5:
                state["pos"] = 0
                out.append(_LZ_KEYS[state["val"]])
                state["val"] = 0
            else:
                state["pos"] += 1
            value >>= 1

    dictionary, to_create = {}, set()
    w, enlarge, dict_size, num_bits = "", 2, 3, 2

    def emit_w():
        nonlocal enlarge, num_bits
        if w in to_create:
            code = ord(w[0])
            if code < 256:
                write(0, num_bits)
                write(code, 8)
            else:
                write(1, num_bits)
                write(code, 16)
            enlarge -= 1
            if enlarge == 0:
                enlarge = 1 << num_bits
                num_bits += 1
            to_create.discard(w)
        else:
            write(dictionary[w], num_bits)
        enlarge -= 1
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1

    for c in units:
        if c not in dictionary:
            dictionary[c] = dict_size
            dict_size += 1
            to_create.add(c)
        wc = w + c
        if wc in dictionary:
            w = wc
        else:
            emit_w()
            dictionary[wc] = dict_size
            dict_size += 1
            w = c
    if w:
        emit_w()
    write(2, num_bits)
    while True:
        state["val"] <<= 1
        if state["pos"] == 5:
            out.append(_LZ_KEYS[state["val"]])
            break
        state["pos"] += 1
    return "".join(out)


_ABBREV = {v: k for k, v in rackula.CATEGORY_ABBREV.items()}


def to_minimal(layout):
    """Rackula's toMinimalLayout for a file-shaped layout (positions in 1/6 U)."""
    racks = layout["racks"]
    short = {r["id"]: str(i) for i, r in enumerate(racks)}
    used = {d["device_type"] for r in racks for d in r["devices"]}
    dt = []
    for t in layout["device_types"]:
        if t["slug"] not in used:
            continue
        m = {"s": t["slug"], "h": t["u_height"]}
        if t.get("manufacturer"):
            m["mf"] = t["manufacturer"]
        if t.get("model"):
            m["m"] = t["model"]
        m["c"] = t["colour"]
        m["x"] = _ABBREV.get(t["category"], "o")
        if t.get("slots"):
            m["sl"] = [{"id": s["id"], "r": s["position"]["row"], "cl": s["position"]["col"]} for s in t["slots"]]
        dt.append(m)
    rs = []
    for r in racks:
        index = {d["id"]: i for i, d in enumerate(r["devices"])}
        ds = []
        for d in r["devices"]:
            child = d.get("container_id") in index and d.get("slot_id") is not None
            md = {"t": d["device_type"], "p": d["position"] if child else d["position"] / 6, "f": d["face"]}
            if d.get("name"):
                md["n"] = d["name"]
            if child:
                md["ci"] = index[d["container_id"]]
                md["si"] = d["slot_id"]
            ds.append(md)
        mr = {"i": short[r["id"]], "n": r["name"], "h": r["height"], "w": 10 if r["width"] == 10 else 19}
        if r["width"] in (21, 23):
            mr["wx"] = r["width"]
        mr["d"] = ds
        rs.append(mr)
    out = {"v": layout["version"], "fv": 2, "n": layout["name"], "rs": rs}
    if layout.get("rack_groups"):
        out["rg"] = [dict({"rs": [short[x] for x in g["rack_ids"]]}, **({"n": g["name"]} if g.get("name") else {}))
                     for g in layout["rack_groups"]]
    out["dt"] = dt
    return out


def _js_json(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------- base


class Base(unittest.TestCase):
    def setUp(self):
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.empty = schema.new_doc()

    def campus(self):
        if not (CAMPUS_DIR / "project.json").exists():
            self.skipTest("campus sample not present")
        return read_json(CAMPUS_DIR / "project.json")

    def preview(self, payload, doc=None):
        return rackula.preview(self.empty if doc is None else doc, payload)

    def assertApplies(self, doc, result):
        new, touched = schema.apply_ops(doc, result["ops"])
        errs = [p for p in schema.validate_doc(new) if p["level"] == "error" and p["ref"] in touched]
        self.assertEqual(errs, [])
        return new

    @staticmethod
    def by_name(result, name):
        return [d for d in result["devices"] if d["name"] == name]

    @staticmethod
    def put(result, coll, eid):
        for op in result["ops"]:
            if op["coll"] == coll and op["id"] == eid:
                return op
        raise AssertionError(f"no op for {coll}/{eid}")


# ---------------------------------------------------------------- mini_yaml


class MiniYamlLoads(unittest.TestCase):
    def test_block_mappings_and_sequences(self):
        text = (
            "# comment\n---\nname: Lab   # trailing\nracks:\n  - id: a\n    devices:\n      - {id: d1, position: 6}\n"
            "      - id: d2\n        tags: [x, 'y z', \"w\"]\n  - id: b\n    devices: []\nempty:\nlist:\n- 1\n- - 2\n  - 3\n...\n"
        )
        self.assertEqual(mini_yaml.loads(text), {
            "name": "Lab",
            "racks": [{"id": "a", "devices": [{"id": "d1", "position": 6}, {"id": "d2", "tags": ["x", "y z", "w"]}]},
                      {"id": "b", "devices": []}],
            "empty": None, "list": [1, [2, 3]],
        })

    def test_scalars(self):
        doc = mini_yaml.loads(
            "a: 1\nb: -2.5\nc: 1e3\nd: 0x1F\ne: true\nf: False\ng: ~\nh: null\ni: .inf\nj: 26.9.2\nk: '10'\n"
            "l: 'it''s'\nm: \"tab\\tnl\\n\\u00e9\\x41\\\"\"\nn: plain text # note\no: 'a#b'\np: http://x/y#z\nq: 10:30\n"
        )
        self.assertEqual(doc["a"], 1)
        self.assertEqual(doc["b"], -2.5)
        self.assertEqual(doc["c"], 1000.0)
        self.assertEqual(doc["d"], 31)
        self.assertIs(doc["e"], True)
        self.assertIs(doc["f"], False)
        self.assertIsNone(doc["g"])
        self.assertIsNone(doc["h"])
        self.assertTrue(math.isinf(doc["i"]))
        self.assertEqual(doc["j"], "26.9.2")
        self.assertEqual(doc["k"], "10")
        self.assertEqual(doc["l"], "it's")
        self.assertEqual(doc["m"], 'tab\tnl\n\u00e9A"')
        self.assertEqual(doc["n"], "plain text")
        self.assertEqual(doc["o"], "a#b")
        self.assertEqual(doc["p"], "http://x/y#z")
        self.assertEqual(doc["q"], "10:30")

    def test_multiline_plain_and_quoted(self):
        doc = mini_yaml.loads("a: one\n  two\n\n  three\nb: \"x\n  y\"\n")
        self.assertEqual(doc, {"a": "one two\nthree", "b": "x y"})

    def test_block_scalars(self):
        doc = mini_yaml.loads(
            "lit: |\n  line 1\n    indented\n  line 2\n\nstrip: |-\n  x\n\nkeep: |+\n  y\n\n"
            "fold: >\n  a\n  b\n\n  c\nfoldstrip: >-\n  p\n  q\nind: |2\n    two\nend: 1\n"
        )
        self.assertEqual(doc["lit"], "line 1\n  indented\nline 2\n")
        self.assertEqual(doc["strip"], "x")
        self.assertEqual(doc["keep"], "y\n\n")
        self.assertEqual(doc["fold"], "a b\nc\n")
        self.assertEqual(doc["foldstrip"], "p q")
        self.assertEqual(doc["ind"], "  two\n")
        self.assertEqual(doc["end"], 1)

    def test_flow_collections(self):
        self.assertEqual(mini_yaml.loads("a: {row: 0, col: 1}\nb: [1, two, 'three', [4]]\nc: {}\nd: [ ]\n"),
                         {"a": {"row": 0, "col": 1}, "b": [1, "two", "three", [4]], "c": {}, "d": []})

    def test_errors_carry_line_numbers(self):
        cases = {
            "a: 1\nb: &x 2\n": "line 2: anchors",
            "a: 1\nb: *x\n": "line 2: aliases",
            "a: !!str 1\n": "line 1: tags",
            "a: 1\na: 2\n": "line 2: duplicate key",
            "a:\n\t- 1\n": "line 2: tabs",
            "a: [1, 2\n": "line 1: unterminated",
            "a: \"open\n": "line 1: unterminated",
            "%YAML 1.2\n---\na: 1\n": "line 1: directives",
            "? a\n: b\n": "line 1: complex keys",
            "a: 1\n---\nb: 2\n": "line 2: multiple documents",
            "a: b: c\n": "line 1:",
            "- a\nb: 1\n": "line 2:",
        }
        for text, msg in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as cm:
                    mini_yaml.loads(text)
                self.assertIn(msg, str(cm.exception))

    def test_empty_document(self):
        self.assertIsNone(mini_yaml.loads(""))
        self.assertIsNone(mini_yaml.loads("# only a comment\n---\n"))

    def test_real_rackula_and_netbox_files(self):
        files = sorted(FIX.glob("*.yaml")) + sorted((FIX / "netbox").glob("*.yaml"))
        self.assertGreaterEqual(len(files), 12)
        for f in files:
            with self.subTest(f=f.name):
                doc = mini_yaml.loads(f.read_text(encoding="utf-8"))
                self.assertIsInstance(doc, dict)
                self.assertEqual(mini_yaml.loads(mini_yaml.dumps(doc)), doc)
        rep = mini_yaml.loads(_text("v26.9.2-representative.rackula.yaml"))
        self.assertEqual(rep["metadata"]["schema_version"], "1.1")
        self.assertEqual(rep["version"], "26.9.2")
        self.assertEqual(rep["racks"][0]["devices"][2]["ports"][1]["signal_type"], "digital-audio-aes3")
        split = mini_yaml.loads(_text("custom-split-with-gap.rackula.yaml"))
        self.assertEqual(split["device_types"][1]["slots"][0]["position"], {"row": 0, "col": 0})
        self.assertEqual(split["device_types"][1]["slot_gaps"], [20, 0])
        pdu = mini_yaml.loads((FIX / "netbox" / "AP7900B.yaml").read_text(encoding="utf-8"))
        self.assertTrue(pdu["comments"].startswith("Rack PDU, Switched, 1U"))
        self.assertEqual(len(pdu["power-outlets"]), 8)


class MiniYamlDumps(unittest.TestCase):
    def test_round_trip_tricky_values(self):
        obj = {
            "plain": "Rack A", "yes": "yes", "no": "No", "num": "26.9.2", "int_str": "10", "time": "10:30", "date": "2024-01-01",
            "empty": "", "space": " lead", "colon": "a: b", "hash": "#x", "dash": "- x", "quote": "it's \"q\"",
            "multi": "line 1\nline 2", "trail": "end\n", "keep": "x\n\n", "unicode": "Café \u2028 \ufeff", "ctrl": "a\x01b",
            "none": None, "t": True, "f": False, "i": -3, "x": 1.5, "inf": float("inf"),
            "list": [1, "two", {"k": "v", "n": [1, 2]}, [], {}], "nested": {"a": {"b": [{"c": None}]}}, "emptylist": [], "emptymap": {},
            "key with space": 1, "true": "key named true",
        }
        text = mini_yaml.dumps(obj)
        self.assertEqual(mini_yaml.loads(text), obj)
        self.assertIn("plain: Rack A\n", text)
        self.assertNotIn("\nyes:", text)
        self.assertNotIn("\nnum: 26.9.2", text)

    def test_block_style(self):
        text = mini_yaml.dumps({"a": [{"id": "x", "num": 1}], "b": {"c": 2}})
        self.assertEqual(text, "a:\n  - id: x\n    num: 1\nb:\n  c: 2\n")

    def test_top_level_list_and_scalar(self):
        self.assertEqual(mini_yaml.loads(mini_yaml.dumps([1, "a"])), [1, "a"])
        self.assertEqual(mini_yaml.loads(mini_yaml.dumps("text")), "text")


# ---------------------------------------------------------------- share links


class ShareLinks(Base):
    def setUp(self):
        super().setUp()
        self.vectors = read_json(FIX / "share-vectors.json")

    def test_encoder_matches_lz_string(self):
        self.assertEqual(lz_compress_uri(_js_json(self.vectors["layout"])), self.vectors["lz"])

    def test_decodes_reference_vectors(self):
        for key in ("lz", "zlib", "gzip"):
            with self.subTest(key=key):
                self.assertEqual(rackula.decode_share(self.vectors[key]), self.vectors["layout"])

    def test_lz_round_trip_unicode(self):
        for s in ("", "a", "aaaaaaaaaaaaaaaaaaaaaaaa", "Café 🎛 — 中文", json.dumps({"k": list(range(200))})):
            with self.subTest(s=s[:20]):
                enc = lz_compress_uri(s)
                self.assertEqual(rackula.lz_decompress_uri(enc), s)

    def test_url_forms(self):
        code = self.vectors["lz"]
        forms = [code, "https://count.racku.la/?l=" + code, "https://app.racku.la/?x=1&l=" + code + "#top",
                 "?l=" + code, "l=" + code, "  " + code + "\n", code.replace("+", " ")]
        for form in forms:
            with self.subTest(form=form[:40]):
                p = rackula.preview(self.empty, {"url": form})
                self.assertEqual([r["name"] for r in p["racks"]], ["Rack A", "Rack B 🎛"])
        p = rackula.preview(self.empty, {"text": "https://count.racku.la/?l=" + code})
        self.assertEqual(p["layout"]["format"], "share")

    def test_share_layout_mapping(self):
        p = rackula.preview(self.empty, {"url": self.vectors["lz"]})
        a, b = p["racks"]
        self.assertEqual((a["id"], a["width_in"], a["units"], a["row"], a["order"]), ("rk-rack-a", 23, 12, "Stage Row", 0))
        self.assertEqual((b["width_in"], b["row"], b["order"]), (10, "Stage Row", 1))
        sw = self.by_name(p, "Core Switch")[0]
        self.assertEqual((sw["u"], sw["kind"], sw["manufacturer"]), (10, "switch", "Ubiquiti"))
        mini = self.by_name(p, "Mini PC")[0]
        self.assertEqual((mini["shelf"], mini["slot"], mini["u"]), ("ri-1", 1, 3))
        self.assertEqual([(i["type"], i["u"]) for i in p["items"]], [("shelf", 3), ("blank", 12)])
        self.assertEqual(self.by_name(p, "ATEM 2 M/E Production Studio")[0]["kind"], "video_switcher")
        self.assertApplies(self.empty, p)

    def test_layout_encoded_in_test_matches_file_import(self):
        layout = rackula.read_layout({"text": _text("hand-edge-cases.rackula.yaml")})
        raw = mini_yaml.loads(_text("hand-edge-cases.rackula.yaml"))
        raw["racks"] = [r for r in raw["racks"]]
        for r in raw["racks"]:
            r["devices"] = [d for d in r["devices"] if d["device_type"] in {t["slug"] for t in raw["device_types"]}
                            and d.get("container_id") in (None, "s-shelf")]
        minimal = to_minimal(raw)
        url = "https://count.racku.la/?l=" + lz_compress_uri(_js_json(minimal))
        self.assertEqual(rackula.decode_share(url), minimal)
        via_share = rackula.preview(self.empty, {"url": url})
        raw_text = mini_yaml.dumps(raw)
        via_file = rackula.preview(self.empty, {"text": raw_text})
        keep = ("id", "name", "kind", "manufacturer", "model", "rack", "u", "height", "shelf", "slot")
        self.assertEqual([{k: d[k] for k in keep} for d in via_share["devices"]],
                         [{k: d[k] for k in keep} for d in via_file["devices"]])
        self.assertEqual([(r["name"], r["units"], r["width_in"]) for r in via_share["racks"]],
                         [(r["name"], r["units"], r["width_in"]) for r in via_file["racks"]])
        self.assertEqual([r["row"] for r in via_share["racks"]], ["Group 2", "Stage"])
        self.assertEqual([i["type"] for i in via_share["items"]], [i["type"] for i in via_file["items"]])
        self.assertEqual(len(layout["racks"]), 2)
        self.assertApplies(self.empty, via_share)

    def test_legacy_pako_link(self):
        minimal = {"v": "0.6.0", "n": "Old link", "r": {"n": "Rack", "h": 6, "w": 19, "d": [{"t": "sw", "p": 2, "f": "rear"}]},
                   "dt": [{"s": "sw", "h": 1, "m": "Switch", "c": "#7B6BA8", "x": "n"}]}
        raw = zlib.compress(json.dumps(minimal).encode())
        code = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        p = rackula.preview(self.empty, {"url": "https://count.racku.la/?l=" + code})
        self.assertEqual([(d["name"], d["u"], d["face"]) for d in p["devices"]], [("Switch", 2, "rear")])

    def test_bad_links(self):
        for bad in ("https://count.racku.la/", "https://count.racku.la/?x=1", "!!!!", "?l=", "A" * 40):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    rackula.preview(self.empty, {"url": bad})
        with self.assertRaises(ValueError) as cm:
            rackula.decode_share("A" * (rackula.MAX_ENCODED + 1))
        self.assertIn("too large", str(cm.exception))
        bomb = base64.urlsafe_b64encode(zlib.compress(b" " * (rackula.MAX_DECOMPRESSED + 10))).decode().rstrip("=")
        with self.assertRaises(ValueError) as cm:
            rackula.decode_share(bomb)
        self.assertIn("size limit", str(cm.exception))
        not_layout = lz_compress_uri(json.dumps({"hello": 1}))
        with self.assertRaises(ValueError):
            rackula.preview(self.empty, {"url": not_layout})


# ---------------------------------------------------------------- file mapping


class RackulaFiles(Base):
    def test_representative_layout(self):
        p = self.preview({"text": _text("v26.9.2-representative.rackula.yaml")})
        self.assertEqual(p["layout"], {"name": "Representative Lab", "version": "26.9.2", "format": "yaml"})
        self.assertEqual([(r["id"], r["row"], r["order"], r["source"]) for r in p["racks"]],
                         [("rk-rack-a", "Bayed Pair", 0, "rack-a"), ("rk-rack-b", "Bayed Pair", 1, "rack-b")])
        rack = self.put(p, "racks", "rk-rack-a")["value"]
        self.assertEqual({k: rack[k] for k in ("units", "numbering", "start_u", "width_in", "form_factor", "depth_mm")},
                         {"units": 12, "numbering": "bottom_up", "start_u": 1, "width_in": 19, "form_factor": "cabinet", "depth_mm": 1000})
        self.assertNotIn("weight_kg", rack)
        self.assertEqual(rack["items"], [{"id": "ri-1", "type": "shelf", "u": 1, "height": 4, "face": "front", "depth": "full",
                                          "label": "Blade Chassis 4U", "slots": 2}])
        blade = self.put(p, "devices", "blade-server")["value"]
        self.assertEqual(blade["rack"], {"id": "rk-rack-a", "u": 1, "height": 1, "face": "front", "side": "full", "shelf": "ri-1", "slot": 0})
        self.assertEqual(blade["kind"], "computer")
        audio = self.put(p, "devices", "interface-1u")["value"]
        self.assertEqual(audio["kind"], "video")
        self.assertEqual(audio["rack"]["u"], 5)
        self.assertEqual([(x["name"], x["dir"], x["medium"], x["connector"]) for x in audio["ports"]],
                         [("Mic In", "in", "analog", "XLR3F"), ("AES Out", "out", "aes3", "XLR3M")])
        self.assertEqual(self.put(p, "devices", "switch-24p")["value"]["kind"], "switch")
        self.assertEqual(self.put(p, "devices", "router-1u")["value"]["kind"], "network")
        self.assertEqual(p["warnings"], [])
        self.assertApplies(self.empty, p)

    def test_legacy_positions(self):
        for name in ("legacy-layout-v0.6.yaml", "v0.6.0-single-rack.rackula.yaml"):
            with self.subTest(name=name):
                p = self.preview({"text": _text(name)})
                self.assertTrue(any("whole-U positions" in w for w in p["warnings"]))
                self.assertApplies(self.empty, p)
        p = self.preview({"text": _text("legacy-layout-v0.6.yaml")})
        self.assertEqual([(d["model"], d["u"], d["height"]) for d in p["devices"]], [("", 10, 2), ("", 1, 1)])
        self.assertEqual([d["id"] for d in p["devices"]], ["test-server", "test-switch"])

    def test_legacy_zip_and_rack_field(self):
        p = self.preview({"zip_b64": _zip_b64("carlton-5123home.Rackula.zip")})
        self.assertEqual(p["layout"]["format"], "zip")
        self.assertEqual([r["id"] for r in p["racks"]], ["rk-5123home"])
        unraid = self.by_name(p, "UnRaid Server")[0]
        self.assertEqual((unraid["u"], unraid["height"]), (2, 4))
        self.assertEqual(self.put(p, "devices", unraid["id"])["value"]["rack"]["depth"], "full")
        pdu = self.by_name(p, "USP-PDU-Pro")[0]
        self.assertEqual((pdu["u"], pdu["face"], pdu["kind"]), (18, "rear", "power"))
        self.assertEqual(self.put(p, "devices", pdu["id"])["value"]["rack"]["depth"], "half")
        self.assertEqual([(i["type"], i["u"], i["label"]) for i in p["items"]], [("brush", 27, "Brush Panel 1U")])
        self.assertEqual(self.by_name(p, "UDM-Pro")[0]["kind"], "network")
        self.assertEqual(self.by_name(p, "24-Port Blank Keystone Patch Panel")[0]["kind"], "patch_panel")
        self.assertEqual(len(self.by_name(p, "24-Port Blank Keystone Patch Panel")), 2)
        self.assertApplies(self.empty, p)
        p = self.preview({"zip_b64": "data:application/zip;base64," + _zip_b64("legacy-test-layout.Rackula.zip")})
        self.assertEqual([d["u"] for d in p["devices"]], [10, 1])

    def test_carrier_children(self):
        p = self.preview({"text": _text("custom-split-with-gap.rackula.yaml")})
        self.assertEqual([(i["type"], i["u"], i["slots"], i["depth"]) for i in p["items"]], [("shelf", 5, 3, "full")])
        self.assertEqual([(d["name"], d["shelf"], d["slot"]) for d in p["devices"]],
                         [("Mini 100", "ri-1", 0), ("Mini 100", "ri-1", 1), ("Mini 100", "ri-1", 2)])
        self.assertEqual([d["id"] for d in p["devices"]], ["mini-100", "mini-100-2", "mini-100-3"])
        self.assertApplies(self.empty, p)

    def test_pre_carrier_half_width(self):
        p = self.preview({"text": _text("pre-carrier-slot-position.rackula.yaml")})
        sides = {self.put(p, "devices", d["id"])["value"]["rack"]["side"] for d in p["devices"] if d["u"] == 40}
        self.assertEqual(sides, {"left", "right"})
        self.assertFalse(any("overlap" in w for w in p["warnings"]))
        self.assertApplies(self.empty, p)

    def test_over_rack_position_is_clamped(self):
        p = self.preview({"text": _text("over-rack-rail-position.rackula.yaml")})
        self.assertEqual(p["devices"][0]["u"], 10)
        self.assertTrue(any("moved to U10" in w for w in p["warnings"]))

    def test_newer_schema_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.preview({"text": _text("schema-version-future-3.0.rackula.yaml")})
        self.assertIn("newer Rackula", str(cm.exception))
        with self.assertRaises(ValueError):
            self.preview({"text": "metadata: {schema_version: '2.O'}\nname: x\nracks: []\ndevice_types: []\n"})

    def test_signal_types_refine_media(self):
        p = self.preview({"text": _text("v26.7.0-signal-type.rackula.yaml")})
        ports = self.put(p, "devices", p["devices"][0]["id"])["value"]["ports"]
        self.assertTrue(ports)
        raw = mini_yaml.loads(_text("v26.7.0-signal-type.rackula.yaml"))
        from fathom.parsers.netbox_devicetype import SIGNAL_MEDIUM
        wanted = [SIGNAL_MEDIUM[i["signal_type"]] for i in raw["device_types"][0]["interfaces"] if i.get("signal_type") in SIGNAL_MEDIUM]
        self.assertTrue(set(wanted) <= {x["medium"] for x in ports})

    def test_static_template(self):
        p = self.preview({"text": _text("media-server.rackula.yaml")})
        self.assertEqual(len(p["racks"]), 1)
        self.assertGreaterEqual(len(p["devices"]), 5)
        self.assertApplies(self.empty, p)


class EdgeCases(Base):
    def setUp(self):
        super().setUp()
        self.p = self.preview({"text": _text("hand-edge-cases.rackula.yaml")})

    def rack(self, rid):
        return self.put(self.p, "racks", rid)["value"]

    def dev(self, did):
        return self.put(self.p, "devices", did)["value"]

    def test_racks(self):
        foh, sl = self.rack("rk-foh-rack"), self.rack("rk-stage-left")
        self.assertEqual((foh["form_factor"], foh["row"], foh["order"]), ("wall_mount", "g2", 0))
        self.assertEqual({k: sl[k] for k in ("units", "numbering", "start_u", "width_in", "form_factor", "depth_mm", "weight_kg", "notes", "order", "row")},
                         {"units": 60, "numbering": "top_down", "start_u": 0, "width_in": 21, "form_factor": "two_post", "depth_mm": 600,
                          "weight_kg": 12.5, "notes": "Left of stage", "order": 1, "row": "Stage"})
        self.assertIn("Stage Left: 64U is taller than Fathom's 60U limit; clamped to 60U", self.p["warnings"])

    def test_items(self):
        items = {i["id"]: i for i in self.rack("rk-stage-left")["items"]}
        self.assertEqual(items["ri-1"], {"id": "ri-1", "type": "shelf", "u": 10, "height": 1, "face": "front", "depth": "full",
                                         "label": "Six-up shelf", "color": "#aabbcc", "slots": 4})
        self.assertEqual((items["ri-2"]["type"], items["ri-2"]["depth"]), ("vent", "half"))
        self.assertEqual((items["ri-3"]["type"], items["ri-3"]["face"]), ("lacing_bar", "rear"))
        self.assertEqual((items["ri-4"]["type"], items["ri-4"]["height"], items["ri-4"]["weight_kg"]), ("drawer", 2, 9.98))
        self.assertIn("Stage Left: Six-up shelf has 6 cells; Fathom shelves hold 4", self.p["warnings"])
        self.assertEqual(len(self.p["items"]), 4)

    def test_shelf_children(self):
        self.assertEqual(self.dev("box-a")["rack"], {"id": "rk-stage-left", "u": 10, "height": 1, "face": "front", "side": "full",
                                                     "shelf": "ri-1", "slot": 0})
        self.assertEqual(self.dev("box-b1")["rack"]["slot"], 1)
        self.assertEqual(self.dev("box-b2")["rack"]["slot"], 1)
        self.assertNotIn("rack", self.dev("box-f"))
        self.assertNotIn("rack", self.dev("lost-box"))
        w = self.p["warnings"]
        self.assertIn("Stage Left: Box F is in cell 6 of Six-up shelf, past its 4 slots; left unracked", w)
        self.assertIn("Stage Left: Box B2 and Box B1 share cell 2 of Six-up shelf", w)
        self.assertIn("Stage Left: Lost Box sits in a container that is missing; left unracked", w)

    def test_devices(self):
        router = self.dev("edge-router-x")
        self.assertEqual((router["kind"], router["rack"]["u"]), ("network", 11))
        self.assertEqual([(x["id"], x["medium"], x["connector"]) for x in router["ports"]],
                         [("wan0", "network", "RJ45"), ("lan-1", "network", "RJ45"), ("lan-2", "network", "RJ45"), ("sfp1", "fiber", "SFP+")])
        self.assertEqual([self.dev(i)["rack"]["face"] for i in ("switch", "switch-2")], ["front", "rear"])
        self.assertEqual(self.dev("switch")["rack"]["depth"], "half")
        self.assertEqual(self.dev("mini-server")["rack"], {"id": "rk-foh-rack", "u": 1, "height": 1, "face": "front", "depth": "full", "side": "full"})
        amp = self.dev("amp-one")
        self.assertEqual((amp["kind"], amp["weight_kg"], amp["power_w"], amp["note"]), ("amp", 4.54, 120.0, "Feeds the\nside fills"))
        self.assertEqual([(x["group"], x["dir"], x["medium"], x["connector"]) for x in amp["ports"]][3:],
                         [("Input", "in", "analog", "XLR3F"), ("Out A", "out", "speaker", "NL4"), ("Dante", "io", "dante", "RJ45"),
                          ("PSU", "in", "power", "IEC C14")])
        console = self.dev("foh-cl5")
        self.assertEqual(console["rack"], {"id": "rk-stage-left", "u": 12, "height": 2, "face": "front", "depth": "full", "side": "full", "color": "#123456"})
        self.assertEqual(self.dev("high-console")["rack"]["u"], 59)
        self.assertIn("Stage Left: High Console at U66 runs past the top of the rack; moved to U59", self.p["warnings"])
        self.assertEqual(self.dev("half-box")["rack"]["side"], "left")
        self.assertEqual((self.dev("ghost")["kind"], self.dev("ghost")["model"]), ("other", "ghost-box"))
        self.assertIn("device type 'ghost-box' is not in the layout", self.p["warnings"])

    def test_collisions_are_warnings(self):
        self.assertIn("Stage Left: Amp One and Amp Two overlap at U6 (front and rear)", self.p["warnings"])
        self.assertFalse(any("Vent Panel" in w and "overlap" in w for w in self.p["warnings"]))
        self.assertApplies(self.empty, self.p)

    def test_preview_shape(self):
        self.assertEqual(set(self.p), {"layout", "racks", "devices", "items", "warnings", "ops"})
        self.assertEqual(set(self.p["devices"][0]), {"id", "name", "kind", "manufacturer", "model", "template", "rack", "u", "height",
                                                     "face", "shelf", "slot", "new"})
        self.assertTrue(all(op["op"] == "put" for op in self.p["ops"]))
        self.assertEqual([op["coll"] for op in self.p["ops"]][:2], ["racks", "racks"])
        self.assertTrue(all(d["new"] for d in self.p["devices"]))

    def test_json_legacy_layout(self):
        p = self.preview({"text": _text("hand-edge-cases.json")})
        self.assertEqual(p["layout"]["format"], "json")
        self.assertEqual([(d["name"], d["kind"], d["u"]) for d in p["devices"]],
                         [("Patch Panel 24", "patch_panel", 2), ("ATEM Mini Extreme", "video_switcher", 3)])
        self.assertEqual([(i["type"], i["u"]) for i in p["items"]], [("blank", 10)])
        rack = self.put(p, "racks", "rk-old-rack")["value"]
        self.assertEqual((rack["width_in"], rack["form_factor"]), (10, "open_frame"))
        self.assertApplies(self.empty, p)


class IntoExistingDoc(Base):
    def test_campus_reuse_ids_and_order(self):
        doc = self.campus()
        p = self.preview({"text": _text("hand-edge-cases.rackula.yaml")}, doc)
        cl5 = self.by_name(p, "FOH CL5")[0]
        self.assertFalse(cl5["new"])
        self.assertEqual(cl5["id"], "foh-cl5")
        op = self.put(p, "devices", "foh-cl5")
        self.assertEqual(op["op"], "merge")
        self.assertEqual(set(op["value"]), {"rack"})
        self.assertEqual([r["order"] for r in p["racks"]], [4, 5])
        self.assertIn("a rack named 'FOH Rack' already exists; the import adds another", p["warnings"])
        new = self.assertApplies(doc, p)
        moved = [d for d in new["devices"] if d["id"] == "foh-cl5"][0]
        self.assertEqual(moved["rack"]["id"], "rk-stage-left")
        self.assertEqual(moved["template"], "yamaha-cl5")

        again = self.preview({"text": _text("hand-edge-cases.rackula.yaml")}, new)
        self.assertEqual([r["id"] for r in again["racks"]], ["rk-foh-rack-2", "rk-stage-left-2"])
        self.assertEqual(sorted(d["name"] for d in again["devices"] if not d["new"]), ["Box F", "Lost Box"])
        self.assertEqual(self.by_name(again, "FOH CL5")[0]["id"], "foh-cl5-2")
        self.assertApplies(new, again)

    def test_room(self):
        doc = self.campus()
        p = self.preview({"text": _text("legacy-layout-v0.6.yaml"), "room": "chapel"}, doc)
        self.assertEqual(self.put(p, "racks", p["racks"][0]["id"])["value"]["room"], "chapel")
        self.assertEqual({self.put(p, "devices", d["id"])["value"]["room"] for d in p["devices"]}, {"chapel"})
        p = self.preview({"text": _text("legacy-layout-v0.6.yaml"), "room": "nowhere"}, doc)
        self.assertEqual(self.put(p, "racks", p["racks"][0]["id"])["value"]["room"], schema.default_room_id(doc))

    def test_library_template_match(self):
        layout = (
            "version: 26.9.2\nname: T\nracks:\n  - id: r\n    name: R\n    height: 10\n    width: 19\n    position: 0\n"
            "    devices:\n      - {id: a, device_type: yamaha-cl5, position: 6, face: front}\n"
            "device_types:\n  - {slug: yamaha-cl5, manufacturer: Yamaha, model: CL5, u_height: 1, colour: '#000000', category: av-media}\n"
        )
        p = self.preview({"text": layout})
        dev = self.put(p, "devices", p["devices"][0]["id"])["value"]
        from fathom.library import get_template
        tpl = get_template("yamaha-cl5")
        if tpl is None:
            self.skipTest("built-in yamaha-cl5 template not present")
        self.assertEqual((dev["template"], dev["kind"]), ("yamaha-cl5", tpl["kind"]))
        self.assertTrue(dev["ports"])
        self.assertEqual({x["origin"] for x in dev["ports"]}, {"template"})
        self.assertApplies(self.empty, p)

    def test_racked_devices_are_not_reused(self):
        doc = self.campus()
        racked = [d for d in doc["devices"] if isinstance(d.get("rack"), dict) and d["rack"].get("id")][0]
        layout = (
            "version: 26.9.2\nname: T\nracks:\n  - id: r\n    name: R\n    height: 10\n    width: 19\n    position: 0\n"
            f"    devices:\n      - {{id: a, device_type: x, position: 6, face: front, name: {json.dumps(racked['name'])}}}\n"
            "device_types:\n  - {slug: x, model: X, u_height: 1, colour: '#000000', category: other}\n"
        )
        p = self.preview({"text": layout}, doc)
        self.assertTrue(p["devices"][0]["new"])
        self.assertNotEqual(p["devices"][0]["id"], racked["id"])


class Payloads(Base):
    def test_unreadable_input(self):
        cases = [
            {}, {"text": ""}, {"text": "   "}, {"text": "a: [1"}, {"text": "{not json"}, {"text": "[1, 2]"}, {"text": "a: 1\n"},
            {"text": "racks: []\ndevice_types: []\n"}, {"zip_b64": "%%%"}, {"zip_b64": base64.b64encode(b"not a zip").decode()},
            {"url": 5}, {"text": "name: x\nracks:\n  - {id: r, name: R, height: 4, devices: []}\ndevice_types: 3\n"},
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:60]):
                with self.assertRaises(ValueError):
                    self.preview(payload)
        with self.assertRaises(ValueError):
            rackula.preview(self.empty, "text")

    def _zip(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        return base64.b64encode(buf.getvalue()).decode()

    def test_zip_variants(self):
        yaml_text = _text("legacy-layout-v0.6.yaml")
        p = self.preview({"zip_b64": self._zip({"Lab/assets/x/a.yaml": "junk: [", "Lab/Lab.yaml": yaml_text, "__MACOSX/Lab/._Lab.yaml": "x"})})
        self.assertEqual(len(p["devices"]), 2)
        p = self.preview({"zip_b64": self._zip({"layout.json": _text("hand-edge-cases.json")})})
        self.assertEqual(p["layout"]["format"], "zip")
        p = self.preview({"zip_b64": self._zip({"A-1/a.rackula.yaml": yaml_text, "B-2/b.rackula.yaml": yaml_text})})
        self.assertIn("the archive holds 2 layouts; imported A-1/a.rackula.yaml", p["warnings"])
        with self.assertRaises(ValueError) as cm:
            self.preview({"zip_b64": self._zip({"Lab/assets/img.png": b"\x89PNG"})})
        self.assertIn("no layout YAML", str(cm.exception))

    def test_text_accepts_bytes_and_bom(self):
        p = self.preview({"text": ("\ufeff" + _text("legacy-layout-v0.6.yaml")).encode("utf-8")})
        self.assertEqual(len(p["devices"]), 2)

    def test_minimal_json_as_text(self):
        vectors = read_json(FIX / "share-vectors.json")
        p = self.preview({"text": json.dumps(vectors["layout"])})
        self.assertEqual(p["layout"]["format"], "share")
        self.assertEqual(len(p["racks"]), 2)

    def test_does_not_mutate_doc(self):
        doc = self.campus()
        before = copy.deepcopy(doc)
        self.preview({"text": _text("hand-edge-cases.rackula.yaml")}, doc)
        self.assertEqual(doc, before)


if __name__ == "__main__":
    unittest.main()
