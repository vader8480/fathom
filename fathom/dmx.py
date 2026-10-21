"""Lighting addressing: DMX schedule, problems, sACN / Art-Net helpers (SPEC FR-DMX).

``device.dmx = {universe 1–63999, address 1–512, footprint 1–512, mode, channel,
protocol dmx|sacn|artnet, port}``. Overlay DMX (Eos / Lightwright imports) fills
rows for devices without a manual ``dmx`` (manual wins).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]

DMX_COLUMNS: List[Dict[str, str]] = [
    {"key": "universe", "label": "Universe"}, {"key": "address", "label": "Address"}, {"key": "end", "label": "End"},
    {"key": "footprint", "label": "Footprint"}, {"key": "device", "label": "Device"}, {"key": "room", "label": "Room"},
    {"key": "mode", "label": "Mode"}, {"key": "channel", "label": "Console channel"}, {"key": "protocol", "label": "Protocol"},
    {"key": "sacn_group", "label": "sACN group"}, {"key": "artnet", "label": "Art-Net (net:sub:uni)"}, {"key": "source", "label": "Source"},
]


def sacn_group(universe: int) -> str:
    """sACN (E1.31) multicast group ``239.255.<u >> 8>.<u & 255>``."""
    u = int(universe)
    return f"239.255.{(u >> 8) & 255}.{u & 255}"


def artnet_split(universe: int) -> Tuple[int, int, int]:
    """Art-Net port-address ``u - 1`` → ``(net, sub_net, universe)`` (Art-Net counts from 0)."""
    pa = int(universe) - 1
    return (pa >> 8) & 0x7F, (pa >> 4) & 0x0F, pa & 0x0F


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _template_footprint(doc: Doc, template_id: str) -> Optional[int]:
    if not template_id:
        return None
    t = None
    for x in doc.get("templates") or []:
        if isinstance(x, dict) and x.get("id") == template_id:
            t = x
    if t is None:
        try:
            from .library import get_template  # W2
            t = get_template(template_id, doc)
        except Exception:
            t = None
    return _int((t or {}).get("dmx_footprint"))


def dmx_entries(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One entry per addressed device: manual ``dmx`` first, overlay ``dmx`` for the rest."""
    from .trace import doc_devices

    ov = (overlay or {}).get("dmx") or {}
    out: List[Dict[str, Any]] = []
    for d in doc_devices(doc, overlay):
        manual = d.get("dmx") if isinstance(d.get("dmx"), dict) else None
        src = "manual"
        data = manual if manual and (manual.get("universe") is not None or manual.get("address") is not None) else None
        if data is None and isinstance(ov.get(d["id"]), dict):
            data, src = ov[d["id"]], str(ov[d["id"]].get("source") or "import")
        if data is None:
            continue
        if d.get("auto") and d.get("source"):
            src = str(d["source"]) if src == "manual" else src
        fp = _int(data.get("footprint"))
        if fp is None and manual:
            fp = _int(manual.get("footprint"))
        if fp is None:
            fp = _template_footprint(doc, d.get("template") or "")
        out.append({"device": d, "universe": _int(data.get("universe")), "address": _int(data.get("address")), "footprint": fp,
                    "mode": data.get("mode") or "", "channel": str(data.get("channel") or ""), "protocol": data.get("protocol") or "dmx",
                    "port": data.get("port") or "", "source": src})
    return out


def _problem(code: str, dev_id: str, message: str) -> Dict[str, Any]:
    return {"level": "warning", "code": code, "ref": f"devices/{dev_id}", "path": f"devices/{dev_id}/dmx", "message": message}


def dmx_problems(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """``dmx_range`` / ``dmx_footprint_unknown`` / ``dmx_overflow`` / ``dmx_overlap`` warnings."""
    out: List[Dict[str, Any]] = []
    entries = dmx_entries(doc, overlay)
    for e in entries:
        d, u, a, fp = e["device"], e["universe"], e["address"], e["footprint"]
        name = d.get("name") or d["id"]
        bad = []
        if u is None or not 1 <= u <= 63999:
            bad.append(f"universe {u}")
        if a is None or not 1 <= a <= 512:
            bad.append(f"address {a}")
        if fp is not None and not 1 <= fp <= 512:
            bad.append(f"footprint {fp}")
        if bad:
            out.append(_problem("dmx_range", d["id"], f"{name} ({d['id']}): {', '.join(bad)} out of range."))
            continue
        if fp is None:
            out.append(_problem("dmx_footprint_unknown", d["id"], f"{name} ({d['id']}): DMX footprint unknown; set it on the device or template."))
        elif a + fp - 1 > 512:
            out.append(_problem("dmx_overflow", d["id"], f"{name} ({d['id']}): {u}/{a}–{a + fp - 1} runs past channel 512."))
    valid = [e for e in entries if e["universe"] and e["address"] and 1 <= e["address"] <= 512 and 1 <= e["universe"] <= 63999]
    by_u: Dict[int, List[Dict[str, Any]]] = {}
    for e in valid:
        by_u.setdefault(e["universe"], []).append(e)
    for u in sorted(by_u):
        rows = sorted(by_u[u], key=lambda e: (e["address"], e["device"]["id"]))
        for i, x in enumerate(rows):
            xe = x["address"] + (x["footprint"] or 1) - 1
            for y in rows[i + 1:]:
                if y["address"] > xe:
                    break
                ye = y["address"] + (y["footprint"] or 1) - 1
                xn, yn = x["device"].get("name") or x["device"]["id"], y["device"].get("name") or y["device"]["id"]
                out.append(_problem("dmx_overlap", y["device"]["id"],
                                    f"{yn} ({y['device']['id']}) {u}/{y['address']}–{ye} overlaps {xn} ({x['device']['id']}) {u}/{x['address']}–{xe}."))
    return out


def dmx_schedule(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*") -> Dict[str, Any]:
    """DMX schedule per universe sorted by address (§5.8.2 ``dmx`` columns)."""
    rooms = {r.get("id"): r.get("name") or r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict)}
    rows: List[Dict[str, Any]] = []
    for e in dmx_entries(doc, overlay):
        d = e["device"]
        if room not in ("*", None) and (d.get("room") or "") != room:
            continue
        u, a, fp = e["universe"], e["address"], e["footprint"]
        valid_u = u is not None and 1 <= u <= 63999
        net = artnet_split(u) if valid_u else None
        rows.append({
            "universe": u, "address": a, "end": (a + fp - 1) if (a is not None and fp) else None, "footprint": fp,
            "device": d.get("name") or d["id"], "device_id": d["id"],
            "room": rooms.get(d.get("room"), d.get("room") or ""), "room_id": d.get("room") or "",
            "mode": e["mode"], "channel": e["channel"], "protocol": e["protocol"],
            "sacn_group": sacn_group(u) if valid_u else "", "artnet": f"{net[0]}:{net[1]}:{net[2]}" if net else "",
            "source": e["source"],
        })
    rows.sort(key=lambda r: (r["universe"] if r["universe"] is not None else 1 << 30, r["address"] if r["address"] is not None else 1 << 30, r["device_id"]))
    ids = {r["device_id"] for r in rows}
    problems = [p for p in dmx_problems(doc, overlay) if room in ("*", None) or p["ref"].split("/", 1)[1] in ids]
    return {"kind": "dmx", "columns": [dict(c) for c in DMX_COLUMNS], "rows": rows, "problems": problems}


__all__ = ["dmx_schedule", "dmx_problems", "dmx_entries", "sacn_group", "artnet_split"]
