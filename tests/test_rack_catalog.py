"""Rackula rack catalog (``fathom/library/rackula/catalog.json``), its images, attribution and generator."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "fathom" / "library" / "rackula" / "catalog.json"
IMAGES = REPO / "fathom" / "static" / "rack-images"
NOTICES = REPO / "THIRD_PARTY_NOTICES.md"
TOOL = REPO / "tools" / "rackula_catalog.py"
RACKULA_SRC = Path("/tmp/rackula")
PINNED = "9c7af6dd28209a776aebdb92080bcf2916cd29e6"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
CATEGORIES = {"server", "network", "firewall", "patch-panel", "power", "storage", "kvm", "av-media", "cooling",
              "shelf", "blank", "cable-management", "chassis", "other"}
AIRFLOWS = {"front-to-rear", "rear-to-front", "left-to-right", "right-to-left", "side-to-rear", "passive", "mixed"}
IMAGE_VENDORS = {"generic", "apc", "eaton", "ac-infinity", "ubiquiti", "netgear", "cisco", "tp-link", "mikrotik",
                 "synology", "qnap", "dell", "apple", "lenovo", "supermicro"}
IMAGE_BUDGET = int(4.5 * 1024 * 1024)


def _tool():
    spec = importlib.util.spec_from_file_location("rackula_catalog", str(TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


class CatalogData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = _catalog()
        cls.templates = cls.cat["templates"]

    def test_header(self):
        c = self.cat
        self.assertEqual(c["source"], "https://github.com/RackulaLives/Rackula")
        self.assertEqual(c["license"], "MIT (Rackula) / CC0 (NetBox devicetype-library data)")
        self.assertEqual(c["commit"], PINNED)
        self.assertRegex(c["generated"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(c["count"], len(self.templates))

    def test_at_least_600_templates(self):
        self.assertGreaterEqual(len(self.templates), 600)

    def test_one_template_per_line(self):
        lines = CATALOG.read_text(encoding="utf-8").splitlines()
        rows = [ln for ln in lines if ln.startswith("    {")]
        self.assertEqual(len(rows), len(self.templates))

    def test_sorted_by_manufacturer_then_model(self):
        keys = [(t["manufacturer"].lower(), t["model"].lower()) for t in self.templates]
        self.assertEqual(keys, sorted(keys))

    def test_ids_unique_and_well_formed(self):
        ids = [t["id"] for t in self.templates]
        self.assertEqual(len(ids), len(set(ids)))
        bad = [i for i in ids if not ID_RE.match(i)]
        self.assertEqual(bad, [])

    def test_no_collision_with_builtin_or_preset_ids(self):
        from fathom import presets

        builtin = {p.stem for p in (REPO / "fathom" / "library" / "templates").glob("*.json")}
        preset_ids = {p["id"] for p in presets.all_presets()}
        ids = {t["id"] for t in self.templates}
        self.assertEqual(ids & builtin, set())
        self.assertEqual(ids & preset_ids, set())
        self.assertIn("cisco-catalyst-9200-24p-rk", ids, "a colliding Rackula slug gets the -rk suffix")

    def test_kinds_in_vocab(self):
        from fathom.vocab import KINDS

        bad = sorted({t["kind"] for t in self.templates} - set(KINDS))
        self.assertEqual(bad, [])

    def test_every_template_validates(self):
        from fathom.library import validate_template

        problems = {t["id"]: validate_template(t) for t in self.templates}
        self.assertEqual({k: v for k, v in problems.items() if v}, {})

    def test_field_shapes(self):
        for t in self.templates:
            with self.subTest(t["id"]):
                self.assertNotIn("source", t, "the library loader stamps source")
                self.assertEqual(t["name"], t["model"])
                self.assertTrue(t["manufacturer"])
                self.assertIsInstance(t["ru"], int)
                self.assertGreaterEqual(t["ru"], 1)
                self.assertIsInstance(t["full_depth"], bool)
                self.assertIn(t["rack_category"], CATEGORIES)
                self.assertNotIn(t["rack_category"], ("blank", "shelf", "cable-management"))
                if "airflow" in t:
                    self.assertIn(t["airflow"], AIRFLOWS)
                if "width" in t:
                    self.assertEqual(t["width"], "half")
                if "weight_kg" in t:
                    self.assertGreaterEqual(t["weight_kg"], 0)
                self.assertEqual(t["tags"], ["rackula"])
                self.assertIsInstance(t["ports"], list)

    def test_kind_mapping_samples(self):
        by_id = {t["id"]: t for t in self.templates}
        expect = {
            "1u-server": "computer", "24-port-switch": "switch", "1u-router-firewall": "network",
            "24-port-patch-panel": "patch_panel", "2u-ups": "power", "1u-fan-panel": "other",
            "1u-video-switcher": "video_switcher", "1u-amplifier": "amp", "1u-audio-processor": "processor",
            "1u-streaming-encoder": "encoder", "blackmagicdesign-atem-constellation-8k": "video_switcher",
            "ubiquiti-uacc-rack-panel-patch-blank-24": "patch_panel", "ubiquiti-usg": "network",
            "ubiquiti-er-x": "network", "tp-link-oc200": "network", "ubiquiti-unifi-application-server": "computer",
            "eaton-tripp-lite-b064-016-02-ipg": "computer", "vertiv-acs8008sac": "network",
            "supermicro-sse-g3648b": "switch",
        }
        for tid, kind in expect.items():
            self.assertEqual(by_id[tid]["kind"], kind, tid)
        routers = [t for t in self.templates if t["rack_category"] == "network" and re.search(r"(?i)edgerouter|\bisr\d", t["model"])]
        self.assertTrue(routers)
        self.assertEqual({t["kind"] for t in routers}, {"network"})
        panels = [t for t in self.templates if re.search(r"(?i)patch\s*panel|keystone", t["model"])]
        self.assertGreaterEqual(len(panels), 9)
        self.assertEqual({t["kind"] for t in panels}, {"patch_panel"})

    def test_ports_from_interfaces(self):
        by_id = {t["id"]: t for t in self.templates}
        self.assertEqual(by_id["24-port-switch"]["ports"],
                         [{"group": "Port", "dir": "io", "medium": "network", "connector": "RJ45", "count": 24}])
        amp = by_id["1u-amplifier"]["ports"]
        self.assertEqual([(g["group"], g["dir"], g["medium"], g.get("count")) for g in amp],
                         [("Input", "in", "analog", 2), ("Speaker", "out", "speaker", 2), ("Control", "io", "rs232", None)])
        self.assertEqual(by_id["1u-fiber-patch-panel"]["ports"][0]["medium"], "fiber")


class CatalogImages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = _catalog()["templates"]

    def _paths(self):
        return {t[k] for t in self.templates for k in ("image_front", "image_rear") if t.get(k)}

    def test_every_image_path_exists(self):
        paths = self._paths()
        self.assertTrue(paths)
        missing = sorted(p for p in paths if not (IMAGES / p).is_file())
        self.assertEqual(missing, [])
        for p in paths:
            self.assertTrue(p.endswith(".webp"), p)
            self.assertIn(p.split("/")[0], IMAGE_VENDORS, p)
            self.assertEqual(len(p.split("/")), 2, p)

    def test_image_paths_are_servable(self):
        """The static route serves only segments starting with a letter or digit."""
        n = 0
        for t in self.templates:
            for k in ("image_front", "image_rear"):
                p = t.get(k)
                if not p:
                    continue
                n += 1
                with self.subTest(t["id"], face=k):
                    bad = [s for s in p.split("/") if not s or s[0] in "_."]
                    self.assertEqual(bad, [], p)
                    self.assertTrue((IMAGES / p).is_file(), p)
        self.assertGreater(n, 0)
        self.assertTrue(any(t.get("image_front", "").startswith("generic/") for t in self.templates))
        dirs = [d.name for d in IMAGES.iterdir() if d.is_dir()]
        self.assertEqual([d for d in dirs if d[0] in "_."], [])

    def test_faces_match_file_names(self):
        for t in self.templates:
            for face in ("front", "rear"):
                if t.get("image_" + face):
                    self.assertTrue(t["image_" + face].endswith("." + face + ".webp"), t["id"])

    def test_no_orphan_images(self):
        files = {p.relative_to(IMAGES).as_posix() for p in IMAGES.glob("*/*.webp")}
        self.assertEqual(files - self._paths(), set())

    def test_image_total_within_budget(self):
        total = sum(p.stat().st_size for p in IMAGES.rglob("*.webp"))
        self.assertLessEqual(total, IMAGE_BUDGET)

    def test_images_are_webp(self):
        for p in sorted(IMAGES.rglob("*.webp"))[:400]:
            head = p.read_bytes()[:12]
            self.assertEqual((head[:4], head[8:12]), (b"RIFF", b"WEBP"), p.name)

    def test_readme_states_origin_and_licence(self):
        text = (IMAGES / "README.md").read_text(encoding="utf-8")
        for word in ("Rackula", "MIT", "vastoholic", "CC0", "tools/rackula_catalog.py"):
            self.assertIn(word, text)


class Attribution(unittest.TestCase):
    def test_notice_mentions_sources_and_licences(self):
        text = NOTICES.read_text(encoding="utf-8")
        for word in ("Rackula", "MIT", "NetBox", "CC0", "vastoholic", "Dracula"):
            self.assertIn(word, text)
        self.assertIn("Copyright (c) 2026 Gareth Evans", text)
        self.assertIn("Permission is hereby granted, free of charge", text)

    def test_package_data_ships_the_catalog(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"library/rackula/*.json"', text)
        self.assertIn('"rackula/*.json"', text)
        self.assertRegex(text, r"(?m)^dependencies = \[\]$")

    def test_generator_credits(self):
        head = TOOL.read_text(encoding="utf-8")[:1200]
        for word in ("Rackula", "MIT", "NetBox", "CC0", "vastoholic"):
            self.assertIn(word, head)


class GeneratorUnits(unittest.TestCase):
    """Generator pieces that need no Rackula checkout."""

    @classmethod
    def setUpClass(cls):
        cls.tool = _tool()

    def test_literal_reader(self):
        ts = '''
        import { CATEGORY_COLOURS } from "$lib/types/constants";
        export const fooDevices: DeviceType[] = [
          // a comment
          { slug: "a-1", u_height: 2, colour: CATEGORY_COLOURS.power, 'quoted-key': 'x\\'y', },
          /* block */ { slug: "b", u_height: 0.5, colour: CATEGORY_COLOURS["av-media"],
            interfaces: portInterfaces(3, "1000base-t"), list: [1, -2, true, null, undefined,], },
        ];
        export function nope(): void { const x = a ?? b; }
        '''
        env = {"CATEGORY_COLOURS": {"power": "#A84A4A", "av-media": "#A85A7A"}}
        out = self.tool.read_device_arrays(ts, env, {"portInterfaces": self.tool._port_interfaces}, "foo.ts")
        self.assertEqual(out[0], {"slug": "a-1", "u_height": 2, "colour": "#A84A4A", "quoted-key": "x'y"})
        self.assertEqual(out[1]["u_height"], 0.5)
        self.assertEqual(out[1]["colour"], "#A85A7A")
        self.assertEqual(out[1]["interfaces"], [{"name": "1", "type": "1000base-t"}, {"name": "2", "type": "1000base-t"},
                                                {"name": "3", "type": "1000base-t"}])
        self.assertEqual(out[1]["list"], [1, -2, True, None, None])

    def test_literal_reader_rejects_unknown_references(self):
        with self.assertRaises(ValueError):
            self.tool.read_device_arrays("const xDevices: T[] = [{ a: SOMETHING }];", {}, {}, "x.ts")
        with self.assertRaises(ValueError):
            self.tool.read_device_arrays("const xDevices: T[] = [...other];", {}, {}, "x.ts")

    def test_sanitize_id(self):
        s = self.tool.sanitize_id
        self.assertEqual(s("Foo_Bar  2.0"), "foo-bar-2-0")
        self.assertEqual(s("--a--b--"), "a-b")
        self.assertEqual(len(s("x" * 200)), 80)

    def test_kind_for(self):
        k = self.tool.kind_for
        self.assertEqual(k("network", "USW-Pro-24"), "switch")
        self.assertEqual(k("network", "UDM-Pro"), "network")
        self.assertEqual(k("network", "CCR2004-16G-2S+"), "network")
        self.assertEqual(k("firewall", "PA-220"), "network")
        self.assertEqual(k("av-media", "Smart Videohub 40x40"), "video_router")
        self.assertEqual(k("av-media", "HyperDeck Studio"), "recorder")
        self.assertEqual(k("av-media", "Wireless Receiver"), "wireless_rx")
        self.assertEqual(k("av-media", "Teranex Mini"), "video")
        self.assertEqual(k("chassis", "Blade Chassis"), "computer")
        self.assertEqual(k("mystery", "X"), "other")

    def test_kind_for_model_keywords_beat_the_category(self):
        k = self.tool.kind_for
        self.assertEqual(k("network", "24-Port Blank Keystone Patch Panel"), "patch_panel")
        self.assertEqual(k("other", "Keystone Panel"), "patch_panel")
        self.assertEqual(k("network", "Cat6 PatchPanel 48"), "patch_panel")
        self.assertEqual(k("power", "Tripp Lite B064-016-02-IPG"), "computer")
        self.assertEqual(k("power", "KVM Console"), "computer")
        self.assertEqual(k("power", "Tripp Lite B096-016"), "network")
        self.assertEqual(k("power", "ACS8008SAC"), "network")
        self.assertEqual(k("other", "Serial Console Server"), "network")
        self.assertEqual(k("power", "Tripp Lite PDUMH15AT"), "power")
        self.assertEqual(k("power", "SMT1500RMI2UC"), "power")

    def test_kind_for_network_and_server_model_codes(self):
        k = self.tool.kind_for
        for model in ("ER-X", "ER-12P", "ERPro-8", "ER605-V2", "ER7206", "OC200", "TD-W8950N", "USG", "USG-Pro-4"):
            self.assertEqual(k("network", model), "network", model)
        self.assertEqual(k("network", "UniFi Application Server"), "computer")
        for model in ("ECS-24-PoE", "S3300-52X", "US-24-250W", "M4350-32F8V", "XSM7224S", "TL-SE2109PB"):
            self.assertEqual(k("network", model), "switch", model)
        self.assertEqual(k("server", "SSE-G3648B"), "switch")
        self.assertEqual(k("server", "Storage SuperServer SSG-610P-ACR12N4H"), "computer")

    def test_ports_grouping(self):
        p = self.tool.ports_from_interfaces
        self.assertEqual(p(None), [])
        got = p([{"name": "HDMI In 2", "type": "hdmi"}, {"name": "HDMI In 3", "type": "hdmi"},
                 {"name": "SDI Out", "type": "sdi-bnc"}, {"name": "Network", "type": "management"},
                 {"name": "Network", "type": "1000base-t"}, {"name": "Uplink", "type": "10gbase-x-sfpp"},
                 {"name": "Odd", "type": "weird"}])
        self.assertEqual(got, [
            {"group": "HDMI In", "dir": "in", "medium": "hdmi", "connector": "HDMI-A", "count": 2, "start": 2},
            {"group": "SDI Out", "dir": "out", "medium": "sdi", "connector": "BNC"},
            {"group": "Network", "dir": "io", "medium": "network", "connector": "RJ45"},
            {"group": "Network 2", "dir": "io", "medium": "network", "connector": "RJ45"},
            {"group": "Uplink", "dir": "io", "medium": "fiber", "connector": "SFP"},
            {"group": "Odd", "dir": "io", "medium": "other"},
        ])
        from fathom.library import validate_template

        self.assertEqual(validate_template({"id": "x-1", "manufacturer": "M", "model": "X", "kind": "other", "ports": got}), [])

    def test_weight_conversion(self):
        w = self.tool.weight_kg
        self.assertEqual(w({"weight": 10, "weight_unit": "lb"}), 4.5)
        self.assertEqual(w({"weight": 2.25, "weight_unit": "kg"}), 2.2)
        self.assertIsNone(w({}))
        self.assertIsNone(w({"weight": 3, "weight_unit": "stone"}))


def _rackula_at_pin():
    if not (RACKULA_SRC / "src" / "lib" / "data").is_dir():
        return False
    try:
        head = subprocess.run(["git", "-C", str(RACKULA_SRC), "rev-parse", "HEAD"], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    return head == PINNED


@unittest.skipUnless(_rackula_at_pin(), "needs a Rackula checkout at %s in %s" % (PINNED[:7], RACKULA_SRC))
class GeneratorDeterminism(unittest.TestCase):
    def _run(self, out_dir: Path, date: str) -> None:
        tool = _tool()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = tool.main(["--src", str(RACKULA_SRC), "--out", str(out_dir / "catalog.json"),
                            "--images", str(out_dir / "img"), "--date", date])
        self.assertEqual(rc, 0)

    def test_regenerates_the_committed_files_byte_for_byte(self):
        date = _catalog()["generated"]
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            a, b = Path(a), Path(b)
            self._run(a, date)
            self._run(b, date)
            self.assertEqual((a / "catalog.json").read_bytes(), (b / "catalog.json").read_bytes())
            self.assertEqual((a / "catalog.json").read_bytes(), CATALOG.read_bytes(), "catalog.json is stale: rerun the generator")
            gen = {p.relative_to(a / "img").as_posix(): p.read_bytes() for p in (a / "img").rglob("*.webp")}
            committed = {p.relative_to(IMAGES).as_posix(): p.read_bytes() for p in IMAGES.rglob("*.webp")}
            self.assertEqual(sorted(gen), sorted(committed))
            self.assertTrue(all(gen[k] == committed[k] for k in gen))


if __name__ == "__main__":
    unittest.main()
