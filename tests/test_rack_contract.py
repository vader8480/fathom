"""Rack contract (docs/notes/rackula.md sections B-C) against fathom.racks.

Data-driven from tests/fixtures/rack_contract.json, shared with
tests/js/rack-contract.test.mjs. One test per case and expect key; a test
skips only while the racks function it exercises is missing.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from fathom import racks

FIXTURE = Path(__file__).parent / "fixtures" / "rack_contract.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
JS_ONLY = ("width_px", "rows", "add_item")


def _rack(doc, rack_id):
    for r in doc.get("racks") or []:
        if r.get("id") == rack_id:
            return r
    raise AssertionError(f"fixture rack {rack_id!r} missing")


def _device(doc, dev_id):
    for d in doc.get("devices") or []:
        if d.get("id") == dev_id:
            return d
    raise AssertionError(f"fixture device {dev_id!r} missing")


def _cell_device(v):
    if isinstance(v, dict):
        return v.get("id") or v.get("device")
    return v


class RackContract(unittest.TestCase):
    def need(self, name):
        fn = getattr(racks, name, None)
        if not callable(fn):
            self.skipTest(f"awaiting racks.{name}")
        return fn

    def check_labels(self, case, exp):
        ru_label = self.need("ru_label")
        rack = _rack(case["doc"], case["rack"])
        for u, label in exp.items():
            self.assertEqual(ru_label(rack, int(u)), label, f"U{u}")

    def check_collisions(self, case, exp):
        got = self.need("collisions")(case["doc"], case["rack"])
        self.assertEqual([dict(c) for c in got], exp)

    def check_fits(self, case, exp):
        for e in exp:
            rack_id = e.get("rack", case["rack"])
            if "item" in e:
                fn = getattr(racks, "item_fits", None)
                if not callable(fn):
                    continue
                got = fn(case["doc"], rack_id, e["item"], e["u"], e.get("spec") or {})
            else:
                fn = getattr(racks, "fits", None)
                if not callable(fn):
                    continue
                got = fn(case["doc"], rack_id, e["device"], e["u"], e.get("opts") or {})
            with self.subTest(entry=e):
                self.assertEqual(got["ok"], e["ok"])
                self.assertEqual(got["reason"], e["reason"])
                self.assertEqual(sorted(got["conflicts"]), sorted(e["conflicts"]))
        if not callable(getattr(racks, "fits", None)) and not callable(getattr(racks, "item_fits", None)):
            self.skipTest("awaiting racks.fits / racks.item_fits")

    def check_shelf(self, case, exp):
        got = self.need("shelf_contents")(case["doc"], case["rack"], exp["item"])
        self.assertEqual([{"slot": c["slot"], "device": _cell_device(c["device"])} for c in got], exp["cells"])

    def check_totals(self, case, exp):
        got = self.need("rack_totals")(case["doc"], case["rack"])
        for k, v in exp.items():
            self.assertIn(k, got)
            if v is None:
                self.assertIsNone(got[k], k)
            else:
                self.assertAlmostEqual(got[k], v, places=9, msg=k)

    def check_problems(self, case, exp):
        if not hasattr(racks, "ITEM_TYPES"):
            self.skipTest("awaiting racks.ITEM_TYPES (items-aware validate_racks)")
        got = {p["code"] for p in racks.validate_racks(case["doc"]) if str(p.get("code", "")).startswith("rack_")}
        self.assertEqual(got, set(exp))

    def check_annotations(self, case, exp):
        fn = self.need("annotation_value")
        for dev_id, fields in exp.items():
            dev = _device(case["doc"], dev_id)
            for field, value in fields.items():
                self.assertEqual(fn(case["doc"], dev, field), value, f"{dev_id}.{field}")


def _make(case, key):
    def test(self):
        c = copy.deepcopy(case)
        getattr(self, "check_" + key)(c, c["expect"][key])
    return test


for _case in CASES:
    for _key in _case["expect"]:
        if _key in JS_ONLY:
            continue
        _name = "test_" + _case["name"].replace("-", "_") + "__" + _key
        setattr(RackContract, _name, _make(_case, _key))


class FixtureShape(unittest.TestCase):
    def test_fixture_has_enough_cases(self):
        self.assertGreaterEqual(len(CASES), 14)
        names = [c["name"] for c in CASES]
        self.assertEqual(len(names), len(set(names)))
        for c in CASES:
            self.assertIn(c["rack"], [r["id"] for r in c["doc"]["racks"]])
            for key in c["expect"]:
                self.assertTrue(key in JS_ONLY or hasattr(RackContract, "check_" + key), f"{c['name']}: unknown expect key {key}")


if __name__ == "__main__":
    unittest.main()
