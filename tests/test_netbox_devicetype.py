"""NetBox device-type YAML <-> Fathom templates (fathom.parsers.netbox_devicetype)."""

from __future__ import annotations

import unittest
from unittest import mock

try:
    from _helpers import fixture_path, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import fixture_path, temp_data_dir

import fathom.library as library
from fathom.parsers import mini_yaml
from fathom.parsers import netbox_devicetype as nb

NB = fixture_path("rackula", "netbox")


def _text(name):
    return (NB / name).read_text(encoding="utf-8")


def _ports(t):
    return [(p["id"], p["name"], p["dir"], p["medium"], p.get("connector", ""), int(p.get("channels") or 1), p.get("label", ""))
            for p in library.expand_port_groups(t.get("ports") or [])]


def _strip(t):
    return {k: v for k, v in t.items() if k != "notes"}


class Base(unittest.TestCase):
    def setUp(self):
        self._ctx = temp_data_dir()
        self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)


class ToTemplate(Base):
    def test_pdu(self):
        notes = []
        t = nb.to_template(_text("AP7900B.yaml"), notes)
        self.assertEqual(library.validate_template(t), [])
        self.assertEqual({k: t[k] for k in ("id", "manufacturer", "model", "kind", "part_number", "ru", "full_depth", "airflow", "weight_kg",
                                            "rack_category", "tags")},
                         {"id": "apc-ap7900b", "manufacturer": "APC", "model": "AP7900B", "kind": "power", "part_number": "AP7900B", "ru": 1,
                          "full_depth": False, "airflow": "passive", "weight_kg": 2.25, "rack_category": "power", "tags": ["netbox"]})
        self.assertTrue(t["notes"].startswith("Rack PDU, Switched"))
        self.assertEqual(t["ports"], [
            {"group": "Management", "dir": "io", "medium": "network", "connector": "RJ45"},
            {"group": "Serial", "dir": "io", "medium": "rs232", "connector": "RJ12"},
            {"group": "Power Port 1", "dir": "in", "medium": "power", "connector": "L5-20"},
            {"group": "Power Outlet", "dir": "out", "medium": "power", "connector": "Edison 5-15", "count": 8},
        ])
        self.assertEqual(notes, [])

    def test_switch(self):
        t = nb.to_template(_text("USW-24.yaml"))
        self.assertEqual((t["kind"], t["rack_category"], t["part_number"], t.get("brand")), ("switch", "network", "USW-24", "ubiquiti"))
        self.assertEqual([(g["group"], g["medium"], g.get("connector"), g.get("count")) for g in t["ports"]],
                         [("Port", "network", "RJ45", 24), ("SFP", "fiber", "SFP", 2), ("Input", "power", "IEC C14", None)])
        self.assertEqual(library.validate_template(t), [])

    def test_video_switcher(self):
        t = nb.to_template(_text("atem-constellation-1-m-e-hd.yaml"))
        self.assertEqual((t["kind"], t["rack_category"], t["power_w"], t["airflow"]), ("video_switcher", "av-media", 36.0, "right-to-left"))
        groups = {g["group"]: g for g in t["ports"]}
        self.assertEqual((groups["SDI-INPUT"]["dir"], groups["SDI-INPUT"]["count"], groups["SDI-INPUT"]["connector"]), ("in", 12, "BNC"))
        self.assertEqual((groups["SDI-OUTPUT"]["dir"], groups["SDI-OUTPUT"]["count"]), ("out", 6))
        self.assertEqual(groups["USB0"]["medium"], "usb")
        self.assertEqual(library.validate_template(t), [])

    def test_patch_panel_folds_rear_ports(self):
        t = nb.to_template(_text("24-port-copper-patch-panel-half-depth.yaml"))
        self.assertEqual(t["kind"], "patch_panel")
        self.assertEqual(t["ports"], [{"group": "Port", "dir": "io", "medium": "network", "connector": "RJ45", "count": 24}])
        self.assertFalse(t["full_depth"])

    def test_kind_heuristic(self):
        def kind(extra):
            return nb.to_template(dict({"manufacturer": "Acme", "model": "Box", "slug": "acme-box"}, **extra))["kind"]

        self.assertEqual(kind({"power-outlets": [{"name": "1", "type": "iec-60320-c13"}]}), "power")
        self.assertEqual(kind({"front-ports": [{"name": "1", "type": "8p8c", "rear_port": "1"}], "rear-ports": [{"name": "1", "type": "8p8c"}]}),
                         "patch_panel")
        self.assertEqual(kind({"rear-ports": [{"name": "A", "type": "lc"}], "is_powered": False}), "patch_panel")
        self.assertEqual(kind({"interfaces": [{"name": f"eth{i}", "type": "1000base-t"} for i in range(8)]}), "switch")
        self.assertEqual(kind({"interfaces": [{"name": f"eth{i}", "type": "1000base-t"} for i in range(7)]}), "other")
        self.assertEqual(kind({"interfaces": [{"name": f"eth{i}", "type": "1000base-t", "mgmt_only": i == 0} for i in range(8)]}), "other")
        self.assertEqual(kind({"model": "Edge Router 4"}), "network")
        self.assertEqual(kind({"model": "HyperDeck Studio"}), "recorder")
        self.assertEqual(kind({}), "other")

    def test_units_weight_and_airflow(self):
        notes = []
        t = nb.to_template({"manufacturer": "Acme", "model": "Half", "slug": "acme-half", "u_height": 0.5, "weight": 10, "weight_unit": "lb",
                            "airflow": "sideways"}, notes)
        self.assertEqual((t["ru"], t["weight_kg"]), (1, 4.54))
        self.assertNotIn("airflow", t)
        self.assertIn("u_height 0.5 rounded up to 1U", notes)
        self.assertIn("airflow 'sideways' is not a NetBox value; dropped", notes)
        self.assertEqual(nb.to_template({"manufacturer": "A", "model": "B", "weight": 500, "weight_unit": "g"})["weight_kg"], 0.5)
        self.assertEqual(nb.to_template({"manufacturer": "A", "model": "B", "weight": 16, "weight_unit": "oz"})["weight_kg"], 0.45)
        notes = []
        t = nb.to_template({"manufacturer": "A", "model": "B", "u_height": 70, "weight": 1, "weight_unit": "stone",
                            "module-bays": [{"name": "1"}]}, notes)
        self.assertEqual(t["ru"], 60)
        self.assertNotIn("weight_kg", t)
        self.assertIn("u_height 70 is above 60; capped", notes)
        self.assertIn("module-bays are not imported", notes)

    def test_template_id(self):
        self.assertEqual(nb.to_template({"manufacturer": "A", "model": "B", "slug": "Bad Slug!"})["id"], "a-b")
        self.assertEqual(nb.to_template({"manufacturer": "Acme", "model": "X 1", "slug": "acme_x_1"})["id"], "acme-x-1")

    def test_inputs_and_errors(self):
        text = _text("USW-24.yaml")
        self.assertEqual(nb.to_template(text.encode("utf-8")), nb.to_template(text))
        self.assertEqual(nb.to_template(mini_yaml.loads(text)), nb.to_template(text))
        for bad in ("", "- a\n- b\n", "model: X\n", "manufacturer: A\n", "a: [1\n", 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    nb.to_template(bad)

    def test_rejected_extension_keys_are_stripped(self):
        real = library.validate_template

        def strict(t):
            return ["unknown key airflow"] if "airflow" in t else real(t)

        notes = []
        with mock.patch.object(library, "validate_template", strict):
            t = nb.to_template(_text("USW-24.yaml"), notes)
        for k in ("full_depth", "airflow", "part_number", "rack_category"):
            self.assertNotIn(k, t)
        self.assertTrue(any(n.startswith("dropped full_depth, airflow, part_number, rack_category") for n in notes))


class Ports(unittest.TestCase):
    def test_port_kind(self):
        cases = [
            (("interfaces", "1000base-t"), ("network", "RJ45")),
            (("interfaces", "10gbase-x-sfpp"), ("fiber", "SFP+")),
            (("interfaces", "100gbase-x-qsfp28"), ("fiber", "QSFP28")),
            (("interfaces", "1000base-lx"), ("fiber", "LC")),
            (("interfaces", "virtual"), None),
            (("interfaces", "ieee802.11ax"), None),
            (("interfaces", "xlr-3", "in"), ("analog", "XLR3F")),
            (("interfaces", "xlr-3", "out"), ("analog", "XLR3M")),
            (("interfaces", "speakon"), ("speaker", "NL4")),
            (("interfaces", "sdi-bnc"), ("sdi", "BNC")),
            (("interfaces", "dante"), ("dante", "RJ45")),
            (("interfaces", "other"), ("other", "")),
            (("console-ports", "de-9"), ("rs232", "DB9")),
            (("console-ports", "usb-c"), ("usb", "USB-C")),
            (("power-ports", "iec-60320-c14"), ("power", "IEC C14")),
            (("power-ports", "nema-5-15p"), ("power", "Edison 5-15")),
            (("power-ports", "dc-terminal"), ("power_dc", "terminal")),
            (("power-outlets", "iec-60320-c13"), ("power", "IEC C13")),
            (("power-outlets", "neutrik-powercon-20a"), ("power", "powerCON")),
            (("front-ports", "8p8c"), ("network", "RJ45")),
            (("rear-ports", "lc-apc"), ("fiber", "LC")),
            (("rear-ports", "bnc"), ("sdi", "BNC")),
            (("rear-ports", "xlr-3", "in"), ("analog", "XLR3F")),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(nb.port_kind(*args), want)

    def test_port_groups(self):
        e = lambda name, medium="network", dir_="io", section="interfaces", **kw: dict(name=name, medium=medium, dir=dir_, section=section, **kw)
        groups = nb.port_groups([
            e("eth1"), e("eth2"), e("eth3"), e("eth5"), e("mgmt"), e("ge0"), e("ge1"),
            e("RF Out Ch1", "rf"), e("RF Out Ch2", "rf"), e("In 1", "analog", "in", label="Kick"), e("In 2", "analog", "in", label="Snare"),
            e("1", "power", "out", "power-outlets"), e("2", "power", "out", "power-outlets"), e("3", "power", "out", "power-outlets"),
            e("Port 1", "network", "io", "rear-ports"),
        ])
        self.assertEqual(groups, [
            {"group": "eth", "dir": "io", "medium": "network", "count": 3},
            {"group": "eth5", "dir": "io", "medium": "network"},
            {"group": "mgmt", "dir": "io", "medium": "network"},
            {"group": "ge", "dir": "io", "medium": "network", "names": ["0", "1"]},
            {"group": "RF Out", "dir": "io", "medium": "rf", "names": ["Ch1", "Ch2"]},
            {"group": "In", "dir": "in", "medium": "analog", "count": 2, "labels": ["Kick", "Snare"]},
            {"group": "Outlet", "dir": "out", "medium": "power", "count": 3},
            {"group": "Port 1", "dir": "io", "medium": "network"},
        ])
        ids = [p["id"] for p in library.expand_port_groups(groups)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("rf-out-ch1", ids)

    def test_group_names_unique_across_sections(self):
        e = lambda name, section: {"name": name, "section": section, "medium": "network", "dir": "io"}
        groups = nb.port_groups([e("Port 1", "interfaces"), e("Port 1", "rear-ports"), e("Port 1", "front-ports")])
        self.assertEqual([g["group"] for g in groups], ["Port 1", "Rear Port 1", "Front Port 1"])


class FromTemplate(Base):
    def test_fixtures_round_trip(self):
        for name in sorted(p.name for p in NB.glob("*.yaml")):
            with self.subTest(name=name):
                t = nb.to_template(_text(name))
                y = nb.from_template(t)
                self.assertTrue(y.startswith("---\n"))
                self.assertIsInstance(mini_yaml.loads(y), dict)
                self.assertEqual(_strip(nb.to_template(y)), _strip(t))

    def test_library_templates_round_trip_ports(self):
        templates = library.list_templates()
        self.assertGreater(len(templates), 10)
        for s in templates:
            t = library.get_template(s["id"])
            with self.subTest(id=t["id"]):
                back = nb.to_template(nb.from_template(t))
                self.assertEqual(sorted(_ports(back)), sorted(_ports(t)))
                self.assertEqual((back["id"], back["manufacturer"], back.get("ru")), (t["id"], t.get("manufacturer") or "Generic", t.get("ru")))
                self.assertEqual(library.validate_template(back), [])

    def test_patch_panel_preset(self):
        t = library.get_template("generic-patch-panel-copper")
        if t is None:
            self.skipTest("patch panel preset not present")
        doc = mini_yaml.loads(nb.from_template(t))
        self.assertIs(doc["is_powered"], False)
        self.assertEqual(len(doc["front-ports"]), len(doc["rear-ports"]))
        self.assertEqual(len(doc["port-mappings"]), len(doc["front-ports"]))
        self.assertEqual(doc["port-mappings"][0], {"front_port": doc["front-ports"][0]["name"], "front_port_position": 1,
                                                   "rear_port": doc["rear-ports"][0]["name"], "rear_port_position": 1})
        self.assertEqual(nb.to_template(nb.from_template(t))["kind"], "patch_panel")

    def test_written_fields(self):
        t = {"id": "acme-amp", "manufacturer": "Acme", "model": "Amp 4", "kind": "amp", "ru": 2, "full_depth": True, "airflow": "front-to-rear",
             "weight_kg": 12.5, "power_w": 450, "part_number": "AMP-4", "notes": "Four channels",
             "ports": [{"group": "In", "dir": "in", "medium": "analog", "connector": "XLR3F", "count": 4},
                       {"group": "Out", "dir": "out", "medium": "speaker", "connector": "NL4", "count": 2},
                       {"group": "Dante", "dir": "io", "medium": "dante", "connector": "etherCON", "channels": 8},
                       {"group": "Mains", "dir": "in", "medium": "power", "connector": "powerCON"}]}
        doc = mini_yaml.loads(nb.from_template(t))
        self.assertEqual({k: doc[k] for k in ("manufacturer", "model", "slug", "part_number", "u_height", "is_full_depth", "airflow", "weight",
                                              "weight_unit", "comments")},
                         {"manufacturer": "Acme", "model": "Amp 4", "slug": "acme-amp", "part_number": "AMP-4", "u_height": 2,
                          "is_full_depth": True, "airflow": "front-to-rear", "weight": 12.5, "weight_unit": "kg", "comments": "Four channels"})
        self.assertEqual(doc["power-ports"], [{"name": "Mains", "type": "neutrik-powercon-20", "allocated_draw": 450}])
        self.assertEqual(doc["interfaces"][0]["type"], "1000base-t")
        self.assertIn("medium=dante", doc["interfaces"][0]["description"])
        self.assertIn("channels=8", doc["interfaces"][0]["description"])
        self.assertEqual([(p["name"], p["type"]) for p in doc["rear-ports"][:2]], [("In 1", "other"), ("In 2", "other")])
        self.assertEqual(doc["rear-ports"][0]["description"], "fathom: medium=analog connector=XLR3F")
        back = nb.to_template(nb.from_template(t))
        self.assertEqual(sorted(_ports(back)), sorted(_ports(t)))
        self.assertEqual((back["power_w"], back["weight_kg"], back["airflow"]), (450.0, 12.5, "front-to-rear"))

    def test_not_a_template(self):
        for bad in (None, {}, {"model": "x"}, "x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    nb.from_template(bad)


if __name__ == "__main__":
    unittest.main()
