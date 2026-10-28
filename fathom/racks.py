"""Rack elevations: occupancy, collisions, validation, SVG and schedule (SPEC FR-RACK).

A placement is ``device.rack = {id, u, height, face, side, depth}``: ``u`` is the
lowest occupied RU (1-based, 1 = bottom), ``height`` defaults to the template
``ru`` (else 1), ``face`` front|rear, ``side`` full|left|right (half width),
``depth`` full|half (full depth occupies both faces; default ``full``).

Racks may also hold accessories (``rack.items[]``: blanks, vents, shelves, drawers,
cable managers, brush panels, lacing bars). Items are always full width and
collide with devices under the same face/depth rules. A device whose placement
names a ``shelf`` sits in a cell (``slot``) of that shelf item and is left out of
rack-level occupancy and collisions.
"""

from __future__ import annotations

import base64
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

Doc = Dict[str, Any]

RU_PX = 22
RACK_W = 320
RAIL_W = 30
TITLE_H = 28
CAPTION_H = 18
FACE_GAP = 24
ANNOT_GAP = 10
ANNOT_W = 180
FACES = ("front", "rear")
RACK_IMAGES_DIR = Path(__file__).parent / "static" / "rack-images"
IMAGE_BUDGET = 3 * 1024 * 1024
RACK_COLUMNS: List[Dict[str, str]] = [
    {"key": "rack", "label": "Rack"}, {"key": "room", "label": "Room"}, {"key": "units", "label": "Units"},
    {"key": "face", "label": "Face"}, {"key": "u", "label": "U"}, {"key": "height", "label": "Height"},
    {"key": "side", "label": "Side"}, {"key": "device", "label": "Device"}, {"key": "model", "label": "Model"},
]

ITEM_TYPES: List[Dict[str, Any]] = [
    {"type": "blank", "label": "Blank panel", "height": 1, "face": "front", "depth": "half", "color": "#44475a", "slots": None},
    {"type": "vent", "label": "Vent panel", "height": 1, "face": "front", "depth": "half", "color": "#44475a", "slots": None},
    {"type": "shelf", "label": "Shelf", "height": 1, "face": "front", "depth": "full", "color": "#6272a4", "slots": 2},
    {"type": "drawer", "label": "Drawer", "height": 2, "face": "front", "depth": "full", "color": "#6272a4", "slots": None},
    {"type": "cable_manager", "label": "Cable manager", "height": 1, "face": "front", "depth": "half", "color": "#6272a4", "slots": None},
    {"type": "brush", "label": "Brush panel", "height": 1, "face": "front", "depth": "half", "color": "#6272a4", "slots": None},
    {"type": "lacing_bar", "label": "Lacing bar", "height": 1, "face": "rear", "depth": "half", "color": "#6272a4", "slots": None},
    {"type": "other", "label": "Accessory", "height": 1, "face": "front", "depth": "half", "color": "#6272a4", "slots": None},
]
_ITEM_SPEC: Dict[str, Dict[str, Any]] = {t["type"]: t for t in ITEM_TYPES}

CATEGORY_COLORS: Dict[str, str] = {
    "server": "#4A7A8A", "network": "#7968A6", "firewall": "#C0392B", "storage": "#3D7A4A", "power": "#A84A4A",
    "kvm": "#926A40", "av-media": "#A85A7A", "cooling": "#75753F", "chassis": "#5A6A8A", "shelf": "#6272A4",
    "blank": "#44475A", "cable-management": "#6272A4", "patch-panel": "#6272A4", "other": "#6272A4",
}

ANNOTATION_LABELS: Dict[str, str] = {
    "name": "Name", "model": "Model", "ip": "IP", "serial": "Serial", "asset_tag": "Asset tag",
    "code": "Code", "power": "Power", "weight": "Weight", "status": "Status",
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_IMG_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*(?:/[A-Za-z0-9_][A-Za-z0-9._-]*)*$")
_IMG_MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

Memo = Optional[Dict[str, Any]]


# ------------------------------------------------------------------ helpers

def _racks(doc: Doc) -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in doc.get("racks") or [] if isinstance(r, dict) and r.get("id")}


def _int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (math.inf, -math.inf):
        return None
    return v


def _round1(x: float) -> float:
    return math.floor(x * 10 + 0.5) / 10


def _fmt_num(x: float) -> str:
    if isinstance(x, int):
        return str(x)
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _color(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and _COLOR_RE.match(v) else None


def _units(rack: Optional[Dict[str, Any]]) -> int:
    try:
        u = int((rack or {}).get("units"))
    except (TypeError, ValueError):
        return 1
    return min(u, 60) if u >= 1 else 1


def _t(s: Any) -> str:
    return escape(_BAD_XML.sub("", str(s)))


def _a(s: Any) -> str:
    return escape(_BAD_XML.sub("", str(s)), {'"': "&quot;"})


def _template(doc: Doc, template_id: str, memo: Memo = None) -> Optional[Dict[str, Any]]:
    if not template_id or not isinstance(template_id, str):
        return None
    key = "tpl:" + template_id
    if memo is not None and key in memo:
        return memo[key]
    t: Optional[Dict[str, Any]] = None
    try:
        from .library import get_template
        t = get_template(template_id, doc)
    except Exception:
        t = None
    if t is None:
        for x in doc.get("templates") or []:
            if isinstance(x, dict) and x.get("id") == template_id:
                t = x
    if memo is not None:
        memo[key] = t
    return t


def _template_ru(doc: Doc, template_id: str, memo: Memo = None) -> Optional[int]:
    ru = (_template(doc, template_id, memo) or {}).get("ru")
    return int(ru) if isinstance(ru, (int, float)) and not isinstance(ru, bool) and ru >= 1 else None


def ru_label(rack: Optional[Dict[str, Any]], u: int) -> str:
    """Printed label of physical RU ``u``: bottom_up ``u - 1 + start_u``, top_down ``units - u + start_u``."""
    s = _int((rack or {}).get("start_u"))
    s = s if s is not None and s >= 0 else 1
    if ((rack or {}).get("numbering") or "bottom_up") == "top_down":
        return str(_units(rack) - int(u) + s)
    return str(int(u) - 1 + s)


def rack_width_px(rack: Optional[Dict[str, Any]]) -> int:
    """Drawn rack width: ``round(320 * width_in / 19)`` (10" 168, 19" 320, 21" 354, 23" 387)."""
    w = _num((rack or {}).get("width_in"))
    w = w if w is not None and w > 0 else 19
    return int(math.floor(RACK_W * w / 19 + 0.5))


# --------------------------------------------------------------- placements

def placement(doc: Doc, dev: Dict[str, Any], _memo: Memo = None) -> Optional[Dict[str, Any]]:
    """Normalized placement of a racked device (``None`` if not racked)."""
    r = dev.get("rack")
    if not isinstance(r, dict) or not r.get("id"):
        return None
    h = r.get("height")
    if not isinstance(h, int) or isinstance(h, bool) or h < 1:
        h = _template_ru(doc, dev.get("template") or "", _memo) or 1
    u = _int(r.get("u"))
    shelf = r.get("shelf")
    return {
        "device": dev["id"], "rack": r["id"], "u": u, "height": int(h),
        "face": r.get("face") if r.get("face") in FACES else "front",
        "side": r.get("side") if r.get("side") in ("full", "left", "right") else "full",
        "depth": r.get("depth") if r.get("depth") in ("full", "half") else "full",
        "shelf": shelf if isinstance(shelf, str) and shelf else None,
        "slot": _int(r.get("slot")),
        "color": _color(r.get("color")),
    }


def _faces_of(p: Dict[str, Any]) -> Tuple[str, ...]:
    return FACES if p["depth"] == "full" else (p["face"],)


def _sides_of(p: Dict[str, Any]) -> Tuple[str, ...]:
    return ("left", "right") if p["side"] == "full" else (p["side"],)


def _blocks(p: Dict[str, Any], face: str) -> bool:
    return p["face"] == face or p["depth"] == "full"


def rack_devices(doc: Doc, rack_id: str, _memo: Memo = None) -> List[Dict[str, Any]]:
    """Placements of every device in the rack, shelf children included (``shelf`` set)."""
    out = []
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id"):
            p = placement(doc, d, _memo)
            if p and p["rack"] == rack_id:
                out.append(p)
    return out


def _items_of(rack: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    items = rack.get("items")
    if not isinstance(items, list):
        return out
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not it["id"]:
            continue
        spec = _ITEM_SPEC.get(it.get("type")) or _ITEM_SPEC["other"]
        h = _int(it.get("height"))
        slots = None
        if spec["type"] == "shelf":
            s = _int(it.get("slots"))
            slots = min(max(s, 1), 4) if s is not None else spec["slots"]
        out.append({
            "id": "item:" + it["id"], "item": it["id"], "index": i, "type": spec["type"], "type_label": spec["label"],
            "u": _int(it.get("u")), "height": h if h is not None and h >= 1 else spec["height"],
            "face": it.get("face") if it.get("face") in FACES else spec["face"],
            "depth": it.get("depth") if it.get("depth") in ("full", "half") else spec["depth"],
            "side": "full", "label": str(it.get("label") or ""), "color": _color(it.get("color")) or spec["color"],
            "slots": slots, "weight_kg": _num(it.get("weight_kg")), "notes": str(it.get("notes") or ""),
        })
    return out


def rack_items(doc: Doc, rack_id: str) -> List[Dict[str, Any]]:
    """Normalized items of a rack: ``[{id: 'item:<id>', item, index, type, type_label, u, height, face, depth,
    side: 'full', label, color, slots, weight_kg, notes}]`` (``[]`` for an unknown rack)."""
    rack = _racks(doc).get(rack_id)
    return _items_of(rack) if rack is not None else []


def _participants(doc: Doc, rack_id: str, memo: Memo) -> List[Dict[str, Any]]:
    """Rack-level occupants with a ``ref`` (device id or ``item:<id>``)."""
    out = [dict(p, ref=p["device"]) for p in rack_devices(doc, rack_id, memo) if not p["shelf"] and p["u"] is not None]
    out += [dict(it, ref=it["id"]) for it in rack_items(doc, rack_id) if it["u"] is not None]
    return out


def collisions(doc: Doc, rack_id: str, _memo: Memo = None) -> List[Dict[str, Any]]:
    """``[{a, b, u, face}]`` per colliding pair and face; ``a < b``, sorted by ``(u, face, a, b)``."""
    if rack_id not in _racks(doc):
        return []
    ps = _participants(doc, rack_id, _memo)
    out: List[Dict[str, Any]] = []
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            p, q = ps[i], ps[j]
            if p["ref"] == q["ref"]:
                continue
            lo = max(p["u"], q["u"])
            if lo > min(p["u"] + p["height"] - 1, q["u"] + q["height"] - 1):
                continue
            if not (p["side"] == "full" or q["side"] == "full" or p["side"] == q["side"]):
                continue
            a, b = sorted((p["ref"], q["ref"]))
            for face in FACES:
                if _blocks(p, face) and _blocks(q, face):
                    out.append({"a": a, "b": b, "u": lo, "face": face})
    out.sort(key=lambda c: (c["u"], c["face"], c["a"], c["b"]))
    return out


def rack_occupancy(doc: Doc, rack_id: str) -> Dict[str, Any]:
    """``{"rack", "devices", "items", "shelved", "slots": [{u, front:{left,right}, rear:{left,right}}], "collisions"}``.

    ``devices`` are rack-level placements, ``shelved`` the shelf children; slot cells hold a device id or
    ``item:<id>`` (the first occupant in doc order, devices before items)."""
    rack = _racks(doc).get(rack_id)
    if rack is None:
        raise KeyError(rack_id)
    memo: Dict[str, Any] = {}
    units = _units(rack)
    slots = [{"u": u, "front": {"left": None, "right": None}, "rear": {"left": None, "right": None}} for u in range(1, units + 1)]
    placed = rack_devices(doc, rack_id, memo)
    for p in _participants(doc, rack_id, memo):
        for u in range(max(p["u"], 1), min(p["u"] + p["height"] - 1, units) + 1):
            for face in _faces_of(p):
                for side in _sides_of(p):
                    if slots[u - 1][face][side] is None:
                        slots[u - 1][face][side] = p["ref"]
    info = {k: rack.get(k) for k in ("id", "name", "room", "location", "units", "width_in", "form_factor", "row") if rack.get(k) is not None}
    info["numbering"] = rack.get("numbering") or "bottom_up"
    info["faces"] = list(rack.get("faces") or ["front", "rear"])
    info["start_u"] = _int(rack.get("start_u")) if _int(rack.get("start_u")) is not None else 1
    return {
        "rack": info, "devices": [p for p in placed if not p["shelf"]], "items": _items_of(rack),
        "shelved": [p for p in placed if p["shelf"]], "slots": slots, "collisions": collisions(doc, rack_id, memo),
    }


def shelf_contents(doc: Doc, rack_id: str, item_id: str) -> List[Dict[str, Any]]:
    """``[{slot, device}]`` for each cell of a shelf item (``device`` = first device on it in doc order, or None)."""
    shelf = next((it for it in rack_items(doc, rack_id) if it["item"] == item_id and it["type"] == "shelf"), None)
    if shelf is None:
        return []
    cells: List[Dict[str, Any]] = [{"slot": i, "device": None} for i in range(shelf["slots"])]
    for d in doc.get("devices") or []:
        r = d.get("rack") if isinstance(d, dict) and d.get("id") else None
        if not isinstance(r, dict) or r.get("id") != rack_id or r.get("shelf") != item_id:
            continue
        s = _int(r.get("slot"))
        if s is not None and 0 <= s < len(cells) and cells[s]["device"] is None:
            cells[s]["device"] = d["id"]
    return cells


def _device_value(doc: Doc, dev: Dict[str, Any], key: str, memo: Memo) -> float:
    v = _num(dev.get(key))
    if v is None:
        v = _num((_template(doc, dev.get("template") or "", memo) or {}).get(key))
    return v if v is not None else 0


def rack_totals(doc: Doc, rack_id: str, _memo: Memo = None) -> Dict[str, Any]:
    """``{units, used_u, free_u, weight_kg, max_load_kg, power_w, power_limit_w, devices, items}`` (1 decimal)."""
    rack = _racks(doc).get(rack_id)
    if rack is None:
        raise KeyError(rack_id)
    units = _units(rack)
    used = set()
    for p in _participants(doc, rack_id, _memo):
        used.update(range(max(p["u"], 1), min(p["u"] + p["height"] - 1, units) + 1))
    items = _items_of(rack)
    weight = _num(rack.get("weight_kg")) or 0
    power = 0.0
    n = 0
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        r = d.get("rack")
        if isinstance(r, dict) and r.get("id") == rack_id:
            n += 1
            weight += _device_value(doc, d, "weight_kg", _memo)
            power += _device_value(doc, d, "power_w", _memo)
    weight += sum(it["weight_kg"] or 0 for it in items)
    max_load, limit = _num(rack.get("max_load_kg")), _num(rack.get("power_limit_w"))
    return {
        "units": units, "used_u": len(used), "free_u": units - len(used),
        "weight_kg": _round1(weight), "max_load_kg": _round1(max_load) if max_load is not None else None,
        "power_w": _round1(power), "power_limit_w": _round1(limit) if limit is not None else None,
        "devices": n, "items": len(items),
    }


def annotation_value(doc: Doc, device: Dict[str, Any], field: str, _memo: Memo = None) -> str:
    """Text for the rack annotation column (``''`` when unknown or empty)."""
    if not isinstance(device, dict):
        return ""
    if field == "name":
        return str(device.get("name") or "")
    if field == "model":
        return f"{device.get('manufacturer') or ''} {device.get('model') or ''}".strip()
    if field == "ip":
        ifs = [i for i in device.get("interfaces") or [] if isinstance(i, dict) and i.get("ip")]
        pick = next((i for i in ifs if i.get("role") == "primary"), ifs[0] if ifs else None)
        return str(pick["ip"]) if pick else ""
    if field in ("serial", "asset_tag"):
        inv = device.get("inventory")
        return str(inv.get(field) or "") if isinstance(inv, dict) else ""
    if field == "code":
        return str(device.get("code") or "")
    if field in ("power", "weight"):
        v = _device_value(doc, device, "power_w" if field == "power" else "weight_kg", _memo)
        return f"{_fmt_num(v)} {'W' if field == 'power' else 'kg'}" if v > 0 else ""
    if field == "status":
        return str(device.get("status") or "installed")
    return ""


# --------------------------------------------------------------- validation

def _problem(code: str, dev_id: str, message: str) -> Dict[str, Any]:
    return {"level": "warning", "code": code, "ref": f"devices/{dev_id}", "path": f"devices/{dev_id}/rack", "message": message}


def _item_problem(code: str, rack_id: str, index: int, message: str) -> Dict[str, Any]:
    return {"level": "warning", "code": code, "ref": f"racks/{rack_id}", "path": f"racks/{rack_id}/items/{index}", "message": message}


def _rack_problem(code: str, rack_id: str, field: str, message: str) -> Dict[str, Any]:
    return {"level": "warning", "code": code, "ref": f"racks/{rack_id}", "path": f"racks/{rack_id}/{field}", "message": message}


def _item_name(it: Dict[str, Any]) -> str:
    return it["label"] or it["type_label"]


def validate_racks(doc: Doc) -> List[Dict[str, Any]]:
    """Rack warnings (§4.7): ``rack_unknown``, ``rack_out_of_range``, ``rack_overlap`` (devices and items),
    ``rack_shelf_unknown``, ``rack_slot_out_of_range``, ``rack_shelf_overlap``, ``rack_overweight``, ``rack_over_power``."""
    racks = _racks(doc)
    memo: Dict[str, Any] = {}
    names = {d["id"]: d.get("name") or d["id"] for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    items = {rid: _items_of(rack) for rid, rack in racks.items()}
    shelves = {rid: {it["item"]: it for it in its if it["type"] == "shelf"} for rid, its in items.items()}
    cells: Dict[Tuple[str, str, int], str] = {}
    out: List[Dict[str, Any]] = []
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        p = placement(doc, d, memo)
        if p is None:
            continue
        rack = racks.get(p["rack"])
        if rack is None:
            out.append(_problem("rack_unknown", d["id"], f"{names[d['id']]} is placed in unknown rack '{p['rack']}'."))
            continue
        rname = rack.get("name") or rack["id"]
        if p["shelf"]:
            shelf = shelves[rack["id"]].get(p["shelf"])
            if shelf is None:
                out.append(_problem("rack_shelf_unknown", d["id"], f"{names[d['id']]} is on shelf '{p['shelf']}', which is not a shelf in {rname}."))
            elif p["slot"] is None or not 0 <= p["slot"] < shelf["slots"]:
                out.append(_problem("rack_slot_out_of_range", d["id"], f"{names[d['id']]} uses cell {p['slot']} of {_item_name(shelf)} in {rname}, which has {shelf['slots']} cells."))
            else:
                key = (rack["id"], shelf["item"], p["slot"])
                if key in cells:
                    out.append(_problem("rack_shelf_overlap", d["id"], f"{names[d['id']]} shares cell {p['slot']} of {_item_name(shelf)} with {names.get(cells[key], cells[key])} in {rname}."))
                else:
                    cells[key] = d["id"]
            continue
        units = _units(rack)
        if p["u"] is None or p["u"] < 1 or p["u"] + p["height"] - 1 > units:
            out.append(_problem("rack_out_of_range", d["id"], f"{names[d['id']]} (U{p['u']}, {p['height']}U) does not fit in {rname} ({units}U)."))
    for rack_id, rack in racks.items():
        rname = rack.get("name") or rack_id
        units = _units(rack)
        by_ref = {it["id"]: it for it in items[rack_id]}
        for it in items[rack_id]:
            if it["u"] is None or it["u"] < 1 or it["u"] + it["height"] - 1 > units:
                out.append(_item_problem("rack_out_of_range", rack_id, it["index"], f"{_item_name(it)} (U{it['u']}, {it['height']}U) does not fit in {rname} ({units}U)."))

        def label(ref: str) -> str:
            return _item_name(by_ref[ref]) if ref in by_ref else names.get(ref, ref)

        for c in collisions(doc, rack_id, memo):
            msg = f"{label(c['b'])} overlaps {label(c['a'])} at U{c['u']} ({c['face']}) in {rname}."
            dev = next((r for r in (c["b"], c["a"]) if r not in by_ref), None)
            out.append(_problem("rack_overlap", dev, msg) if dev else _item_problem("rack_overlap", rack_id, by_ref[c["b"]]["index"], msg))
        t = rack_totals(doc, rack_id, memo)
        if t["max_load_kg"] is not None and t["weight_kg"] > t["max_load_kg"]:
            out.append(_rack_problem("rack_overweight", rack_id, "max_load_kg", f"{rname} carries {_fmt_num(t['weight_kg'])} kg, over its {_fmt_num(t['max_load_kg'])} kg limit."))
        if t["power_limit_w"] is not None and t["power_w"] > t["power_limit_w"]:
            out.append(_rack_problem("rack_over_power", rack_id, "power_limit_w", f"{rname} draws {_fmt_num(t['power_w'])} W, over its {_fmt_num(t['power_limit_w'])} W limit."))
    return out


# ---------------------------------------------------------------------- SVG

def _disc_color(dev: Dict[str, Any]) -> str:
    try:
        from . import vocab
        from .trace import device_discipline
        return vocab.DISCIPLINES.get(device_discipline(dev), {}).get("color") or "#9aa3b5"
    except Exception:  # pragma: no cover
        return "#9aa3b5"


def _device_color(dev: Dict[str, Any], p: Dict[str, Any], tpl: Optional[Dict[str, Any]]) -> str:
    if p.get("color"):
        return p["color"]
    cat = (tpl or {}).get("rack_category")
    if isinstance(cat, str) and cat in CATEGORY_COLORS:
        return CATEGORY_COLORS[cat]
    return _disc_color(dev)


def _text_on(hex_color: str) -> str:
    """``#000`` or ``#fff``, whichever contrasts more with the colour (WCAG relative luminance)."""
    def ch(i: int) -> float:
        c = int(hex_color[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)
    return "#000" if (lum + 0.05) / 0.05 > 1.05 / (lum + 0.05) else "#fff"


def _block_y(rack: Dict[str, Any], u: int, height: int, top: int = TITLE_H) -> int:
    """Top edge of a block spanning ``u..u+height-1`` (physical RU 1 is always the bottom row)."""
    return top + (_units(rack) - (u + height - 1)) * RU_PX


def _clip(s: str, width: float, px: float = 5.8) -> str:
    n = max(int(width / px), 1)
    return s if len(s) <= n else s[:max(n - 1, 1)] + "…"


class _Images:
    """Template rack images for one SVG: ``href`` URLs, or embedded data URIs under ``IMAGE_BUDGET``."""

    def __init__(self, enabled: bool, base_url: str) -> None:
        self.enabled, self.base = enabled, base_url or ""
        self.symbols: List[str] = []
        self.ids: Dict[str, Optional[str]] = {}
        self.used = 0

    def _embed(self, path: str) -> Optional[str]:
        if path in self.ids:
            return self.ids[path]
        sym = None
        mime = _IMG_MIME.get(Path(path).suffix.lower())
        root = Path(RACK_IMAGES_DIR).resolve()
        try:
            f = (root / path).resolve()
            ok = mime is not None and f.is_file() and f.is_relative_to(root)
            size = f.stat().st_size if ok else 0
            if ok and self.used + size <= IMAGE_BUDGET:
                data = base64.b64encode(f.read_bytes()).decode("ascii")
                self.used += size
                sym = f"rki-{len(self.symbols) + 1}"
                self.symbols.append(f'<symbol id="{sym}" viewBox="0 0 100 100" preserveAspectRatio="none">'
                                    f'<image width="100" height="100" preserveAspectRatio="none" href="data:{mime};base64,{data}"/></symbol>')
        except OSError:
            sym = None
        self.ids[path] = sym
        return sym

    def element(self, tpl: Optional[Dict[str, Any]], face: str, x: float, y: float, w: float, h: float) -> str:
        if not self.enabled:
            return ""
        path = (tpl or {}).get("image_" + face)
        if not isinstance(path, str) or not _IMG_PATH.match(path) or ".." in path.split("/"):
            return ""
        box = f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"'
        if self.base:
            return f'<image class="rk-img" {box} preserveAspectRatio="none" href="{_a(self.base + "static/rack-images/" + path)}"/>'
        sym = self._embed(path)
        return f'<use class="rk-img" href="#{sym}" {box}/>' if sym else ""


def _device_svg(parts: List[str], p: Dict[str, Any], box: Tuple[float, float, float, float], *,
                label: str, tail: str, color: str, stroke: str, opacity: str, image: str, attrs: str = "", small: bool = False) -> None:
    x, y, w, h = box
    fs, fs2 = (9, 8) if small else (11, 9)
    halo = ' stroke="#0b1020" stroke-width="3" paint-order="stroke"' if image else ""
    parts.append(f'<g class="rk-block" data-device="{_a(p["device"])}" opacity="{opacity}"{attrs}>')
    parts.append(f'<rect x="{x + 1:g}" y="{y + 1:g}" width="{w - 2:g}" height="{h - 2:g}" rx="2" fill="#1e293b"/>')
    parts.append(image or f'<rect x="{x + 1:g}" y="{y + 1:g}" width="{w - 2:g}" height="{h - 2:g}" rx="2" fill="{color}" fill-opacity="0.35"/>')
    parts.append(f'<rect x="{x + 1:g}" y="{y + 1:g}" width="5" height="{h - 2:g}" fill="{color}"/>')
    parts.append(f'<rect x="{x + 1:g}" y="{y + 1:g}" width="{w - 2:g}" height="{h - 2:g}" rx="2" fill="none" stroke="{stroke}" stroke-width="1.2"/>')
    ty = y + min(15, h / 2 + 4) if small else y + 15
    parts.append(f'<text x="{x + 12:g}" y="{ty:g}" font-size="{fs}" font-weight="600" fill="#f3f4f6"{halo}>{_t(label)}</text>')
    if tail:
        parts.append(f'<text x="{x + w - 6:g}" y="{ty:g}" text-anchor="end" font-size="{fs2}" fill="#9ca3af"{halo}>{_t(tail)}</text>')
    parts.append("</g>")


def _item_svg(parts: List[str], it: Dict[str, Any], box: Tuple[float, float, float, float], *, stroke: str, opacity: str, label: str) -> None:
    x, y, w, h = box
    t, color = it["type"], it["color"]
    fg = _text_on(color)
    parts.append(f'<g class="rk-item rk-item-{t}" data-item="{_a(it["item"])}" data-type="{t}" opacity="{opacity}">')
    if t == "lacing_bar":
        by = y + h / 2 - 3
        parts.append(f'<rect x="{x + 1:g}" y="{by:g}" width="{w - 2:g}" height="6" rx="3" fill="{color}" stroke="{stroke}" stroke-width="1"/>')
        for cx in (x + 8, x + w - 8):
            parts.append(f'<circle cx="{cx:g}" cy="{by + 3:g}" r="2" fill="#111827"/>')
        if label:
            parts.append(f'<text x="{x + w / 2:g}" y="{by - 2:g}" text-anchor="middle" font-size="8" fill="#9ca3af">{_t(label)}</text>')
        parts.append("</g>")
        return
    base = "#111827" if t == "shelf" else color
    parts.append(f'<rect x="{x + 1:g}" y="{y + 1:g}" width="{w - 2:g}" height="{h - 2:g}" rx="2" fill="{base}" stroke="{stroke}" stroke-width="1"/>')
    if t == "vent":
        n = max(int((w - 24) // 14), 3)
        step = (w - 24) / n
        d = "".join(f"M{x + 12 + i * step + 2:g} {y + r * RU_PX + 8:g}h{step - 4:g}v6h-{step - 4:g}z" for r in range(int(h // RU_PX)) for i in range(n))
        parts.append(f'<path class="rk-vent" d="{d}" fill="#1f2230"/>')
    elif t == "brush":
        bx, bw, by = x + 16, w - 32, y + h / 2 - 4
        parts.append(f'<rect x="{bx:g}" y="{by:g}" width="{bw:g}" height="8" fill="#1f2230"/>')
        d = "".join(f"M{bx + 2 + i * 4:g} {by + 1:g}v6" for i in range(int((bw - 4) // 4) + 1))
        parts.append(f'<path class="rk-brush" d="{d}" stroke="#6b7280" stroke-width="0.6"/>')
    elif t == "drawer":
        hw = w * 0.3
        parts.append(f'<line x1="{x + 4:g}" y1="{y + 5:g}" x2="{x + w - 4:g}" y2="{y + 5:g}" stroke="#1f2230" stroke-width="1"/>')
        parts.append(f'<rect class="rk-handle" x="{x + (w - hw) / 2:g}" y="{y + h / 2 - 2.5:g}" width="{hw:g}" height="5" rx="2.5" fill="#d1d5db"/>')
    elif t == "cable_manager":
        n = max(int(w // 50), 3)
        for i in range(n):
            cx = x + (i + 0.5) * w / n
            parts.append(f'<rect class="rk-ring" x="{cx - 7:g}" y="{y + 4:g}" width="14" height="{h - 8:g}" rx="4" fill="none" stroke="#d1d5db" stroke-width="1.5"/>')
    elif t == "shelf":
        slots = it["slots"] or 1
        parts.append(f'<rect class="rk-tray" x="{x + 1:g}" y="{y + h - 5:g}" width="{w - 2:g}" height="4" fill="{color}"/>')
        for i in range(1, slots):
            cx = x + i * w / slots
            parts.append(f'<line class="rk-cell" x1="{cx:g}" y1="{y + 3:g}" x2="{cx:g}" y2="{y + h - 5:g}" stroke="{color}" stroke-width="1" stroke-dasharray="3 2"/>')
    if label and t not in ("vent", "brush", "cable_manager"):
        anchor = 'x="{:g}" text-anchor="middle"'.format(x + w / 2)
        ty = y + h - 8 if t == "shelf" else y + min(15, h / 2 + 4)
        fill = "#9ca3af" if t == "shelf" else fg
        parts.append(f'<text {anchor} y="{ty:g}" font-size="9" fill="{fill}">{_t(label)}</text>')
    elif label:
        parts.append(f'<text x="{x + 8:g}" y="{y + min(15, h / 2 + 4):g}" font-size="9" fill="{fg}">{_t(label)}</text>')
    parts.append("</g>")


def rack_svg(doc: Doc, rack_id: str, face: str = "front", scale: float = 1.0, *, images: bool = False,
             annotate: Optional[str] = None, base_url: str = "") -> str:
    """Standalone SVG elevation of one rack face, or ``face="both"`` (front and rear side by side).

    Rails with RU labels, device blocks (colour: ``rack.color`` > template ``rack_category`` > discipline),
    accessories, shelf cells with their devices, optional template images (``images``: ``href`` under
    ``base_url``, else embedded data URIs up to ``IMAGE_BUDGET``) and an ``annotate`` column."""
    racks = _racks(doc)
    if rack_id not in racks:
        raise KeyError(rack_id)
    rack = racks[rack_id]
    memo: Dict[str, Any] = {}
    faces = FACES if face == "both" else ((face,) if face in FACES else ("front",))
    both = len(faces) == 2
    annot = annotate if isinstance(annotate, str) and annotate else None
    units = _units(rack)
    rw = rack_width_px(rack)
    panel_w = RAIL_W * 2 + rw
    top = TITLE_H + (CAPTION_H if both or annot else 0)
    panels_w = panel_w * len(faces) + FACE_GAP * (len(faces) - 1)
    w = panels_w + (ANNOT_GAP + ANNOT_W if annot else 0)
    h = top + units * RU_PX + 8
    devs = {d["id"]: d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    colls = collisions(doc, rack_id, memo)
    placed = rack_devices(doc, rack_id, memo)
    level = [p for p in placed if not p["shelf"] and p["u"] is not None]
    items = [it for it in _items_of(rack) if it["u"] is not None]
    shelves = {it["item"]: it for it in items if it["type"] == "shelf"}
    cells: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for p in placed:
        s = shelves.get(p["shelf"] or "")
        if s is not None and p["slot"] is not None and 0 <= p["slot"] < s["slots"]:
            cells.setdefault(s["item"], {}).setdefault(p["slot"], p)
    totals = rack_totals(doc, rack_id, memo)
    img = _Images(bool(images), base_url)

    name = str(rack.get("name") or rack_id)
    title = f"{name} · {'front + rear' if both else faces[0]}"
    weight = f"{_fmt_num(totals['weight_kg'])}" + (f"/{_fmt_num(totals['max_load_kg'])}" if totals["max_load_kg"] is not None else "") + " kg"
    power = f"{_fmt_num(totals['power_w'])}" + (f"/{_fmt_num(totals['power_limit_w'])}" if totals["power_limit_w"] is not None else "") + " W"
    stats = [
        (f"{totals['used_u']}/{units}U used · {totals['free_u']}U free", False),
        (weight, totals["max_load_kg"] is not None and totals["weight_kg"] > totals["max_load_kg"]),
        (power, totals["power_limit_w"] is not None and totals["power_w"] > totals["power_limit_w"]),
    ]
    chars = len(title) + sum(len(s) + 3 for s, _ in stats)
    fs = round(max(7.0, min(13.0, (w - 12) / (0.56 * chars))), 1)
    spans = "".join(f'<tspan fill="{"#f87171" if warn else "#9ca3af"}"> · {_t(s)}</tspan>' for s, warn in stats)
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * scale:g}" height="{h * scale:g}" viewBox="0 0 {w} {h}" '
        f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" data-rack="{_a(rack_id)}" data-face="{"both" if both else faces[0]}">',
        f'<title>{_t(title)}</title>',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#0b1020"/>',
        f'<text class="rk-title" x="{w / 2:g}" y="18" text-anchor="middle" font-size="{fs:g}" font-weight="600" fill="#e5e7eb">{_t(title)}'
        f'<tspan font-weight="400">{spans}</tspan></text>',
    ]
    parts: List[str] = []
    x0 = RAIL_W

    def look(dev_id: str) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        d = devs.get(dev_id, {})
        return d, _template(doc, d.get("template") or "", memo)

    for fi, f in enumerate(faces):
        colliding = {c["a"] for c in colls if c["face"] == f} | {c["b"] for c in colls if c["face"] == f}
        other = "rear" if f == "front" else "front"
        parts.append(f'<g class="rk-face" data-face="{f}" transform="translate({fi * (panel_w + FACE_GAP)},0)">')
        if both:
            parts.append(f'<text class="rk-caption" x="{panel_w / 2:g}" y="{TITLE_H + 12}" text-anchor="middle" font-size="11" '
                         f'font-weight="600" fill="#cbd5e1">{"Front" if f == "front" else "Rear"}</text>')
        parts.append(f'<rect x="0" y="{top}" width="{RAIL_W}" height="{units * RU_PX}" fill="#1f2937"/>')
        parts.append(f'<rect x="{x0 + rw}" y="{top}" width="{RAIL_W}" height="{units * RU_PX}" fill="#1f2937"/>')
        for u in range(1, units + 1):
            y = _block_y(rack, u, 1, top)
            parts.append(f'<rect class="rk-blank" x="{x0}" y="{y}" width="{rw}" height="{RU_PX}" fill="#111827" stroke="#273041" stroke-width="0.5"/>')
            for rx in (RAIL_W / 2, x0 + rw + RAIL_W / 2):
                parts.append(f'<text x="{rx:g}" y="{y + 15}" text-anchor="middle" font-size="10" fill="#9ca3af">{_t(ru_label(rack, u))}</text>')
        for it in items:
            if not _blocks(it, f):
                continue
            own = it["face"] == f
            y = _block_y(rack, it["u"], it["height"], top)
            ih = it["height"] * RU_PX
            label = it["label"] or ("" if it["type"] in ("blank", "vent", "brush", "lacing_bar", "cable_manager") else it["type_label"])
            if it["type"] == "shelf" and cells.get(it["item"]):
                label = it["label"]
            if label and not own:
                label = f"{label} ({other})"
            stroke = "#ef4444" if it["id"] in colliding else "#4b5563"
            opacity = "1" if own else "0.45"
            _item_svg(parts, it, (x0, y, rw, ih), stroke=stroke, opacity=opacity, label=label)
            if it["type"] == "shelf":
                cw = rw / it["slots"]
                for slot, p in sorted(cells.get(it["item"], {}).items()):
                    d, tpl = look(p["device"])
                    bx, by, bw, bh = x0 + slot * cw + 2, y + 2, cw - 4, ih - 8
                    cname = _clip(str(d.get("name") or p["device"]), bw - 14)
                    _device_svg(parts, p, (bx, by, bw, bh), label=cname, tail="", color=_device_color(d, p, tpl),
                                stroke="#4b5563", opacity=opacity, image=img.element(tpl, f, bx + 1, by + 1, bw - 2, bh - 2),
                                attrs=f' data-shelf="{_a(it["item"])}" data-slot="{slot}"', small=True)
        for p in level:
            own = p["face"] == f
            if not own and p["depth"] != "full":
                continue
            d, tpl = look(p["device"])
            y = _block_y(rack, p["u"], p["height"], top)
            bx = x0 + (rw // 2 if p["side"] == "right" else 0)
            bw = rw if p["side"] == "full" else rw // 2
            bh = p["height"] * RU_PX
            dname = str(d.get("name") or p["device"])
            model = f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip()
            tail = f"{p['height']}U"
            if model and (bw >= RACK_W or bh > RU_PX):
                tail = f"{model} · {tail}"
            _device_svg(parts, p, (bx, y, bw, bh), label=dname if own else f"{dname} ({other})", tail=tail,
                        color=_device_color(d, p, tpl), stroke="#ef4444" if p["device"] in colliding else "#4b5563",
                        opacity="1" if own else "0.45", image=img.element(tpl, f, bx + 1, y + 1, bw - 2, bh - 2))
        parts.append("</g>")

    if annot:
        ax = panels_w + ANNOT_GAP
        parts.append(f'<g class="rk-annotations" data-field="{_a(annot)}">')
        parts.append(f'<text x="{ax}" y="{TITLE_H + 12}" font-size="10" font-weight="600" fill="#9ca3af">{_t(ANNOTATION_LABELS.get(annot, annot))}</text>')
        rows: Dict[Tuple[int, int], List[Tuple[str, str]]] = {}
        shown = [p for p in level if any(_blocks(p, f) for f in faces)]
        for it in items:
            if it["item"] in cells and any(_blocks(it, f) for f in faces):
                shown += [dict(p, u=it["u"], height=it["height"]) for _, p in sorted(cells[it["item"]].items())]
        for p in shown:
            val = annotation_value(doc, devs.get(p["device"], {}), annot, memo)
            if val:
                rows.setdefault((_block_y(rack, p["u"], p["height"], top), p["height"]), []).append((p["device"], val))
        for (y, _hgt), vals in sorted(rows.items()):
            ids = " ".join(i for i, _ in vals)
            text = _clip(" · ".join(v for _, v in vals), ANNOT_W, 5.6)
            parts.append(f'<g class="rk-annot" data-devices="{_a(ids)}">'
                         f'<line x1="{panels_w + 2}" y1="{y + 11}" x2="{ax - 2}" y2="{y + 11}" stroke="#374151" stroke-dasharray="2 2"/>'
                         f'<text x="{ax}" y="{y + 15}" font-size="10" fill="#d1d5db">{_t(text)}</text></g>')
        parts.append("</g>")
    defs = ["<defs>" + "".join(img.symbols) + "</defs>"] if img.symbols else []
    return "\n".join(head + defs + parts + ["</svg>"]) + "\n"


# ----------------------------------------------------------------- schedule

def rack_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]:
    """Racks schedule (§5.8.2): one row per racked device, then one per item, racks in doc order, top RU first."""
    racks = _racks(doc)
    rooms = {r.get("id"): r.get("name") or r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict)}
    devs = {d["id"]: d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    memo: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    for rack_id, rack in racks.items():
        if room not in ("*", None) and (rack.get("room") or "") != room:
            continue
        base = {
            "rack": rack.get("name") or rack_id, "rack_id": rack_id,
            "room": rooms.get(rack.get("room"), rack.get("room") or ""), "room_id": rack.get("room") or "",
            "units": rack.get("units"),
        }
        placed = sorted(rack_devices(doc, rack_id, memo), key=lambda p: (0 if p["face"] == "front" else 1, -(p["u"] or 0), p["device"]))
        for p in placed:
            d = devs[p["device"]]
            rows.append(dict(base, **{
                "face": p["face"], "u": p["u"], "height": p["height"], "side": p["side"],
                "device": d.get("name") or d["id"], "device_id": d["id"],
                "model": f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip(),
            }))
        for it in sorted(_items_of(rack), key=lambda it: (0 if it["face"] == "front" else 1, -(it["u"] or 0), it["item"])):
            rows.append(dict(base, **{
                "face": it["face"], "u": it["u"], "height": it["height"], "side": "full",
                "device": it["label"] or it["type_label"], "device_id": "", "item_id": it["item"], "item_type": it["type"],
                "model": it["type_label"],
            }))
    in_room = {k for k, r in racks.items() if (r.get("room") or "") == room}

    def keep(pr: Dict[str, Any]) -> bool:
        if room in ("*", None):
            return True
        kind, _, ref = str(pr.get("ref") or "").partition("/")
        if kind == "racks":
            return ref in in_room
        rk = devs.get(ref, {}).get("rack")
        return isinstance(rk, dict) and rk.get("id") in in_room

    return {"kind": "racks", "columns": [dict(c) for c in RACK_COLUMNS], "rows": rows, "problems": [pr for pr in validate_racks(doc) if keep(pr)]}


__all__ = [
    "rack_occupancy", "validate_racks", "rack_svg", "rack_schedule", "rack_devices", "placement", "RU_PX", "RACK_W",
    "ITEM_TYPES", "CATEGORY_COLORS", "ANNOTATION_LABELS", "RACK_IMAGES_DIR", "IMAGE_BUDGET", "ru_label", "rack_width_px",
    "collisions", "rack_items", "shelf_contents", "rack_totals", "annotation_value",
]
