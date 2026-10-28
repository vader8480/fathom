"""Phase 1 inventory model (SPEC FR-INV-06..08, §4.3.8): ``inventory.condition``,
``inventory.fields`` (custom fields), ``device.container`` and the inventory CSV columns."""

from __future__ import annotations

import csv
import io
import json
import unittest

try:
    from _helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


def _codes(problems, code):
    return [p for p in problems if p.get("code") == code]


class Condition(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.vocab = requires("vocab")

    def test_vocab(self):
        self.assertEqual(self.vocab.CONDITIONS, ("new", "good", "fair", "poor", "broken"), fr("FR-INV-06", "A.5"))
        self.assertEqual(self.vocab.as_dict()["conditions"], list(self.vocab.CONDITIONS))
        self.assertIn("container", self.vocab.KINDS, fr("FR-INV-08", "A.1", "container kind"))
        self.assertEqual(self.vocab.KINDS["container"]["discipline"], "other")
        self.assertEqual(len(self.vocab.KINDS), 35, fr("FR-VOC-01", "A.1"))

    def test_normalize_keeps_known_drops_unknown(self):
        doc = sunday_doc()
        doc["devices"][0]["inventory"] = {"condition": "good"}
        doc["devices"][1]["inventory"] = {"condition": "mint"}
        n = self.schema.normalize(doc)
        self.assertEqual(n["devices"][0]["inventory"]["condition"], "good")
        self.assertNotIn("inventory", n["devices"][1], "unknown condition dropped (and the empty inventory with it)")

    def test_validate_warns_bad_condition(self):
        doc = self.schema.normalize(sunday_doc())
        doc["devices"][0]["inventory"] = {"condition": "mint"}
        probs = _codes(self.schema.validate_doc(doc), "bad_condition")
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0]["level"], "warning")
        self.assertEqual(probs[0]["ref"], "devices/" + doc["devices"][0]["id"])
        doc["devices"][0]["inventory"]["condition"] = "poor"
        self.assertEqual(_codes(self.schema.validate_doc(doc), "bad_condition"), [])

    def test_json_schema(self):
        inv = self.schema.JSON_SCHEMA["properties"]["devices"]["items"]["properties"]["inventory"]["properties"]
        self.assertEqual(inv["condition"]["enum"], list(self.vocab.CONDITIONS))
        self.assertEqual(inv["fields"]["additionalProperties"], {"type": "string"})
        dev = self.schema.JSON_SCHEMA["properties"]["devices"]["items"]["properties"]
        self.assertIn("container", dev)
        self.assertIn("short_code", dev)


class CustomFields(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def norm_fields(self, fields):
        doc = sunday_doc()
        doc["devices"][0]["inventory"] = {"fields": fields}
        n = self.schema.normalize(doc)
        return (n["devices"][0].get("inventory") or {}).get("fields")

    def test_limits(self):
        got = self.norm_fields({" Owner ": "Dana", "": "dropped", "n": 7, "flag": True, "obj": {"a": 1}, "x" * 50: "y" * 600, "none": None})
        self.assertEqual(got["Owner"], "Dana", "keys are trimmed")
        self.assertNotIn("", got, "empty keys dropped")
        self.assertEqual(got["n"], "7", "values stringified")
        self.assertEqual(got["flag"], "true")
        self.assertEqual(got["obj"], json.dumps({"a": 1}))
        self.assertIn("x" * 40, got, "keys cut to 40 chars")
        self.assertEqual(len(got["x" * 40]), 500, "values cut to 500 chars")
        self.assertNotIn("none", got, "null / empty values are dropped like every other empty field")

    def test_max_32_keys(self):
        got = self.norm_fields({"k%02d" % i: str(i) for i in range(40)})
        self.assertEqual(len(got), 32)
        self.assertEqual(sorted(got)[0], "k00")

    def test_empty_dropped(self):
        self.assertIsNone(self.norm_fields({}))
        self.assertIsNone(self.norm_fields({"": "x"}))
        self.assertIsNone(self.norm_fields("not a dict"))


class Containers(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def doc(self):
        doc = self.schema.normalize(sunday_doc())
        doc["devices"].append({"id": "case-1", "name": "Road case 1", "kind": "container", "room": "", "ports": []})
        return doc

    def test_contents_and_ok(self):
        doc = self.doc()
        doc["devices"][0]["container"] = "case-1"
        doc["devices"][1]["container"] = "case-1"
        probs = self.schema.validate_doc(doc)
        for code in ("container_missing", "container_not_container", "container_cycle"):
            self.assertEqual(_codes(probs, code), [], code)
        self.assertEqual(self.schema.container_contents(doc), {"case-1": [doc["devices"][0]["id"], doc["devices"][1]["id"]]})
        self.assertEqual(self.schema.container_contents(sunday_doc()), {})

    def test_missing(self):
        doc = self.doc()
        doc["devices"][0]["container"] = "nope"
        probs = _codes(self.schema.validate_doc(doc), "container_missing")
        self.assertEqual([(p["level"], p["ref"]) for p in probs], [("warning", "devices/" + doc["devices"][0]["id"])])

    def test_not_container(self):
        doc = self.doc()
        doc["devices"][0]["container"] = "sound-board"
        probs = _codes(self.schema.validate_doc(doc), "container_not_container")
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0]["level"], "warning")
        self.assertEqual(_codes(self.schema.validate_doc(doc), "container_missing"), [])

    def test_cycle(self):
        doc = self.doc()
        doc["devices"].append({"id": "case-2", "name": "Road case 2", "kind": "container", "ports": []})
        doc["devices"][-1]["container"] = "case-1"
        doc["devices"][-2]["container"] = "case-2"
        probs = _codes(self.schema.validate_doc(doc), "container_cycle")
        self.assertEqual(sorted(p["ref"] for p in probs), ["devices/case-1", "devices/case-2"])
        self.assertTrue(all(p["level"] == "warning" for p in probs))
        doc["devices"][-1]["container"] = "case-1"  # self-containment
        self.assertTrue(_codes(self.schema.validate_doc(doc), "container_cycle"))

    def test_normalize_keeps_string_drops_blank(self):
        doc = sunday_doc()
        doc["devices"][0]["container"] = " case-1 "
        doc["devices"][1]["container"] = ""
        doc["devices"][2]["container"] = 7
        n = self.schema.normalize(doc)
        self.assertEqual(n["devices"][0]["container"], "case-1")
        self.assertNotIn("container", n["devices"][1])
        self.assertNotIn("container", n["devices"][2])

    def test_container_not_v1_expressible(self):
        doc = self.schema.normalize(sunday_doc())
        base = self.schema.is_v1_expressible(doc)
        doc["devices"][0]["container"] = "sound-board"
        self.assertFalse(self.schema.is_v1_expressible(doc))
        self.assertIsInstance(base, bool)


class InventoryCsv(unittest.TestCase):
    def setUp(self):
        self.bom = requires("bom")
        self.schema = requires("schema")

    def doc(self):
        doc = self.schema.normalize(sunday_doc())
        doc["devices"].append({"id": "case-1", "name": "Road case 1", "kind": "container", "room": "", "ports": []})
        d0, d1 = doc["devices"][0], doc["devices"][1]
        d0["inventory"] = dict(d0.get("inventory") or {}, condition="fair", fields={"Owner": "Dana", "Zone": "FOH"})
        d0["container"] = "case-1"
        d0["short_code"] = "ABCD2345"
        d1["inventory"] = dict(d1.get("inventory") or {}, fields={"Alpha": "1"})
        return doc

    def test_columns_and_values(self):
        s = self.bom.inventory_schedule(self.doc())
        keys = [c["key"] for c in s["columns"]]
        base = list(self.bom.INVENTORY_KEYS)
        self.assertEqual(keys[:len(base)], base, "existing columns keep their place")
        self.assertEqual(keys[len(base) - 3:len(base)], ["condition", "container", "short_code"], fr("FR-INV-06..09", "5.8.2"))
        self.assertEqual(keys[len(base):], ["field:Alpha", "field:Owner", "field:Zone"], "one sorted column per custom key")
        r0 = s["rows"][0]
        self.assertEqual((r0["condition"], r0["container"], r0["short_code"]), ("fair", "Road case 1", "ABCD-2345"))
        self.assertEqual((r0["field:Owner"], r0["field:Zone"], r0["field:Alpha"]), ("Dana", "FOH", ""))
        r1 = s["rows"][1]
        self.assertEqual((r1["condition"], r1["container"], r1["short_code"], r1["field:Alpha"]), ("", "", "", "1"))

    def test_no_custom_fields_no_extra_columns(self):
        s = self.bom.inventory_schedule(self.schema.normalize(sunday_doc()))
        self.assertEqual([c["key"] for c in s["columns"]], list(self.bom.INVENTORY_KEYS))

    def test_csv_route(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            doc = self.doc()
            st, _, b = call(app, "PUT", "/api/v2/projects/proj", {"doc": doc, "base_revision": 1}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            st, h, b = call(app, "GET", "/api/v2/projects/proj/schedules/inventory?format=csv")
            self.assertEqual(st, 200)
            self.assertTrue(h.get("content-type", "").startswith("text/csv"))
            rows = list(csv.reader(io.StringIO(b.decode("utf-8"))))
            head = rows[0]
            for col in ("condition", "container", "short_code", "field:Owner", "field:Zone", "field:Alpha"):
                self.assertIn(col, head, fr("FR-INV-06..09", "5.8.2", col))
            first = dict(zip(head, rows[1]))
            self.assertEqual((first["condition"], first["container"], first["short_code"], first["field:Owner"]), ("fair", "Road case 1", "ABCD-2345", "Dana"))
            st, _, b = call(app, "GET", "/api/v2/projects/proj/schedules/inventory")
            j = jbody(b)
            self.assertIn("field:Owner", [c["key"] for c in j["columns"]])

    def test_meta_conditions(self):
        app = get_app()
        with temp_data_dir():
            st, _, b = call(app, "GET", "/api/v2/meta")
            self.assertEqual(st, 200)
            j = jbody(b)
            self.assertEqual(j["conditions"], ["new", "good", "fair", "poor", "broken"], fr("FR-INV-06", "5.12"))
            self.assertEqual(j["vocab"]["conditions"], j["conditions"])
            self.assertIn("container", j["vocab"]["kinds"])


if __name__ == "__main__":
    unittest.main()
