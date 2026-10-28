"""Cable runs on floor plans (FR-PLAN-14..17, SPEC §6.9.9): shared paths, run
geometry and length estimates.

Pure functions over a doc (no I/O). Coordinates are the floor plan's
normalised ``[0, 1]`` plan coordinates (as ``floorplan.markers[]``); lengths
come out in metres through the plan's calibration (FR-PLAN-10) or in plan
pixels (``unit: "px"``) when the plan is not calibrated.

* ``floorplan.paths[]`` — the venue's shared trunks (tray, catwalk, trench …)
  that *Nearest Route* snaps cables onto.
* ``cable.route`` / ``bundle.route`` — advisory routing of one cable on one
  plan: user corners (``manual``) or the ordered paths it follows (``via``),
  plus slack and the vertical drops at both ends.
* A **run** exists on a plan only when both end devices have a marker there.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Doc = Dict[str, Any]
Point = Tuple[float, float]
Run = Dict[str, Any]

FT_PER_M = 1 / 0.3048
PATH_KINDS = ("tray", "catwalk", "trench", "conduit", "floor", "other")
ROUTE_MODES = ("auto", "manual")
#: default snap distance of ``snap`` / ``project_to_paths`` (normalised plan units)
SNAP_DIST = 0.02
_EPS = 1e-12


# --------------------------------------------------------------- helpers


def _num(v: Any, default: float = 0.0) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    f = float(v)
    return f if math.isfinite(f) else default


def _pt(v: Any) -> Optional[Point]:
    """``[x, y]`` (or ``{"x", "y"}``) → ``(x, y)`` floats, else ``None``."""
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y")]
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        return None
    x, y = v[0], v[1]
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (float(x), float(y))


def _points(v: Any) -> List[Point]:
    out: List[Point] = []
    for p in v if isinstance(v, list) else []:
        q = _pt(p)
        if q is not None:
            out.append(q)
    return out


def _r(v: float) -> float:
    return round(float(v), 2)


def _entities(doc: Doc, coll: str) -> List[Dict[str, Any]]:
    return [e for e in doc.get(coll) or [] if isinstance(e, dict) and e.get("id")]


def find_plan(doc: Doc, fp_id: str) -> Optional[Dict[str, Any]]:
    for f in _entities(doc, "floorplans"):
        if f.get("id") == fp_id:
            return f
    return None


def plan_paths(fp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The plan's usable paths: dicts with an id and at least two valid points."""
    out = []
    for p in fp.get("paths") or []:
        if isinstance(p, dict) and p.get("id") and len(_points(p.get("points"))) >= 2:
            out.append(p)
    return out


# ----------------------------------------------------------------- scale


def plan_size(fp: Dict[str, Any]) -> Tuple[float, float]:
    img = fp.get("image") if isinstance(fp.get("image"), dict) else {}
    w = _num(img.get("width"), 0.0) or 1000.0
    h = _num(img.get("height"), 0.0) or 1000.0
    return (w, h)


def meters_per_norm(fp: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """``(mx, my)``: metres per normalised unit along x and y, from
    ``fp.calibration`` (``p1``, ``p2`` normalised, ``distance``, ``unit`` m|ft;
    FR-PLAN-10) and the image size; ``None`` when the plan is not calibrated."""
    cal = fp.get("calibration") if isinstance(fp.get("calibration"), dict) else None
    if not cal:
        return None
    p1, p2 = _pt(cal.get("p1")), _pt(cal.get("p2"))
    dist = _num(cal.get("distance"), 0.0)
    if p1 is None or p2 is None or dist <= 0:
        return None
    if str(cal.get("unit") or "m").lower() == "ft":
        dist = dist / FT_PER_M
    w, h = plan_size(fp)
    px = math.hypot((p2[0] - p1[0]) * w, (p2[1] - p1[1]) * h)
    if px <= _EPS:
        return None
    mpp = dist / px  # metres per plan pixel
    return (w * mpp, h * mpp)


def _scale(fp: Dict[str, Any]) -> Tuple[float, float, str]:
    """``(sx, sy, unit)``: multipliers from normalised to metres, or to plan pixels (``"px"``)."""
    m = meters_per_norm(fp)
    if m is not None:
        return (m[0], m[1], "m")
    w, h = plan_size(fp)
    return (w, h, "px")


def polyline_length(points: Sequence[Any], fp: Dict[str, Any]) -> float:
    """Length of a normalised polyline in metres (plan pixels when uncalibrated)."""
    sx, sy, _ = _scale(fp)
    pts = _points(list(points))
    return sum(math.hypot((b[0] - a[0]) * sx, (b[1] - a[1]) * sy) for a, b in zip(pts, pts[1:]))


# -------------------------------------------------------------- polylines
# Nearest-point and slicing work in normalised plan coordinates (what the
# path tool draws and what ``max_dist_norm`` is expressed in); lengths are
# converted afterwards.


def _cum(pts: Sequence[Point]) -> List[float]:
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return out


def _nearest_on_segment(a: Point, b: Point, p: Point) -> Tuple[Point, float]:
    """Closest point to ``p`` on segment ``a``–``b`` and its fraction along it."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d2 = dx * dx + dy * dy
    if d2 <= _EPS:
        return a, 0.0
    u = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2
    u = max(0.0, min(1.0, u))
    return (a[0] + dx * u, a[1] + dy * u), u


def _nearest(pts: Sequence[Point], p: Point) -> Tuple[Point, float, float]:
    """``(point, s, dist)`` on polyline ``pts``: ``s`` is the arc position (normalised units)."""
    cum = _cum(pts)
    best: Optional[Tuple[Point, float, float]] = None
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        q, u = _nearest_on_segment(a, b, p)
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if best is None or d < best[2] - 1e-15:
            best = (q, cum[i] + u * (cum[i + 1] - cum[i]), d)
    if best is None:
        q = pts[0]
        return q, 0.0, math.hypot(q[0] - p[0], q[1] - p[1])
    return best


def _point_at(pts: Sequence[Point], cum: Sequence[float], s: float) -> Point:
    if s <= 0:
        return pts[0]
    if s >= cum[-1]:
        return pts[-1]
    for i in range(len(pts) - 1):
        if cum[i] <= s <= cum[i + 1]:
            seg = cum[i + 1] - cum[i]
            u = (s - cum[i]) / seg if seg > _EPS else 0.0
            a, b = pts[i], pts[i + 1]
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
    return pts[-1]


def _slice(pts: Sequence[Point], s0: float, s1: float) -> List[Point]:
    """Sub-polyline from arc position ``s0`` to ``s1`` (reversed when ``s1 < s0``)."""
    cum = _cum(pts)
    lo, hi = (s0, s1) if s0 <= s1 else (s1, s0)
    out: List[Point] = [_point_at(pts, cum, lo)]
    for i in range(1, len(pts) - 1):
        if lo < cum[i] < hi:
            out.append(pts[i])
    out.append(_point_at(pts, cum, hi))
    if s0 > s1:
        out.reverse()
    return out


def _is_closed(pts: Sequence[Point]) -> bool:
    return len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-9


def _along(pts: Sequence[Point], s0: float, s1: float) -> List[Point]:
    """Points along the path from ``s0`` to ``s1``, the shorter way round on a closed loop."""
    direct = _slice(pts, s0, s1)
    if not _is_closed(pts):
        return direct
    total = _cum(pts)[-1]
    if abs(s1 - s0) <= total / 2:
        return direct
    # wrap through the shared first/last point
    if s0 < s1:
        return _slice(pts, s0, 0.0) + _slice(pts, total, s1)[1:]
    return _slice(pts, s0, total) + _slice(pts, 0.0, s1)[1:]


def _seg_intersection(a: Point, b: Point, c: Point, d: Point) -> Optional[Point]:
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) <= _EPS:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (a[0] + r[0] * t, a[1] + r[1] * t)
    return None


def _closest_between(pa: Sequence[Point], pb: Sequence[Point]) -> Tuple[float, float]:
    """Arc positions ``(sa, sb)`` of the closest pair of points on two polylines
    (vertex-to-polyline both ways, plus crossings)."""
    best: Optional[Tuple[float, float, float]] = None
    for v in pb:
        q, s, d = _nearest(pa, v)
        if best is None or d < best[0]:
            best = (d, s, _nearest(pb, q)[1])
    for v in pa:
        q, s, d = _nearest(pb, v)
        if best is None or d < best[0]:
            best = (d, _nearest(pa, q)[1], s)
    if best is not None and best[0] > _EPS:
        for a, b in zip(pa, pa[1:]):
            for c, d in zip(pb, pb[1:]):
                x = _seg_intersection(a, b, c, d)
                if x is not None:
                    return _nearest(pa, x)[1], _nearest(pb, x)[1]
    return (best[1], best[2]) if best is not None else (0.0, 0.0)


# ------------------------------------------------------------- public geometry


def nearest_point_on_path(path: Any, pt: Any) -> Tuple[List[float], float, float]:
    """``(point, t, dist)`` for a path dict (or a bare point list): the closest
    point on the path to ``pt`` (normalised), ``t`` = its position along the
    path as a fraction 0..1 of the path length, ``dist`` in normalised units."""
    pts = _points(path.get("points") if isinstance(path, dict) else path)
    p = _pt(pt)
    if len(pts) < 2 or p is None:
        return ([0.0, 0.0], 0.0, float("inf"))
    q, s, d = _nearest(pts, p)
    total = _cum(pts)[-1]
    return ([q[0], q[1]], (s / total) if total > _EPS else 0.0, d)


def project_to_paths(fp: Dict[str, Any], pt: Any, max_dist_norm: float = SNAP_DIST) -> Optional[Tuple[str, List[float], float]]:
    """``(path_id, point, dist)`` of the nearest path within ``max_dist_norm``, else ``None``."""
    best: Optional[Tuple[str, List[float], float, float]] = None
    for path in plan_paths(fp):
        q, t, d = nearest_point_on_path(path, pt)
        if d <= max_dist_norm and (best is None or d < best[2]):
            best = (str(path["id"]), q, d, t)
    return (best[0], best[1], best[2]) if best is not None else None


def snap(fp: Dict[str, Any], pt: Any, max_dist_norm: float = SNAP_DIST) -> Optional[Dict[str, Any]]:
    """Nearest-route helper for the UI: ``{"path", "point", "dist", "t"}`` or ``None``."""
    hit = project_to_paths(fp, pt, max_dist_norm)
    if hit is None:
        return None
    path = next(p for p in plan_paths(fp) if str(p["id"]) == hit[0])
    _, t, _ = nearest_point_on_path(path, pt)
    return {"path": hit[0], "point": [_r6(hit[1][0]), _r6(hit[1][1])], "dist": _r6(hit[2]), "t": _r6(t)}


def _r6(v: float) -> float:
    return round(float(v), 6)


# ------------------------------------------------------------------ runs


def _marker_pos(fp: Dict[str, Any], device: Any) -> Optional[Point]:
    if not device:
        return None
    for m in fp.get("markers") or []:
        if isinstance(m, dict) and m.get("device") == device:
            return _pt([m.get("x"), m.get("y")])
    return None


def _ends(doc: Doc, ent: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], str]:
    """``(from_device, to_device, kind)``; a bundle's ends are its first member cable's."""
    fr, to = ent.get("from"), ent.get("to")
    if isinstance(fr, dict) or isinstance(to, dict):
        return ((fr or {}).get("device") if isinstance(fr, dict) else None,
                (to or {}).get("device") if isinstance(to, dict) else None, "cable")
    for c in _entities(doc, "cables"):
        if c.get("bundle") == ent.get("id") and isinstance(c.get("from"), dict) and isinstance(c.get("to"), dict):
            return c["from"].get("device"), c["to"].get("device"), "bundle"
    return None, None, "bundle"


def _route_for(ent: Dict[str, Any], fp_id: str) -> Dict[str, Any]:
    route = ent.get("route")
    if not isinstance(route, dict):
        return {}
    if route.get("plan") and route.get("plan") != fp_id:
        return {}
    return route


def _medium_of(doc: Doc, ent: Dict[str, Any], kind: str) -> str:
    if ent.get("medium"):
        return str(ent["medium"])
    if kind == "bundle":
        for c in _entities(doc, "cables"):
            if c.get("bundle") == ent.get("id") and c.get("medium"):
                return str(c["medium"])
    return "other"


def resolve_run(doc: Doc, fp: Dict[str, Any], cable: Dict[str, Any]) -> Optional[Run]:
    """Geometry of one cable (or bundle) on plan ``fp``; ``None`` unless both
    ends have a marker on the plan. ``mode: "manual"`` uses the stored corners
    verbatim; otherwise a straight line, or — when ``via`` names paths — marker
    → nearest point on the first path → along it to the point nearest the next
    path (or the far marker) → … → marker."""
    fp_id = str(fp.get("id") or "")
    a_dev, b_dev, kind = _ends(doc, cable)
    a, b = _marker_pos(fp, a_dev), _marker_pos(fp, b_dev)
    if a is None or b is None:
        return None
    route = _route_for(cable, fp_id)
    mode = str(route.get("mode") or "auto")
    sx, sy, unit = _scale(fp)

    def mlen(pts: Sequence[Point]) -> float:
        return sum(math.hypot((q[0] - p[0]) * sx, (q[1] - p[1]) * sy) for p, q in zip(pts, pts[1:]))

    paths = {str(p["id"]): p for p in plan_paths(fp)}
    legs: List[Tuple[str, Optional[str], List[Point]]] = []  # (kind, path id, points)
    via_used: List[str] = []
    if mode == "manual":
        legs.append(("free", None, [a] + _points(route.get("points")) + [b]))
    else:
        via = [str(v) for v in (route.get("via") or []) if isinstance(v, str) and v in paths]
        cur = a
        for i, pid in enumerate(via):
            pts = _points(paths[pid]["points"])
            _, s_in, _ = _nearest(pts, cur)
            if i + 1 < len(via):
                s_out, _ = _closest_between(pts, _points(paths[via[i + 1]]["points"]))
            else:
                _, s_out, _ = _nearest(pts, b)
            along = _along(pts, s_in, s_out)
            legs.append(("free", None, [cur, along[0]]))
            legs.append(("path", pid, along))
            via_used.append(pid)
            cur = along[-1]
        legs.append(("free", None, [cur, b]))

    points: List[Point] = []
    segments: List[Dict[str, Any]] = []
    slack = max(0.0, _num(route.get("slack_m")))
    drop = max(0.0, _num(route.get("drop_m")))
    if drop > 0:
        segments.append({"kind": "drop", "path": None, "length_m": _r(drop)})
    for leg_kind, pid, pts in legs:
        length = mlen(pts)
        if leg_kind == "free" and length <= _EPS and len(pts) <= 2:
            if not points:
                points.extend(pts[:1])
            continue
        if points and pts and math.hypot(points[-1][0] - pts[0][0], points[-1][1] - pts[0][1]) <= 1e-12:
            points.extend(pts[1:])
        else:
            points.extend(pts)
        segments.append({"kind": leg_kind, "path": pid, "length_m": _r(length)})
    if len(points) < 2:
        points = [a, b]
    if drop > 0:
        segments.append({"kind": "drop", "path": None, "length_m": _r(drop)})
    length = mlen(points)
    elevation = sum(max(0.0, _num(paths[p].get("elevation_m"))) for p in via_used)
    estimate = length + slack + 2 * drop + elevation
    return {
        "cable": str(cable.get("id")), "kind": kind, "plan": fp_id,
        "from": a_dev, "to": b_dev, "medium": _medium_of(doc, cable, kind),
        "points": [[_r6(x), _r6(y)] for x, y in points],
        "segments": segments, "length_m": _r(length), "estimate_m": _r(estimate),
        "slack_m": _r(slack), "drop_m": _r(drop), "elevation_m": _r(elevation),
        "unit": unit, "auto": mode != "manual", "mode": "manual" if mode == "manual" else "auto", "via": via_used,
    }


def scene_doc(doc: Doc, scene: Optional[str]) -> Doc:
    """The doc as scene ``scene`` sees it (``None`` / ``""`` = the live doc).
    ``KeyError`` for an unknown scene (from ``fathom.scenes``)."""
    if not scene:
        return doc
    from . import scenes as S

    return S.apply(doc, S.scene_data(doc, scene))


def runs_for_plan(doc: Doc, fp_id: str, scene: Optional[str] = None) -> List[Run]:
    """One run per cable and bundle whose two ends are placed on the plan (scene-aware)."""
    return plan_runs(doc, fp_id, scene)["runs"]


def plan_runs(doc: Doc, fp_id: str, scene: Optional[str] = None) -> Dict[str, Any]:
    """Payload of ``GET …/floorplans/<fp>/runs`` (§5.7): ``plan``, ``unit``,
    ``calibrated``, ``paths``, ``runs``, ``totals``, ``unplaced`` (cables with
    exactly one end on the plan). ``KeyError`` when the plan does not exist."""
    doc = scene_doc(doc, scene)
    fp = find_plan(doc, fp_id)
    if fp is None:
        raise KeyError(fp_id)
    _, _, unit = _scale(fp)
    runs: List[Run] = []
    unplaced: List[str] = []
    for coll in ("cables", "bundles"):
        for ent in _entities(doc, coll):
            if ent.get("auto"):
                continue
            run = resolve_run(doc, fp, ent)
            if run is not None:
                runs.append(run)
                continue
            a_dev, b_dev, _ = _ends(doc, ent)
            if (_marker_pos(fp, a_dev) is None) != (_marker_pos(fp, b_dev) is None):
                unplaced.append(str(ent["id"]))
    paths = []
    for p in fp.get("paths") or []:
        if isinstance(p, dict) and p.get("id"):
            q = dict(p)
            q["length_m"] = _r(polyline_length(_points(p.get("points")), fp))
            paths.append(q)
    return {
        "plan": fp_id, "unit": unit, "calibrated": unit == "m", "paths": paths, "runs": runs,
        "totals": {"runs": len(runs), "length_m": _r(sum(r["length_m"] for r in runs)), "estimate_m": _r(sum(r["estimate_m"] for r in runs))},
        "unplaced": unplaced,
    }


# -------------------------------------------------------------- estimates


def estimate(doc: Doc, fp_id: str, cable_id: str) -> Optional[float]:
    """Estimated length in metres of a cable (or bundle) on a plan: run length
    + slack + 2 × drop + the elevation of the paths used. ``None`` when the
    cable has no run on the plan or the plan is not calibrated."""
    fp = find_plan(doc, fp_id)
    if fp is None:
        return None
    ent = next((e for e in _entities(doc, "cables") + _entities(doc, "bundles") if e.get("id") == cable_id), None)
    if ent is None:
        return None
    run = resolve_run(doc, fp, ent)
    if run is None or run["unit"] != "m":
        return None
    return float(run["estimate_m"])


def estimates(doc: Doc) -> Dict[str, float]:
    """``{cable or bundle id: estimate_m}`` over every calibrated plan (the first
    plan, in doc order, on which the cable has a run wins)."""
    out: Dict[str, float] = {}
    for fp in _entities(doc, "floorplans"):
        if meters_per_norm(fp) is None:
            continue
        for coll in ("cables", "bundles"):
            for ent in _entities(doc, coll):
                cid = str(ent["id"])
                if cid in out or ent.get("auto"):
                    continue
                run = resolve_run(doc, fp, ent)
                if run is not None:
                    out[cid] = float(run["estimate_m"])
    return out


def round_up(value: float, round_to: float = 0.5) -> float:
    """``value`` rounded *up* to the next multiple of ``round_to`` (2 decimals when ``round_to`` ≤ 0)."""
    if round_to is None or round_to <= 0:
        return _r(value)
    n = math.ceil(value / round_to - 1e-9)
    return _r(n * round_to)


def estimate_plan(doc: Doc, fp_id: str, cable_ids: Optional[Iterable[str]] = None, *, round_to: float = 0.5) -> Dict[str, Any]:
    """Ops and bookkeeping for ``POST …/runs/estimate``: ``{"ops", "updated": [{"cable", "from_m", "to_m"}], "skipped": [ids]}``.
    ``cable_ids`` ``None`` = every cable and bundle with a run on the plan.
    A cable whose rounded estimate equals its ``length_m`` is neither updated nor skipped."""
    fp = find_plan(doc, fp_id)
    if fp is None:
        raise KeyError(fp_id)
    ents: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for coll in ("cables", "bundles"):
        for e in _entities(doc, coll):
            ents.setdefault(str(e["id"]), (coll, e))
    wanted = [str(c) for c in cable_ids] if cable_ids is not None else [cid for cid, (coll, e) in ents.items() if not e.get("auto") and resolve_run(doc, fp, e) is not None]
    ops: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for cid in wanted:
        hit = ents.get(cid)
        if hit is None:
            skipped.append(cid)
            continue
        coll, ent = hit
        est = estimate(doc, fp_id, cid)
        if est is None:
            skipped.append(cid)
            continue
        to_m = round_up(est, round_to)
        cur = ent.get("length_m")
        cur_f = _num(cur, float("nan")) if cur is not None else None
        if cur_f is not None and abs(cur_f - to_m) < 1e-9:
            continue
        ops.append({"op": "merge", "coll": coll, "id": cid, "value": {"length_m": to_m}})
        updated.append({"cable": cid, "from_m": cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None, "to_m": to_m})
    return {"ops": ops, "updated": updated, "skipped": skipped}


def estimate_ops(doc: Doc, fp_id: str, cable_ids: Optional[Iterable[str]] = None, *, round_to: float = 0.5) -> List[Dict[str, Any]]:
    """§4.9 ``merge`` ops writing ``length_m`` (estimate rounded up to ``round_to``)
    for the cables whose estimate differs from their ``length_m``."""
    return estimate_plan(doc, fp_id, cable_ids, round_to=round_to)["ops"]


__all__ = [
    "PATH_KINDS", "ROUTE_MODES", "SNAP_DIST", "meters_per_norm", "polyline_length", "nearest_point_on_path", "project_to_paths",
    "snap", "resolve_run", "runs_for_plan", "plan_runs", "estimate", "estimates", "estimate_ops", "estimate_plan", "round_up",
    "scene_doc", "find_plan", "plan_paths",
]
