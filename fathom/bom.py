"""Bill of materials (FR-PLN-03) and inventory schedule (FR-INV-04)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .vocab import MEDIA, kind_discipline

Doc = Dict[str, Any]

BOM_COLUMNS: List[Tuple[str, str]] = [
    ("category", "Category"), ("manufacturer", "Manufacturer"), ("model", "Model"), ("template", "Template"), ("qty", "Qty"),
    ("unit_cost", "Unit cost"), ("extended", "Extended"), ("currency", "Currency"), ("planned", "Planned"),
    ("installed", "Installed"), ("spare", "Spare"), ("retired", "Retired"), ("length_total_m", "Total length (m)"),
]
INVENTORY_KEYS = (
    "id", "name", "room", "location", "kind", "discipline", "manufacturer", "model", "status", "serial", "asset_tag", "firmware",
    "purchase_date", "warranty_until", "vendor", "cost", "currency", "po", "rack", "ru", "ips", "notes",
)
_STATUSES = ("planned", "installed", "spare", "retired")


def _included(status: str, state: str) -> bool:
    status = status or "installed"
    if status == "spare":
        return True  # spares always count in BOM / inventory
    if state == "everything":
        return True
    if status == "retired":
        return False
    if state == "as_built":
        return status == "installed"
    return True


def _template_cost(tid: str, doc: Doc) -> Optional[float]:
    if not tid:
        return None
    try:
        from .library import get_template

        t = get_template(tid, doc)
    except Exception:
        t = None
    c = (t or {}).get("cost")
    return float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None


def _room_ok(dev_room: str, room: str) -> bool:
    return room in ("*", None) or (dev_room or "") == room


def bom(doc: Doc, state: str = "all", room: str = "*") -> Dict[str, Any]:
    currency0 = str((doc.get("settings") or {}).get("currency") or "USD")
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    tcost_cache: Dict[str, Optional[float]] = {}
    kept: set = set()
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or d.get("auto"):
            continue
        status = d.get("status") or "installed"
        if not _included(status, state) or not _room_ok(d.get("room", ""), room):
            continue
        kept.add(d.get("id"))
        n = int(d.get("count") or 1)
        inv = d.get("inventory") or {}
        tid = d.get("template") or ""
        if isinstance(inv.get("cost"), (int, float)) and not isinstance(inv.get("cost"), bool):
            unit = float(inv["cost"])
        else:
            if tid not in tcost_cache:
                tcost_cache[tid] = _template_cost(tid, doc)
            unit = tcost_cache[tid] or 0.0
        cur = str(inv.get("currency") or currency0)
        if tid:
            key = ("t:" + tid, cur)
        elif d.get("manufacturer") or d.get("model"):
            key = ("m:" + f"{d.get('manufacturer', '')}\x1f{d.get('model', '')}".lower(), cur)
        else:
            key = ("k:" + str(d.get("kind", "other")), cur)
        g = groups.get(key)
        if g is None:
            g = {
                "category": d.get("discipline") or kind_discipline(d.get("kind", "")),
                "manufacturer": d.get("manufacturer", ""), "model": d.get("model", "") or ("" if tid or d.get("manufacturer") else d.get("kind", "")),
                "template": tid, "qty": 0, "unit_cost": None, "extended": 0.0, "currency": cur,
                "planned": 0, "installed": 0, "spare": 0, "retired": 0, "length_total_m": "", "devices": [], "_units": set(),
            }
            groups[key] = g
            order.append(key)
        g["qty"] += n
        g["extended"] += unit * n
        g["_units"].add(round(unit, 6))
        g[status if status in _STATUSES else "installed"] += n
        g["devices"].append(d.get("id"))
    rows: List[Dict[str, Any]] = []
    for key in order:
        g = groups[key]
        units = g.pop("_units")
        g["extended"] = round(g["extended"], 2)
        g["unit_cost"] = round(g["extended"] / g["qty"], 2) if len(units) == 1 and g["qty"] else None
        rows.append(g)
    rows.sort(key=lambda r: (str(r["category"]), str(r["manufacturer"]).lower(), str(r["model"]).lower(), str(r["template"])))
    cab: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for c in doc.get("cables") or []:
        if not isinstance(c, dict) or c.get("auto"):
            continue
        st = c.get("status") or "installed"
        if not _included(st, state) or st == "spare" and state not in ("all", "everything"):
            continue
        a, b = (c.get("from") or {}).get("device"), (c.get("to") or {}).get("device")
        if a not in kept and b not in kept:
            continue
        medium = c.get("medium") or "other"
        typ = c.get("type") or ""
        k = (medium, typ)
        line = cab.get(k)
        if line is None:
            label = (MEDIA.get(medium) or {}).get("label", medium)
            line = {
                "category": "cable", "manufacturer": "", "model": f"{label} · {typ}" if typ else label, "template": "",
                "qty": 0, "unit_cost": None, "extended": 0.0, "currency": currency0,
                "planned": 0, "installed": 0, "spare": 0, "retired": 0, "length_total_m": 0.0, "medium": medium, "type": typ,
            }
            cab[k] = line
        line["qty"] += 1
        line[st if st in _STATUSES else "installed"] += 1
        if isinstance(c.get("length_m"), (int, float)):
            line["length_total_m"] = round(line["length_total_m"] + float(c["length_m"]), 2)
    rows += [cab[k] for k in sorted(cab)]
    totals: Dict[str, float] = {}
    for r in rows:
        if r["category"] != "cable":
            totals[r["currency"]] = round(totals.get(r["currency"], 0.0) + r["extended"], 2)
    if not totals:
        totals[currency0] = 0.0
    return {"kind": "bom", "columns": [{"key": k, "label": lab} for k, lab in BOM_COLUMNS], "rows": rows, "totals": totals, "problems": []}


def inventory_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]:
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    locs = {r.get("id"): r for r in doc.get("locations") or [] if isinstance(r, dict)}
    racks = {r.get("id"): r for r in doc.get("racks") or [] if isinstance(r, dict)}
    cur0 = str((doc.get("settings") or {}).get("currency") or "USD")
    rows = []
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or d.get("auto") or not _room_ok(d.get("room", ""), room):
            continue
        inv = d.get("inventory") or {}
        rk = d.get("rack") or {}
        ips = [str(i.get("ip")) for i in d.get("interfaces") or [] if isinstance(i, dict) and i.get("ip")]
        rows.append({
            "id": d.get("id", ""), "name": d.get("name", ""),
            "room": (rooms.get(d.get("room")) or {}).get("name", d.get("room", "")), "room_id": d.get("room", ""),
            "location": (locs.get(d.get("location")) or {}).get("name", d.get("location", "")), "location_id": d.get("location", ""),
            "kind": d.get("kind", ""), "discipline": d.get("discipline") or kind_discipline(d.get("kind", "")),
            "manufacturer": d.get("manufacturer", ""), "model": d.get("model", ""), "status": d.get("status", "installed"),
            "serial": inv.get("serial", ""), "asset_tag": inv.get("asset_tag", ""), "firmware": inv.get("firmware", ""),
            "purchase_date": inv.get("purchase_date", ""), "warranty_until": inv.get("warranty_until", ""),
            "vendor": inv.get("vendor", ""), "cost": inv.get("cost", ""), "currency": inv.get("currency") or (cur0 if inv.get("cost") is not None else ""),
            "po": inv.get("po", ""), "rack": (racks.get(rk.get("id")) or {}).get("name", rk.get("id", "")), "rack_id": rk.get("id", ""),
            "ru": rk.get("u", ""), "ips": ";".join(ips), "notes": inv.get("notes", "") or d.get("note", ""),
        })
    return {"kind": "inventory", "columns": [{"key": k, "label": k} for k in INVENTORY_KEYS], "rows": rows, "problems": []}


__all__ = ["bom", "inventory_schedule", "BOM_COLUMNS", "INVENTORY_KEYS"]
