"""Phase 5 P5C: patch canvas SVG / PNG / PDF and floor plan PNG / PDF exports (SPEC §3.23 FR-EXP-06/07, §5.7, §5.9, §6.9.10).

``fathom.patch_svg`` is checked against the campus sample (one card per device, one wire per cable, ghost cards for
cross-room ends, legend, unplaced devices laid out, ``?scene=`` through the Phase 3 scenes API) and its ``GEOM`` is
compared with ``patchview-core.js`` (regex-read from the source). The raster routes are checked for their 400
``chrome_missing`` answer with ``find_chrome`` patched to None, for HEAD answering without rendering, and - when
``FATHOM_CHROME`` points at a browser - for a real PNG (> 5 kB) and PDF (``%PDF``). Builds must contain
``rooms/<room>/patch.svg``.

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_patch_export.py``.
"""
from __future__ import annotations

import json
import os
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

try:
    from _helpers import REPO, call, fr, get_app, install_campus, jbody, read_json, requires, temp_data_dir, uniq
except ImportError:  # pragma: no cover
    from tests._helpers import REPO, call, fr, get_app, install_campus, jbody, read_json, requires, temp_data_dir, uniq

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
CORE_JS = REPO / "fathom" / "static" / "js" / "patchview-core.js"


def _ids(svg, attr):
    return re.findall(r'%s="([^"]+)"' % attr, svg)


def _campus_doc():
    return read_json(REPO / "fathom" / "samples" / "campus-demo" / "project.json")


def _expected_main(doc):
    """Devices in ``main`` (status != retired), the cables that touch them and the cross-room ends those cables add."""
    by_id = {d["id"]: d for d in doc["devices"]}
    ok = lambda e: (e.get("status") or "installed") != "retired"  # noqa: E731
    prim = {d["id"] for d in doc["devices"] if d.get("room") == "main" and ok(d)}
    ghosts = set()
    for c in doc["cables"]:
        f, t = c["from"]["device"], c["to"]["device"]
        if not (ok(c) and ok(by_id[f]) and ok(by_id[t])):
            continue
        if f in prim and t not in prim:
            ghosts.add(t)
        elif t in prim and f not in prim:
            ghosts.add(f)
    cards = prim | ghosts
    cables = [c["id"] for c in doc["cables"] if c["from"]["device"] in cards and c["to"]["device"] in cards
              and ok(c) and ok(by_id[c["from"]["device"]]) and ok(by_id[c["to"]["device"]])]
    return prim, ghosts, cables


# ================================================================== fathom.patch_svg


class PatchSvg(unittest.TestCase):
    def setUp(self):
        self.mod = requires("patch_svg")
        self.doc = _campus_doc()

    def test_campus_main_cards_and_wires(self):
        svg = self.mod.patch_svg(self.doc, "main")
        prim, ghosts, cables = _expected_main(self.doc)
        self.assertTrue(prim and ghosts and cables, "campus main has devices, cross-room cables and ghosts")
        devs = _ids(svg, "data-device")
        self.assertEqual(sorted(devs), sorted(prim | ghosts), fr("FR-EXP-06", "6.9.10", "one card per device (+ ghost per cross-room end)"))
        self.assertEqual(len(devs), len(set(devs)), "every card once")
        self.assertEqual(sorted(_ids(svg, "data-cable")), sorted(cables), fr("FR-EXP-06", "6.9.10", "one wire per cable"))
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg", "well-formed SVG with the SVG namespace")
        self.assertEqual((root.get("data-room"), root.get("data-devices"), root.get("data-cables")), ("main", str(len(devs)), str(len(cables))))
        self.assertEqual(len(re.findall(r'<g class="card ext"', svg)), len(ghosts), "ghost cards are marked ext")
        for gid in ghosts:
            self.assertRegex(svg, r'data-device="%s"' % re.escape(gid))
        self.assertNotIn("<script", svg)
        self.assertNotIn("<foreignObject", svg)

    def test_title_block_and_legend(self):
        svg = self.mod.patch_svg(self.doc, "main")
        title = re.search(r"<title>(.*?)</title>", svg).group(1)
        self.assertIn("Main Auditorium", title)
        self.assertIn('<g class="title">', svg)
        meta = self.doc.get("meta") or {}
        self.assertIn(str(meta.get("org") or meta.get("title") or "Fathom").split(" ")[0], svg, "title block names the project")
        import datetime

        self.assertIn(datetime.date.today().isoformat(), svg, "title block carries the date")
        self.assertRegex(svg, r"\d+ devices \u00b7 \d+ cables")
        legend = re.search(r'<g class="legend">(.*?)</g>', svg, re.S).group(1)
        labels = re.findall(r'<text[^>]*>([^<]+)</text>', legend)
        self.assertIn("Audio", labels, fr("FR-EXP-06", "6.9.10", "legend lists the disciplines in use"))
        self.assertIn("Video", labels)
        self.assertEqual(len(labels), len(set(labels)), "each discipline once")
        self.assertNotIn("Scene:", svg, "no scene line while Base is active")

    def test_unplaced_devices_are_laid_out(self):
        # campus main stores no patch positions at all: every card goes through auto_layout
        self.assertFalse(any(isinstance(d.get("patch"), dict) and "x" in d["patch"] for d in self.doc["devices"] if d.get("room") == "main"))
        svg = self.mod.patch_svg(self.doc, "main")
        xy = [(float(a), float(b)) for a, b in re.findall(r'<g class="card[^"]*" data-device="[^"]+" transform="translate\(([-\d.]+) ([-\d.]+)\)"', svg)]
        self.assertEqual(len(xy), len(_ids(svg, "data-device")))
        self.assertEqual(len(set(xy)), len(xy), fr("FR-EXP-06", "6.9.10", "unplaced cards get distinct positions"))
        # a mix: the placed card keeps its coordinates, the unplaced one is put below the placed block
        doc = {"fathom": 2, "meta": {"title": "Mix"}, "rooms": [{"id": "r", "name": "R"}],
               "devices": [{"id": "a", "name": "A", "kind": "mixer", "room": "r", "patch": {"x": 100, "y": 200},
                            "ports": [{"id": "o1", "name": "Out 1", "dir": "out", "medium": "analog"}]},
                           {"id": "b", "name": "B", "kind": "speaker", "room": "r",
                            "ports": [{"id": "i1", "name": "In 1", "dir": "in", "medium": "analog"}]}],
               "cables": [{"id": "c1", "medium": "analog", "from": {"device": "a", "port": "o1"}, "to": {"device": "b", "port": "i1"}}]}
        svg = self.mod.patch_svg(doc, "r")
        pos = dict((d, (float(x), float(y))) for d, x, y in re.findall(r'data-device="([^"]+)" transform="translate\(([-\d.]+) ([-\d.]+)\)"', svg))
        self.assertEqual(pos["a"], (100.0, 200.0))
        self.assertIn("b", pos)
        self.assertGreater(pos["b"][1], 200.0, "the unplaced card is laid out below the placed ones")
        self.assertEqual(_ids(svg, "data-cable"), ["c1"])

    def test_filters_and_empty_room(self):
        svg_all = self.mod.patch_svg(self.doc, "main")
        svg_audio = self.mod.patch_svg(self.doc, "main", filter={"disciplines": ["audio"]})
        self.assertLess(len(_ids(svg_audio, "data-device")), len(_ids(svg_all, "data-device")), "discipline filter drops cards")
        svg_built = self.mod.patch_svg(self.doc, "main", filter={"state": "as_built"})
        planned = {d["id"] for d in self.doc["devices"] if d.get("status") == "planned"}
        self.assertTrue(planned.isdisjoint(set(_ids(svg_built, "data-device"))), "as_built leaves planned devices out")
        doc = dict(self.doc, rooms=self.doc["rooms"] + [{"id": "void", "name": "Void"}])
        svg = self.mod.patch_svg(doc, "void")
        self.assertEqual(_ids(svg, "data-device"), [])
        self.assertIn("No devices in Void.", svg)
        ET.fromstring(svg)

    def test_scene_argument(self):
        scenes = requires("scenes")
        with self.assertRaises(KeyError):
            self.mod.patch_svg(self.doc, "main", scene="sc-nope")
        base = self.mod.patch_svg(self.doc, "main", scene="base")
        self.assertEqual(sorted(_ids(base, "data-cable")), sorted(_ids(self.mod.patch_svg(self.doc, "main"), "data-cable")))
        self.assertTrue(hasattr(scenes, "apply") and hasattr(scenes, "scene_data"), "scenes API the renderer builds on")

    def test_geom_matches_patchview_core(self):
        src = CORE_JS.read_text(encoding="utf-8")
        m = re.search(r"export const GEOM\s*=\s*\{([^}]*)\}", src)
        self.assertIsNotNone(m, "patchview-core.js exports GEOM")
        js = {}
        for k, v in re.findall(r"(\w+)\s*:\s*([-\d.]+)", m.group(1)):
            js[k] = float(v) if "." in v else int(v)
        self.assertEqual(self.mod.GEOM, js, fr("FR-EXP-06", "6.9.10", "fathom.patch_svg.GEOM mirrors patchview-core.js GEOM"))


# ================================================================== routes (§5.7, §5.9)


class ExportRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = temp_data_dir()
        cls.data = cls._ctx.__enter__()
        cls.name = uniq("campus")
        install_campus(cls.data, cls.name)

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def setUp(self):
        self.app = get_app()

    def req(self, method, path, body=None):
        return call(self.app, method, path, body, dict(JSON_H) if body is not None else {"X-Fathom": "1"})

    def url(self, tail):
        return "/api/v2/projects/%s/%s" % (self.name, tail)

    def test_patch_svg_route(self):
        st, h, b = self.req("GET", self.url("rooms/main/patch.svg"))
        self.assertEqual(st, 200, b[:300])
        self.assertTrue(h["content-type"].startswith("image/svg+xml"))
        self.assertIn('filename="%s-main-patch.svg"' % self.name, h["content-disposition"])
        svg = b.decode("utf-8")
        prim, ghosts, cables = _expected_main(_campus_doc())
        devs = _ids(svg, "data-device")
        # the route adds the import overlay's devices as dotted "auto" cards, as the live canvas does
        auto = len(re.findall(r'<g class="card[^"]*\bauto\b', svg))
        self.assertTrue(set(prim | ghosts) <= set(devs))
        self.assertEqual(len(devs), len(prim | ghosts) + auto, "doc cards + overlay (auto) cards")
        self.assertEqual(len(_ids(svg, "data-cable")), len(cables))
        st, _, _ = self.req("GET", self.url("rooms/nope/patch.svg"))
        self.assertEqual(st, 404)
        st, _, _ = self.req("GET", self.url("rooms/main/patch.svg?scene=sc-nope"))
        self.assertEqual(st, 404, "unknown scene -> 404")
        st, _, _ = self.req("GET", self.url("rooms/main/patch.svg?state=bogus"))
        self.assertEqual(st, 400)
        st, _, b = self.req("GET", self.url("rooms/main/patch.svg?state=as_built"))
        self.assertEqual(st, 200)
        self.assertLess(len(_ids(b.decode(), "data-device")), len(devs), "as_built leaves the planned cards out")

    def test_scene_query_changes_the_cable_set(self):
        st, _, b = self.req("GET", self.url(""))
        self.assertEqual(st, 200)
        rev = jbody(b)["revision"]
        st, _, b = self.req("POST", self.url("scenes"), {"name": "P5C scene", "activate": True})
        self.assertIn(st, (200, 201), b[:300])
        sid = jbody(b)["scene"]["id"]
        _, _, b = self.req("GET", self.url(""))
        j = jbody(b)
        rev = j["revision"]
        base_svg = self.req("GET", self.url("rooms/main/patch.svg?scene=base"))[2].decode()
        before = _ids(base_svg, "data-cable")
        victim = before[0]
        st, _, b = self.req("POST", self.url("changes"), {"base_revision": rev, "summary": "p5c", "ops": [{"op": "del", "coll": "cables", "id": victim}]})
        self.assertEqual(st, 200, b[:300])
        scene_svg = self.req("GET", self.url("rooms/main/patch.svg?scene=%s" % sid))[2].decode()
        live_svg = self.req("GET", self.url("rooms/main/patch.svg"))[2].decode()
        base_svg = self.req("GET", self.url("rooms/main/patch.svg?scene=base"))[2].decode()
        self.assertIn(victim, _ids(base_svg, "data-cable"), fr("FR-EXP-06", "5.9", "?scene=base still draws the cable"))
        self.assertNotIn(victim, _ids(scene_svg, "data-cable"), fr("FR-EXP-06", "5.9", "?scene=<sid> draws the scene's cables"))
        self.assertEqual(len(_ids(scene_svg, "data-cable")), len(before) - 1)
        self.assertNotIn(victim, _ids(live_svg, "data-cable"), "the live doc is the active scene")
        self.assertIn("Scene: P5C scene", live_svg, "the active scene is named in the title block")
        self.assertIn("Scene: P5C scene", scene_svg)
        st, _, b = self.req("POST", self.url("scenes/base/activate"), {})
        self.assertEqual(st, 200, b[:300])

    def test_chrome_missing_400(self):
        with mock.patch("fathom.export.find_chrome", return_value=None):
            for tail in ("rooms/main/patch.png", "rooms/main/patch.pdf", "floorplans/fp-main-floor.png", "floorplans/fp-main-floor.pdf?runs=1"):
                for method in ("GET", "HEAD"):
                    st, h, b = self.req(method, self.url(tail))
                    self.assertEqual(st, 400, "%s %s -> %s %s" % (method, tail, st, b[:200]))
                    if method == "GET":
                        j = jbody(b)
                        self.assertEqual(j["error"], "chrome_missing", fr("FR-EXP-06", "5.9", "400 chrome_missing"))
                        self.assertIn("Google Chrome", j["message"])
                        self.assertIn("SVG export always works", j["message"])
            st, _, _ = self.req("GET", self.url("rooms/main/patch.svg"))
            self.assertEqual(st, 200, "SVG export never needs Chrome")

    def test_head_answers_without_rendering(self):
        def boom(*a, **kw):
            raise AssertionError("HEAD must not render")

        with mock.patch("fathom.export.find_chrome", return_value="/usr/bin/true"), \
                mock.patch("fathom.patch_svg.patch_svg", side_effect=boom), \
                mock.patch("fathom.floorplan.plan_svg", side_effect=boom), \
                mock.patch("fathom.raster.render_bytes", side_effect=boom):
            st, h, b = self.req("HEAD", self.url("rooms/main/patch.png"))
            self.assertEqual(st, 200, b[:200])
            self.assertEqual(b, b"")
            self.assertEqual(h["content-type"], "image/png")
            self.assertEqual(h["content-disposition"], 'attachment; filename="%s-main-patch.png"' % self.name)
            st, h, _ = self.req("HEAD", self.url("rooms/main/patch.pdf"))
            self.assertEqual((st, h["content-type"]), (200, "application/pdf"))
            st, h, _ = self.req("HEAD", self.url("floorplans/fp-main-floor.pdf?runs=1"))
            self.assertEqual((st, h["content-type"]), (200, "application/pdf"))
            self.assertEqual(h["content-disposition"], 'attachment; filename="%s-fp-main-floor-runs.pdf"' % self.name)
            st, _, _ = self.req("HEAD", self.url("rooms/nope/patch.png"))
            self.assertEqual(st, 404)
            st, _, _ = self.req("HEAD", self.url("floorplans/nope.png"))
            self.assertEqual(st, 404)

    def test_chrome_failed_502(self):
        raster = requires("raster")
        with mock.patch("fathom.export.find_chrome", return_value="/usr/bin/true"), \
                mock.patch("fathom.raster.render_bytes", side_effect=raster.RasterError("chrome_failed", "exit 1: boom")):
            st, _, b = self.req("GET", self.url("rooms/main/patch.png"))
            self.assertEqual(st, 502, b[:200])
            j = jbody(b)
            self.assertEqual(j.get("code"), "chrome_failed")
            self.assertEqual(j["details"]["detail"], "exit 1: boom")
            st, _, _ = self.req("GET", self.url("rooms/main/patch.png?width=99999"))
            self.assertEqual(st, 502, "width is clamped, not rejected")
            st, _, _ = self.req("GET", self.url("rooms/main/patch.pdf?paper=A0"))
            self.assertEqual(st, 400, "unknown paper -> 400")

    def _chrome(self):
        export = requires("export")
        if not os.environ.get("FATHOM_CHROME") or not export.find_chrome():
            self.skipTest("set FATHOM_CHROME to render PNG/PDF with headless Chrome")

    def test_patch_png_and_pdf_with_chrome(self):
        self._chrome()
        st, h, b = self.req("GET", self.url("rooms/chapel/patch.png?width=800"))
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(h["content-type"], "image/png")
        self.assertTrue(b.startswith(b"\x89PNG"), "PNG signature")
        self.assertGreater(len(b), 5 * 1024, fr("FR-EXP-06", "5.9", "patch.png > 5 kB"))
        import struct

        w = struct.unpack(">I", b[16:20])[0]
        self.assertEqual(w, 800, "?width= sets the pixel width")
        self.assertEqual(h["content-disposition"], 'attachment; filename="%s-chapel-patch.png"' % self.name)
        st, h, b = self.req("GET", self.url("rooms/chapel/patch.pdf"))
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(h["content-type"], "application/pdf")
        self.assertTrue(b.startswith(b"%PDF"), fr("FR-EXP-06", "5.9", "patch.pdf starts with %PDF"))
        self.assertEqual(h["content-disposition"], 'attachment; filename="%s-chapel-patch.pdf"' % self.name)

    def test_floorplan_png_with_chrome(self):
        self._chrome()
        st, h, b = self.req("GET", self.url("floorplans/fp-chapel.png?width=600&runs=1"))
        self.assertEqual(st, 200, b[:300])
        self.assertTrue(b.startswith(b"\x89PNG"))
        self.assertGreater(len(b), 5 * 1024, fr("FR-EXP-07", "5.7", "floor plan PNG > 5 kB"))
        self.assertEqual(h["content-disposition"], 'attachment; filename="%s-fp-chapel-runs.png"' % self.name)

    def test_openapi_lists_the_routes(self):
        st, _, b = self.req("GET", "/api/openapi.json")
        self.assertEqual(st, 200)
        paths = jbody(b)["paths"]
        for p in ("/api/v2/projects/{name}/rooms/{room}/patch.svg", "/api/v2/projects/{name}/rooms/{room}/patch.{fmt}",
                  "/api/v2/projects/{name}/floorplans/{fp}.{fmt}"):
            self.assertIn(p, paths, "export route documented")
            self.assertIn("get", paths[p])
            self.assertTrue(paths[p]["get"].get("summary"))


# ================================================================== raster helpers


class RasterModule(unittest.TestCase):
    def test_viewbox_and_errors(self):
        raster = requires("raster")
        self.assertEqual(raster.viewbox_size('<svg viewBox="-10 -20 300 150">'), (300.0, 150.0))
        self.assertEqual(raster.viewbox_size('<svg width="40" height="30">'), (40.0, 30.0))
        err = raster.RasterError("chrome_failed", "x")
        self.assertEqual((err.code, err.detail), ("chrome_failed", "x"))
        self.assertEqual(raster.RasterError("chrome_missing").code, "chrome_missing")
        with mock.patch("fathom.export.find_chrome", return_value=None):
            self.assertFalse(raster.available())
            with self.assertRaises(raster.RasterError) as cm:
                raster.render_bytes("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'/>", "png")
            self.assertEqual(cm.exception.code, "chrome_missing")
        self.assertEqual(sorted(raster.PAPERS), ["A3", "A4", "letter", "tabloid"])
        self.assertEqual(raster.MAX_PNG_WIDTH, 6000)


# ================================================================== builds (§5.9)


class BuildFiles(unittest.TestCase):
    def test_build_writes_patch_svg_per_room(self):
        export = requires("export")
        requires("export:build_doc")
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            run = Path(export.build_doc(str(pdir), run_dir=data / "runs" / "p5c", base_url="http://localhost:8080"))
            doc = read_json(pdir / "project.json")
            for room in doc["rooms"]:
                p = run / "rooms" / room["id"] / "patch.svg"
                self.assertTrue(p.is_file(), fr("FR-EXP-06", "5.9", "build has rooms/%s/patch.svg" % room["id"]))
                svg = p.read_text(encoding="utf-8")
                self.assertEqual(re.search(r'data-room="([^"]+)"', svg).group(1), room["id"])
                self.assertFalse((run / "rooms" / room["id"] / "patch.pdf").exists(), "no PDF without the pdf flag")
            notes = (run / "build-notes.txt").read_text(encoding="utf-8")
            self.assertIn("rooms/main/patch.svg", notes, "build notes list the patch canvases")
            import inspect

            from fathom.floorplan import plan_svg

            runs_svg = run / "floorplans" / "fp-main-floor-runs.svg"
            if "runs" in inspect.signature(plan_svg).parameters:
                self.assertTrue(runs_svg.is_file(), fr("FR-EXP-07", "5.9", "floorplans/<id>-runs.svg when plan_svg takes runs="))
                self.assertIn("floorplans/fp-main-floor-runs.svg", notes)
            else:
                self.assertFalse(runs_svg.exists())
                self.assertIn("runs", notes, "the notes say why the runs SVGs are missing")
            names = json.loads((run / "project.json").read_text(encoding="utf-8")).get("rooms")
            self.assertEqual(len(names), len(doc["rooms"]))


if __name__ == "__main__":
    unittest.main()
