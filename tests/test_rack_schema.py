"""Rackula schema additions (contract section B; SPEC §4.3.7, §4.3.8, §4.7):
rack width / form factor / start U / load / row / accessory items, device weight and
power, and shelf / slot / colour / image placement fields."""

from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

try:
    from _helpers import CAMPUS_DIR, RRC_DIR, read_json, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover - run as a package
    from tests._helpers import CAMPUS_DIR, RRC_DIR, read_json, sunday_doc, temp_data_dir

from fathom import schema as s

#: validate_doc output for the samples before the rack additions (level, code, ref, path)
BASE_SAMPLE_PROBLEMS = {
    "campus-demo": [
        ("warning", "medium_mismatch", "cables/c-0042", "cables/c-0042"),
        ("warning", "medium_mismatch", "cables/c-0047", "cables/c-0047"),
        ("warning", "medium_mismatch", "cables/c-0105", "cables/c-0105"),
        ("warning", "port_overuse", "cables/c-0036", "cables/c-0036/to"),
    ],
    "rrc-littleton": [],
}
NEW_RACK_KEYS = ("width_in", "form_factor", "start_u", "weight_kg", "max_load_kg", "power_limit_w", "row", "items")
NEW_PLACEMENT_KEYS = ("shelf", "slot", "color", "image_front", "image_rear")


def keyed(problems):
    return sorted((p["level"], p["code"], p["ref"], p["path"]) for p in problems)


def campus():
    return s.load_any(read_json(CAMPUS_DIR / "project.json"))


def full_rack():
    """A rack using every new field; nothing overlaps and the load stays under the limits."""
    return {
        "id": "rk-new", "name": "New rack", "room": "main", "units": 12, "numbering": "bottom_up", "faces": ["front", "rear"],
        "depth_mm": 600, "order": 9, "notes": "test", "width_in": 19, "form_factor": "four_post", "start_u": 0,
        "weight_kg": 40.5, "max_load_kg": 500, "power_limit_w": 1800, "row": "Row A",
        "items": [
            {"id": "ri-1", "type": "shelf", "u": 1, "height": 1, "face": "front", "depth": "full", "label": "Shelf",
             "color": "#6272a4", "slots": 2, "weight_kg": 2.0, "notes": "cantilever"},
            {"id": "ri-2", "type": "blank", "u": 2},
            {"id": "ri-3", "type": "vent", "u": 3, "face": "front", "depth": "half"},
            {"id": "ri-4", "type": "drawer", "u": 4, "height": 2, "weight_kg": 0},
            {"id": "ri-5", "type": "cable_manager", "u": 6},
            {"id": "ri-6", "type": "brush", "u": 7},
            {"id": "ri-7", "type": "lacing_bar", "u": 8, "face": "rear", "depth": "half"},
            {"id": "ri-8", "type": "other", "u": 9, "label": "Fan tray", "color": "#44475a"},
        ],
    }


def full_doc():
    doc = campus()
    doc["racks"].append(full_rack())
    doc["devices"].append({
        "id": "shelf-mac", "name": "Shelf Mac", "kind": "computer", "room": "main", "ports": [], "weight_kg": 1.2, "power_w": 30,
        "rack": {"id": "rk-new", "u": 1, "height": 1, "face": "front", "side": "full", "shelf": "ri-1", "slot": 0},
    })
    doc["devices"].append({
        "id": "new-amp", "name": "New amp", "kind": "amp", "room": "main", "ports": [], "weight_kg": 12, "power_w": 600.5,
        "rack": {"id": "rk-new", "u": 10, "height": 2, "face": "front", "side": "full", "depth": "full", "slot": 0,
                 "color": "#4a7a8a", "image_front": "att-front", "image_rear": "att-rear"},
    })
    return doc


def rack_of(doc, rid="rk-new"):
    return next(r for r in doc["racks"] if r["id"] == rid)


def device_of(doc, did):
    return next(d for d in doc["devices"] if d["id"] == did)


def schema_validate(node, value, path="$", errs=None):
    """The JSON Schema subset JSON_SCHEMA uses (type, enum, required, properties, items, minimum, maximum)."""
    errs = [] if errs is None else errs
    t = node.get("type")
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "null": lambda v: v is None}
    if t and not any(checks[x](value) for x in (t if isinstance(t, list) else [t])):
        errs.append(f"{path}: type")
        return errs
    if "enum" in node and value not in node["enum"]:
        errs.append(f"{path}: enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errs.append(f"{path}: minimum")
        if "maximum" in node and value > node["maximum"]:
            errs.append(f"{path}: maximum")
    if isinstance(value, dict):
        errs.extend(f"{path}: required {k}" for k in node.get("required", []) if k not in value)
        for k, sub in node.get("properties", {}).items():
            if k in value:
                schema_validate(sub, value[k], f"{path}.{k}", errs)
    if isinstance(value, list) and isinstance(node.get("items"), dict):
        for i, item in enumerate(value):
            schema_validate(node["items"], item, f"{path}[{i}]", errs)
    return errs


class ValidDocs(unittest.TestCase):
    def test_every_new_field_gives_no_new_problem(self):
        self.assertEqual(keyed(s.validate_doc(full_doc())), keyed(s.validate_doc(campus())))

    def test_float_weights_and_float_width(self):
        doc = full_doc()
        rack_of(doc)["width_in"] = 19.0
        rack_of(doc)["max_load_kg"] = 0.0
        rack_of(doc)["weight_kg"] = 0
        device_of(doc, "new-amp")["weight_kg"] = 0.0
        self.assertEqual(s.errors(s.validate_doc(doc)), [])

    def test_each_width_and_form_factor(self):
        for w in s.RACK_WIDTHS:
            for ff in s.RACK_FORM_FACTORS:
                doc = full_doc()
                rack_of(doc).update(width_in=w, form_factor=ff)
                self.assertEqual(s.errors(s.validate_doc(doc)), [], (w, ff))

    def test_each_item_type(self):
        self.assertEqual(s.RACK_ITEM_TYPES, ("blank", "vent", "shelf", "drawer", "cable_manager", "brush", "lacing_bar", "other"))
        doc = full_doc()
        rack_of(doc)["items"] = [{"id": f"ri-{i}", "type": t, "u": 1} for i, t in enumerate(s.RACK_ITEM_TYPES)]
        self.assertEqual(s.errors(s.validate_doc(doc)), [])

    def test_nulls_count_as_unset(self):
        doc = full_doc()
        rack_of(doc).update({k: None for k in NEW_RACK_KEYS})
        device_of(doc, "new-amp").update(weight_kg=None, power_w=None)
        device_of(doc, "new-amp")["rack"].update({k: None for k in NEW_PLACEMENT_KEYS})
        self.assertEqual(s.errors(s.validate_doc(doc)), [])

    def test_empty_items(self):
        doc = full_doc()
        rack_of(doc)["items"] = []
        self.assertEqual(s.errors(s.validate_doc(doc)), [])

    def test_json_schema(self):
        js = s.JSON_SCHEMA
        self.assertEqual(schema_validate(js, full_doc()), [])
        self.assertEqual(schema_validate(js, campus()), [])
        self.assertEqual(schema_validate(js, sunday_doc()), [])
        json.dumps(js)
        rack = js["properties"]["racks"]["items"]["properties"]
        for k in NEW_RACK_KEYS:
            self.assertIn(k, rack)
        item = rack["items"]["items"]
        self.assertEqual(item["required"], ["id", "type", "u"])
        self.assertEqual(item["properties"]["type"]["enum"], list(s.RACK_ITEM_TYPES))
        dev = js["properties"]["devices"]["items"]["properties"]
        self.assertIn("weight_kg", dev)
        self.assertIn("power_w", dev)
        for k in NEW_PLACEMENT_KEYS:
            self.assertIn(k, dev["rack"]["properties"])

    def test_json_schema_rejects(self):
        js = s.JSON_SCHEMA
        cases = [
            (lambda d: rack_of(d).update(width_in=20), "width_in: enum"),
            (lambda d: rack_of(d).update(form_factor="tower"), "form_factor: enum"),
            (lambda d: rack_of(d).update(start_u=-1), "start_u: minimum"),
            (lambda d: rack_of(d).update(items={}), "items: type"),
            (lambda d: rack_of(d)["items"][0].pop("u"), "required u"),
            (lambda d: rack_of(d)["items"][0].update(slots=5), "slots: maximum"),
            (lambda d: rack_of(d)["items"][0].update(type="tray"), "type: enum"),
            (lambda d: device_of(d, "new-amp").update(power_w=-5), "power_w: minimum"),
            (lambda d: device_of(d, "new-amp")["rack"].update(slot=-1), "slot: minimum"),
        ]
        for mutate, needle in cases:
            doc = full_doc()
            mutate(doc)
            errs = schema_validate(js, doc)
            self.assertTrue(any(needle in e for e in errs), (needle, errs))


#: (description, mutation, code, path); one problem each
BAD = [
    ("width_in 20", lambda d: rack_of(d).update(width_in=20), "bad_enum", "racks/rk-new/width_in"),
    ("width_in '19'", lambda d: rack_of(d).update(width_in="19"), "bad_enum", "racks/rk-new/width_in"),
    ("width_in true", lambda d: rack_of(d).update(width_in=True), "bad_enum", "racks/rk-new/width_in"),
    ("form_factor", lambda d: rack_of(d).update(form_factor="tower"), "bad_enum", "racks/rk-new/form_factor"),
    ("start_u -1", lambda d: rack_of(d).update(start_u=-1), "bad_type", "racks/rk-new/start_u"),
    ("start_u 1.5", lambda d: rack_of(d).update(start_u=1.5), "bad_type", "racks/rk-new/start_u"),
    ("start_u '1'", lambda d: rack_of(d).update(start_u="1"), "bad_type", "racks/rk-new/start_u"),
    ("rack weight str", lambda d: rack_of(d).update(weight_kg="40"), "bad_type", "racks/rk-new/weight_kg"),
    ("rack weight neg", lambda d: rack_of(d).update(weight_kg=-1), "bad_type", "racks/rk-new/weight_kg"),
    ("max_load bool", lambda d: rack_of(d).update(max_load_kg=True), "bad_type", "racks/rk-new/max_load_kg"),
    ("power_limit str", lambda d: rack_of(d).update(power_limit_w="20A"), "bad_type", "racks/rk-new/power_limit_w"),
    ("row int", lambda d: rack_of(d).update(row=3), "bad_type", "racks/rk-new/row"),
    ("items object", lambda d: rack_of(d).update(items={"ri-1": {}}), "bad_type", "racks/rk-new/items"),
    ("items str", lambda d: rack_of(d).update(items="blank"), "bad_type", "racks/rk-new/items"),
    ("item not object", lambda d: rack_of(d)["items"].append("blank"), "bad_type", "racks/rk-new/items/8"),
    ("item null", lambda d: rack_of(d)["items"].append(None), "bad_type", "racks/rk-new/items/8"),
    ("item no id", lambda d: rack_of(d)["items"][1].pop("id"), "missing_field", "racks/rk-new/items/1/id"),
    ("item empty id", lambda d: rack_of(d)["items"][1].update(id=""), "missing_field", "racks/rk-new/items/1/id"),
    ("item int id", lambda d: rack_of(d)["items"][1].update(id=7), "bad_type", "racks/rk-new/items/1/id"),
    ("item no type", lambda d: rack_of(d)["items"][1].pop("type"), "missing_field", "racks/rk-new/items/1/type"),
    ("item bad type", lambda d: rack_of(d)["items"][1].update(type="tray"), "bad_enum", "racks/rk-new/items/1/type"),
    ("item no u", lambda d: rack_of(d)["items"][1].pop("u"), "missing_field", "racks/rk-new/items/1/u"),
    ("item empty u", lambda d: rack_of(d)["items"][1].update(u=""), "missing_field", "racks/rk-new/items/1/u"),
    ("item u 0", lambda d: rack_of(d)["items"][1].update(u=0), "bad_type", "racks/rk-new/items/1/u"),
    ("item u str", lambda d: rack_of(d)["items"][1].update(u="2"), "bad_type", "racks/rk-new/items/1/u"),
    ("item u float", lambda d: rack_of(d)["items"][1].update(u=2.5), "bad_type", "racks/rk-new/items/1/u"),
    ("item height 0", lambda d: rack_of(d)["items"][3].update(height=0), "bad_type", "racks/rk-new/items/3/height"),
    ("item slots 0", lambda d: rack_of(d)["items"][0].update(slots=0), "bad_type", "racks/rk-new/items/0/slots"),
    ("item slots 5", lambda d: rack_of(d)["items"][0].update(slots=5), "bad_type", "racks/rk-new/items/0/slots"),
    ("item face", lambda d: rack_of(d)["items"][2].update(face="both"), "bad_enum", "racks/rk-new/items/2/face"),
    ("item depth", lambda d: rack_of(d)["items"][2].update(depth="quarter"), "bad_enum", "racks/rk-new/items/2/depth"),
    ("item weight str", lambda d: rack_of(d)["items"][0].update(weight_kg="2kg"), "bad_type", "racks/rk-new/items/0/weight_kg"),
    ("item label int", lambda d: rack_of(d)["items"][0].update(label=1), "bad_type", "racks/rk-new/items/0/label"),
    ("item color list", lambda d: rack_of(d)["items"][0].update(color=[1]), "bad_type", "racks/rk-new/items/0/color"),
    ("item notes obj", lambda d: rack_of(d)["items"][0].update(notes={}), "bad_type", "racks/rk-new/items/0/notes"),
    ("duplicate item id", lambda d: rack_of(d)["items"][2].update(id="ri-1"), "duplicate_id", "racks/rk-new/items/2/id"),
    ("device weight str", lambda d: device_of(d, "new-amp").update(weight_kg="12"), "bad_type", "devices/new-amp/weight_kg"),
    ("device weight neg", lambda d: device_of(d, "new-amp").update(weight_kg=-2), "bad_type", "devices/new-amp/weight_kg"),
    ("device power str", lambda d: device_of(d, "new-amp").update(power_w="600 W"), "bad_type", "devices/new-amp/power_w"),
    ("device power bool", lambda d: device_of(d, "new-amp").update(power_w=False), "bad_type", "devices/new-amp/power_w"),
    ("shelf int", lambda d: device_of(d, "shelf-mac")["rack"].update(shelf=1), "bad_type", "devices/shelf-mac/rack/shelf"),
    ("slot -1", lambda d: device_of(d, "shelf-mac")["rack"].update(slot=-1), "bad_type", "devices/shelf-mac/rack/slot"),
    ("slot str", lambda d: device_of(d, "shelf-mac")["rack"].update(slot="0"), "bad_type", "devices/shelf-mac/rack/slot"),
    ("rack color int", lambda d: device_of(d, "new-amp")["rack"].update(color=0x4A7A8A), "bad_type", "devices/new-amp/rack/color"),
    ("image_front int", lambda d: device_of(d, "new-amp")["rack"].update(image_front=3), "bad_type", "devices/new-amp/rack/image_front"),
    ("image_rear list", lambda d: device_of(d, "new-amp")["rack"].update(image_rear=["a"]), "bad_type", "devices/new-amp/rack/image_rear"),
]


class BadDocs(unittest.TestCase):
    def test_each_bad_case(self):
        self.assertEqual(s.errors(s.validate_doc(full_doc())), [])
        for name, mutate, code, path in BAD:
            with self.subTest(name):
                doc = full_doc()
                mutate(doc)
                errs = s.errors(s.validate_doc(doc))
                self.assertEqual([(p["code"], p["path"]) for p in errs], [(code, path)])
                self.assertEqual(errs[0]["ref"], "/".join(path.split("/")[:2]))
                self.assertTrue(errs[0]["message"])

    def test_errors_block_save(self):
        from fathom import project

        with temp_data_dir():
            project.new_project("t")
            doc, pdir = project.load_doc("t")
            doc["racks"].append({"id": "rk-x", "name": "X", "units": 4, "items": [{"id": "a", "type": "tray", "u": 1}]})
            with self.assertRaises(project.ValidationError):
                project.save_doc(doc, pdir, base_revision=doc["revision"])

    def test_many_problems_in_one_item(self):
        doc = full_doc()
        rack_of(doc)["items"].append({"face": "side", "depth": 3, "height": "2"})
        got = sorted((p["code"], p["path"]) for p in s.errors(s.validate_doc(doc)))
        p = "racks/rk-new/items/8/"
        self.assertEqual(got, sorted([
            ("missing_field", p + "id"), ("missing_field", p + "type"), ("missing_field", p + "u"),
            ("bad_type", p + "height"), ("bad_enum", p + "face"), ("bad_enum", p + "depth"),
        ]))

    def test_duplicates_are_per_rack(self):
        doc = full_doc()
        r2 = copy.deepcopy(full_rack())
        r2["id"] = "rk-new2"
        doc["racks"].append(r2)
        self.assertEqual(s.errors(s.validate_doc(doc)), [], "ri-1 in two racks is fine")
        r2["items"].append({"id": "ri-1", "type": "blank", "u": 12})
        r2["items"].append({"id": "ri-1", "type": "blank", "u": 11})
        got = [(p["code"], p["ref"], p["path"]) for p in s.errors(s.validate_doc(doc))]
        self.assertEqual(got, [("duplicate_id", "racks/rk-new2", "racks/rk-new2/items/8/id"),
                               ("duplicate_id", "racks/rk-new2", "racks/rk-new2/items/9/id")])


class Samples(unittest.TestCase):
    def sample_docs(self):
        return {"campus-demo": read_json(CAMPUS_DIR / "project.json"), "rrc-littleton": read_json(RRC_DIR / "project.json")}

    def test_samples_problem_lists_unchanged(self):
        for name, raw in self.sample_docs().items():
            with self.subTest(name):
                self.assertEqual(keyed(s.validate_doc(s.load_any(raw))), sorted(BASE_SAMPLE_PROBLEMS[name]))

    def test_samples_same_with_new_checks_off(self):
        for name, raw in self.sample_docs().items():
            doc = s.load_any(raw)
            with mock.patch.object(s, "_rack_field_problems", lambda r, ref: []), \
                    mock.patch.object(s, "_device_rack_field_problems", lambda d, ref: []):
                before = keyed(s.validate_doc(doc))
            self.assertEqual(keyed(s.validate_doc(doc)), before, name)

    def test_new_doc_and_sunday(self):
        self.assertEqual(s.validate_doc(s.new_doc("X")), [])
        doc = sunday_doc()
        with mock.patch.object(s, "_rack_field_problems", lambda r, ref: []), \
                mock.patch.object(s, "_device_rack_field_problems", lambda d, ref: []):
            before = keyed(s.validate_doc(doc))
        self.assertEqual(keyed(s.validate_doc(doc)), before)

    def test_old_docs_load_unchanged(self):
        for name, raw in self.sample_docs().items():
            doc = s.load_any(raw)
            self.assertEqual(s.load_any(copy.deepcopy(doc)), doc, name)
            self.assertEqual(doc["fathom"], s.SCHEMA_VERSION)
        self.assertEqual(s.SCHEMA_VERSION, 2)


class Normalize(unittest.TestCase):
    def test_new_keys_kept(self):
        doc = full_doc()
        n = s.normalize(doc)
        self.assertEqual(rack_of(n), full_rack())
        self.assertEqual(rack_of(n)["start_u"], 0, "0 is a value, not empty")
        self.assertEqual(device_of(n, "shelf-mac")["rack"]["slot"], 0)
        self.assertEqual(device_of(n, "new-amp"), device_of(doc, "new-amp"))
        self.assertEqual(s.normalize(n), n, "idempotent")
        self.assertEqual(s.load_any(json.loads(json.dumps(n))), n, "JSON round trip")

    def test_empty_values_dropped(self):
        doc = full_doc()
        rack_of(doc).update(row="", items=[])
        rack_of(doc)["items"] = [{"id": "ri-1", "type": "blank", "u": 1, "label": "", "notes": None}]
        n = rack_of(s.normalize(doc))
        self.assertNotIn("row", n)
        self.assertEqual(n["items"], [{"id": "ri-1", "type": "blank", "u": 1}])

    def test_ops_and_diff_keep_items(self):
        doc = s.normalize(full_doc())
        items = rack_of(doc)["items"] + [{"id": "ri-9", "type": "blank", "u": 12}]
        new, touched = s.apply_ops(doc, [{"op": "merge", "coll": "racks", "id": "rk-new", "value": {"items": items}}])
        self.assertEqual(rack_of(new)["items"], items)
        self.assertIn("racks/rk-new", touched)
        self.assertEqual(s.apply_ops(doc, s.diff_docs(doc, new))[0], new)

    def test_save_and_reload(self):
        from fathom import project

        with temp_data_dir():
            project.new_project("t")
            doc, pdir = project.load_doc("t")
            doc["racks"].append(full_rack())
            doc["devices"].append(copy.deepcopy(device_of(full_doc(), "new-amp")))
            doc["devices"][-1]["room"] = doc["rooms"][0]["id"]
            project.save_doc(doc, pdir, base_revision=doc["revision"])
            again, _ = project.load_doc("t")
            self.assertEqual(rack_of(again), full_rack())
            self.assertEqual(device_of(again, "new-amp")["rack"], device_of(full_doc(), "new-amp")["rack"])
            self.assertEqual(device_of(again, "new-amp")["power_w"], 600.5)


class V1Compat(unittest.TestCase):
    def test_racks_are_v2_only(self):
        doc = s.load_any(read_json(RRC_DIR / "project.json"))
        self.assertTrue(s.is_v1_expressible(doc))
        with_rack = copy.deepcopy(doc)
        with_rack["racks"].append(full_rack())
        self.assertFalse(s.is_v1_expressible(with_rack))

    def test_device_weight_and_power_are_v2_only(self):
        doc = s.load_any(read_json(RRC_DIR / "project.json"))
        for key, val in (("weight_kg", 3.5), ("power_w", 40), ("power_w", 0)):
            d = copy.deepcopy(doc)
            d["devices"][0][key] = val
            self.assertFalse(s.is_v1_expressible(d), key)


if __name__ == "__main__":
    unittest.main()
