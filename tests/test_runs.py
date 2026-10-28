"""Phase 5 P5A — cable runs on floor plans (FR-PLAN-14..17, SPEC §4.3.10/11, §5.7, §6.9.9).

Geometry (`fathom/runs.py`), schema (`paths[]`, `route`), the plan SVG runs layer,
the schedule's `length_est_m` column and the three `/floorplans/<fp>/runs*` routes.
"""

from __future__ import annotations

import copy
import csv
import io
import math
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from _helpers import SAMPLES, basic, call, fr, get_app, install_project, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import SAMPLES, basic, call, fr, get_app, install_project, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
DXF = SAMPLES / "floorplans" / "main-floor.dxf"
P = "/api/v2/projects/proj"
FP = "fp-main"
FT_PER_M = 1 / 0.3048


def _dxf_size():
    """(width, height) of the DXF fixture's rendered SVG (what an upload stores in ``image``)."""
    floorplan = requires("floorplan")
    res = floorplan.convert(DXF)
    return float(res.width), float(res.height)


def _plan(w, h, *, unit="m", calibrated=True, markers=None, paths=None):
    fp = {"id": FP, "name": "Main floor", "room": "main", "source": {"kind": "dxf"},
          "image": {"kind": "svg", "width": w, "height": h}, "markers": markers or [], "paths": paths or []}
    if calibrated:
        # 10 m between x = 0.1 and x = 0.5 (0.4 of the width)
        fp["calibration"] = {"p1": [0.1, 0.5], "p2": [0.5, 0.5], "distance": 10.0 * (FT_PER_M if unit == "ft" else 1.0), "unit": unit}
    return fp


def _cable(cid, a, b, route=None, **extra):
    c = {"id": cid, "from": {"device": a}, "to": {"device": b}, "medium": "dante"}
    if route is not None:
        c["route"] = route
    c.update(extra)
    return c


def _doc(fp, cables, devices=("a", "b", "c")):
    """A sunday-demo doc with extra bare devices, the plan and the cables (valid for the API)."""
    d = sunday_doc()
    for did in devices:
        d["devices"].append({"id": did, "name": did.upper(), "kind": "other", "room": "main", "ports": []})
    d["floorplans"] = [fp]
    d["cables"] = [c for c in d["cables"] if not c.get("bundle")] + cables
    d["bundles"] = []
    return d


def _mx_my(w, h):
    """metres per normalised unit for ``_plan``: 10 m over 0.4 of the width; pixels are square."""
    mx = 10.0 / 0.4
    return mx, mx * h / w


class Geometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = requires("runs")
        cls.w, cls.h = _dxf_size()

    def test_scale_from_calibration(self):
        R = self.runs
        fp = _plan(self.w, self.h)
        mx, my = R.meters_per_norm(fp)
        emx, emy = _mx_my(self.w, self.h)
        self.assertAlmostEqual(mx, emx, places=6, msg=fr("FR-PLAN-10", "6.9.9", "x metres per normalised unit"))
        self.assertAlmostEqual(my, emy, places=6, msg="y scale follows the image aspect (square pixels)")
        self.assertAlmostEqual(R.polyline_length([[0.1, 0.2], [0.5, 0.2]], fp), 10.0, places=6)
        self.assertIsNone(R.meters_per_norm(_plan(self.w, self.h, calibrated=False)), "uncalibrated -> None")
        bad = _plan(self.w, self.h)
        bad["calibration"]["p2"] = bad["calibration"]["p1"]
        self.assertIsNone(R.meters_per_norm(bad), "zero-length calibration is no calibration")

    def test_straight_run_on_dxf_plan_is_ten_metres(self):
        R = self.runs
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}])
        doc = _doc(fp, [_cable("c1", "a", "b")])
        run = R.resolve_run(doc, fp, doc["cables"][-1])
        self.assertIsNotNone(run)
        self.assertLess(abs(run["length_m"] - 10.0) / 10.0, 0.01, fr("FR-PLAN-16", "6.9.9", "10 m calibrated -> 10 m run (±1 %)"))
        self.assertEqual((run["unit"], run["auto"], run["mode"], run["plan"], run["cable"]), ("m", True, "auto", FP, "c1"))
        self.assertEqual(run["points"], [[0.1, 0.2], [0.5, 0.2]])
        self.assertEqual([s["kind"] for s in run["segments"]], ["free"])
        self.assertEqual(run["estimate_m"], run["length_m"], "no slack / drop / elevation")
        # a vertical pair spanning the same pixel distance is also 10 m (y scale)
        dy = 0.4 * self.w / self.h
        fp2 = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.3, "y": 0.1}, {"device": "b", "x": 0.3, "y": 0.1 + dy}])
        run2 = R.resolve_run(_doc(fp2, [_cable("c1", "a", "b")]), fp2, _cable("c1", "a", "b"))
        self.assertLess(abs(run2["length_m"] - 10.0) / 10.0, 0.01)

    def test_run_needs_both_markers(self):
        R = self.runs
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}])
        doc = _doc(fp, [_cable("c1", "a", "b"), _cable("c2", "b", "c")])
        self.assertIsNone(R.resolve_run(doc, fp, doc["cables"][-2]), "one marker missing -> no run")
        out = R.plan_runs(doc, FP)
        self.assertEqual(([r["cable"] for r in out["runs"]], out["unplaced"]), ([], ["c1"]), fr("FR-PLAN-15", "5.7", "unplaced = exactly one end placed"))
        self.assertEqual(out["totals"], {"runs": 0, "length_m": 0.0, "estimate_m": 0.0})
        with self.assertRaises(KeyError):
            R.plan_runs(doc, "fp-none")

    def test_via_path_follows_the_corners(self):
        R = self.runs
        mx, my = _mx_my(self.w, self.h)
        path = {"id": "pt-tray", "name": "Tray", "kind": "tray", "points": [[0.1, 0.3], [0.3, 0.3], [0.3, 0.4], [0.5, 0.4], [0.5, 0.3]]}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}], paths=[path])
        doc = _doc(fp, [_cable("c1", "a", "b", {"plan": FP, "via": ["pt-tray"]})])
        run = R.resolve_run(doc, fp, doc["cables"][-1])
        # a -> down to the tray start, along the three corners, up to b
        expected = 0.1 * my + (0.2 * mx + 0.1 * my + 0.2 * mx + 0.1 * my) + 0.1 * my
        self.assertLess(abs(run["length_m"] - expected) / expected, 0.01, fr("FR-PLAN-15", "6.9.9", "via run = hand-computed polyline"))
        self.assertEqual(run["points"], [[0.1, 0.2], [0.1, 0.3], [0.3, 0.3], [0.3, 0.4], [0.5, 0.4], [0.5, 0.3], [0.5, 0.2]])
        self.assertEqual([(s["kind"], s["path"]) for s in run["segments"]], [("free", None), ("path", "pt-tray"), ("free", None)])
        self.assertAlmostEqual(run["segments"][1]["length_m"], round(R.polyline_length(path["points"], fp), 2), places=1)
        self.assertEqual(run["via"], ["pt-tray"])
        self.assertTrue(run["auto"])
        # the path's own length is reported with the plan
        out = R.plan_runs(doc, FP)
        self.assertAlmostEqual(out["paths"][0]["length_m"], round(0.4 * mx + 0.2 * my, 2), places=1)

    def test_via_enters_at_the_nearest_point_and_chains_paths(self):
        R = self.runs
        mx, my = _mx_my(self.w, self.h)
        tray = {"id": "pt-1", "kind": "tray", "points": [[0.0, 0.3], [1.0, 0.3]]}
        trench = {"id": "pt-2", "kind": "trench", "points": [[0.5, 0.3], [0.5, 0.9]]}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.2, "y": 0.1}, {"device": "b", "x": 0.6, "y": 0.8}], paths=[tray, trench])
        doc = _doc(fp, [_cable("c1", "a", "b", {"plan": FP, "via": ["pt-1", "pt-2"]})])
        run = R.resolve_run(doc, fp, doc["cables"][-1])
        self.assertEqual(run["points"], [[0.2, 0.1], [0.2, 0.3], [0.5, 0.3], [0.5, 0.8], [0.6, 0.8]],
                         "drop onto the tray, along it to where the trench starts, down the trench, across to b")
        expected = 0.2 * my + 0.3 * mx + 0.5 * my + 0.1 * mx
        self.assertLess(abs(run["length_m"] - expected) / expected, 0.01)
        self.assertEqual([(s["kind"], s["path"]) for s in run["segments"]], [("free", None), ("path", "pt-1"), ("path", "pt-2"), ("free", None)])
        # unknown via ids are ignored (straight line), a route for another plan too
        d2 = _doc(fp, [_cable("c1", "a", "b", {"plan": FP, "via": ["pt-none"]}), _cable("c2", "a", "b", {"plan": "fp-other", "via": ["pt-1"]})])
        self.assertEqual(R.resolve_run(d2, fp, d2["cables"][-2])["points"], [[0.2, 0.1], [0.6, 0.8]])
        self.assertEqual(R.resolve_run(d2, fp, d2["cables"][-1])["points"], [[0.2, 0.1], [0.6, 0.8]])

    def test_manual_points_slack_drop_elevation(self):
        R = self.runs
        mx, my = _mx_my(self.w, self.h)
        path = {"id": "pt-1", "kind": "catwalk", "points": [[0.1, 0.3], [0.5, 0.3]], "elevation_m": 4}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}], paths=[path])
        manual = _cable("c1", "a", "b", {"plan": FP, "mode": "manual", "points": [[0.1, 0.6], [0.5, 0.6]], "slack_m": 1.5, "drop_m": 2})
        auto = _cable("c2", "a", "b", {"plan": FP, "via": ["pt-1"], "slack_m": 0.5, "drop_m": 1})
        doc = _doc(fp, [manual, auto])
        run = R.resolve_run(doc, fp, manual)
        self.assertEqual(run["points"], [[0.1, 0.2], [0.1, 0.6], [0.5, 0.6], [0.5, 0.2]], "manual corners verbatim between the markers")
        self.assertFalse(run["auto"])
        geo = 0.4 * my + 0.4 * mx + 0.4 * my
        self.assertAlmostEqual(run["length_m"], round(geo, 2), places=1)
        self.assertAlmostEqual(run["estimate_m"], round(geo + 1.5 + 2 * 2, 2), places=1, msg="estimate = length + slack + 2 × drop")
        self.assertEqual([s["kind"] for s in run["segments"]], ["drop", "free", "drop"])
        self.assertEqual((run["segments"][0]["length_m"], run["segments"][-1]["length_m"]), (2.0, 2.0))
        run2 = R.resolve_run(doc, fp, auto)
        geo2 = 0.1 * my + 0.4 * mx + 0.1 * my
        self.assertAlmostEqual(run2["estimate_m"], round(geo2 + 0.5 + 2 * 1 + 4, 2), places=1, msg="+ elevation of the path used, once")
        self.assertEqual(run2["elevation_m"], 4.0)

    def test_feet_and_uncalibrated_plans(self):
        R = self.runs
        markers = [{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}]
        fp_ft = _plan(self.w, self.h, unit="ft", markers=markers)
        run = R.resolve_run(_doc(fp_ft, [_cable("c1", "a", "b")]), fp_ft, _cable("c1", "a", "b"))
        self.assertLess(abs(run["length_m"] - 10.0) / 10.0, 0.01, fr("FR-PLAN-10", "6.9.9", "ft calibration converted to metres"))
        self.assertEqual(run["unit"], "m")
        fp_px = _plan(self.w, self.h, calibrated=False, markers=markers)
        doc = _doc(fp_px, [_cable("c1", "a", "b")])
        run = R.resolve_run(doc, fp_px, doc["cables"][-1])
        self.assertEqual(run["unit"], "px")
        self.assertAlmostEqual(run["length_m"], round(0.4 * self.w, 2), places=1, msg="uncalibrated: plan pixels")
        out = R.plan_runs(doc, FP)
        self.assertEqual((out["unit"], out["calibrated"]), ("px", False))
        self.assertIsNone(R.estimate(doc, FP, "c1"), "no metres without a calibration")
        self.assertEqual(R.estimate_ops(doc, FP, ["c1"]), [])

    def test_snap_and_nearest_point(self):
        R = self.runs
        path = {"id": "pt-1", "kind": "tray", "points": [[0.1, 0.4], [0.6, 0.4], [0.6, 0.8]]}
        fp = _plan(self.w, self.h, paths=[path, {"id": "pt-2", "kind": "floor", "points": [[0.0, 0.0], [0.0, 1.0]]}])
        hit = R.snap(fp, [0.3, 0.41])
        self.assertEqual((hit["path"], hit["point"]), ("pt-1", [0.3, 0.4]), fr("FR-PLAN-14", "5.7", "Nearest Route snaps onto the tray"))
        self.assertAlmostEqual(hit["dist"], 0.01, places=6)
        self.assertAlmostEqual(hit["t"], 0.2 / 0.9, places=5, msg="t = fraction of the path length")
        self.assertIsNone(R.snap(fp, [0.3, 0.5]), "0.1 away > default 0.02")
        self.assertIsNotNone(R.snap(fp, [0.3, 0.5], max_dist_norm=0.15))
        self.assertEqual(R.snap(fp, [0.01, 0.9])["path"], "pt-2", "nearest of several paths")
        pt, t, dist = R.nearest_point_on_path(path, [0.6, 0.95])
        self.assertEqual((pt, t), ([0.6, 0.8], 1.0))
        self.assertAlmostEqual(dist, 0.15, places=9)
        pt, t, dist = R.nearest_point_on_path(path, [0.8, 0.6])
        self.assertEqual(pt, [0.6, 0.6])
        self.assertEqual(R.project_to_paths(fp, [0.3, 0.41], 0.02)[0], "pt-1")
        self.assertIsNone(R.project_to_paths(_plan(self.w, self.h), [0.3, 0.4], 1.0), "no paths -> None")

    def test_estimate_ops_round_up_and_skip_equal(self):
        R = self.runs
        markers = [{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}]
        fp = _plan(self.w, self.h, markers=markers)
        cables = [_cable("c1", "a", "b", {"plan": FP, "slack_m": 0.2}),  # 10.2 -> 10.5
                  _cable("c2", "a", "b", length_m=10.0),  # equal -> no op
                  _cable("c3", "a", "c"),  # c not placed -> skipped
                  _cable("c4", "a", "b", length_m=12.0)]  # 10.0 differs -> op
        doc = _doc(fp, cables)
        self.assertAlmostEqual(R.estimate(doc, FP, "c1"), 10.2, places=2)
        self.assertIsNone(R.estimate(doc, FP, "c3"))
        self.assertIsNone(R.estimate(doc, FP, "nope"))
        plan = R.estimate_plan(doc, FP, ["c1", "c2", "c3", "c4", "zz"])
        self.assertEqual(plan["ops"], [{"op": "merge", "coll": "cables", "id": "c1", "value": {"length_m": 10.5}},
                                       {"op": "merge", "coll": "cables", "id": "c4", "value": {"length_m": 10.0}}], fr("FR-PLAN-17", "6.9.9", "merge ops, rounded up to 0.5"))
        self.assertEqual(plan["updated"], [{"cable": "c1", "from_m": None, "to_m": 10.5}, {"cable": "c4", "from_m": 12.0, "to_m": 10.0}])
        self.assertEqual(plan["skipped"], ["c3", "zz"])
        self.assertEqual([o["id"] for o in R.estimate_ops(doc, FP, None)], ["c1", "c4"], "None = every cable with a run")
        self.assertEqual(R.estimate_ops(doc, FP, ["c1"], round_to=1)[0]["value"], {"length_m": 11.0})
        self.assertEqual(R.estimate_ops(doc, FP, ["c1"], round_to=0)[0]["value"], {"length_m": 10.2}, "round_to 0 = exact (2 decimals)")
        self.assertEqual((R.round_up(10.0, 0.5), R.round_up(10.01, 0.5), R.round_up(7.3, 1), R.round_up(2.5, 2.5)), (10.0, 10.5, 8.0, 2.5))

    def test_scene_aware(self):
        R = self.runs
        S = requires("scenes")
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}])
        doc = _doc(fp, [_cable("c1", "a", "b")])
        doc, scene = S.create(doc, "Christmas")
        live = copy.deepcopy(doc)
        live["floorplans"][0]["markers"] = [{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.9, "y": 0.2}]
        self.assertAlmostEqual(R.runs_for_plan(live, FP)[0]["length_m"], 20.0, places=1, msg="live doc")
        self.assertAlmostEqual(R.runs_for_plan(live, FP, scene=scene["id"])[0]["length_m"], 10.0, places=1, msg=fr("FR-SCN", "6.9.9", "scene markers"))
        with self.assertRaises(KeyError):
            R.runs_for_plan(live, FP, scene="sc-00000000")

    def test_bundle_runs_use_member_ends(self):
        R = self.runs
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}])
        doc = _doc(fp, [_cable("c1", "a", "b", bundle="b-1"), _cable("c2", "a", "b", bundle="b-1")])
        doc["bundles"] = [{"id": "b-1", "kind": "multicore", "route": {"plan": FP, "slack_m": 2}}, {"id": "b-2", "kind": "loom"}]
        runs = {r["cable"]: r for r in R.runs_for_plan(doc, FP)}
        self.assertEqual(sorted(runs), ["b-1", "c1", "c2"])
        self.assertEqual((runs["b-1"]["kind"], runs["b-1"]["estimate_m"]), ("bundle", 12.0))
        self.assertEqual(R.estimate_ops(doc, FP, ["b-1"]), [{"op": "merge", "coll": "bundles", "id": "b-1", "value": {"length_m": 12.0}}])


class Schema(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.w, self.h = 1000.0, 500.0

    def _problems(self, doc):
        return [(p["level"], p["code"], p["path"]) for p in self.schema.validate_doc(doc)]

    def test_paths_and_routes_validate(self):
        s = self.schema
        path = {"id": "pt-1", "name": "Tray", "kind": "tray", "points": [[0.1, 0.3], [0.5, 0.3]]}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}], paths=[path])
        good = _doc(fp, [_cable("c1", "a", "b", {"plan": FP, "via": ["pt-1"], "slack_m": 1, "drop_m": 0.5, "mode": "auto"}),
                         _cable("c2", "a", "b", {"plan": FP, "mode": "manual", "points": [[0.2, 0.2]]})])
        codes = {c for _, c, _ in self._problems(good)}
        self.assertFalse(codes & {"path_bad_points", "route_dangling_path", "route_wrong_plan", "bad_type", "bad_enum"}, codes)
        n = s.normalize(good)
        self.assertEqual(n["floorplans"][0]["paths"], [path], "paths kept through normalize")
        self.assertEqual(n["cables"][-1]["route"], good["cables"][-1]["route"], "route kept")
        self.assertEqual(s.normalize(n), n, "idempotent")
        bare = _doc(_plan(self.w, self.h), [])
        del bare["floorplans"][0]["paths"]
        self.assertEqual(s.normalize(bare)["floorplans"][0]["paths"], [], fr("FR-PLAN-14", "4.3.11", "missing paths -> []"))
        self.assertNotIn("route", s.normalize(bare)["cables"][0], "no route is added")
        bad = copy.deepcopy(good)
        bad["floorplans"][0]["paths"].append({"id": "pt-2", "kind": "trench", "points": [[0.1, 0.1]]})
        bad["floorplans"][0]["paths"].append({"id": "pt-3", "kind": "trench", "points": [[0.1, 0.1], [1.4, 0.2]]})
        bad["cables"][-2]["route"]["via"] = ["pt-1", "pt-missing"]
        bad["cables"][-1]["route"]["plan"] = "fp-elsewhere"
        probs = self._problems(bad)
        self.assertIn(("error", "path_bad_points", f"floorplans/{FP}/paths/1/points"), probs, fr("FR-PLAN-14", "4.7", "< 2 points is an error"))
        self.assertIn(("warning", "path_bad_points", f"floorplans/{FP}/paths/2/points"), probs, "outside [0,1] is a warning")
        self.assertIn(("warning", "route_dangling_path", "cables/c1/route/via/1"), probs, fr("FR-PLAN-15", "4.7", "dangling via is advisory"))
        self.assertIn(("warning", "route_wrong_plan", "cables/c2/route/plan"), probs)
        self.assertFalse([p for p in probs if p[0] == "error" and p[1] != "path_bad_points"], "advisory routes never block a write")
        worse = copy.deepcopy(good)
        worse["cables"][-1]["route"] = "nope"
        worse["cables"][-2]["route"]["mode"] = "teleport"
        worse["floorplans"][0]["paths"] = {"pt": 1}
        probs = self._problems(worse)
        self.assertIn(("error", "bad_type", "cables/c2/route"), probs)
        self.assertIn(("error", "bad_enum", "cables/c1/route/mode"), probs)
        self.assertIn(("error", "bad_type", f"floorplans/{FP}/paths"), probs)

    def test_json_schema_lists_the_fields(self):
        js = self.schema.JSON_SCHEMA["properties"]
        fp_props = js["floorplans"]["items"]["properties"]
        self.assertIn("paths", fp_props)
        self.assertEqual(fp_props["paths"]["items"]["required"], ["id", "points"])
        self.assertEqual(fp_props["paths"]["items"]["properties"]["kind"]["enum"], ["tray", "catwalk", "trench", "conduit", "floor", "other"])
        for coll in ("cables", "bundles"):
            route = js[coll]["items"]["properties"]["route"]["properties"]
            self.assertEqual(sorted(route), ["drop_m", "mode", "plan", "points", "slack_m", "via"], coll)
            self.assertEqual(route["mode"]["enum"], ["auto", "manual"])


class PlanSvgAndSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.floorplan = requires("floorplan")
        cls.cables = requires("cables")
        cls.w, cls.h = 1000.0, 500.0

    def _doc(self):
        path = {"id": "pt-1", "name": "Main tray", "kind": "tray", "points": [[0.1, 0.3], [0.5, 0.3]]}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}], paths=[path])
        return _doc(fp, [_cable("c1", "a", "b"), _cable("c2", "a", "b", {"plan": FP, "via": ["pt-1"], "slack_m": 1}),
                         _cable("c3", "a", "b", {"plan": FP, "mode": "manual", "points": [[0.3, 0.1]]}), _cable("c4", "a", "c")])

    def test_runs_layer(self):
        doc = self._doc()
        with temp_data_dir() as data:
            pdir = install_project(data, "proj", doc=doc)
            plain = self.floorplan.plan_svg(doc, FP, pdir)
            self.assertNotIn("data-cable", plain, "runs=False: unchanged (FR-PLAN-13 output)")
            self.assertNotIn('class="paths"', plain)
            self.assertNotIn("Runs:", plain)
            svg = self.floorplan.plan_svg(doc, FP, pdir, runs=True)
            root = ET.fromstring(svg)
            tags = lambda el: el.tag.split("}")[-1]  # noqa: E731
            groups = [g for g in root.iter() if tags(g) == "g"]
            classes = [g.get("class") for g in groups]
            self.assertLess(classes.index("markers"), classes.index("paths"), "paths after markers")
            self.assertLess(classes.index("paths"), classes.index("runs"))
            run_groups = [g for g in groups if g.get("data-cable")]
            self.assertEqual(sorted(g.get("data-cable") for g in run_groups), ["c1", "c2", "c3"], fr("FR-PLAN-16", "3.8", "one <g data-cable> per run"))
            for g in run_groups:
                self.assertTrue(float(g.get("data-length")) > 0)
                self.assertEqual([tags(c) for c in g], ["polyline", "text"])
                self.assertRegex(g[1].text, r"^\d+(\.\d+)? m$")
            c1 = next(g for g in run_groups if g.get("data-cable") == "c1")
            self.assertIn("stroke-dasharray", c1[0].attrib, "auto runs are dashed")
            c3 = next(g for g in run_groups if g.get("data-cable") == "c3")
            self.assertNotIn("stroke-dasharray", c3[0].attrib, "manual runs are solid")
            vocab = requires("vocab")
            self.assertEqual(g[0].get("stroke"), vocab.DISCIPLINES[vocab.medium_discipline("dante")]["color"], "colour of the medium's discipline")
            paths = [p for p in root.iter() if tags(p) == "polyline" and p.get("data-path")]
            self.assertEqual([(p.get("data-path"), p.get("class")) for p in paths], [("pt-1", "path path-tray")])
            texts = [t.text for t in root.iter() if tags(t) == "text"]
            self.assertIn("Main tray", texts)
            legend = [t for t in texts if t and t.startswith("Runs:")]
            self.assertEqual(len(legend), 1)
            self.assertRegex(legend[0], r"^Runs: 3 · total \d+(\.\d+)? m \(estimated\)$")

    def test_scene_argument(self):
        S = requires("scenes")
        doc = self._doc()
        doc, scene = S.create(doc, "Christmas")
        live = copy.deepcopy(doc)
        live["floorplans"][0]["markers"] = [{"device": "a", "x": 0.1, "y": 0.2}]
        with temp_data_dir() as data:
            pdir = install_project(data, "proj", doc=live)
            self.assertEqual(self.floorplan.plan_svg(live, FP, pdir, runs=True).count("data-cable="), 0)
            self.assertEqual(self.floorplan.plan_svg(live, FP, pdir, runs=True, scene=scene["id"]).count("data-cable="), 3)

    def test_schedule_length_est_m(self):
        doc = self._doc()
        sched = self.cables.cable_schedule(doc)
        keys = [c["key"] for c in sched["columns"]]
        self.assertEqual(keys[keys.index("length_unit") + 1], "length_est_m", fr("FR-PLAN-17", "5.8.2", "column after the length columns"))
        rows = {r["id"]: r for r in sched["rows"]}
        self.assertAlmostEqual(rows["c1"]["length_est_m"], 10.0, places=1)
        self.assertAlmostEqual(rows["c2"]["length_est_m"], rows["c1"]["length_est_m"] + 2 * 0.1 * _mx_my(self.w, self.h)[1] + 1, places=1)
        self.assertIsNone(rows["c4"]["length_est_m"], "no run -> None")
        self.assertIn("length_m", rows["c1"])
        text = self.cables.to_csv(sched)
        header = next(csv.reader(io.StringIO(text)))
        self.assertEqual(header[header.index("Unit") + 1], "Est. m")
        self.assertEqual(header, [lab for _, lab in self.cables.CABLE_COLUMNS])


class Routes(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("runs")
        self.w, self.h = 1000.0, 500.0

    def _doc(self):
        path = {"id": "pt-1", "name": "Tray", "kind": "tray", "points": [[0.1, 0.3], [0.5, 0.3]]}
        fp = _plan(self.w, self.h, markers=[{"device": "a", "x": 0.1, "y": 0.2}, {"device": "b", "x": 0.5, "y": 0.2}], paths=[path])
        return _doc(fp, [_cable("c1", "a", "b"), _cable("c2", "a", "b", {"plan": FP, "via": ["pt-1"], "slack_m": 1.1}, length_m=3),
                         _cable("c3", "a", "c"), _cable("c4", "a", "b", length_m=10)])

    def _get(self, path, status=200, headers=None):
        st, _, b = call(self.app, "GET", path, headers=headers)
        self.assertEqual(st, status, b[:300])
        return jbody(b)

    def _post(self, path, body=None, status=200, headers=None):
        h = dict(JSON_H)
        h.update(headers or {})
        st, hdrs, b = call(self.app, "POST", path, body if body is not None else {}, h)
        self.assertEqual(st, status, b[:300])
        return jbody(b)

    def test_runs_snap_estimate(self):
        with temp_data_dir() as data:
            install_project(data, "proj", doc=self._doc())
            out = self._get(P + f"/floorplans/{FP}/runs")
            self.assertEqual((out["plan"], out["unit"], out["calibrated"]), (FP, "m", True), fr("FR-PLAN-16", "5.7", "GET runs"))
            self.assertEqual(sorted(r["cable"] for r in out["runs"]), ["c1", "c2", "c4"])
            self.assertEqual(out["unplaced"], ["c3"])
            self.assertEqual([p["id"] for p in out["paths"]], ["pt-1"])
            self.assertEqual(out["totals"]["runs"], 3)
            self.assertGreater(out["totals"]["estimate_m"], out["totals"]["length_m"], "slack counts in the estimate")
            for k in ("cable", "plan", "points", "segments", "length_m", "estimate_m", "unit", "auto"):
                self.assertIn(k, out["runs"][0], k)
            self.assertIn("revision", out)
            self._get(P + "/floorplans/fp-none/runs", 404)
            self._get(P + f"/floorplans/{FP}/runs?scene=sc-00000000", 404)
            self.assertEqual(len(self._get(P + f"/floorplans/{FP}/runs?scene=base")["runs"]), 3, "?scene=base = Base")
            # snap
            hit = self._post(P + f"/floorplans/{FP}/runs/snap", {"point": [0.3, 0.31]})
            self.assertEqual((hit["path"], hit["point"]), ("pt-1", [0.3, 0.3]), fr("FR-PLAN-14", "5.7", "snap"))
            self.assertEqual(self._post(P + f"/floorplans/{FP}/runs/snap", {"point": [0.3, 0.6]})["path"], None)
            self.assertEqual(self._post(P + f"/floorplans/{FP}/runs/snap", {"point": [0.3, 0.6], "max": 0.5})["path"], "pt-1")
            self._post(P + f"/floorplans/{FP}/runs/snap", {"point": "x"}, 400)
            self._post(P + "/floorplans/fp-none/runs/snap", {"point": [0.3, 0.3]}, 404)
            # estimate
            rev = self._get(P)["revision"]
            self._post(P + f"/floorplans/{FP}/runs/estimate", {"all": True}, 428)
            self._post(P + f"/floorplans/{FP}/runs/estimate", {"base_revision": rev}, 400)
            self._post(P + "/floorplans/fp-none/runs/estimate", {"all": True, "base_revision": rev}, 404)
            r = self._post(P + f"/floorplans/{FP}/runs/estimate", {"cables": ["c1", "c2", "c3", "c4"], "base_revision": rev})
            self.assertEqual(r["revision"], rev + 1, fr("FR-PLAN-17", "5.7", "one revision"))
            self.assertEqual([(u["cable"], u["from_m"]) for u in r["updated"]], [("c1", None), ("c2", 3)])
            self.assertEqual(r["updated"][0]["to_m"], 10.0)
            self.assertEqual(r["skipped"], ["c3"], "c4 already equals its estimate: neither updated nor skipped")
            doc = self._get(P)["doc"]
            lengths = {c["id"]: c.get("length_m") for c in doc["cables"]}
            self.assertEqual((lengths["c1"], lengths["c4"]), (10.0, 10))
            self.assertEqual(lengths["c2"], r["updated"][1]["to_m"])
            self.assertEqual(lengths["c2"] % 0.5, 0, "rounded up to 0.5 m")
            hist = self._get(P + "/history")["revisions"][0]
            self.assertEqual((hist["source"], hist["summary"]), ("plan", "Estimated cable lengths from Main floor (2 cables)"))
            again = self._post(P + f"/floorplans/{FP}/runs/estimate", {"all": True, "base_revision": rev + 1})
            self.assertEqual((again["revision"], again["updated"], again["skipped"]), (rev + 1, [], []), "no-op writes nothing")
            # round_to and the stale revision
            r2 = self._post(P + f"/floorplans/{FP}/runs/estimate", {"cables": ["c2"], "base_revision": rev + 1, "round_to": 0})
            self.assertNotEqual(r2["updated"][0]["to_m"] % 0.5, 0)
            self._post(P + "/changes", {"base_revision": r2["revision"], "ops": [{"op": "merge", "coll": "cables", "id": "c1", "value": {"length_m": 99}}]})
            st, _, b = call(self.app, "POST", P + f"/floorplans/{FP}/runs/estimate", {"cables": ["c1"], "base_revision": r2["revision"]}, JSON_H)
            self.assertEqual(st, 409, fr("FR-HIST", "5.4", "stale base on a touched cable -> 409"))
            self.assertEqual(jbody(b)["code"], "conflict")
            cur = self._get(P)["revision"]
            st, _, b = call(self.app, "POST", P + f"/floorplans/{FP}/runs/estimate", {"all": True, "base_revision": cur + 7}, JSON_H)
            self.assertEqual(st, 409)

    def test_locked_and_viewer(self):
        users = requires("users")
        with temp_data_dir() as data:
            install_project(data, "proj", doc=self._doc())
            rev = self._get(P)["revision"]
            self._post(P + "/changes", {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": {"locked": True}}]})
            st, _, b = call(self.app, "POST", P + f"/floorplans/{FP}/runs/estimate", {"all": True, "base_revision": rev + 1}, JSON_H)
            self.assertEqual(st, 423, b[:200])
            self.assertEqual(jbody(b)["code"], "locked", fr("FR-USER-12", "5.3", "estimate honours the editing lock"))
            self._get(P + f"/floorplans/{FP}/runs")
            self._post(P + f"/floorplans/{FP}/runs/snap", {"point": [0.3, 0.3]})
            users.add_user("eve", "eve-password-1", role="editor")
            users.add_user("vic", "vic-password-1", role="viewer")
            vic, eve = basic("vic", "vic-password-1"), basic("eve", "eve-password-1")
            self._get(P + f"/floorplans/{FP}/runs", headers=vic)
            self._post(P + f"/floorplans/{FP}/runs/snap", {"point": [0.3, 0.3]}, headers=vic)
            st, _, b = call(self.app, "POST", P + f"/floorplans/{FP}/runs/estimate", {"all": True, "base_revision": rev + 1}, dict(JSON_H, **vic))
            self.assertEqual(st, 403, fr("FR-USER-03", "5.2", "viewer cannot estimate"))
            st, _, b = call(self.app, "POST", P + f"/floorplans/{FP}/runs/estimate", {"all": True, "base_revision": rev + 1}, dict(JSON_H, **eve))
            self.assertEqual(st, 423, "editor: still locked")
            st, _, _ = call(self.app, "GET", P + f"/floorplans/{FP}/runs")
            self.assertEqual(st, 401, "auth on: anonymous is refused")

    def test_plan_svg_route_unchanged(self):
        with temp_data_dir() as data:
            install_project(data, "proj", doc=self._doc())
            st, h, b = call(self.app, "GET", P + f"/floorplans/{FP}.svg")
            self.assertEqual(st, 200)
            self.assertNotIn(b"data-cable", b, "the export SVG route is untouched (P5C adds the runs layer to builds)")
            self.assertEqual(b.count(b"data-device="), 2)


if __name__ == "__main__":
    unittest.main()
