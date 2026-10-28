"""Rack items, shelves, totals, annotations and the extended rack SVG (Rackula contract B/C, RPY)."""

from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from _helpers import sunday_doc, temp_data_dir

from fathom import racks

SVG = "{http://www.w3.org/2000/svg}"


def base_doc(**rack):
    r = {"id": "rk-a", "name": "Rack A", "room": "main", "units": 12}
    r.update(rack)
    return {"rooms": [{"id": "main", "name": "Main"}, {"id": "booth", "name": "Booth"}], "racks": [r], "devices": [], "templates": []}


def dev(did, **rack):
    d = {"id": did, "name": did.upper(), "kind": "amp"}
    if rack:
        d["rack"] = dict({"id": "rk-a"}, **rack)
    return d


def texts(svg):
    return [e.text or "" for e in ET.fromstring(svg).iter() if e.tag == SVG + "text"]


class Base(unittest.TestCase):
    def setUp(self):
        self._data = temp_data_dir()
        self._data.__enter__()

    def tearDown(self):
        self._data.__exit__(None, None, None)


class ItemTypes(Base):
    def test_table_order_and_values(self):
        self.assertEqual([t["type"] for t in racks.ITEM_TYPES],
                         ["blank", "vent", "shelf", "drawer", "cable_manager", "brush", "lacing_bar", "other"])
        by = {t["type"]: t for t in racks.ITEM_TYPES}
        self.assertEqual(by["shelf"], {"type": "shelf", "label": "Shelf", "height": 1, "face": "front", "depth": "full", "color": "#6272a4", "slots": 2})
        self.assertEqual((by["drawer"]["height"], by["drawer"]["depth"]), (2, "full"))
        self.assertEqual((by["lacing_bar"]["face"], by["lacing_bar"]["depth"]), ("rear", "half"))
        self.assertEqual((by["blank"]["color"], by["vent"]["color"], by["other"]["label"]), ("#44475a", "#44475a", "Accessory"))
        self.assertTrue(all(t["slots"] is None for t in racks.ITEM_TYPES if t["type"] != "shelf"))

    def test_category_colors(self):
        self.assertEqual(racks.CATEGORY_COLORS["server"], "#4A7A8A")
        self.assertEqual(racks.CATEGORY_COLORS["av-media"], "#A85A7A")
        self.assertEqual(len(racks.CATEGORY_COLORS), 14)


class Labels(Base):
    def test_ru_label(self):
        r = {"units": 12}
        self.assertEqual([racks.ru_label(r, u) for u in (1, 12)], ["1", "12"])
        self.assertEqual(racks.ru_label(dict(r, start_u=0), 1), "0")
        self.assertEqual(racks.ru_label(dict(r, start_u=0), 12), "11")
        self.assertEqual(racks.ru_label(dict(r, start_u=5), 3), "7")
        self.assertEqual(racks.ru_label(dict(r, numbering="top_down"), 1), "12")
        self.assertEqual(racks.ru_label(dict(r, numbering="top_down"), 12), "1")
        self.assertEqual(racks.ru_label(dict(r, numbering="top_down", start_u=0), 12), "0")
        self.assertEqual(racks.ru_label(dict(r, start_u=-3), 1), "1", "negative start_u falls back to 1")

    def test_width_px(self):
        self.assertEqual([racks.rack_width_px({"width_in": w}) for w in (10, 19, 21, 23)], [168, 320, 354, 387])
        self.assertEqual(racks.rack_width_px({}), 320)
        self.assertEqual(racks.rack_width_px({"width_in": "wide"}), 320)


class Placement(Base):
    def test_shelf_slot_color(self):
        d = base_doc()
        p = racks.placement(d, dev("x", u=3, shelf="ri-1", slot=1, color="#112233"))
        self.assertEqual((p["shelf"], p["slot"], p["color"]), ("ri-1", 1, "#112233"))
        p = racks.placement(d, dev("y", u=3, color="red"))
        self.assertEqual((p["shelf"], p["slot"], p["color"]), (None, None, None))

    def test_rack_devices_mark_shelf_children(self):
        d = base_doc(items=[{"id": "ri-1", "type": "shelf", "u": 2}])
        d["devices"] = [dev("a", u=5), dev("b", u=2, shelf="ri-1", slot=0)]
        ps = {p["device"]: p for p in racks.rack_devices(d, "rk-a")}
        self.assertEqual(set(ps), {"a", "b"})
        self.assertIsNone(ps["a"]["shelf"])
        self.assertEqual(ps["b"]["shelf"], "ri-1")


class Items(Base):
    def test_defaults_and_normalization(self):
        d = base_doc(items=[
            {"id": "ri-1", "type": "drawer", "u": 3},
            {"id": "ri-2", "type": "shelf", "u": 5, "slots": 9, "label": "Top", "color": "#abcdef", "weight_kg": 2.5},
            {"type": "blank", "u": 1},
            "junk",
            {"id": "ri-3", "type": "mystery", "u": 7, "face": "rear", "depth": "full", "height": 2},
            {"id": "ri-4", "type": "lacing_bar", "u": "x"},
        ])
        its = racks.rack_items(d, "rk-a")
        self.assertEqual([i["id"] for i in its], ["item:ri-1", "item:ri-2", "item:ri-3", "item:ri-4"])
        a, b, c, e = its
        self.assertEqual((a["height"], a["face"], a["depth"], a["side"], a["slots"], a["index"]), (2, "front", "full", "full", None, 0))
        self.assertEqual((b["slots"], b["label"], b["color"], b["weight_kg"], b["index"]), (4, "Top", "#abcdef", 2.5, 1))
        self.assertEqual((c["type"], c["face"], c["depth"], c["height"], c["index"]), ("other", "rear", "full", 2, 4))
        self.assertEqual((e["u"], e["face"]), (None, "rear"))
        self.assertEqual(racks.rack_items(d, "rk-none"), [])
        self.assertEqual(racks.rack_items(base_doc(items="nope"), "rk-a"), [])


class Collisions(Base):
    def test_device_vs_item_front(self):
        d = base_doc(items=[{"id": "ri-1", "type": "blank", "u": 4}])
        d["devices"] = [dev("amp", u=4, height=2)]
        self.assertEqual(racks.collisions(d, "rk-a"), [
            {"a": "amp", "b": "item:ri-1", "u": 4, "face": "front"},
        ])

    def test_half_depth_item_vs_rear_device(self):
        d = base_doc(items=[{"id": "ri-1", "type": "vent", "u": 4}])
        d["devices"] = [dev("amp", u=4, face="rear", depth="half")]
        self.assertEqual(racks.collisions(d, "rk-a"), [])
        d["devices"] = [dev("amp", u=4, face="rear")]
        self.assertEqual(racks.collisions(d, "rk-a"), [{"a": "amp", "b": "item:ri-1", "u": 4, "face": "front"}],
                         "a full-depth rear device reaches the front face")

    def test_full_depth_shelf_vs_rear_device(self):
        d = base_doc(items=[{"id": "ri-1", "type": "shelf", "u": 6}])
        d["devices"] = [dev("zz", u=6, face="rear", depth="half")]
        self.assertEqual(racks.collisions(d, "rk-a"), [{"a": "item:ri-1", "b": "zz", "u": 6, "face": "rear"}])

    def test_half_width_devices_vs_full_width_item(self):
        d = base_doc(items=[{"id": "ri-1", "type": "cable_manager", "u": 2}])
        d["devices"] = [dev("left", u=2, side="left", depth="half"), dev("right", u=2, side="right", depth="half")]
        self.assertEqual(racks.collisions(d, "rk-a"), [
            {"a": "item:ri-1", "b": "left", "u": 2, "face": "front"},
            {"a": "item:ri-1", "b": "right", "u": 2, "face": "front"},
        ])

    def test_order_lowest_u_and_shelf_children_excluded(self):
        d = base_doc(items=[{"id": "ri-1", "type": "shelf", "u": 3, "height": 2}, {"id": "ri-2", "type": "drawer", "u": 9}])
        d["devices"] = [
            dev("b", u=9), dev("a", u=10, height=2),
            dev("c", u=1, height=4),
            dev("kid", u=3, shelf="ri-1", slot=0),
        ]
        got = racks.collisions(d, "rk-a")
        self.assertEqual(got, [
            {"a": "c", "b": "item:ri-1", "u": 3, "face": "front"},
            {"a": "c", "b": "item:ri-1", "u": 3, "face": "rear"},
            {"a": "b", "b": "item:ri-2", "u": 9, "face": "front"},
            {"a": "b", "b": "item:ri-2", "u": 9, "face": "rear"},
            {"a": "a", "b": "item:ri-2", "u": 10, "face": "front"},
            {"a": "a", "b": "item:ri-2", "u": 10, "face": "rear"},
        ])
        self.assertFalse([c for c in got if "kid" in (c["a"], c["b"])])
        self.assertEqual(racks.collisions(d, "rk-none"), [])

    def test_item_vs_item(self):
        d = base_doc(items=[{"id": "ri-2", "type": "blank", "u": 1}, {"id": "ri-1", "type": "vent", "u": 1}])
        self.assertEqual(racks.collisions(d, "rk-a"), [{"a": "item:ri-1", "b": "item:ri-2", "u": 1, "face": "front"}])

    def test_occupancy_cells(self):
        d = base_doc(items=[{"id": "ri-1", "type": "lacing_bar", "u": 2}, {"id": "ri-2", "type": "shelf", "u": 3}])
        d["devices"] = [dev("kid", u=3, shelf="ri-2", slot=1), dev("amp", u=5)]
        occ = racks.rack_occupancy(d, "rk-a")
        self.assertEqual(occ["slots"][1]["rear"], {"left": "item:ri-1", "right": "item:ri-1"})
        self.assertEqual(occ["slots"][1]["front"], {"left": None, "right": None})
        self.assertEqual(occ["slots"][2]["front"]["left"], "item:ri-2")
        self.assertEqual(occ["slots"][2]["rear"]["right"], "item:ri-2")
        self.assertEqual([p["device"] for p in occ["devices"]], ["amp"])
        self.assertEqual([p["device"] for p in occ["shelved"]], ["kid"])
        self.assertEqual([i["item"] for i in occ["items"]], ["ri-1", "ri-2"])
        self.assertEqual(occ["collisions"], [])
        self.assertEqual(occ["rack"]["start_u"], 1)
        with self.assertRaises(KeyError):
            racks.rack_occupancy(d, "rk-none")


class Shelves(Base):
    def doc(self):
        d = base_doc(items=[{"id": "ri-1", "type": "shelf", "u": 2, "slots": 3}, {"id": "ri-2", "type": "blank", "u": 5}])
        d["devices"] = [
            dev("p1", u=2, shelf="ri-1", slot=2),
            dev("p2", u=2, shelf="ri-1", slot=0),
            dev("p3", u=2, shelf="ri-1", slot=2),
            dev("p4", u=2, shelf="ri-1", slot=3),
            dev("p5", u=2, shelf="ri-1"),
        ]
        return d

    def test_cells(self):
        self.assertEqual(racks.shelf_contents(self.doc(), "rk-a", "ri-1"), [
            {"slot": 0, "device": "p2"}, {"slot": 1, "device": None}, {"slot": 2, "device": "p1"},
        ])

    def test_default_slots_and_unknowns(self):
        d = base_doc(items=[{"id": "ri-1", "type": "shelf", "u": 2}])
        self.assertEqual(racks.shelf_contents(d, "rk-a", "ri-1"), [{"slot": 0, "device": None}, {"slot": 1, "device": None}])
        self.assertEqual(racks.shelf_contents(self.doc(), "rk-a", "ri-2"), [], "not a shelf")
        self.assertEqual(racks.shelf_contents(self.doc(), "rk-a", "ri-9"), [])
        self.assertEqual(racks.shelf_contents(self.doc(), "rk-none", "ri-1"), [])

    def test_problems(self):
        probs = racks.validate_racks(self.doc())
        codes = [(p["code"], p["ref"]) for p in probs]
        self.assertIn(("rack_shelf_overlap", "devices/p3"), codes)
        self.assertIn(("rack_slot_out_of_range", "devices/p4"), codes)
        self.assertIn(("rack_slot_out_of_range", "devices/p5"), codes, "a shelf child without a slot has no cell")
        self.assertNotIn("rack_out_of_range", [c for c, _ in codes], "shelf children are not range-checked against the rack")
        self.assertEqual([p for p in probs if p["ref"] in ("devices/p1", "devices/p2")], [])

    def test_shelf_deleted(self):
        d = self.doc()
        d["racks"][0]["items"] = [{"id": "ri-2", "type": "blank", "u": 5}]
        d["devices"].append(dev("p6", u=5, shelf="ri-2", slot=0))
        probs = racks.validate_racks(d)
        self.assertEqual(sorted(p["ref"] for p in probs if p["code"] == "rack_shelf_unknown"),
                         ["devices/p%d" % i for i in range(1, 7)])
        self.assertEqual({p["code"] for p in probs}, {"rack_shelf_unknown"}, "orphans are not in rack-level collisions")
        p6 = [p for p in probs if p["ref"] == "devices/p6"][0]
        self.assertEqual((p6["level"], p6["path"]), ("warning", "devices/p6/rack"))


class Totals(Base):
    def test_totals(self):
        d = base_doc(weight_kg=20, max_load_kg=40, power_limit_w=500,
                     items=[{"id": "ri-1", "type": "shelf", "u": 1, "weight_kg": 1.25}, {"id": "ri-2", "type": "lacing_bar", "u": 12}])
        d["templates"] = [{"id": "t-amp", "name": "Amp", "kind": "amp", "ru": 2, "weight_kg": 9.55, "power_w": 300}]
        d["devices"] = [
            dict(dev("a", u=3), template="t-amp"),
            dict(dev("b", u=6, face="rear", depth="half"), template="t-amp", weight_kg=4, power_w=0),
            dict(dev("kid", u=1, shelf="ri-1", slot=0), weight_kg=0.3, power_w=12.04),
            dev("loose"),
            dict(dev("out", u=11, height=3)),
        ]
        t = racks.rack_totals(d, "rk-a")
        self.assertEqual(t, {
            "units": 12, "used_u": 7, "free_u": 5,
            "weight_kg": 35.1, "max_load_kg": 40, "power_w": 312.0, "power_limit_w": 500,
            "devices": 4, "items": 2,
        })
        self.assertEqual(racks.rack_totals(base_doc(), "rk-a")["max_load_kg"], None)
        self.assertEqual(racks.rack_totals(base_doc(), "rk-a")["power_limit_w"], None)
        with self.assertRaises(KeyError):
            racks.rack_totals(d, "rk-none")

    def test_rounding_half_up(self):
        d = base_doc(weight_kg=0.25)
        self.assertEqual(racks.rack_totals(d, "rk-a")["weight_kg"], 0.3)
        d = base_doc(weight_kg=1.04999)
        self.assertEqual(racks.rack_totals(d, "rk-a")["weight_kg"], 1.0)

    def test_overweight_and_over_power(self):
        d = base_doc(weight_kg=10, max_load_kg=10, power_limit_w=100)
        d["devices"] = [dict(dev("a", u=1), weight_kg=0.1, power_w=100)]
        codes = [p["code"] for p in racks.validate_racks(d)]
        self.assertIn("rack_overweight", codes)
        self.assertNotIn("rack_over_power", codes, "equal to the limit is fine")
        d["devices"][0]["power_w"] = 100.5
        p = [p for p in racks.validate_racks(d) if p["code"] == "rack_over_power"][0]
        self.assertEqual((p["ref"], p["path"]), ("racks/rk-a", "racks/rk-a/power_limit_w"))


class Annotations(Base):
    def test_fields(self):
        d = base_doc()
        d["templates"] = [{"id": "t-x", "name": "X", "kind": "amp", "power_w": 450, "weight_kg": 12.5}]
        x = {"id": "x", "name": "Amp 1", "manufacturer": " Powersoft", "model": "X8 ", "code": "A-01", "template": "t-x",
             "inventory": {"serial": "SN1", "asset_tag": "AT-9"},
             "interfaces": [{"ip": ""}, {"ip": "10.0.0.5"}, {"ip": "10.0.0.9", "role": "primary"}]}
        av = lambda f: racks.annotation_value(d, x, f)  # noqa: E731
        self.assertEqual(av("name"), "Amp 1")
        self.assertEqual(av("model"), "Powersoft X8")
        self.assertEqual(av("ip"), "10.0.0.9")
        self.assertEqual(av("serial"), "SN1")
        self.assertEqual(av("asset_tag"), "AT-9")
        self.assertEqual(av("code"), "A-01")
        self.assertEqual(av("power"), "450 W")
        self.assertEqual(av("weight"), "12.5 kg")
        self.assertEqual(av("status"), "installed")
        self.assertEqual(av("bogus"), "")
        x["interfaces"] = [{"ip": "10.0.0.5"}, {"ip": "", "role": "primary"}]
        x["status"], x["power_w"], x["weight_kg"] = "spare", 0, 3.0
        self.assertEqual((av("ip"), av("status"), av("power"), av("weight")), ("10.0.0.5", "spare", "", "3 kg"))
        bare = {"id": "y"}
        self.assertEqual([racks.annotation_value(d, bare, f) for f in ("name", "model", "ip", "serial", "asset_tag", "code", "power", "weight")],
                         [""] * 8)
        self.assertEqual(racks.annotation_value(d, None, "name"), "")


class Validation(Base):
    def test_sunday_clean(self):
        self.assertEqual(racks.validate_racks(sunday_doc()), [])

    def test_items_out_of_range_and_overlap(self):
        d = base_doc(items=[{"id": "ri-1", "type": "drawer", "u": 12}, {"id": "ri-2", "type": "blank", "u": 0}, {"id": "ri-3", "type": "vent", "u": 5}, {"id": "ri-4", "type": "vent", "u": 5}])
        d["devices"] = [dev("amp", u=12)]
        probs = racks.validate_racks(d)
        oor = [(p["ref"], p["path"]) for p in probs if p["code"] == "rack_out_of_range"]
        self.assertEqual(oor, [("racks/rk-a", "racks/rk-a/items/0"), ("racks/rk-a", "racks/rk-a/items/1")])
        ov = [(p["ref"], p["path"]) for p in probs if p["code"] == "rack_overlap"]
        self.assertIn(("racks/rk-a", "racks/rk-a/items/3"), ov, "item vs item points at item b")
        self.assertIn(("devices/amp", "devices/amp/rack"), ov, "device vs item points at the device")
        self.assertEqual(len(ov), 3, "drawer is full depth: amp/drawer on front and rear, vent pair on front")

    def test_start_u_zero_and_top_down_do_not_move_ranges(self):
        d = base_doc(start_u=0, numbering="top_down", items=[{"id": "ri-1", "type": "blank", "u": 1}])
        d["devices"] = [dev("amp", u=12)]
        self.assertEqual(racks.validate_racks(d), [])


class Svg(Base):
    def doc(self):
        d = base_doc(items=[
            {"id": "ri-1", "type": "shelf", "u": 1, "slots": 2},
            {"id": "ri-2", "type": "vent", "u": 2},
            {"id": "ri-3", "type": "drawer", "u": 3},
            {"id": "ri-4", "type": "cable_manager", "u": 5},
            {"id": "ri-5", "type": "brush", "u": 6},
            {"id": "ri-6", "type": "lacing_bar", "u": 7},
            {"id": "ri-7", "type": "other", "u": 8, "label": "Work light"},
            {"id": "ri-8", "type": "blank", "u": 9},
        ])
        d["templates"] = [
            {"id": "t-srv", "name": "Server", "kind": "computer", "ru": 1, "rack_category": "server", "image_front": "acme/srv.front.webp", "image_rear": "acme/srv.rear.webp"},
            {"id": "t-big", "name": "Big", "kind": "computer", "ru": 1, "rack_category": "storage", "image_front": "acme/big.front.webp"},
        ]
        d["devices"] = [
            dict(dev("srv", u=10), template="t-srv", interfaces=[{"ip": "10.1.1.1"}]),
            dict(dev("amp", u=11, color="#123456")),
            dict(dev("kid", u=1, shelf="ri-1", slot=1), name="Shelf Kid"),
            dict(dev("big", u=12), template="t-big"),
        ]
        return d

    def test_legacy_signature(self):
        d = self.doc()
        for svg in (racks.rack_svg(d, "rk-a"), racks.rack_svg(d, "rk-a", "rear"), racks.rack_svg(d, "rk-a", face="rear"), racks.rack_svg(d, "rk-a", "front", 2.0)):
            ET.fromstring(svg)
        root = ET.fromstring(racks.rack_svg(d, "rk-a", "front", 2.0))
        self.assertEqual(root.get("data-face"), "front")
        vb = [float(x) for x in root.get("viewBox").split()]
        self.assertEqual(float(root.get("width")), vb[2] * 2)
        with self.assertRaises(KeyError):
            racks.rack_svg(d, "rk-none")

    def test_items_distinguishable(self):
        root = ET.fromstring(racks.rack_svg(self.doc(), "rk-a", face="front"))
        groups = {g.get("data-item"): g for g in root.iter(SVG + "g") if g.get("data-item")}
        self.assertEqual(set(groups), {"ri-1", "ri-2", "ri-3", "ri-4", "ri-5", "ri-7", "ri-8"}, "lacing bar is rear-only and half depth")
        cls = lambda g: {e.get("class") for e in g.iter()}  # noqa: E731
        self.assertIn("rk-vent", cls(groups["ri-2"]))
        self.assertIn("rk-handle", cls(groups["ri-3"]))
        self.assertIn("rk-ring", cls(groups["ri-4"]))
        self.assertIn("rk-brush", cls(groups["ri-5"]))
        self.assertIn("rk-tray", cls(groups["ri-1"]))
        self.assertIn("rk-cell", cls(groups["ri-1"]))
        self.assertIn("Work light", [t.text for t in groups["ri-7"].iter(SVG + "text")])
        self.assertEqual(len(list(groups["ri-8"])), 1, "a blank is one flat rect")
        rear = ET.fromstring(racks.rack_svg(self.doc(), "rk-a", face="rear"))
        lb = [g for g in rear.iter(SVG + "g") if g.get("data-item") == "ri-6"]
        self.assertTrue(lb and lb[0].get("data-type") == "lacing_bar")
        rect = lb[0].find(SVG + "rect")
        self.assertEqual(rect.get("height"), "6", "a lacing bar is a thin bar")

    def test_shelf_child_in_cell(self):
        d = self.doc()
        root = ET.fromstring(racks.rack_svg(d, "rk-a"))
        kid = [g for g in root.iter(SVG + "g") if g.get("data-device") == "kid"]
        self.assertEqual(len(kid), 1)
        self.assertEqual((kid[0].get("data-shelf"), kid[0].get("data-slot")), ("ri-1", "1"))
        x = float(kid[0].find(SVG + "rect").get("x"))
        self.assertGreater(x, racks.RAIL_W + racks.RACK_W / 2, "slot 1 of 2 is the right half")
        d["devices"][2]["rack"]["slot"] = 7
        root = ET.fromstring(racks.rack_svg(d, "rk-a"))
        self.assertFalse([g for g in root.iter(SVG + "g") if g.get("data-device") == "kid"], "a device outside the cells is not drawn")

    def test_both_faces(self):
        svg = racks.rack_svg(self.doc(), "rk-a", face="both")
        root = ET.fromstring(svg)
        self.assertEqual(root.get("data-face"), "both")
        faces = [g.get("data-face") for g in root.iter(SVG + "g") if g.get("class") == "rk-face"]
        self.assertEqual(faces, ["front", "rear"])
        caps = [t.text for t in root.iter(SVG + "text") if t.get("class") == "rk-caption"]
        self.assertEqual(caps, ["Front", "Rear"])
        single = float(ET.fromstring(racks.rack_svg(self.doc(), "rk-a")).get("viewBox").split()[2])
        self.assertEqual(float(root.get("viewBox").split()[2]), single * 2 + racks.FACE_GAP)

    def test_width_follows_width_in(self):
        for w, px in ((10, 168), (23, 387)):
            d = self.doc()
            d["racks"][0]["width_in"] = w
            root = ET.fromstring(racks.rack_svg(d, "rk-a"))
            self.assertEqual(float(root.get("viewBox").split()[2]), px + 2 * racks.RAIL_W)
            blanks = [r for r in root.iter(SVG + "rect") if r.get("class") == "rk-blank"]
            self.assertEqual({r.get("width") for r in blanks}, {str(px)})

    def test_labels_start_u_and_top_down(self):
        d = base_doc(units=4, start_u=0)
        self.assertEqual(sorted(set(t for t in texts(racks.rack_svg(d, "rk-a")) if t.isdigit())), ["0", "1", "2", "3"])
        d = base_doc(units=4, numbering="top_down")
        d["devices"] = [dev("low", u=1)]
        root = ET.fromstring(racks.rack_svg(d, "rk-a"))
        rows = [(float(t.get("y")), t.text) for t in root.iter(SVG + "text") if t.text and t.text.isdigit() and float(t.get("x")) < racks.RAIL_W]
        self.assertEqual([lab for _, lab in sorted(rows)], ["1", "2", "3", "4"], "top_down prints 1 at the top")
        blk = [g for g in root.iter(SVG + "g") if g.get("data-device") == "low"][0]
        y = float(blk.find(SVG + "rect").get("y"))
        self.assertGreater(y, max(yy for yy, _ in rows) - racks.RU_PX, "u=1 stays the bottom row")

    def test_colors(self):
        root = ET.fromstring(racks.rack_svg(self.doc(), "rk-a"))

        def stripe(did):
            g = [g for g in root.iter(SVG + "g") if g.get("data-device") == did][0]
            return [r.get("fill") for r in g.iter(SVG + "rect") if r.get("width") == "5"][0]

        self.assertEqual(stripe("amp"), "#123456", "rack.color wins")
        self.assertEqual(stripe("srv"), "#4A7A8A", "template rack_category")
        from fathom import vocab
        self.assertEqual(stripe("kid"), vocab.DISCIPLINES["audio"]["color"], "discipline colour (amp → audio)")

    def test_title_totals(self):
        d = self.doc()
        d["racks"][0].update(weight_kg=30, max_load_kg=20)
        d["devices"][0]["power_w"] = 250
        root = ET.fromstring(racks.rack_svg(d, "rk-a"))
        title = [t for t in root.iter(SVG + "text") if t.get("class") == "rk-title"][0]
        full = "".join(title.itertext())
        self.assertIn("Rack A · front", full)
        self.assertIn("12/12U used · 0U free", full)
        self.assertIn("30/20 kg", full)
        self.assertIn("250 W", full)
        warn = [s for s in title.iter(SVG + "tspan") if s.get("fill") == "#f87171"]
        self.assertEqual([s.text for s in warn], [" · 30/20 kg"])

    def test_escaping(self):
        d = self.doc()
        d["racks"][0]["name"] = '<script>"x"&'
        d["devices"][0]["name"] = "Bad\x01<b>"
        d["racks"][0]["items"][6]["label"] = "</text>"
        svg = racks.rack_svg(d, "rk-a", face="both", annotate="name")
        root = ET.fromstring(svg)
        self.assertNotIn("<script>", svg)
        self.assertIn('<script>"x"&', root.find(SVG + "title").text)
        self.assertIn("Bad<b>", texts(svg))
        self.assertIn("</text>", texts(svg))

    def test_annotate_column(self):
        d = self.doc()
        svg = racks.rack_svg(d, "rk-a", annotate="ip")
        root = ET.fromstring(svg)
        col = [g for g in root.iter(SVG + "g") if g.get("class") == "rk-annotations"]
        self.assertEqual(len(col), 1)
        self.assertEqual(col[0].get("data-field"), "ip")
        rows = [(g.get("data-devices"), "".join(g.itertext())) for g in col[0] if g.get("class") == "rk-annot"]
        self.assertEqual(rows, [("srv", "10.1.1.1")])
        self.assertIn("IP", texts(svg))
        names = [(g.get("data-devices"), "".join(g.itertext())) for g in ET.fromstring(racks.rack_svg(d, "rk-a", face="both", annotate="name")).iter(SVG + "g") if g.get("class") == "rk-annot"]
        self.assertEqual(sorted(names), [("amp", "AMP"), ("big", "BIG"), ("kid", "Shelf Kid"), ("srv", "SRV")])
        plain = float(ET.fromstring(racks.rack_svg(d, "rk-a")).get("viewBox").split()[2])
        self.assertEqual(float(root.get("viewBox").split()[2]), plain + racks.ANNOT_GAP + racks.ANNOT_W)
        self.assertNotIn("rk-annotations", racks.rack_svg(d, "rk-a", annotate=""))


class SvgImages(Base):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="rk-img-"))
        (self.root / "acme").mkdir()
        (self.root / "acme" / "srv.front.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPfront")
        (self.root / "acme" / "srv.rear.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPrear")
        (self.root / "acme" / "big.front.webp").write_bytes(b"B" * 4000)
        (self.root.parent / (self.root.name + "-secret.webp")).write_bytes(b"secret")
        self.patch = mock.patch.object(racks, "RACK_IMAGES_DIR", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        (self.root.parent / (self.root.name + "-secret.webp")).unlink()
        super().tearDown()

    def doc(self):
        return Svg.doc(self)

    def uses(self, root):
        return {g.get("data-device"): g.find(SVG + "use") for g in root.iter(SVG + "g") if g.get("data-device")}

    def test_data_uri(self):
        svg = racks.rack_svg(self.doc(), "rk-a", images=True)
        root = ET.fromstring(svg)
        u = self.uses(root)
        self.assertIsNotNone(u["srv"])
        self.assertIsNone(u["amp"], "no template image → block")
        sym = root.find(SVG + "defs/" + SVG + "symbol")
        href = sym.find(SVG + "image").get("href")
        self.assertTrue(href.startswith("data:image/webp;base64,"))
        import base64
        self.assertEqual(base64.b64decode(href.split(",", 1)[1]), b"RIFF\x00\x00\x00\x00WEBPfront")
        self.assertEqual(u["srv"].get("href"), "#" + sym.get("id"))
        rear = racks.rack_svg(self.doc(), "rk-a", face="rear", images=True)
        self.assertIn(__import__("base64").b64encode(b"RIFF\x00\x00\x00\x00WEBPrear").decode(), rear)
        self.assertNotIn(__import__("base64").b64encode(b"RIFF\x00\x00\x00\x00WEBPfront").decode(), rear, "never the front image on the rear")
        self.assertIsNone(self.uses(ET.fromstring(rear))["big"], "big has no rear image")
        self.assertNotIn("<use", racks.rack_svg(self.doc(), "rk-a"), "images off by default")

    def test_both_faces_embed_each_file_once(self):
        d = self.doc()
        d["devices"].append(dict(dev("srv2", u=4, side="left", depth="half"), template="t-srv"))
        d["racks"][0]["items"] = []
        root = ET.fromstring(racks.rack_svg(d, "rk-a", face="both", images=True))
        syms = list(root.iter(SVG + "symbol"))
        self.assertEqual(len(syms), 3, "srv front, srv rear, big front")

    def test_budget_and_missing_files(self):
        with mock.patch.object(racks, "IMAGE_BUDGET", 100):
            root = ET.fromstring(racks.rack_svg(self.doc(), "rk-a", images=True))
            u = self.uses(root)
            self.assertIsNotNone(u["srv"])
            self.assertIsNone(u["big"], "over the cap → block")
        (self.root / "acme" / "srv.front.webp").unlink()
        root = ET.fromstring(racks.rack_svg(self.doc(), "rk-a", images=True))
        self.assertIsNone(self.uses(root)["srv"], "missing file → block")

    def test_path_traversal_rejected(self):
        d = self.doc()
        d["templates"][0]["image_front"] = "../" + self.root.name + "-secret.webp"
        d["templates"][1]["image_front"] = "/etc/passwd"
        svg = racks.rack_svg(d, "rk-a", images=True)
        self.assertNotIn("<use", svg)
        self.assertNotIn(__import__("base64").b64encode(b"secret").decode(), svg)
        self.assertNotIn("<image", racks.rack_svg(d, "rk-a", images=True, base_url="/x/"))

    def test_base_url_href(self):
        root = ET.fromstring(racks.rack_svg(self.doc(), "rk-a", images=True, base_url="/fathom/"))
        imgs = {g.get("data-device"): g.find(SVG + "image") for g in root.iter(SVG + "g") if g.get("data-device")}
        self.assertEqual(imgs["srv"].get("href"), "/fathom/static/rack-images/acme/srv.front.webp")
        self.assertIsNone(root.find(SVG + "defs"))


class Schedule(Base):
    def test_item_rows(self):
        d = base_doc(items=[{"id": "ri-1", "type": "drawer", "u": 3, "label": "Mic drawer"}, {"id": "ri-2", "type": "lacing_bar", "u": 1}])
        d["devices"] = [dev("amp", u=8)]
        s = racks.rack_schedule(d)
        self.assertEqual([c["key"] for c in s["columns"]], ["rack", "room", "units", "face", "u", "height", "side", "device", "model"])
        rows = [(r["device"], r["model"], r["face"], r["u"], r["height"], r["side"]) for r in s["rows"]]
        self.assertEqual(rows, [
            ("AMP", "", "front", 8, 1, "full"),
            ("Mic drawer", "Drawer", "front", 3, 2, "full"),
            ("Lacing bar", "Lacing bar", "rear", 1, 1, "full"),
        ])
        self.assertEqual(s["rows"][1]["item_id"], "ri-1")
        self.assertEqual(s["rows"][1]["room"], "Main")

    def test_room_filter_keeps_rack_problems(self):
        d = base_doc(max_load_kg=1, weight_kg=5)
        d["racks"].append({"id": "rk-b", "name": "B", "room": "booth", "units": 4, "max_load_kg": 1, "weight_kg": 2})
        main = racks.rack_schedule(d, room="main")
        self.assertEqual([p["ref"] for p in main["problems"]], ["racks/rk-a"])
        self.assertEqual(len(racks.rack_schedule(d)["problems"]), 2)

    def test_sunday_unchanged(self):
        s = racks.rack_schedule(copy.deepcopy(sunday_doc()))
        self.assertTrue(all("item_id" not in r for r in s["rows"]))


if __name__ == "__main__":
    unittest.main()
