"""Rack templates (fathom/rack_templates.py): church AV racks as rack + planned devices + RackItems."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, Dict, List, Set, Tuple

from _helpers import CAMPUS_DIR, install_campus, temp_data_dir

from fathom import library, presets, racks, rack_templates, schema

IDS = ["church-audio-12u", "road-case-8u", "video-stream-16u", "network-closet-24u", "desk-10in-6u"]
FORM_FACTORS = ("cabinet", "open_frame", "two_post", "four_post", "wall_mount", "road_case")
RACK_CODES = ("rack_unknown", "rack_out_of_range", "rack_overlap", "rack_shelf_unknown", "rack_shelf_overlap",
              "rack_slot_out_of_range", "rack_overweight", "rack_over_power")


def empty_doc() -> Dict[str, Any]:
    return schema.normalize(schema.new_doc("Test"))


def campus_doc() -> Dict[str, Any]:
    if not (CAMPUS_DIR / "project.json").exists():
        raise unittest.SkipTest("campus sample not present")
    return schema.load_any(json.loads((CAMPUS_DIR / "project.json").read_text(encoding="utf-8")))


def apply(doc: Dict[str, Any], tid: str, **kw: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    res = rack_templates.apply_ops(doc, tid, **kw)
    return schema.normalize(schema.apply_ops(doc, res["ops"])[0]), res


def problem_keys(doc: Dict[str, Any]) -> Set[Tuple[str, str, str]]:
    return {(p["level"], p["code"], p.get("ref", "")) for p in schema.validate_doc(doc)}


def collisions(doc: Dict[str, Any], rack_id: str) -> List[Tuple[str, str, int, str]]:
    """Reference occupancy per contract B/C: rack-level devices (not shelf children) and items.
    Full depth blocks both faces; items are full width; half-width sides meet only their side or full."""
    rack = next(r for r in doc["racks"] if r["id"] == rack_id)
    parts = []
    for d in doc["devices"]:
        p = d.get("rack") or {}
        if p.get("id") != rack_id or p.get("shelf"):
            continue
        parts.append((d["id"], p["u"], p["height"], p["face"], p["depth"], p["side"]))
    for it in rack.get("items") or []:
        parts.append(("item:" + it["id"], it["u"], it["height"], it["face"], it["depth"], "full"))
    cells: Dict[Tuple[int, str, str], str] = {}
    out = []
    for pid, u, h, face, depth, side in parts:
        assert 1 <= u and u + h - 1 <= rack["units"], (pid, u, h, rack["units"])
        for uu in range(u, u + h):
            for f in (("front", "rear") if depth == "full" else (face,)):
                for s in (("left", "right") if side == "full" else (side,)):
                    other = cells.setdefault((uu, f, s), pid)
                    if other != pid and not any(c[:2] == (other, pid) and c[3] == f for c in out):
                        out.append((other, pid, uu, f))
    return out


class Catalogue(unittest.TestCase):
    def test_list_templates_shape(self):
        lst = rack_templates.list_templates()
        self.assertEqual([t["id"] for t in lst], IDS)
        for t in lst:
            self.assertEqual(set(t), {"id", "name", "description", "units", "width_in", "form_factor"})
            self.assertIn(t["form_factor"], FORM_FACTORS)
            self.assertIn(t["width_in"], (10, 19, 21, 23))
            self.assertTrue(1 <= t["units"] <= 60)
            self.assertTrue(t["name"] and t["description"])
        by = {t["id"]: t for t in lst}
        self.assertEqual((by["church-audio-12u"]["form_factor"], by["church-audio-12u"]["units"]), ("cabinet", 12))
        self.assertEqual((by["road-case-8u"]["form_factor"], by["road-case-8u"]["units"]), ("road_case", 8))
        self.assertEqual((by["video-stream-16u"]["form_factor"], by["video-stream-16u"]["units"]), ("cabinet", 16))
        self.assertEqual((by["network-closet-24u"]["form_factor"], by["network-closet-24u"]["units"]), ("four_post", 24))
        self.assertEqual((by["desk-10in-6u"]["form_factor"], by["desk-10in-6u"]["units"], by["desk-10in-6u"]["width_in"]),
                         ("open_frame", 6, 10))

    def test_list_is_a_copy(self):
        rack_templates.list_templates()[0]["name"] = "changed"
        self.assertNotEqual(rack_templates.list_templates()[0]["name"], "changed")
        t = rack_templates.get_rack_template("road-case-8u")
        t["layout"].clear()
        self.assertTrue(rack_templates.get_rack_template("road-case-8u")["layout"])
        self.assertIsNone(rack_templates.get_rack_template("nope"))

    def test_library_ids_are_builtin_or_preset(self):
        for tid in IDS:
            for lid in rack_templates.template_ids(tid):
                builtin = (library.BUILTIN_DIR / (lid + ".json")).is_file()
                self.assertTrue(builtin or presets.get_preset(lid) is not None, "%s uses unknown template %s" % (tid, lid))
                self.assertIsNotNone(library.get_template(lid), lid)

    def test_placement_heights_follow_template_ru(self):
        for t in rack_templates.TEMPLATES:
            for e in t["layout"]:
                if "template" in e:
                    self.assertEqual(e["height"], library.get_template(e["template"]).get("ru") or 1, (t["id"], e["name"]))

    def test_item_defaults_match_contract(self):
        self.assertEqual(list(rack_templates.ITEM_DEFAULTS),
                         ["blank", "vent", "shelf", "drawer", "cable_manager", "brush", "lacing_bar", "other"])
        engine = getattr(racks, "ITEM_TYPES", None)
        if engine is None:
            self.skipTest("awaiting racks.ITEM_TYPES")
        for row in engine:
            mine = rack_templates.ITEM_DEFAULTS[row["type"]]
            for k in ("height", "face", "depth"):
                self.assertEqual(mine[k], row[k], (row["type"], k))

    def test_unknown_template(self):
        with self.assertRaises(KeyError):
            rack_templates.apply_ops(empty_doc(), "no-such-rack")
        with self.assertRaises(KeyError):
            rack_templates.apply_ops(empty_doc(), "")


class Contents(unittest.TestCase):
    """Each template holds the gear its description promises."""

    def built(self, tid: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        doc, res = apply(empty_doc(), tid)
        rack = next(r for r in doc["racks"] if r["id"] == res["rack_id"])
        return rack, rack["items"], [d for d in doc["devices"] if (d.get("rack") or {}).get("id") == rack["id"]]

    def kinds(self, devs: List[Dict[str, Any]], shelf: bool = False) -> List[str]:
        return [d["kind"] for d in devs if bool(d["rack"].get("shelf")) == shelf]

    def test_church_audio(self):
        rack, items, devs = self.built("church-audio-12u")
        types = [i["type"] for i in items]
        self.assertEqual(types.count("vent"), 1)
        self.assertGreaterEqual(types.count("blank"), 2)
        self.assertIn("power", self.kinds(devs))
        self.assertIn("stage_io", self.kinds(devs))
        self.assertGreaterEqual(self.kinds(devs).count("wireless_rx"), 2)
        shelf = next(i for i in items if i["type"] == "shelf")
        self.assertEqual(shelf["slots"], 2)
        self.assertEqual(len(self.kinds(devs, shelf=True)), 2)

    def test_road_case(self):
        rack, items, devs = self.built("road-case-8u")
        self.assertEqual(sorted({i["type"] for i in items}), ["blank", "drawer"])
        self.assertEqual(next(i for i in items if i["type"] == "drawer")["height"], 2)
        self.assertIn("power", self.kinds(devs))
        self.assertGreaterEqual(self.kinds(devs).count("wireless_rx"), 2)

    def test_video_stream(self):
        rack, items, devs = self.built("video-stream-16u")
        for k in ("video_switcher", "video_router", "encoder", "power"):
            self.assertIn(k, self.kinds(devs))
        self.assertEqual(self.kinds(devs, shelf=True), ["computer"])
        ups = next(d for d in devs if d["template"] == "generic-ups")
        self.assertEqual(ups["rack"]["height"], 2)

    def test_network_closet(self):
        rack, items, devs = self.built("network-closet-24u")
        k = self.kinds(devs)
        self.assertGreaterEqual(k.count("patch_panel"), 2)
        self.assertGreaterEqual(k.count("power"), 2)
        self.assertIn("network", k)
        self.assertIn("generic-switch-48", [d["template"] for d in devs])
        self.assertGreaterEqual([i["type"] for i in items].count("cable_manager"), 2)
        pdu = next(d for d in devs if d["template"] == "generic-pdu")
        self.assertEqual((pdu["rack"]["face"], pdu["rack"]["depth"]), ("rear", "half"))

    def test_desk_10in(self):
        rack, items, devs = self.built("desk-10in-6u")
        self.assertEqual(rack["width_in"], 10)
        self.assertIn("switch", self.kinds(devs))
        self.assertIn("power", self.kinds(devs))
        self.assertIn("shelf", [i["type"] for i in items])


class Apply(unittest.TestCase):
    def check_built(self, before: Dict[str, Any], doc: Dict[str, Any], res: Dict[str, Any], tid: str, room: str = "", location: str = "") -> None:
        spec = rack_templates.get_rack_template(tid)
        rid = res["rack_id"]
        self.assertTrue(all(op["op"] == "put" and op["coll"] in ("racks", "devices") for op in res["ops"]))
        self.assertEqual(res["ops"][0], {"op": "put", "coll": "racks", "id": rid, "value": res["ops"][0]["value"]})
        rack = next(r for r in doc["racks"] if r["id"] == rid)
        self.assertTrue(rid.startswith("rk-"))
        self.assertEqual((rack["units"], rack["width_in"], rack["form_factor"]), (spec["units"], spec["width_in"], spec["form_factor"]))
        self.assertEqual(rack.get("room", ""), room)
        self.assertEqual(rack.get("location", ""), location)
        # ids: unique per collection, items ri-1..n
        for coll in ("racks", "devices"):
            ids = [e["id"] for e in doc[coll]]
            self.assertEqual(len(ids), len(set(ids)), coll)
            self.assertTrue(all(schema.ID_RE.match(i) for i in ids))
        self.assertEqual([i["id"] for i in rack["items"]], ["ri-%d" % n for n in range(1, len(rack["items"]) + 1)])
        # devices
        new = [d for d in doc["devices"] if d["id"] not in {x["id"] for x in before["devices"]}]
        self.assertEqual(len(new), len(rack_templates.template_ids(tid)))
        self.assertEqual([d["template"] for d in new], rack_templates.template_ids(tid))
        for d in new:
            self.assertEqual(d["status"], "planned")
            self.assertEqual(d.get("room", ""), room)
            self.assertEqual(d.get("location", ""), location)
            self.assertEqual(d["rack"]["id"], rid)
            lt = library.get_template(d["template"])
            self.assertEqual(d["kind"], lt["kind"])
            self.assertEqual(len(d["ports"]), len(library.expand_port_groups(lt["ports"])))
            if d["rack"].get("shelf"):
                shelf = next(i for i in rack["items"] if i["id"] == d["rack"]["shelf"])
                self.assertEqual(shelf["type"], "shelf")
                self.assertTrue(0 <= d["rack"]["slot"] < shelf["slots"])
                self.assertEqual((d["rack"]["u"], d["rack"]["face"], d["rack"]["height"]), (shelf["u"], shelf["face"], 1))
            else:
                self.assertEqual(set(d["rack"]), {"id", "u", "height", "face", "side", "depth"})
        cells = [(d["rack"]["shelf"], d["rack"]["slot"]) for d in new if d["rack"].get("shelf")]
        self.assertEqual(len(cells), len(set(cells)), "two devices on one shelf cell")
        # no collisions (reference occupancy, and the engine's when it knows items)
        self.assertEqual(collisions(doc, rid), [])
        if hasattr(racks, "collisions"):
            self.assertEqual(racks.collisions(doc, rid), [])
        old = {(p["code"], p["ref"], p["path"]) for p in racks.validate_racks(before)}
        self.assertEqual([p for p in racks.validate_racks(doc) if (p["code"], p["ref"], p["path"]) not in old], [])
        # validation: nothing new compared to the doc before
        self.assertEqual(problem_keys(doc) - problem_keys(before), set())

    def test_each_template_on_empty_doc(self):
        for tid in IDS:
            with self.subTest(tid):
                before = empty_doc()
                doc, res = apply(before, tid)
                self.check_built(before, doc, res, tid)
                self.assertEqual(res["rack_id"], "rk-" + library._slug(rack_templates.get_rack_template(tid)["name"]))
                self.assertEqual([p for p in schema.validate_doc(doc) if p["code"] in RACK_CODES or p["level"] == "error"], [])

    def test_each_template_on_campus(self):
        for tid in IDS:
            with self.subTest(tid):
                before = campus_doc()
                doc, res = apply(before, tid, name="New rack", room="main", location="foh")
                self.check_built(before, doc, res, tid, room="main", location="foh")
                self.assertEqual(res["rack_id"], "rk-new-rack")

    def test_dedupes_against_doc(self):
        before = campus_doc()
        doc, res = apply(before, "video-stream-16u", name="FOH")
        self.assertEqual(res["rack_id"], "rk-foh-2")
        rack = next(r for r in doc["racks"] if r["id"] == "rk-foh-2")
        self.assertEqual(rack["name"], "FOH")
        ids = {d["template"]: d["id"] for d in doc["devices"] if d.get("rack", {}).get("id") == "rk-foh-2"}
        self.assertEqual(ids["generic-encoder-decoder"], "encoder-2")

    def test_dedupes_within_template(self):
        doc, res = apply(empty_doc(), "network-closet-24u")
        devs = [d for d in doc["devices"] if d["rack"]["id"] == res["rack_id"]]
        self.assertEqual(len({d["id"] for d in devs}), len(devs))
        doc = {"devices": [{"id": "patch-panel-a"}, {"id": "patch-panel-a-2"}], "racks": []}
        res = rack_templates.apply_ops(doc, "network-closet-24u")
        ids = [op["id"] for op in res["ops"] if op["coll"] == "devices"]
        self.assertIn("patch-panel-a-3", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_twice_gives_distinct_ids(self):
        for start in (empty_doc, campus_doc):
            for tid in IDS:
                with self.subTest(tid, start=start.__name__):
                    d0 = start()
                    d1, r1 = apply(d0, tid)
                    d2, r2 = apply(d1, tid)
                    self.assertNotEqual(r1["rack_id"], r2["rack_id"])
                    first = {op["id"] for op in r1["ops"] if op["coll"] == "devices"}
                    second = {op["id"] for op in r2["ops"] if op["coll"] == "devices"}
                    self.assertFalse(first & second)
                    self.check_built(d1, d2, r2, tid)
                    self.assertEqual(collisions(d2, r1["rack_id"]), [])

    def test_does_not_mutate_input(self):
        doc = campus_doc()
        snap = copy.deepcopy(doc)
        rack_templates.apply_ops(doc, "church-audio-12u", name="X", room="main")
        self.assertEqual(doc, snap)
        a = rack_templates.apply_ops(doc, "church-audio-12u")
        b = rack_templates.apply_ops(doc, "church-audio-12u")
        self.assertEqual(a, b)

    def test_reference_checker_detects_overlaps(self):
        doc, res = apply(empty_doc(), "network-closet-24u")
        rack = next(r for r in doc["racks"] if r["id"] == res["rack_id"])
        self.assertEqual(collisions(doc, rack["id"]), [])
        rack["items"].append({"id": "ri-99", "type": "blank", "u": 16, "height": 1, "face": "rear", "depth": "half"})
        self.assertEqual([c[3] for c in collisions(doc, rack["id"])], ["rear"])
        rack["items"][-1].update(u=5, face="front")
        rack["items"].append({"id": "ri-100", "type": "shelf", "u": 3, "height": 1, "face": "front", "depth": "full", "slots": 2})
        self.assertEqual(sorted(c[3] for c in collisions(doc, rack["id"])), ["front", "rear"])

    def test_shelf_children_sides(self):
        doc, res = apply(empty_doc(), "desk-10in-6u")
        kids = sorted((d["rack"]["slot"], d["rack"]["side"]) for d in doc["devices"] if d["rack"].get("shelf"))
        self.assertEqual(kids, [(0, "left"), (1, "right")])

    def test_blank_name_uses_template_name(self):
        res = rack_templates.apply_ops(empty_doc(), "road-case-8u", name="   ")
        self.assertEqual(res["ops"][0]["value"]["name"], "Wireless road case · 8U")
        self.assertNotIn("room", res["ops"][0]["value"])
        self.assertNotIn("location", res["ops"][0]["value"])


class Pipeline(unittest.TestCase):
    """The ops go through the same path as POST …/changes (project.apply_changes) and persist."""

    def test_apply_changes_on_campus(self):
        from fathom import project

        with temp_data_dir() as data:
            pdir = install_campus(data)
            rev = project.current_revision(pdir)
            doc, _ = project.load_doc(str(pdir))
            res = rack_templates.apply_ops(doc, "church-audio-12u", name="Sanctuary audio", room="main", location="foh")
            out = project.apply_changes(pdir, res["ops"], base_revision=rev, summary="Rack from template")
            self.assertEqual(out["revision"], rev + 1)
            self.assertFalse([p for p in out["problems"] if p["level"] == "error"])
            stored, _ = project.load_doc(str(pdir))
            rack = next(r for r in stored["racks"] if r["id"] == res["rack_id"])
            self.assertEqual(rack, res["ops"][0]["value"])
            shelf_kids = [d for d in stored["devices"] if (d.get("rack") or {}).get("shelf")]
            self.assertEqual(sorted(d["rack"]["slot"] for d in shelf_kids if d["rack"]["id"] == rack["id"]), [0, 1])
            res2 = rack_templates.apply_ops(stored, "church-audio-12u", name="Sanctuary audio")
            out2 = project.apply_changes(pdir, res2["ops"], base_revision=out["revision"])
            self.assertEqual(out2["revision"], rev + 2)
            self.assertEqual(res2["rack_id"], "rk-sanctuary-audio-2")


if __name__ == "__main__":
    unittest.main()
