"""Rack elevations: occupancy, collisions, validation, SVG and schedule (SPEC FR-RACK).

A placement is ``device.rack = {id, u, height, face, side, depth}``: ``u`` is the
lowest occupied RU (1-based, 1 = bottom), ``height`` defaults to the template
``ru`` (else 1), ``face`` front|rear, ``side`` full|left|right (half width),
``depth`` full|half (full depth occupies both faces; default ``full``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

Doc = Dict[str, Any]

RU_PX = 22
RACK_W = 320
RAIL_W = 30
TITLE_H = 28
RACK_COLUMNS: List[Dict[str, str]] = [
    {"key": "rack", "label": "Rack"}, {"key": "room", "label": "Room"}, {"key": "units", "label": "Units"},
    {"key": "face", "label": "Face"}, {"key": "u", "label": "U"}, {"key": "height", "label": "Height"},
    {"key": "side", "label": "Side"}, {"key": "device", "label": "Device"}, {"key": "model", "label": "Model"},
]


def _racks(doc: Doc) -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in doc.get("racks") or [] if isinstance(r, dict) and r.get("id")}


def _template_ru(doc: Doc, template_id: str) -> Optional[int]:
    if not template_id:
        return None
    t: Optional[Dict[str, Any]] = None
    for x in doc.get("templates") or []:
        if isinstance(x, dict) and x.get("id") == template_id:
            t = x
    if t is None:
        try:
            from .library import get_template  # W2
            t = get_template(template_id, doc)
        except Exception:
            t = None
    ru = (t or {}).get("ru")
    return int(ru) if isinstance(ru, (int, float)) and ru >= 1 else None


def placement(doc: Doc, dev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalized placement of a racked device (``None`` if not racked)."""
    r = dev.get("rack")
    if not isinstance(r, dict) or not r.get("id"):
        return None
    h = r.get("height")
    if not isinstance(h, int) or h < 1:
        h = _template_ru(doc, dev.get("template") or "") or 1
    u = r.get("u")
    return {
        "device": dev["id"], "rack": r["id"], "u": u if isinstance(u, int) else None, "height": int(h),
        "face": r.get("face") if r.get("face") in ("front", "rear") else "front",
        "side": r.get("side") if r.get("side") in ("full", "left", "right") else "full",
        "depth": r.get("depth") if r.get("depth") in ("full", "half") else "full",
    }


def _faces_of(p: Dict[str, Any]) -> Tuple[str, ...]:
    return ("front", "rear") if p["depth"] == "full" else (p["face"],)


def _sides_of(p: Dict[str, Any]) -> Tuple[str, ...]:
    return ("left", "right") if p["side"] == "full" else (p["side"],)


def rack_devices(doc: Doc, rack_id: str) -> List[Dict[str, Any]]:
    out = []
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id"):
            p = placement(doc, d)
            if p and p["rack"] == rack_id:
                out.append(p)
    return out


def rack_occupancy(doc: Doc, rack_id: str) -> Dict[str, Any]:
    """``{"rack", "devices", "slots": [{u, front:{left,right}, rear:{left,right}}], "collisions": [{a,b,u,face}]}``."""
    rack = _racks(doc).get(rack_id)
    if rack is None:
        raise KeyError(rack_id)
    units = int(rack.get("units") or 0)
    slots = [{"u": u, "front": {"left": None, "right": None}, "rear": {"left": None, "right": None}} for u in range(1, units + 1)]
    cells: Dict[Tuple[int, str, str], str] = {}
    collisions: List[Dict[str, Any]] = []
    seen = set()
    placed = rack_devices(doc, rack_id)
    for p in placed:
        if p["u"] is None:
            continue
        for u in range(p["u"], p["u"] + p["height"]):
            for face in _faces_of(p):
                for side in _sides_of(p):
                    other = cells.get((u, face, side))
                    if other is None:
                        cells[(u, face, side)] = p["device"]
                        if 1 <= u <= units:
                            slots[u - 1][face][side] = p["device"]
                    elif other != p["device"] and (other, p["device"], face) not in seen:
                        seen.add((other, p["device"], face))
                        collisions.append({"a": other, "b": p["device"], "u": u, "face": face})
    info = {k: rack.get(k) for k in ("id", "name", "room", "location", "units") if rack.get(k) is not None}
    info["numbering"] = rack.get("numbering") or "bottom_up"
    info["faces"] = list(rack.get("faces") or ["front", "rear"])
    return {"rack": info, "devices": placed, "slots": slots, "collisions": collisions}


def _problem(code: str, dev_id: str, message: str) -> Dict[str, Any]:
    return {"level": "warning", "code": code, "ref": f"devices/{dev_id}", "path": f"devices/{dev_id}/rack", "message": message}


def validate_racks(doc: Doc) -> List[Dict[str, Any]]:
    """``rack_unknown`` / ``rack_out_of_range`` / ``rack_overlap`` warnings (§4.7)."""
    racks = _racks(doc)
    names = {d["id"]: d.get("name") or d["id"] for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    out: List[Dict[str, Any]] = []
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        p = placement(doc, d)
        if p is None:
            continue
        rack = racks.get(p["rack"])
        if rack is None:
            out.append(_problem("rack_unknown", d["id"], f"{names[d['id']]} is placed in unknown rack '{p['rack']}'."))
            continue
        units = int(rack.get("units") or 0)
        if p["u"] is None or p["u"] < 1 or p["u"] + p["height"] - 1 > units:
            out.append(_problem("rack_out_of_range", d["id"], f"{names[d['id']]} (U{p['u']}, {p['height']}U) does not fit in {rack.get('name') or rack['id']} ({units}U)."))
    for rack_id, rack in racks.items():
        for c in rack_occupancy(doc, rack_id)["collisions"]:
            out.append(_problem("rack_overlap", c["b"], f"{names.get(c['b'], c['b'])} overlaps {names.get(c['a'], c['a'])} at U{c['u']} ({c['face']}) in {rack.get('name') or rack_id}."))
    return out


def _disc_color(dev: Dict[str, Any]) -> str:
    try:
        from . import vocab
        from .trace import device_discipline
        return vocab.DISCIPLINES.get(device_discipline(dev), {}).get("color") or "#9aa3b5"
    except Exception:  # pragma: no cover
        return "#9aa3b5"


def _block_y(rack: Dict[str, Any], u: int, height: int) -> int:
    units = int(rack.get("units") or 0)
    if (rack.get("numbering") or "bottom_up") == "top_down":
        return TITLE_H + (u - 1) * RU_PX
    return TITLE_H + (units - (u + height - 1)) * RU_PX


def rack_svg(doc: Doc, rack_id: str, face: str = "front", scale: float = 1.0) -> str:
    """Standalone SVG elevation of one rack face (rails, RU numbers, device blocks, blanks)."""
    occ = rack_occupancy(doc, rack_id)
    rack = _racks(doc)[rack_id]
    face = face if face in ("front", "rear") else "front"
    units = int(rack.get("units") or 0)
    devs = {d["id"]: d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    colliding = {c["a"] for c in occ["collisions"] if c["face"] == face} | {c["b"] for c in occ["collisions"] if c["face"] == face}
    w = RAIL_W * 2 + RACK_W
    h = TITLE_H + units * RU_PX + 8
    x0 = RAIL_W
    title = f"{rack.get('name') or rack_id} · {face}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * scale:g}" height="{h * scale:g}" viewBox="0 0 {w} {h}" '
        f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" data-rack="{escape(rack_id)}" data-face="{face}">',
        f'<title>{escape(title)}</title>',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#0b1020"/>',
        f'<text x="{w / 2:g}" y="18" text-anchor="middle" font-size="13" font-weight="600" fill="#e5e7eb">{escape(title)}</text>',
        f'<rect x="0" y="{TITLE_H}" width="{RAIL_W}" height="{units * RU_PX}" fill="#1f2937"/>',
        f'<rect x="{x0 + RACK_W}" y="{TITLE_H}" width="{RAIL_W}" height="{units * RU_PX}" fill="#1f2937"/>',
    ]
    for u in range(1, units + 1):
        y = _block_y(rack, u, 1)
        parts.append(f'<rect class="rk-blank" x="{x0}" y="{y}" width="{RACK_W}" height="{RU_PX}" fill="#111827" stroke="#273041" stroke-width="0.5"/>')
        for rx in (RAIL_W / 2, x0 + RACK_W + RAIL_W / 2):
            parts.append(f'<text x="{rx:g}" y="{y + 15}" text-anchor="middle" font-size="10" fill="#9ca3af">{u}</text>')
    for p in occ["devices"]:
        if p["u"] is None:
            continue
        own = p["face"] == face
        if not own and p["depth"] != "full":
            continue
        d = devs.get(p["device"], {})
        y = _block_y(rack, p["u"], p["height"])
        bx = x0 + (RACK_W // 2 if p["side"] == "right" else 0)
        bw = RACK_W if p["side"] == "full" else RACK_W // 2
        bh = p["height"] * RU_PX
        stroke = "#ef4444" if p["device"] in colliding else "#4b5563"
        opacity = "1" if own else "0.45"
        name = str(d.get("name") or p["device"])
        model = f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip()
        label = name if own else f"{name} (rear)" if face == "front" else f"{name} (front)"
        parts.append(f'<g class="rk-block" data-device="{escape(p["device"])}" opacity="{opacity}">')
        parts.append(f'<rect x="{bx + 1}" y="{y + 1}" width="{bw - 2}" height="{bh - 2}" rx="2" fill="#1e293b" stroke="{stroke}" stroke-width="1.2"/>')
        parts.append(f'<rect x="{bx + 1}" y="{y + 1}" width="5" height="{bh - 2}" fill="{_disc_color(d)}"/>')
        parts.append(f'<text x="{bx + 12}" y="{y + 15}" font-size="11" font-weight="600" fill="#f3f4f6">{escape(label)}</text>')
        tail = f"{p['height']}U"
        if model and (bw >= RACK_W or bh > RU_PX):
            tail = f"{model} · {tail}"
        parts.append(f'<text x="{bx + bw - 6}" y="{y + 15}" text-anchor="end" font-size="9" fill="#9ca3af">{escape(tail)}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def rack_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]:
    """Racks schedule (§5.8.2): one row per racked device, racks in doc order, top RU first."""
    racks = _racks(doc)
    rooms = {r.get("id"): r.get("name") or r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict)}
    devs = {d["id"]: d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    rows: List[Dict[str, Any]] = []
    for rack_id, rack in racks.items():
        if room not in ("*", None) and (rack.get("room") or "") != room:
            continue
        placed = sorted(rack_devices(doc, rack_id), key=lambda p: (0 if p["face"] == "front" else 1, -(p["u"] or 0), p["device"]))
        for p in placed:
            d = devs[p["device"]]
            rows.append({
                "rack": rack.get("name") or rack_id, "rack_id": rack_id,
                "room": rooms.get(rack.get("room"), rack.get("room") or ""), "room_id": rack.get("room") or "",
                "units": rack.get("units"), "face": p["face"], "u": p["u"], "height": p["height"], "side": p["side"],
                "device": d.get("name") or d["id"], "device_id": d["id"],
                "model": f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip(),
            })
    problems = [pr for pr in validate_racks(doc)
                if room in ("*", None) or ((devs.get(pr["ref"].split("/", 1)[1], {}).get("rack") or {}).get("id") in
                                          {k for k, r in racks.items() if (r.get("room") or "") == room})]
    return {"kind": "racks", "columns": [dict(c) for c in RACK_COLUMNS], "rows": rows, "problems": problems}


__all__ = ["rack_occupancy", "validate_racks", "rack_svg", "rack_schedule", "rack_devices", "placement", "RU_PX", "RACK_W"]
