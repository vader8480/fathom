"""Importers, plugin registry, library, floor-plan conversion (SPEC §3.25, §3.22, §3.13, §3.8, §7.4.2)."""

from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from _helpers import (CAMPUS_DIR, RRC_DIR, call, fixture_path, fr, get_app, install_project, install_rrc, jbody, load_fixture,
                          png_bytes, read_json, requires, rrc_dict, sunday_doc, temp_data_dir, temp_env, uniq, upload)
except ImportError:  # pragma: no cover
    from tests._helpers import (CAMPUS_DIR, RRC_DIR, call, fixture_path, fr, get_app, install_project, install_rrc, jbody, load_fixture,
                                png_bytes, read_json, requires, rrc_dict, sunday_doc, temp_data_dir, temp_env, uniq, upload)

IMP = fixture_path("imports")
APPENDIX_E = [
    "yamaha-cl5", "yamaha-ql5", "yamaha-dm7", "yamaha-dm7-compact", "yamaha-tf-rack", "yamaha-rio3224-d2", "yamaha-rio1608-d2", "shure-ulxd4q",
    "shure-ulxd4d", "shure-ad4q", "shure-p10t", "shure-ulxd2-sm58", "shure-sm58", "focusrite-rednet-am2", "focusrite-rednet-mp8r",
    "focusrite-rednet-a16r-mkii", "allen-heath-sq-5", "allen-heath-ar84", "allen-heath-dlive-dm32", "behringer-x32", "behringer-wing",
    "behringer-s32", "midas-m32", "digico-sd12", "l-acoustics-la12x", "l-acoustics-la7-16i", "powersoft-x8", "qsc-core-110f", "qsc-k12-2",
    "blackmagic-atem-mini-pro", "blackmagic-atem-mini-pro-iso", "blackmagic-atem-1me-constellation-hd", "blackmagic-videohub-20x20-12g",
    "blackmagic-web-presenter-hd", "ross-ultrix-fr1", "decimator-md-hx", "panasonic-aw-ue150", "sony-srg-x400", "epson-eb-pu2010",
    "panasonic-pt-req12", "samsung-qb65c", "etc-ion-xe-20", "etc-eos-apex-10", "etc-colorsource-20", "ma-grandma3-light",
    "chauvet-maverick-storm-2-profile", "martin-mac-aura-pxl", "etc-source-four-lustr-x8", "etc-sensor3-48", "etc-response-mk2-4port",
    "cisco-catalyst-9200-24p", "netgear-m4250-26g4f-poe", "ubiquiti-usw-pro-24-poe", "extron-ipcp-pro-350", "crestron-cp4n",
]
REQUIRED_TEMPLATES = ["shure-ulxd4d", "allen-heath-sq-5", "allen-heath-ar84", "blackmagic-atem-mini-pro", "qsc-k12-2", "decimator-md-hx",
                      "yamaha-rio3224-d2", "yamaha-rio1608-d2", "blackmagic-videohub-20x20-12g"]


def importer_for(path):
    plugins = requires("plugins")
    kind = plugins.detect(Path(path))
    imp = plugins.get_importer(kind)
    return kind, imp


def contribute(path, doc, room="main", device="", kind=None, **opts):
    plugins = requires("plugins")
    if kind is None:
        kind, imp = importer_for(path)
    else:
        imp = plugins.get_importer(kind)
    if imp is None or imp.contribute is None:
        raise AssertionError("no contributing importer for %s (detected %r)" % (path, kind))
    res = imp.parse(Path(path), **opts)
    ctx = {"import": {"id": "imp-0099", "kind": kind, "path": str(path), "room": room, "device": device}, "room": room, "device": device}
    return kind, imp.contribute(res, copy.deepcopy(doc), ctx)


def dmx_of(contrib, dev):
    """DMX for a device: contribution['dmx'][dev] or the overlay device's own 'dmx'."""
    d = (contrib.get("dmx") or {}).get(dev)
    if d:
        return d
    for x in contrib.get("devices") or []:
        if x.get("id") == dev and x.get("dmx"):
            return x["dmx"]
    return None


def lighting_doc():
    d = sunday_doc()
    d["devices"].append({"id": "front-l", "name": "Front Left Par", "kind": "fixture", "room": "main", "ports": [], "dmx": {"channel": "1"}})
    d["devices"].append({"id": "front-r", "name": "Front R", "kind": "fixture", "room": "main", "ports": []})
    return d


# ================================================================== registry & legacy importers


class Registry(unittest.TestCase):
    def setUp(self):
        self.plugins = requires("plugins")

    def test_plugin_registry(self):
        kinds = [i.kind for i in self.plugins.importers()]
        for k in ("yamaha", "dante", "waves", "eos", "magicq", "videohub", "csv"):
            self.assertIn(k, kinds, fr("FR-EXT-01", "7.4.2", "built-in importer %s registered" % k))
        imp = self.plugins.get_importer("dante")
        for f in ("kind", "label", "detect", "parse", "contribute", "preview", "mode", "accepts", "folder", "help", "source"):
            self.assertTrue(hasattr(imp, f), "7.4.2 Importer.%s" % f)
        self.assertEqual(self.plugins.get_importer("csv").mode, "oneshot", "7.4.2 generic CSV is one-shot")
        self.assertIsNotNone(self.plugins.get_importer("csv").preview)
        self.assertIsNone(self.plugins.get_importer("nope-nope"))
        self.assertTrue(self.plugins.get_importer("yamaha").folder, "Yamaha CL exports are a folder")

    def test_legacy_parse_counts(self):
        from fathom.parsers import parse_any

        v02 = load_fixture("v02-parse-summaries.json")
        for rel, exp in v02.items():
            with self.subTest(file=rel):
                p = RRC_DIR / "exports" / rel
                for label, res in (("parse_any", parse_any(p)), ("registry", self.plugins.get_importer(exp["kind"]).parse(p))):
                    got = json.loads(json.dumps(res.summary(), default=str))
                    sub = {k: got.get(k) for k in exp["summary"]}
                    self.assertEqual(sub, exp["summary"], fr("FR-IMP-01", "3.25", "%s (%s) parses identically to v0.2" % (rel, label)))

    def test_detect_kind(self):
        from fathom.parsers import detect_kind

        v02 = load_fixture("v02-parse-summaries.json")
        for rel, exp in v02.items():
            self.assertEqual(detect_kind(RRC_DIR / "exports" / rel), exp["kind"], "2.3 item 6 detect_kind %s" % rel)
            self.assertEqual(self.plugins.detect(RRC_DIR / "exports" / rel), exp["kind"])
        self.assertEqual(self.plugins.detect(IMP / "eos-show.csv"), "eos", "FR-IMP-03 detect Eos CSV")
        self.assertEqual(self.plugins.detect(IMP / "show.asc"), "eos", "FR-IMP-04 detect USITT ASCII")
        self.assertEqual(self.plugins.detect(IMP / "videohub-dump.txt"), "videohub", "FR-IMP-07 detect Videohub dump")
        self.assertEqual(self.plugins.detect(fixture_path("csv", "devices.csv")), "csv", "FR-IMP-08 detect generic CSV")
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "junk.bin"
            junk.write_bytes(b"\x00\x01\x02 nothing here")
            self.assertEqual(self.plugins.detect(junk), "unknown")
            self.assertEqual(detect_kind(junk), "unknown")
        if CAMPUS_DIR.exists():
            ex = CAMPUS_DIR / "exports"
            for rel, kind in (("eos/main-patch.csv", "eos"), ("eos/chapel.asc", "eos"), ("videohub/broadcast-router.txt", "videohub"),
                              ("csv/devices.csv", "csv"), ("dante/campus-preset.xml", "dante")):
                if (ex / rel).exists():
                    self.assertEqual(self.plugins.detect(ex / rel), kind, "campus sample %s" % rel)

    def test_legacy_overlay_rrc(self):
        merge = requires("merge:build_overlay")
        schema = requires("schema")
        with temp_data_dir() as data:
            pdir = install_rrc(data, "rrc")
            doc = schema.migrate(rrc_dict())
            before = copy.deepcopy(doc)
            ov = merge(doc, pdir)
            self.assertEqual(doc, before, "4.11 build_overlay never mutates the doc")
            dante = [r for r in ov["routes"] if r.get("kind") == "dante"]
            self.assertGreater(len(dante), 200, fr("FR-IMP-01", "3.25", "RRC overlay has > 200 dante routes (got %d)" % len(dante)))
            ids = {d["id"] for d in doc["devices"]}
            extra = {e["id"] for e in doc["rooms"][0]["flow"].get("extra_cards", [])}
            for r in dante:
                self.assertIn(r["from"]["device"], ids | {d["id"] for d in ov["devices"]}, "4.11 routes reference canonical devices")
                self.assertNotIn(r["from"]["device"], extra)
                self.assertNotIn(r["to"]["device"], extra)
            for d in ov["devices"]:
                self.assertTrue(d.get("auto"), "4.11 overlay devices are auto")
            self.assertIn("foh", ov["detail"], "4.11 detail lifted from legacy importers")
            json.dumps(ov)

    def test_plugin_dir_registers(self):
        with temp_data_dir() as data:
            pdir = data / "plugins"
            pdir.mkdir()
            (pdir / "t1dummy.py").write_text(
                "from fathom.plugins import Importer\n"
                "def register(api):\n"
                "    api.register_importer(Importer(kind='dummy', label='T1 dummy', detect=lambda p: 0.0, parse=lambda p, **k: None,"
                " source='plugin'))\n")
            (pdir / "t1broken.py").write_text("def register(api):\n    raise RuntimeError('t1 broken plugin')\n")
            with temp_env(FATHOM_PLUGINS=str(pdir)), contextlib.redirect_stderr(io.StringIO()):
                loaded = self.plugins.load_plugins([str(pdir)])
                self.assertTrue(any("t1dummy" in m for m in loaded), fr("FR-EXT-01", "3.22", "plugin module loaded: %s" % loaded))
                self.assertIsNotNone(self.plugins.get_importer("dummy"), fr("FR-EXT-01", "3.22"))
                self.assertTrue([e for e in self.plugins.plugin_errors() if "t1broken" in e or "t1 broken" in e], fr("FR-EXT-01", "3.22", "errors listed"))
                self.plugins.load_plugins([str(pdir)])  # idempotent
                self.assertEqual(len([i for i in self.plugins.importers() if i.kind == "dummy"]), 1)
                st, _, b = call(get_app(), "GET", "/api/v2/meta")
                meta = jbody(b)
                self.assertIn("dummy", [i["kind"] for i in meta["importers"]], fr("FR-EXT-01", "3.22", "plugin importer in /api/v2/meta"))
                self.assertTrue([e for e in meta["plugins_errors"] if "t1" in e], fr("FR-EXT-01", "3.22", "plugins_errors in /api/v2/meta"))

    def test_plugin_api(self):
        api = self.plugins.PluginAPI() if callable(getattr(self.plugins, "PluginAPI", None)) else None
        self.assertIsNotNone(api, "7.4.2 PluginAPI")
        self.assertIsInstance(api.version, str, fr("FR-EXT-02", "3.22"))
        with tempfile.TemporaryDirectory() as tmp:
            api.register_template_dir(tmp)
            self.assertIn(Path(tmp).resolve(), [Path(p).resolve() for p in self.plugins.template_dirs()], fr("FR-EXT-02", "3.22"))
            api.register_checklist_dir(tmp)
            self.assertIn(Path(tmp).resolve(), [Path(p).resolve() for p in self.plugins.checklist_dirs()], fr("FR-EXT-02", "3.22"))
            self.assertTrue(callable(api.register_importer))

    def test_cli_plugins(self):
        cli = requires("cli")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(["plugins"])
            except SystemExit as e:
                self.assertIn(e.code, (0, None))
        text = out.getvalue()
        for k in ("yamaha", "dante", "waves", "eos", "videohub", "csv"):
            self.assertIn(k, text, fr("FR-EXT-05", "3.22", "fathom plugins lists %s" % k))


# ================================================================== new importers


class Lighting(unittest.TestCase):
    def setUp(self):
        requires("parsers.eos")

    def test_eos_csv(self):
        kind, c = contribute(IMP / "eos-show.csv", lighting_doc())
        self.assertEqual(kind, "eos")
        self.assertEqual(dmx_of(c, "front-l"), dict(dmx_of(c, "front-l") or {}, universe=1, address=101, footprint=8, channel="1", source="eos") if dmx_of(c, "front-l") else None,
                         fr("FR-IMP-03", "3.25", "channel 1 absolute address 101, footprint 8"))
        fr_ = dmx_of(c, "front-r")
        self.assertIsNotNone(fr_, fr("FR-IMP-06", "3.25", "matched by name = Label"))
        self.assertEqual((fr_["universe"], fr_["address"], fr_["footprint"]), (1, 9, 8), fr("FR-IMP-03", "3.25", "'1/9' -> u1 a9"))
        autos = [d for d in c.get("devices", []) if d.get("auto")]
        self.assertEqual(len(autos), 2, fr("FR-IMP-06", "3.25", "two unmatched channels -> two auto fixtures"))
        got = sorted((dmx_of(c, d["id"])["universe"], dmx_of(c, d["id"])["address"], dmx_of(c, d["id"])["footprint"]) for d in autos)
        self.assertEqual(got, [(2, 1, 14), (3, 1, 14)], fr("FR-IMP-03", "3.25", "'2.1' and absolute 1025 -> u2a1, u3a1; footprint = max offset + 1"))
        for d in autos:
            self.assertEqual((d["kind"], d["room"], d.get("source")), ("fixture", "main", "eos"), fr("FR-IMP-06", "3.25"))

    def test_usitt_ascii(self):
        kind, c = contribute(IMP / "show.asc", sunday_doc(), kind="eos")
        rows = {}
        for dev, d in (c.get("dmx") or {}).items():
            rows[str(d.get("channel"))] = (d["universe"], d["address"])
        for d in c.get("devices", []):
            if d.get("dmx"):
                rows[str(d["dmx"].get("channel"))] = (d["dmx"]["universe"], d["dmx"]["address"])
        self.assertEqual(rows.get("5"), (1, 8), fr("FR-IMP-04", "3.25", "channel 5 -> 1/8"))
        self.assertEqual(rows.get("2"), (1, 9), fr("FR-IMP-04", "3.25", "channel 2 -> 1/9"))
        self.assertEqual(rows.get("7"), (2, 8), fr("FR-IMP-04", "3.25", "dimmer 520 = absolute -> 2/8"))
        self.assertNotIn("0", rows, fr("FR-IMP-04", "3.25", "channel 0 = unpatched"))
        self.assertNotIn("9", rows, fr("FR-IMP-04", "3.25", "ENDDATA stops"))

    def test_lightwright_text(self):
        kind, c = contribute(IMP / "lightwright.txt", sunday_doc(), kind="eos")
        blob = json.dumps(c)
        for s in ("FOH Truss", "Center Special", "Stage Left Wash"):
            self.assertIn(s, blob, fr("FR-IMP-05", "3.25", "position/unit/purpose carried: %s" % s))
        autos = [d for d in c.get("devices", []) if d.get("auto")]
        self.assertEqual(len(autos), 2)
        got = sorted((dmx_of(c, d["id"])["universe"], dmx_of(c, d["id"])["address"]) for d in autos)
        self.assertEqual(got, [(2, 101), (2, 109)], fr("FR-IMP-05", "3.25", "'u/a' Universe Address"))

    def test_lighting_contribution_matching(self):
        kind, c = contribute(IMP / "eos-show.csv", lighting_doc())
        ids = {d["id"] for d in lighting_doc()["devices"]}
        autos = [d for d in c.get("devices", []) if d.get("auto")]
        self.assertTrue(all(d["id"] not in ids for d in autos), "auto devices get fresh ids")
        self.assertIsNotNone(dmx_of(c, "front-l"), fr("FR-IMP-06", "3.25", "matched by dmx.channel"))
        self.assertIsNotNone(dmx_of(c, "front-r"), fr("FR-IMP-06", "3.25", "matched by name"))
        self.assertEqual(len(autos), 2, fr("FR-IMP-06", "3.25", "overlay device count equals unmatched fixtures"))

    def test_eos_overlay_dmx(self):
        merge = requires("merge:build_overlay")
        dmx = requires("dmx")
        with temp_data_dir() as data:
            doc = lighting_doc()
            pdir = install_project(data, "lx", doc=doc)
            (pdir / "exports" / "eos").mkdir(parents=True)
            shutil.copy(str(IMP / "eos-show.csv"), str(pdir / "exports" / "eos" / "show.csv"))
            doc["imports"] = [{"id": "imp-0001", "kind": "eos", "path": "exports/eos/show.csv", "room": "main"}]
            doc["devices"][-2]["dmx"] = {"channel": "1", "universe": 5, "address": 1, "footprint": 4}
            ov = merge(doc, pdir)
            srcs = {k: v.get("source") for k, v in ov["dmx"].items()}
            self.assertTrue(srcs and all(s == "eos" for s in srcs.values()), fr("FR-DMX-03", "3.12", "overlay dmx rows source eos: %s" % srcs))
            sched = dmx.dmx_schedule(doc, ov)
            rows = sched["rows"]
            self.assertTrue([r for r in rows if r.get("source") == "eos"], fr("FR-DMX-03", "3.12"))
            fl = [r for r in rows if r.get("device_id", r.get("device")) in ("front-l", "Front Left Par")]
            self.assertTrue(fl and fl[0]["universe"] == 5 and fl[0].get("source") in ("manual", "", None), fr("FR-DMX-03", "3.12", "manual wins: %s" % fl))


class Video(unittest.TestCase):
    def setUp(self):
        requires("parsers.videohub")

    def _doc_with_router(self, name="Router", dev_id="vhub"):
        library = requires("library")
        d = sunday_doc()
        t = library.get_template("blackmagic-videohub-20x20-12g")
        dev = library.instantiate(t, device_id=dev_id, name=name, room="main")
        d["devices"].append(dev)
        return d

    def test_videohub_dump(self):
        kind, c = contribute(IMP / "videohub-dump.txt", self._doc_with_router(), device="vhub")
        self.assertEqual(kind, "videohub")
        labels = (c.get("port_labels") or {}).get("vhub", {})
        self.assertEqual(len(labels), 40, fr("FR-IMP-07", "3.25", "20x20 sample yields 40 labels"))
        self.assertEqual(labels.get("sdi-in-1"), "CAM 1", fr("FR-IMP-07", "3.25", "zero-based -> sdi-in-<n+1>"))
        self.assertEqual(labels.get("sdi-out-1"), "Program")
        routes = [r for r in c.get("routes", []) if r["to"]["device"] == "vhub"]
        self.assertEqual(len(routes), 20, fr("FR-IMP-07", "3.25", "20 routes"))
        r2 = [r for r in routes if r["to"]["port"] == "sdi-out-2"][0]
        self.assertEqual(r2["from"], {"device": "vhub", "port": "sdi-in-4"}, fr("FR-IMP-07", "3.25", "routing 'o i' -> sdi-in-<i+1> -> sdi-out-<o+1>"))
        self.assertEqual(r2.get("kind"), "videohub")

    def test_videohub_target_resolution(self):
        kind, c = contribute(IMP / "videohub-dump.txt", self._doc_with_router(name="Broadcast Router", dev_id="bc"))
        self.assertEqual(len((c.get("port_labels") or {}).get("bc", {})), 40, fr("FR-IMP-07", "3.25", "matched by friendly name"))
        kind, c = contribute(IMP / "videohub-dump.txt", sunday_doc())
        autos = [d for d in c.get("devices", []) if d.get("auto")]
        self.assertEqual(len(autos), 1, fr("FR-IMP-07", "3.25", "else auto device from the Videohub template"))
        self.assertIn("sdi-in-20", [p["id"] for p in autos[0]["ports"]])
        self.assertEqual(len(c["port_labels"][autos[0]["id"]]), 40)

    def test_atem_xml(self):
        requires("parsers.atem")
        kind, c = contribute(IMP / "atem-settings.xml", sunday_doc(), device="atem-mini", kind="atem")
        labels = (c.get("port_labels") or {}).get("atem-mini", {})
        self.assertTrue(labels, fr("FR-IMP-09", "3.25", "sample XML yields labels"))
        self.assertIn(labels.get("hdmi-in-1"), ("Pulpit Camera", "CAM1"), fr("FR-IMP-09", "3.25", "inputs by index"))


class Dante(unittest.TestCase):
    def test_dante_device_info_addresses(self):
        schema = requires("schema")
        network = requires("network")
        merge = requires("merge:build_overlay")
        doc = schema.migrate(rrc_dict())
        doc["imports"] = [{"id": "imp-0001", "kind": "dante", "path": "exports/dante/device-info.txt", "room": "main"}]
        with temp_data_dir() as data:
            pdir = install_project(data, "di", doc=doc)
            (pdir / "exports" / "dante").mkdir(parents=True)
            shutil.copy(str(IMP / "device-info.txt"), str(pdir / "exports" / "dante" / "device-info.txt"))
            ov = merge(doc, pdir)
        ifs = ov.get("interfaces") or {}
        rio = ifs.get("rio3224") or []
        self.assertEqual(sorted((i["role"], i["ip"]) for i in rio), [("primary", "192.168.1.21"), ("secondary", "192.168.2.21")],
                         fr("FR-IMP-02", "3.25", "Primary/Secondary Address -> interfaces"))
        for i in rio:
            self.assertEqual(i.get("protocol"), "dante")
            self.assertEqual(i.get("source"), "dante")
        self.assertEqual([i["ip"] for i in ifs.get("neve1", [])], ["192.168.1.31"], "N/A secondary ignored")
        sched = network.ip_schedule(doc, ov)
        rows = [r for r in sched["rows"] if r.get("source") == "dante"]
        self.assertTrue(rows, fr("FR-NET-02", "3.11", "rows with source dante"))
        self.assertIn("192.168.1.21", [r["ip"] for r in rows])


class GenericCsv(unittest.TestCase):
    def setUp(self):
        requires("parsers.generic_csv")
        self.plugins = requires("plugins")

    def preview(self, path, doc):
        imp = self.plugins.get_importer("csv")
        res = imp.parse(Path(path))
        return imp.preview(res, copy.deepcopy(doc), {"room": "main", "device": "", "import": None})

    def test_generic_csv_preview(self):
        p = self.preview(fixture_path("csv", "devices.csv"), sunday_doc())
        for k in ("ops", "summary", "warnings"):
            self.assertIn(k, p, fr("FR-IMP-08", "5.7", k))
        merges = [o for o in p["ops"] if o["op"] == "merge"]
        puts = [o for o in p["ops"] if o["op"] == "put"]
        self.assertEqual([o["id"] for o in merges], ["atem-mini"], fr("FR-IMP-08", "5.7.4", "existing name -> merge"))
        self.assertEqual(merges[0]["value"].get("inventory", {}).get("serial"), "ATEM-123")
        self.assertNotIn("notes", merges[0]["value"], "5.7.4 only non-empty cells")
        self.assertEqual(len(puts), 1, fr("FR-IMP-08", "5.7.4", "new device -> put"))
        new = puts[0]["value"]
        self.assertEqual((new["name"], new["kind"], new["room"]), ("Lobby TV", "display", "main"))
        self.assertEqual(new["interfaces"][0]["id"], "primary", "5.7.4 ip populates interface primary")
        self.assertEqual(new["interfaces"][0]["ip"], "10.20.0.77")
        self.assertEqual(p["summary"], {"create": 1, "update": 1, "skip": 0})
        schema = requires("schema")
        newdoc, _ = schema.apply_ops(sunday_doc(), p["ops"])
        self.assertEqual(schema.errors(schema.validate_doc(newdoc)), [], "preview ops produce a valid doc")

    def test_generic_csv_cables(self):
        p = self.preview(fixture_path("csv", "cables.csv"), sunday_doc())
        puts = [o for o in p["ops"] if o["op"] == "put" and o["coll"] == "cables"]
        self.assertEqual(len(puts), 1)
        c = puts[0]["value"]
        self.assertEqual((c["from"], c["to"]), ({"device": "video-converter", "port": "sdi-out-2"}, {"device": "samsung-tv-1", "port": "hdmi-in-1"}))
        self.assertEqual(c["tag"], "V-100")
        self.assertAlmostEqual(c["length_m"], 3.048, places=3, msg="5.7.4 length_unit ft -> meters")
        self.assertTrue(p["warnings"], "5.7.4 unresolvable device -> warning, row skipped")
        self.assertEqual(p["summary"]["skip"], 1)

    def test_campus_devices_csv(self):
        if not (CAMPUS_DIR / "exports" / "csv" / "devices.csv").exists():
            self.skipTest("W2 sample campus-demo/exports/csv/devices.csv not present yet")
        doc = read_json(CAMPUS_DIR / "project.json")
        p = self.preview(CAMPUS_DIR / "exports" / "csv" / "devices.csv", doc)
        ops = p["ops"]
        ids = {d["id"] for d in doc["devices"]}
        self.assertTrue([o for o in ops if o["op"] == "put" and o["id"] not in ids], fr("FR-IMP-08", "3.25", "put ops for new devices"))
        self.assertTrue([o for o in ops if o["op"] == "merge" and o["id"] in ids], fr("FR-IMP-08", "3.25", "merge ops for existing ids"))

    def test_cable_csv_roundtrip(self):
        app = get_app()
        with temp_data_dir() as data:
            install_project(data, "rt", doc=sunday_doc())
            st, _, b = call(app, "GET", "/api/v2/projects/rt/schedules/cables?format=csv")
            self.assertEqual(st, 200)
            rows = list(csv.reader(io.StringIO(b.decode("utf-8"))))
            header = rows[0]
            li, ii = header.index("Length"), header.index("Id")
            target = [r for r in rows[1:] if r[ii] == "c-0003"][0]
            target[li] = str(round(float(target[li]) + 1.0, 2))
            path = data / "cables-edit.csv"
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\r\n").writerows(rows)
            path.write_text(buf.getvalue(), encoding="utf-8")
        p = self.preview(path, sunday_doc()) if path.exists() else None
        if p is None:
            with temp_data_dir() as data2:
                pass
        # (file removed with the temp dir; re-create for the preview)
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "cables-edit.csv"
            q.write_text(buf.getvalue(), encoding="utf-8")
            p = self.preview(q, sunday_doc())
        self.assertEqual(len(p["ops"]), 1, fr("FR-CAB-06", "3.10", "changing one length yields exactly one op, got %s" % p["ops"]))
        op = p["ops"][0]
        self.assertEqual((op["op"], op["coll"], op["id"]), ("merge", "cables", "c-0003"), fr("FR-CAB-06", "3.10"))
        self.assertEqual(list(op["value"]), ["length_m"])
        self.assertGreater(op["value"]["length_m"], 3.0)


    def _rows_preview(self, text, doc=None):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "edit.csv"
            q.write_text(text, encoding="utf-8")
            return self.preview(q, doc or sunday_doc())

    def test_generic_csv_row_validation(self):
        text = ("name,kind,status,ip,mac,vlan,universe,address,footprint,room,purchase_date,cost,colour\n"
                "Good Box,stage_io,Installed,10.0.0.1,001d.c10a.2b3c,20,,,,main,,,\n"
                "\n"
                ",console,,,,,,,,,,,\n"
                "Bad Kind,laser,maybe,10.0.0.300,zz:zz,5000,0,600,4,Basement,15/01/2026,abc,\n"
                "good box,console,,,,,,,,,,,\n"
                "Overflow,fixture,,,,,1,510,8,,,,,extra\n"
                "Video Switch,Video switcher,,,,,,,,,,,\n")
        p = self._rows_preview(text)
        errs = p["errors"]
        by_row = {}
        for e in errs:
            self.assertEqual(set(e), {"row", "column", "value", "message"})
            by_row.setdefault(e["row"], {})[e["column"]] = e
        self.assertNotIn(2, by_row, "valid row (Cisco MAC, mixed-case status) passes")
        self.assertIn("name", by_row[4], "row numbers are spreadsheet rows (blank row 3 counted)")
        bad = by_row[5]
        for col in ("kind", "status", "ip", "mac", "vlan", "universe", "address", "room", "purchase_date", "cost"):
            self.assertIn(col, bad, "row 5 flags %s" % col)
        self.assertIn("laser", bad["kind"]["value"])
        self.assertIn("console", bad["kind"]["message"], "message lists the valid kinds")
        self.assertIn("ups", bad["kind"]["message"], "… and the device type preset aliases")
        self.assertIn("Main", bad["room"]["message"], "message lists the project rooms")
        self.assertIn("duplicate of row 2", by_row[6]["name"]["message"], "names compare case-insensitively")
        self.assertIn("past 512", by_row[7]["footprint"]["message"])
        puts = {o["value"]["name"]: o["value"] for o in p["ops"] if o["op"] == "put"}
        self.assertEqual(sorted(puts), ["Good Box", "Video Switch"], "rows with problems are skipped, the rest preview")
        self.assertEqual(puts["Good Box"]["status"], "installed")
        self.assertEqual(puts["Video Switch"]["kind"], "video_switcher", "kind labels / spaces normalise to the vocab key")
        self.assertEqual(p["summary"], {"create": 2, "update": 0, "skip": 4})
        self.assertTrue(any("colour" in w for w in p["warnings"]), "unknown column reported")
        self.assertTrue(any("row 7" in w and "extra cells" in w for w in p["warnings"]), "extra cells reported")
        self.assertTrue(any(w.startswith("row 5, kind:") for w in p["warnings"]), "errors mirrored into warnings for the CLI")
        schema = requires("schema")
        newdoc, _ = schema.apply_ops(sunday_doc(), p["ops"])
        self.assertEqual(schema.errors(schema.validate_doc(newdoc)), [])

    def test_generic_csv_cable_validation(self):
        text = ("tag,from_device,from_port,to_device,to_port,medium,length,channels,status\n"
                "V-1,Video Converter,sdi-out-2,Samsung TV - 1,hdmi-in-1,sdi,3 m,1,planned\n"
                "V-1,Video Converter,sdi-out-1,Samsung TV - 1,hdmi-in-1,sdi,,,\n"
                "V-2,,,Samsung TV - 1,,sdi,,,\n"
                "V-3,Video Converter,,Samsung TV - 1,,smoke-signal,ten,0,lost\n"
                "V-4,Nowhere Box,out,Samsung TV - 1,,sdi,,,\n")
        p = self._rows_preview(text)
        cols = {(e["row"], e["column"]) for e in p["errors"]}
        self.assertIn((3, "tag"), cols, "duplicate tag in the file")
        self.assertIn((4, "from_device"), cols, "from device required for a new cable")
        for c in ("medium", "length", "channels", "status"):
            self.assertIn((5, c), cols, "row 5 flags %s" % c)
        self.assertIn((6, "from_device"), cols, "unknown device")
        self.assertIn("not found", [e for e in p["errors"] if e["row"] == 6][0]["message"])
        puts = [o for o in p["ops"] if o["op"] == "put"]
        self.assertEqual([o["value"]["tag"] for o in puts], ["V-1"])
        self.assertEqual(puts[0]["value"]["status"], "planned")


class CsvTemplates(unittest.TestCase):
    """Downloadable templates: download → edit → upload (preview) → apply."""

    def setUp(self):
        requires("parsers.generic_csv")
        self.plugins = requires("plugins")

    def test_templates_listed_in_meta(self):
        st, _, b = call(get_app(), "GET", "/api/v2/meta")
        imps = {i["kind"]: i for i in jbody(b)["importers"]}
        tpls = {t["name"]: t for t in imps["csv"]["templates"]}
        self.assertEqual(sorted(tpls), ["cables", "devices"])
        req = [c["key"] for c in tpls["devices"]["columns"] if c["required"]]
        self.assertEqual(req, ["name"])
        self.assertEqual(sorted(c["key"] for c in tpls["cables"]["columns"] if c["required"]), ["from_device", "to_device"])
        self.assertTrue(all(c["key"] in requires("parsers.generic_csv").DEVICE_COLS for c in tpls["devices"]["columns"]), "template headers are canonical")
        self.assertEqual(imps["magicq"]["templates"], [])

    def test_template_download_edit_upload_roundtrip(self):
        app = get_app()
        schema = requires("schema")
        doc = sunday_doc()
        doc["devices"] = [d for d in doc["devices"] if d.get("name") not in ("FOH Console", "Stage Box 1", "Wash 1")]
        with temp_data_dir() as data:
            install_project(data, "tp", doc=doc)
            st, hd, b = call(app, "GET", "/api/v2/projects/tp/imports/templates/csv/devices.csv")
            self.assertEqual(st, 200)
            self.assertIn("text/csv", hd.get("Content-Type"))
            self.assertIn('filename="fathom-devices-template.csv"', hd.get("Content-Disposition"))
            text = b.decode("utf-8")
            self.assertTrue(text.startswith("\ufeff"), "BOM so Excel opens UTF-8 correctly")
            rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
            header = rows[0]
            self.assertEqual(header[0], "name")
            self.assertEqual(len(rows), 4, "header + three example rows")
            room_name = [r["name"] for r in doc["rooms"] if r["id"] == (doc.get("settings") or {}).get("default_room", r["id"])][0]
            self.assertEqual(rows[1][header.index("room")], room_name, "examples use the project's room")

            # unedited template previews cleanly
            st, _, b = upload(app, "/api/v2/projects/tp/imports/preview?room=main", [("fathom-devices-template.csv", text.encode("utf-8"), "text/csv")])
            self.assertEqual(st, 200, b)
            pv = jbody(b)
            self.assertEqual(pv["kind"], "csv", "template auto-detects as the generic CSV")
            self.assertEqual((pv["errors"], pv["summary"]), ([], {"create": 3, "update": 0, "skip": 0}))

            # edit like a user would: rename, add a good row and a bad row, re-save from a spreadsheet (semicolons)
            ni, ii, ai, fi = header.index("name"), header.index("ip"), header.index("address"), header.index("footprint")
            rows[3][ni] = "Wash SR"
            extra = list(rows[3])
            extra[ni], extra[ai] = "Wash SL", "17"
            bad = [""] * len(header)
            bad[ni], bad[ii], bad[header.index("kind")] = "Broken Row", "192.168.1.999", "console"
            rows += [extra, bad]
            buf = io.StringIO()
            csv.writer(buf, delimiter=";", lineterminator="\r\n").writerows(rows)
            st, _, b = upload(app, "/api/v2/projects/tp/imports/preview?kind=csv&room=main", [("edited.csv", buf.getvalue().encode("utf-8"), "text/csv")])
            pv = jbody(b)
            self.assertEqual([(e["row"], e["column"], e["value"]) for e in pv["errors"]], [(6, "ip", "192.168.1.999")],
                             "the bad row is reported with its spreadsheet row and column")
            names = sorted(o["value"]["name"] for o in pv["ops"] if o["op"] == "put")
            self.assertEqual(names, ["FOH Console", "Stage Box 1", "Wash SL", "Wash SR"])
            sl = [o["value"] for o in pv["ops"] if o["op"] == "put" and o["value"]["name"] == "Wash SL"][0]
            self.assertEqual(sl["dmx"], {"universe": 1, "address": 17, "footprint": int(rows[3][fi]), "channel": "101"})
            self.assertTrue([p for p in sl["ports"] if p.get("medium") == "dmx"], "template column instantiates library ports")

            st, _, b = call(app, "POST", "/api/v2/projects/tp/changes", {"base_revision": pv["base_revision"], "ops": pv["ops"], "summary": "csv"},
                            {"X-Fathom": "1"})
            self.assertEqual(st, 200, b)
            st, _, b = call(app, "GET", "/api/v2/projects/tp")
            applied = jbody(b)["doc"]
            self.assertEqual(schema.errors(schema.validate_doc(applied)), [])

            # re-uploading the same edited file now only matches (idempotent)
            st, _, b = upload(app, "/api/v2/projects/tp/imports/preview?kind=csv&room=main", [("edited.csv", buf.getvalue().encode("utf-8"), "text/csv")])
            again = jbody(b)
            self.assertEqual(again["summary"]["create"], 0)
            self.assertEqual(again["summary"]["update"], 0, again["ops"])

            # the cables template connects the template devices without inventing ports
            st, _, b = call(app, "GET", "/api/v2/projects/tp/imports/templates/csv/cables.csv")
            self.assertEqual(st, 200)
            st, _, b = upload(app, "/api/v2/projects/tp/imports/preview?room=main", [("cables.csv", b, "text/csv")])
            cv = jbody(b)
            self.assertEqual(cv["errors"], [])
            self.assertEqual([o["op"] for o in cv["ops"]], ["put", "put"], "no port merges: Dante Primary/Secondary exist")
            self.assertEqual(cv["ops"][0]["value"]["from"], {"device": "stage-box-1", "port": "dante-primary"})
            self.assertAlmostEqual(cv["ops"][1]["value"]["length_m"], 45.72, places=2, msg="150 ft")

    def test_template_errors(self):
        app = get_app()
        with temp_data_dir() as data:
            install_project(data, "tp", doc=sunday_doc())
            for path in ("/api/v2/projects/tp/imports/templates/csv/racks.csv", "/api/v2/projects/tp/imports/templates/magicq/devices.csv",
                         "/api/v2/projects/tp/imports/templates/nope/devices.csv", "/api/v2/projects/nope/imports/templates/csv/devices.csv"):
                st, _, _ = call(app, "GET", path)
                self.assertEqual(st, 404, path)
        with self.assertRaises(KeyError):
            requires("parsers.generic_csv").template_csv("racks")


class MagicQ(unittest.TestCase):
    def setUp(self):
        self.mq = requires("parsers.magicq")
        self.plugins = requires("plugins")

    def parse_text(self, text, name="patch.csv", encoding="utf-8"):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / name
            p.write_bytes(text.encode(encoding))
            return self.plugins.detect(p), self.mq.parse_magicq(p)

    def test_detect(self):
        for f in ("magicq-export-heads.csv", "magicq-print-window.csv"):
            self.assertEqual(self.plugins.detect(IMP / f), "magicq", f)
        for f, kind in (("eos-show.csv", "eos"), ("lightwright.txt", "eos"), ("show.asc", "eos"), ("videohub-dump.txt", "videohub")):
            self.assertEqual(self.plugins.detect(IMP / f), kind, "%s still detected as %s" % (f, kind))
        self.assertEqual(self.plugins.detect(fixture_path("csv", "devices.csv")), "csv")
        kind, _ = self.parse_text("Channel,Universe,Address,Instrument Type,Purpose\n1,1,1,Source Four,Wash\n")
        self.assertEqual(kind, "eos", "a Vectorworks schedule stays with the Lightwright importer")

    def test_export_heads(self):
        r = self.mq.parse_magicq(IMP / "magicq-export-heads.csv")
        self.assertEqual(r.format, "export-heads")
        self.assertEqual(len(r.heads), 7)
        h = {x["head"]: x for x in r.heads}
        self.assertEqual((h["1"]["universe"], h["1"]["address"]), (1, 1), "'0001' / '1-001'")
        self.assertEqual((h["102"]["universe"], h["102"]["address"]), (2, 33))
        self.assertEqual((h["1"]["manufacturer"], h["1"]["model"]), ("Generic", "Dimmer"), "Headtype Manufacturer_Model")
        self.assertEqual(h["101"]["model"], "Maverick Storm 2 Profile")
        self.assertEqual(h["5"]["color"], "R59 Indigo")
        self.assertNotIn("color", h["2"], "'No col' is no gel")
        self.assertTrue(h["101"].get("pinv"))
        self.assertTrue(h["102"].get("tinv") and h["102"].get("swap"))
        self.assertNotIn("pinv", h["102"])
        self.assertEqual(r.notes, [])
        self.assertEqual(r.summary()["universes"], [1, 2])

    def test_print_window(self):
        r = self.mq.parse_magicq(IMP / "magicq-print-window.csv")
        self.assertEqual(r.format, "print-window")
        h = {x["head"]: x for x in r.heads}
        self.assertEqual(sorted(h, key=int), ["1", "2", "11", "12", "21"], "semicolon file; virtual head 20 skipped")
        self.assertEqual((h["1"]["universe"], h["1"]["address"], h["1"]["footprint"]), (1, 101, 8), "Universe column + in-universe DMX")
        self.assertEqual((h["11"]["universe"], h["11"]["address"]), (3, 1))
        self.assertEqual((h["1"]["manufacturer"], h["1"]["model"]), ("ETC", "Source Four LED Series 2 Lustr"), "Manufacturer column wins")
        self.assertEqual(h["11"]["model"], "MAC Aura PXL")
        self.assertEqual(h["11"]["mode"], "Mode 1")
        self.assertEqual(h["1"]["xyz"], [-2.5, 6.0, 4.0])
        self.assertNotIn("xyz", h["11"])
        self.assertEqual(r.unpatched, ["20"])
        notes = " | ".join(r.notes)
        self.assertIn("without a DMX address", notes)
        self.assertIn("heads 11 and 12 overlap at 3-020", notes)
        self.assertIn("head 21: 4-505 with 12 channels runs past address 512", notes)

    def test_address_forms_and_files(self):
        text = ("MagicQ patch - View Heads\n"
                "Head No,Head Name,Universe,DMX,Head Type,# of Data Channels\n"
                "1,A,,513,Generic_Dimmer,1\n"
                "2,B,,1/17,Generic_Dimmer,1\n"
                "3,C,,1.18,Generic_Dimmer,1\n"
                "4,D,2,5,Generic_Dimmer,1\n"
                "\n"
                "5,E,,bogus,Generic_Dimmer,1\n"
                "6,F,,-,Generic_Dimmer,1\n")
        kind, r = self.parse_text(text, encoding="utf-8-sig")
        self.assertEqual(kind, "magicq", "title row before the header; BOM")
        got = {x["head"]: (x["universe"], x["address"]) for x in r.heads}
        self.assertEqual(got, {"1": (2, 1), "2": (1, 17), "3": (1, 18), "4": (2, 5)})
        self.assertTrue(any("DMX 'bogus' not understood" in n for n in r.notes))
        self.assertEqual(r.unpatched, ["6"])
        kind, r = self.parse_text("Headno\tHeadname\tDmxno\tHeadtype\n0007\tTab\t3-100\tGeneric_LED\n", name="paste.txt")
        self.assertEqual((kind, [(x["head"], x["universe"], x["address"]) for x in r.heads]), ("magicq", [("7", 3, 100)]), "tab paste")
        _, r = self.parse_text("Name,Universe,Address\nx,1,1\n")
        self.assertEqual(r.heads, [])
        self.assertTrue(r.fatal, "not a MagicQ head list")

    def test_show_file_refused(self):
        _, r = self.parse_text("\\ MagicQ Show File. Chamsys Ltd.  www.chamsys.co.uk\nV 1\n", name="show.shw")
        self.assertIn("Print Window", r.fatal, "a .shw explains how to export the patch")
        app = get_app()
        with temp_data_dir() as data:
            pdir = install_project(data, "mq", doc=sunday_doc())
            st, _, b = upload(app, "/api/v2/projects/mq/imports", [("rig.shw", b"\\ MagicQ Show File. Chamsys Ltd.\x00\x01binary", "application/octet-stream")])
            self.assertEqual(st, 422, b)
            self.assertIn("EXPORT HEADS", jbody(b)["error"])
            st, _, b = call(app, "GET", "/api/v2/projects/mq")
            self.assertEqual(jbody(b)["doc"].get("imports") or [], [], "nothing registered")
            self.assertFalse(list((pdir / "exports").rglob("rig.shw")), "upload removed")

    def test_contribute(self):
        doc = lighting_doc()
        doc["devices"].append({"id": "spots", "name": "Spots", "kind": "fixture", "room": "main", "ports": []})
        kind, c = contribute(IMP / "magicq-export-heads.csv", doc)
        self.assertEqual(kind, "magicq")
        self.assertEqual(dmx_of(c, "front-l"), {"universe": 1, "address": 1, "channel": "1", "source": "magicq"}, "matched by dmx.channel = head number")
        self.assertIsNone(dmx_of(c, "spots"), "a head name used by several heads is not matched by name")
        autos = [d for d in c["devices"] if d.get("auto")]
        self.assertEqual(len(autos), 6)
        ids = {d["id"] for d in autos}
        self.assertTrue({"mq-2", "mq-3", "mq-101"} <= ids)
        wash = [d for d in autos if d["id"] == "mq-101"][0]
        self.assertEqual((wash["kind"], wash["room"], wash["source"], wash["manufacturer"], wash["model"]),
                         ("fixture", "main", "magicq", "Chauvet", "Maverick Storm 2 Profile"))
        self.assertEqual(wash["name"], "Wash SR · head 101")
        self.assertEqual(c["detail"]["mq-101"]["lighting"].get("pinv"), True)
        kind, c = contribute(IMP / "magicq-print-window.csv", lighting_doc())
        self.assertEqual(dmx_of(c, "front-r")["address"], 109, "matched by a unique head name")
        self.assertEqual(dmx_of(c, "front-l")["footprint"], 8)
        self.assertEqual(dmx_of(c, "mq-11")["mode"], "Mode 1")
        self.assertTrue(any("overlap" in n for n in c["notes"]))

    def test_upload_and_overlay(self):
        app = get_app()
        merge = requires("merge:build_overlay")
        with temp_data_dir() as data:
            pdir = install_project(data, "mq", doc=lighting_doc())
            st, _, b = upload(app, "/api/v2/projects/mq/imports?room=main", [("patch.csv", (IMP / "magicq-print-window.csv").read_bytes(), "text/csv")])
            self.assertEqual(st, 201, b)
            r = jbody(b)
            self.assertEqual((r["import"]["kind"], r["summary"]["heads"], r["summary"]["unpatched"]), ("magicq", 5, 1))
            self.assertTrue((pdir / r["import"]["path"]).exists())
            st, _, b = call(app, "GET", "/api/v2/projects/mq/overlay")
            ov = jbody(b)
            srcs = {k: v.get("source") for k, v in ov["dmx"].items()}
            self.assertEqual(set(srcs.values()), {"magicq"})
            self.assertIn("front-l", srcs)
            self.assertEqual(len([d for d in ov["devices"] if d.get("source") == "magicq"]), 3)
            st, _, b = call(app, "GET", "/api/v2/projects/mq/imports/%s/inspect" % r["import"]["id"])
            self.assertEqual(jbody(b)["summary"]["format"], "print-window")
            self.assertTrue(callable(merge))

    def test_cli_inspect(self):
        cli = requires("cli")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(["inspect", str(IMP / "magicq-export-heads.csv")])
            except SystemExit as e:
                self.assertIn(e.code, (0, None))
        text = out.getvalue()
        self.assertIn("detected: magicq", text)
        self.assertIn("2-033", text)


# ================================================================== library (§3.13, §4.5)


class Library(unittest.TestCase):
    def setUp(self):
        self.library = requires("library")
        self.schema = requires("schema")

    def test_library_count_and_valid(self):
        with temp_data_dir():
            lib = self.library.load_library(refresh=True)
            self.assertGreaterEqual(len(lib), 48, fr("FR-LIB-01", "3.13", "len(load_library()) >= 48 (got %d)" % len(lib)))
            for tid, t in lib.items():
                self.assertEqual(self.library.validate_template(t), [], fr("FR-LIB-01", "3.13", "template %s valid" % tid))
            present = [i for i in APPENDIX_E if i in lib]
            self.assertGreaterEqual(len(present), 48, fr("FR-LIB-01", "Appendix E", "missing: %s" % sorted(set(APPENDIX_E) - set(lib))))
            for tid in REQUIRED_TEMPLATES:
                self.assertIn(tid, lib, fr("FR-LIB-01", "Appendix B/E", "template %s referenced by the fixture/tests" % tid))

    def test_template_schema(self):
        with temp_data_dir():
            lib = self.library.load_library(refresh=True)
        bad = []
        for tid, t in lib.items():
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", tid):
                bad.append("%s id pattern" % tid)
            for k in ("id", "manufacturer", "model", "kind", "ports"):
                if k not in t:
                    bad.append("%s missing %s" % (tid, k))
            if tid in APPENDIX_E and t.get("cost") is not None:
                bad.append("%s cost must be null" % tid)
            ports = self.schema.expand_port_groups(t.get("ports", []))
            if len({p["id"] for p in ports}) != len(ports):
                bad.append("%s duplicate expanded ids" % tid)
        self.assertEqual(bad, [], fr("FR-LIB-02", "4.5"))
        ids = lambda tid: [p["id"] for p in self.schema.expand_port_groups(lib[tid]["ports"])]  # noqa: E731
        self.assertIn("analog-in-32", ids("yamaha-rio3224-d2"), "Appendix E bold group 'Analog In'")
        self.assertIn("slink", ids("allen-heath-sq-5"), "Appendix E bold group 'SLink'")
        vh = ids("blackmagic-videohub-20x20-12g")
        for n in range(1, 21):
            self.assertIn("sdi-in-%d" % n, vh)
            self.assertIn("sdi-out-%d" % n, vh)
        for tid in ("chauvet-maverick-storm-2-profile", "martin-mac-aura-pxl", "etc-source-four-lustr-x8"):
            if tid in lib:
                ps = {p["id"]: p for p in self.schema.expand_port_groups(lib[tid]["ports"])}
                self.assertEqual(ps.get("dmx-in", {}).get("dir"), "in", "Appendix E %s dmx-in dir in" % tid)
                out = ps.get("dmx-out") or ps.get("dmx-thru")
                self.assertTrue(out and out["dir"] == "out", "Appendix E %s dmx-out|dmx-thru dir out" % tid)
        atem = lib["blackmagic-atem-mini-pro"]
        chk = [c for c in atem.get("checks", []) if c.get("id") == "audio-on"]
        self.assertEqual(chk, [{"id": "audio-on", "symptoms": ["no_audio"], "when": {"port_dir": "in", "medium": ["analog", "hdmi"]},
                                "text": "On the {device}'s Audio tab, make sure the **{port}** input is set to ON, not AFV (inputs default to audio-follow-video).",
                                "note": "check Audio tab"}], "Appendix F.6 ATEM audio-on check")
        rio = lib["yamaha-rio3224-d2"]
        self.assertEqual((rio["ru"], rio["kind"]), (5, "stage_io"))
        self.assertEqual(rio.get("dante_channels"), {"tx": 32, "rx": 24})

    def test_instantiate(self):
        t = self.library.get_template("yamaha-rio3224-d2")
        d = self.library.instantiate(t, device_id="rio1", name="Stage Rack", room="main")
        self.assertEqual((d["id"], d["name"], d["kind"], d["template"], d["room"]), ("rio1", "Stage Rack", "stage_io", "yamaha-rio3224-d2", "main"))
        self.assertEqual((d["manufacturer"], d["model"]), ("Yamaha", "Rio3224-D2"))
        self.assertIs(d.get("dante"), True, "4.5 dante:true if template.dante")
        self.assertNotIn("rack", d, "4.5 rack not set until racked")
        self.assertNotIn("discipline", d, "4.5 discipline only if != kind default")
        self.assertEqual(d["ports"], self.schema.expand_port_groups(t["ports"]))
        d2 = self.library.instantiate(t, device_id="rio2")
        self.assertEqual(d2["name"], t.get("name") or t["model"])

    def test_apply_template_idempotent(self):
        t = self.library.get_template("blackmagic-atem-mini-pro")
        doc = sunday_doc()
        ops = self.library.apply_template_ops(doc, "atem-mini", t)
        self.assertTrue(ops, "missing template ports are added")
        new, _ = self.schema.apply_ops(doc, ops)
        ports = {p["id"]: p for p in [d for d in new["devices"] if d["id"] == "atem-mini"][0]["ports"]}
        for pid in ("hdmi-in-1", "analog-in-1", "usb-out-1", "hdmi-out-1"):
            self.assertIn(pid, ports, fr("FR-LIB-05", "3.13", "cabled port %s never removed" % pid))
        self.assertEqual(ports["analog-in-1"].get("label"), "Stream", "existing port data kept")
        for pid in ("hdmi-in-3", "hdmi-in-4"):
            self.assertIn(pid, ports, "template ports added by id")
        self.assertEqual(self.library.apply_template_ops(new, "atem-mini", t), [], fr("FR-LIB-05", "3.13", "applying twice yields no ops"))
        tpl = self.library.template_from_device([d for d in doc["devices"] if d["id"] == "audio-rack-1"][0], "t1-ar84-copy")
        self.assertEqual(tpl["id"], "t1-ar84-copy")
        groups = [g["group"] for g in tpl["ports"]]
        self.assertEqual(groups, ["Analog In", "Analog Out", "Network In"], fr("FR-LIB-05", "3.13", "ports -> groups by group"))
        self.assertEqual(self.library.validate_template(tpl), [])


# ================================================================== floor-plan conversion (§3.8, Appendix D)


class FloorPlans(unittest.TestCase):
    def setUp(self):
        self.fp = requires("floorplan")

    def _svg(self, res):
        return ET.fromstring(res.data)

    def test_drawio_compressed_and_plain(self):
        comp = self.fp.drawio_to_svg(fixture_path("plans", "compressed.drawio").read_text())
        plain = self.fp.drawio_to_svg(fixture_path("plans", "uncompressed.drawio").read_text())
        self.assertEqual(comp.data, plain.data, fr("FR-PLAN-02", "D.1", "compressed and uncompressed yield identical SVG"))
        self.assertEqual(comp.image_kind, "svg")
        self.assertEqual(comp.layers, [], "D.1 layers = []")
        root = self._svg(comp)
        tag = lambda e: e.tag.split("}")[-1]  # noqa: E731
        rects = [e for e in root.iter() if tag(e) == "rect" and e.get("width") == "400"]
        self.assertTrue(rects, fr("FR-PLAN-02", "D.1", "stage rectangle 400 wide"))
        r = rects[0]
        self.assertEqual((float(r.get("width")), float(r.get("height"))), (400.0, 120.0))
        self.assertEqual(r.get("fill", "").lower(), "#f5f5f5")
        self.assertEqual(r.get("stroke", "").lower(), "#666666")
        ells = [e for e in root.iter() if tag(e) == "ellipse"]
        self.assertEqual(len(ells), 1, fr("FR-PLAN-02", "D.1", "one ellipse"))
        e = ells[0]
        self.assertEqual((float(e.get("rx")), float(e.get("ry"))), (40.0, 30.0))
        dashed = [x for x in root.iter() if tag(x) in ("path", "polyline", "line") and (x.get("stroke") or "").lower() == "#3333ff"]
        self.assertEqual(len(dashed), 1, fr("FR-PLAN-02", "D.1", "one dashed edge in #3333ff"))
        self.assertTrue(dashed[0].get("stroke-dasharray"), "edge is dashed")
        pts = dashed[0].get("d") or dashed[0].get("points") or ""
        self.assertTrue(re.search(r"240[ ,]+300", pts), fr("FR-PLAN-02", "D.1", "edge passes the waypoint (240,300): %s" % pts))
        texts = " ".join("".join(t.itertext()) for t in root.iter() if tag(t) == "text")
        self.assertIn("Stage", texts)
        self.assertIn("FOH booth", texts, fr("FR-PLAN-02", "D.1", "HTML stripped from labels"))
        self.assertNotIn("<b>", texts)
        self.assertGreaterEqual(comp.width, 400)
        self.assertGreaterEqual(comp.height, 420)

    def test_dxf_fixture(self):
        res = self.fp.dxf_to_svg(fixture_path("plans", "fixture.dxf").read_text())
        root = self._svg(res)
        self.assertEqual((root.get("width"), root.get("height"), root.get("viewBox")), ("2080", "1580", "0 0 2080 1580"), fr("FR-PLAN-03", "D.2", "scale and margin"))
        tag = lambda e: e.tag.split("}")[-1]  # noqa: E731
        groups = {g.get("data-layer"): g for g in root.iter() if g.get("data-layer")}
        self.assertEqual(sorted(groups), ["SEATS", "WALLS"], fr("FR-PLAN-03", "D.2", "HIDDEN layer skipped"))
        walls = groups["WALLS"]
        kids = list(walls.iter())
        closed = [e for e in kids if tag(e) in ("polygon", "path", "polyline") and (e.get("points") and len(e.get("points").split()) >= 4 or "Z" in (e.get("d") or "").upper())]
        self.assertTrue(closed, fr("FR-PLAN-03", "D.2", "closed polygon with 4 vertices"))
        self.assertEqual(len([e for e in kids if tag(e) == "line"]), 1, fr("FR-PLAN-03", "D.2", "one LINE"))
        arcs = [e for e in kids if tag(e) == "path" and re.search(r"[Aa]\s*200[ ,]+200", e.get("d") or "")]
        self.assertTrue(arcs, fr("FR-PLAN-03", "D.2", "bulge 1.0 -> SVG arc radius 200"))
        arc2 = [e for e in kids if tag(e) == "path" and re.search(r"[Aa]\s*200(\.0+)?[ ,]+200", e.get("d") or "")]
        self.assertGreaterEqual(len(arc2), 2, fr("FR-PLAN-03", "D.2", "LWPOLYLINE bulge arc + ARC entity (both r=200 px)"))
        texts = ["".join(t.itertext()) for t in walls.iter() if tag(t) == "text"]
        joined = " ".join(texts)
        self.assertIn("STAGE", joined)
        self.assertIn("FOH", joined)
        self.assertIn("Booth", joined, fr("FR-PLAN-03", "D.2", "MTEXT \\P -> two lines"))
        self.assertNotIn("\\P", joined)
        circles = [e for e in groups["SEATS"].iter() if tag(e) == "circle"]
        self.assertEqual(len(circles), 2, fr("FR-PLAN-03", "D.2", "two INSERTed seats"))
        centers = sorted((round(float(c.get("cx"))), round(float(c.get("cy"))), round(float(c.get("r")))) for c in circles)
        self.assertEqual(centers, [(540, 1040, 25), (640, 1040, 25)], fr("FR-PLAN-03", "D.2", "INSERT translate, y flipped"))
        self.assertEqual([(l["name"], l["visible"]) for l in res.layers], [("WALLS", True), ("SEATS", True), ("HIDDEN", False)], fr("FR-PLAN-03", "D.2"))
        self.assertEqual(res.units, {"insunits": 6, "meters_per_unit": 1.0})
        self.assertIn(b"#c8cfdd", res.data.lower(), "D.2 default stroke")
        colored = self.fp.dxf_to_svg(fixture_path("plans", "fixture.dxf").read_text(), use_dxf_colors=True).data.lower()
        self.assertIn(b"#ffffff", colored, "D.2 ACI 7 -> #ffffff")
        self.assertIn(b"#00ff00", colored, "D.2 ACI 3 -> #00ff00")
        hidden = self.fp.dxf_to_svg(fixture_path("plans", "fixture.dxf").read_text(), hide_layers=["WALLS"])
        hroot = self._svg(hidden)
        self.assertNotIn("WALLS", [g.get("data-layer") for g in hroot.iter() if g.get("data-layer")], "D.2 hide_layers")
        # SEATS-only bounds: x 4.75..6.25, y 4.75..5.25 -> k = 2000/1.5; height = 0.5k + 80
        self.assertAlmostEqual(float(hroot.get("height")), 0.5 * 2000 / 1.5 + 80, delta=1.0, msg="D.2 bounds from the SEATS circles when WALLS is hidden")

    def test_convert_detect_and_dwg(self):
        with tempfile.TemporaryDirectory() as tmp:
            dwg = Path(tmp) / "plan.dwg"
            dwg.write_bytes(b"AC1032" + b"\x00" * 64)
            with temp_env(FATHOM_ODA=None):
                with self.assertRaises(self.fp.UnsupportedPlan) as cm:
                    self.fp.convert(dwg)
            self.assertEqual(cm.exception.code, "dwg_unsupported", fr("FR-PLAN-06", "3.8"))
            self.assertIn("DXF", str(getattr(cm.exception, "message", "")) + str(cm.exception))
            pngp = Path(tmp) / "a.png"
            pngp.write_bytes(png_bytes(12, 7))
            res = self.fp.convert(pngp)
            self.assertEqual((res.kind, res.image_kind, res.width, res.height), ("png", "png", 12, 7))
            bdxf = Path(tmp) / "b.dxf"
            bdxf.write_bytes(b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 40)
            with self.assertRaises(self.fp.UnsupportedPlan) as cm:
                self.fp.convert(bdxf)
            self.assertIn(cm.exception.code, ("binary_dxf", "unsupported_format"))
        self.assertEqual(self.fp.detect_plan_kind("x.drawio", b"<mxfile>"), "drawio")
        self.assertEqual(self.fp.detect_plan_kind("x.xml", b"<mxGraphModel>"), "drawio")
        self.assertEqual(self.fp.detect_plan_kind("x.dxf", b"0\nSECTION"), "dxf")
        self.assertEqual(self.fp.detect_plan_kind("x.pdf", b"%PDF-1.4"), "pdf")

    def test_pdf_rasterizer_and_fallback(self):
        pdf = Path(tempfile.mkdtemp(prefix="fathom-t1-")) / "rcp.pdf"
        try:
            from test_api import tiny_pdf  # noqa: WPS433
        except ImportError:  # pragma: no cover
            from tests.test_api import tiny_pdf
        pdf.write_bytes(tiny_pdf())
        try:
            fake = pdf.parent / "fake_raster.py"
            fake.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, %r)\nfrom _helpers import png_bytes\n"
                            "Path(sys.argv[2]).write_bytes(png_bytes(8, 6))\nPath(sys.argv[2] + '.args').write_text(' '.join(sys.argv[1:]))\n"
                            % str(Path(__file__).resolve().parent))
            with temp_env(FATHOM_PDF_RASTERIZER="%s %s {in} {out} {page} {dpi}" % (sys.executable, fake)):
                self.assertTrue(self.fp.rasterizer(), "FR-PLAN-05 FATHOM_PDF_RASTERIZER is a rasterizer")
                data = self.fp.pdf_to_png(pdf, page=0, dpi=150)
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", fr("FR-PLAN-05", "3.8", "command template {in} {out} {page} {dpi}"))
            with temp_env(PATH="", FATHOM_PDF_RASTERIZER=None):
                self.assertIsNone(self.fp.rasterizer())
                with self.assertRaises(self.fp.UnsupportedPlan) as cm:
                    self.fp.pdf_to_png(pdf)
                self.assertEqual(cm.exception.code, "pdf_unsupported", fr("FR-PLAN-05", "3.8"))
                self.assertIn("PNG or SVG", str(getattr(cm.exception, "message", "")) + str(cm.exception))
            if self.fp.rasterizer():
                data = self.fp.pdf_to_png(pdf)
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", fr("FR-PLAN-05", "3.8", "system rasterizer %s" % self.fp.rasterizer()))
        finally:
            shutil.rmtree(str(pdf.parent), ignore_errors=True)

    def test_oda_fake_converter(self):
        tmp = Path(tempfile.mkdtemp(prefix="fathom-t1-"))
        try:
            fake = tmp / "fake_oda.py"
            fake.write_text("import sys, shutil\nfrom pathlib import Path\n"
                            "a = sys.argv[1:]\nPath(%r).write_text(repr(a))\n"
                            "shutil.copy(%r, str(Path(a[1]) / (Path(a[6]).stem + '.dxf')))\nsys.exit(3)\n"
                            % (str(tmp / "args.txt"), str(fixture_path("plans", "fixture.dxf"))))
            wrapper = tmp / "oda"
            wrapper.write_text("#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, fake))
            wrapper.chmod(0o755)
            dwg = tmp / "in" / "plan.dwg"
            dwg.parent.mkdir()
            dwg.write_bytes(b"AC1032" + b"\x00" * 64)
            with temp_env(FATHOM_ODA=str(wrapper), FATHOM_ODA_XVFB=None):
                res = self.fp.convert(dwg)
            self.assertEqual(res.image_kind, "svg", fr("FR-PLAN-07", "3.8", "DWG -> DXF via ODA, then processed as DXF"))
            self.assertIn(b'data-layer="WALLS"', res.data)
            args = eval((tmp / "args.txt").read_text())  # noqa: S307 - our own file
            self.assertEqual(args[2:6], ["ACAD2018", "DXF", "0", "1"], fr("FR-PLAN-07", "3.8", "ODA args"))
            self.assertEqual(args[6], "plan.dwg")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
