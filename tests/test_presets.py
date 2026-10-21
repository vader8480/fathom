"""Device type presets (``fathom.presets``): data integrity, library / API exposure, CSV ``kind`` resolution."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from _helpers import call, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

#: every device type the presets must cover (keyword that has to appear in some preset id / label / alias)
REQUIRED_TYPES = [
    "ups", "pdu", "patch panel copper", "patch panel fibre", "network switch", "router", "firewall", "access point", "server",
    "nas", "storage", "kvm", "media converter", "dante", "aes67", "stagebox", "io rack", "audio console", "amplifier", "dsp",
    "wireless mic receiver", "iem transmitter", "video switcher", "projector", "display", "camera", "encoder", "decoder",
    "lighting console", "dimmer", "relay", "dmx node",
]


def _texts(p):
    return [p["id"], p["label"]] + list(p.get("aliases") or [])


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


class PresetData(unittest.TestCase):
    def setUp(self):
        self.presets = requires("presets")
        self.vocab = requires("vocab")
        self.library = requires("library")
        self.schema = requires("schema")

    def test_count_and_required_types(self):
        ps = self.presets.all_presets()
        self.assertGreaterEqual(len(ps), 26, "at least the 26 requested device types")
        hay = [" ".join(_norm(t) for t in _texts(p)) for p in ps]
        missing = [t for t in REQUIRED_TYPES if not any(all(w in h for w in _norm(t).split()) for h in hay)]
        self.assertEqual(missing, [], "presets missing for device types")

    def test_ids_labels_aliases_unique(self):
        ps = self.presets.all_presets()
        ids = [p["id"] for p in ps]
        self.assertEqual(len(ids), len(set(ids)), "preset ids unique")
        for pid in ids:
            self.assertRegex(pid, r"^[a-z0-9][a-z0-9-]{1,79}$", "template id pattern")
        labels = [_norm(p["label"]) for p in ps]
        self.assertEqual(len(labels), len(set(labels)), "labels unique")
        seen = {}
        for p in ps:
            for a in p["aliases"]:
                n = _norm(a)
                self.assertTrue(n, "empty alias on %s" % p["id"])
                self.assertNotIn(n, seen, "alias %r on %s already used by %s" % (a, p["id"], seen.get(n)))
                seen[n] = p["id"]

    def test_fields_valid(self):
        K, M, C = self.vocab.KINDS, self.vocab.MEDIA, set(self.vocab.CONNECTORS)
        for p in self.presets.all_presets():
            with self.subTest(preset=p["id"]):
                self.assertIn(p["kind"], K, "kind must be a vocabulary kind (no new kinds)")
                self.assertIn(p["group"], self.presets.GROUPS)
                self.assertTrue(p["description"].strip())
                self.assertTrue(p["aliases"], "needs at least one alias")
                ru = p.get("ru")
                self.assertTrue(ru is None or (isinstance(ru, int) and 1 <= ru <= 60), "ru %r" % ru)
                self.assertTrue(p["ports"], "needs default ports")
                for g in p["ports"]:
                    self.assertIn(g["dir"], self.vocab.PORT_DIRS)
                    self.assertIn(g["medium"], M, "unknown medium %r" % g.get("medium"))
                    if g.get("connector"):
                        self.assertIn(g["connector"], C, "unknown connector %r" % g["connector"])
                    if g.get("count") is not None:
                        self.assertTrue(1 <= g["count"] <= 512)
                ids = [x["id"] for x in self.schema.expand_port_groups(p["ports"])]
                self.assertEqual(len(ids), len(set(ids)), "expanded port ids unique")
                if p.get("routing"):
                    self.assertIn(p["routing"], self.vocab.ROUTING_MODES)
                if p.get("width"):
                    self.assertIn(p["width"], ("full", "half"))

    def test_sensible_defaults(self):
        get = self.presets.get_preset

        def count(pid, group):
            g = next(x for x in get(pid)["ports"] if x["group"] == group)
            return len(g["names"]) if g.get("names") else g.get("count", 1)

        self.assertEqual(count("generic-switch-24", "Port"), 24)
        self.assertEqual(count("generic-switch-48", "Port"), 48)
        self.assertEqual(count("generic-pdu", "Outlet"), 8)
        self.assertEqual(count("generic-ups", "Mains In"), 1)
        self.assertGreaterEqual(count("generic-ups", "Outlet"), 4)
        self.assertEqual(count("generic-patch-panel-copper", "Port"), 24)
        self.assertEqual(count("generic-patch-panel-fibre", "Port"), 24)
        self.assertEqual(get("generic-patch-panel-fibre")["ports"][0]["medium"], "fiber")
        self.assertEqual(get("generic-ups")["ru"], 2)
        self.assertEqual(get("generic-pdu")["ru"], 1)
        self.assertIsNone(get("generic-wifi-ap")["ru"], "an access point is not rack-mounted")
        self.assertTrue(get("generic-dante-interface")["dante"])
        self.assertTrue(get("generic-stagebox")["dante"])
        self.assertEqual(get("generic-dimmer-pack")["dmx_footprint"], 6)
        self.assertEqual(get("generic-media-converter")["width"], "half")
        self.assertEqual(get("generic-patch-panel-copper")["kind"], "patch_panel")
        self.assertEqual(get("generic-lighting-console")["kind"], "lighting_console")

    def test_templates_validate_and_instantiate(self):
        for p in self.presets.all_presets():
            t = self.presets.as_template(p)
            self.assertEqual(self.library.validate_template(t), [], "preset %s as template" % p["id"])
            self.assertEqual((t["id"], t["manufacturer"], t["source"]), (p["id"], "Generic", "preset"))
            self.assertIn("preset", t["tags"])
            self.assertIsNone(t["cost"])
            dev = self.library.instantiate(t, device_id="x-" + p["id"], room="main")
            self.assertEqual((dev["kind"], dev["template"]), (p["kind"], p["id"]))
            self.assertEqual(len(dev["ports"]), len(self.schema.expand_port_groups(p["ports"])))
            if p.get("dante"):
                self.assertTrue(dev["dante"])
            if p.get("dmx_footprint"):
                self.assertEqual(dev["dmx"]["footprint"], p["dmx_footprint"])
        self.assertEqual(json.loads(json.dumps(self.presets.as_dict()))["groups"], list(self.presets.GROUPS))

    def test_find_and_resolve_kind(self):
        f, r = self.presets.find_preset, self.presets.resolve_kind
        self.assertEqual(f("UPS")["id"], "generic-ups")
        self.assertEqual(f("Patch panel")["id"], "generic-patch-panel-copper")
        self.assertEqual(f("Fiber patch panel")["id"], "generic-patch-panel-fibre")
        self.assertEqual(f("wireless access point")["id"], "generic-wifi-ap")
        self.assertEqual(f("Routers")["id"], "generic-router", "plural")
        self.assertEqual(f("generic-nas")["id"], "generic-nas")
        self.assertIsNone(f("laser"))
        self.assertIsNone(f(""))
        # vocabulary kinds (keys and labels) win and never pull in preset ports
        self.assertEqual(r("switch"), ("switch", None))
        self.assertEqual(r("Video switchers"), ("video_switcher", None))
        self.assertEqual(r("video-switcher"), ("video_switcher", None))
        self.assertEqual(r("patch panel"), ("patch_panel", None))
        # presets fill the gaps
        self.assertEqual(r("ups"), ("power", "generic-ups"))
        self.assertEqual(r("PDU"), ("power", "generic-pdu"))
        self.assertEqual(r("Network switch"), ("switch", "generic-switch-24"))
        self.assertEqual(r("access point"), ("network", "generic-wifi-ap"))
        self.assertEqual(r("copper patch panel"), ("patch_panel", "generic-patch-panel-copper"))
        self.assertEqual(r("laser"), ("", None))

    def test_library_exposes_presets_lowest_precedence(self):
        with temp_data_dir() as data:
            lib = self.library.load_library(refresh=True)
            for p in self.presets.PRESETS:
                self.assertIn(p["id"], lib)
                self.assertEqual(lib[p["id"]]["source"], "preset")
            self.assertEqual(lib["generic-pdu-8"]["source"], "builtin", "file templates untouched")
            self.assertIn("generic-ups", [t["id"] for t in self.library.list_templates(q="ups")])
            # a global custom template with a preset id shadows the preset
            custom = dict(self.presets.as_template(self.presets.get_preset("generic-ups")))
            custom.pop("source")
            custom["model"] = "My UPS"
            self.library.save_custom_template(custom)
            lib = self.library.load_library(refresh=True)
            self.assertEqual((lib["generic-ups"]["source"], lib["generic-ups"]["model"]), ("custom", "My UPS"))
            self.library.delete_custom_template("generic-ups")
            self.assertEqual(self.library.load_library(refresh=True)["generic-ups"]["source"], "preset")


class PresetApi(unittest.TestCase):
    def setUp(self):
        self.presets = requires("presets")
        self.app = get_app()
        ctx = temp_data_dir()
        self.data = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        install_sunday(self.data, "sunday-demo")

    def test_get_presets(self):
        st, h, b = call(self.app, "GET", "/api/v2/presets", None, {})
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        self.assertEqual(j["groups"], list(self.presets.GROUPS))
        self.assertEqual([p["id"] for p in j["presets"]], [p["id"] for p in self.presets.PRESETS])
        for k in ("id", "label", "group", "kind", "description", "aliases", "ru", "ports"):
            self.assertIn(k, j["presets"][0])

    def test_library_routes_serve_presets_and_protect_them(self):
        st, _, b = call(self.app, "GET", "/api/v2/library/generic-switch-24", None, {})
        self.assertEqual(st, 200, b[:300])
        t = jbody(b)
        self.assertEqual((t["kind"], t["ru"], t["source"]), ("switch", 1, "preset"))
        st, _, b = call(self.app, "GET", "/api/v2/library?q=patch+panel", None, {})
        ids = [x["id"] for x in jbody(b)["templates"]]
        self.assertIn("generic-patch-panel-copper", ids)
        self.assertIn("generic-patch-panel-fibre", ids)
        st, _, b = call(self.app, "DELETE", "/api/v2/library/generic-switch-24", None, {"X-Fathom": "1"})
        self.assertEqual(st, 409, "presets cannot be deleted")
        body = dict(self.presets.as_template(self.presets.get_preset("generic-switch-24")))
        body.pop("source")
        st, _, b = call(self.app, "POST", "/api/v2/library", body, {"X-Fathom": "1", "Content-Type": "application/json"})
        self.assertEqual(st, 409, "saving over a preset id needs ?override=1: %s" % b[:200])
        st, _, b = call(self.app, "POST", "/api/v2/library?override=1", body, {"X-Fathom": "1", "Content-Type": "application/json"})
        self.assertEqual(st, 201, b[:200])

    def test_openapi_lists_route(self):
        st, _, b = call(self.app, "GET", "/api/openapi.json", None, {})
        self.assertEqual(st, 200)
        self.assertIn("/api/v2/presets", jbody(b)["paths"])


class PresetCsvKind(unittest.TestCase):
    def setUp(self):
        requires("parsers.generic_csv")
        self.plugins = requires("plugins")
        self.library = requires("library")

    def preview(self, text):
        imp = self.plugins.get_importer("csv")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "devices.csv"
            path.write_text(text, encoding="utf-8")
            res = imp.parse(path)
            with temp_data_dir():
                return imp.preview(res, copy.deepcopy(sunday_doc()), {"room": "main", "device": "", "import": None})

    def test_kind_column_accepts_presets(self):
        p = self.preview("name,kind,room\nRack UPS,ups,main\nEdge,Router / firewall,main\nPlain switch,switch,main\nOdd,laser,main\n")
        puts = {o["value"]["name"]: o["value"] for o in p["ops"] if o["op"] == "put"}
        ups = puts["Rack UPS"]
        self.assertEqual((ups["kind"], ups["template"]), ("power", "generic-ups"))
        self.assertEqual(sum(1 for x in ups["ports"] if x["group"] == "Outlet"), 6, "preset ports instantiated")
        edge = puts["Edge"]
        self.assertEqual((edge["kind"], edge["template"]), ("network", "generic-router"))
        plain = puts["Plain switch"]
        self.assertEqual(plain["kind"], "switch")
        self.assertNotIn("template", plain, "a vocabulary kind stays a plain device")
        self.assertEqual(plain["ports"], [])
        self.assertEqual(puts["Odd"]["kind"], "laser", "unknown kinds are preserved (FR-VOC-07)")

    def test_explicit_template_column_wins(self):
        p = self.preview("name,kind,template\nFOH UPS,ups,generic-pdu-8\n")
        dev = [o["value"] for o in p["ops"] if o["op"] == "put"][0]
        self.assertEqual((dev["kind"], dev["template"]), ("power", "generic-pdu-8"))
        self.assertEqual(sum(1 for x in dev["ports"] if x["group"] == "Outlet"), 8)

    def test_existing_device_keeps_its_ports(self):
        doc = sunday_doc()
        name = doc["devices"][0]["name"]
        p = self.preview("name,kind\n%s,ups\n" % name)
        merges = [o for o in p["ops"] if o["op"] == "merge"]
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["value"].get("kind"), "power")
        self.assertNotIn("template", merges[0]["value"], "matching an existing device never re-templates it")


if __name__ == "__main__":
    unittest.main()
