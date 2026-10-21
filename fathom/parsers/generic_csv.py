"""Generic device / cable CSV, one-shot (``preview`` returns ops, never writes).

Detected by headers (§5.7.4): a devices CSV has a ``name`` column (device,
device name, label) and no ``from_device`` column; a cables CSV has
``from_device`` and ``to_device`` (from/source device/start device,
to/destination device/end device). The cable schedule CSV (``fathom schedule
cables --csv``) re-imports through the same path (FR-CAB-06).

Rows match existing entities by ``id``; else devices by normalised name and
cables by ``tag``. Matched rows become ``merge`` ops with only the cells that
change something; new rows become ``put`` ops.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import ParseResult, check_size, header_map, norm_header, read_rows

DEVICE_COLS: Dict[str, Tuple[str, ...]] = {
    "id": (),
    "name": ("device", "device name", "label"),
    "kind": ("type", "category"),
    "manufacturer": ("make", "brand"),
    "model": (),
    "template": (),
    "room": (),
    "location": (),
    "system": (),
    "status": (),
    "code": (),
    "serial": ("serial number",),
    "asset_tag": ("asset", "asset tag"),
    "firmware": (),
    "purchase_date": (),
    "warranty_until": ("warranty",),
    "vendor": (),
    "cost": ("price", "unit cost"),
    "ip": ("ip address", "primary ip"),
    "mac": (),
    "vlan": (),
    "hostname": (),
    "rack": (),
    "ru": ("u", "rack unit"),
    "height": ("ru height", "size"),
    "face": (),
    "universe": (),
    "address": ("dmx address",),
    "footprint": (),
    "dmx_channel": ("channel",),
    "notes": ("note", "comments"),
}

CABLE_COLS: Dict[str, Tuple[str, ...]] = {
    "id": (),
    "tag": ("cable id", "cable", "label"),
    "from_device": ("from", "source device", "start device"),
    "from_port": ("from port", "source port"),
    "to_device": ("to", "destination device", "end device"),
    "to_port": ("to port", "destination port"),
    "medium": ("signal type",),
    "type": ("cable type", "product"),
    "length": ("len",),
    "length_unit": ("unit",),
    "color": ("colour",),
    "channels": (),
    "signal": (),
    "status": (),
    "note": ("notes",),
    "from_room": ("from room",),
    "to_room": ("to room",),
    "bundle": (),
}

UNIT_M = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0, "ft": 0.3048, "feet": 0.3048, "foot": 0.3048, "'": 0.3048, "in": 0.0254, "inch": 0.0254, "inches": 0.0254, '"': 0.0254, "cm": 0.01, "mm": 0.001}


class CsvTable(ParseResult):
    kind = "csv"

    def __init__(self) -> None:
        super().__init__()
        self.table = ""  # devices | cables | ""
        self.columns: Dict[str, int] = {}
        self.header: List[str] = []
        self.rows: List[Dict[str, str]] = []

    def summary(self) -> Dict[str, object]:
        return {"kind": self.kind, "table": self.table, "rows": len(self.rows), "columns": sorted(self.columns), "notes": list(self.notes)}


def _has(cells: List[str], key: str, syns: Tuple[str, ...]) -> bool:
    return any(norm_header(c) in cells for c in (key,) + syns)


def classify_header(header: List[str]) -> str:
    cells = [norm_header(c) for c in header]
    if _has(cells, "from_device", CABLE_COLS["from_device"]) and _has(cells, "to_device", CABLE_COLS["to_device"]):
        return "cables"
    if _has(cells, "name", DEVICE_COLS["name"]):
        return "devices"
    return ""


def parse_csv(path: Path, **_opts: Any) -> CsvTable:
    res = CsvTable()
    check_size(path)
    res.source_files.append(str(path))
    rows = read_rows(path)
    for i, r in enumerate(rows[:5]):
        t = classify_header(r)
        if t:
            res.table, res.header = t, r
            res.columns = header_map(r, CABLE_COLS if t == "cables" else DEVICE_COLS)
            for data in rows[i + 1:]:
                res.rows.append({k: (data[j].strip() if j < len(data) else "") for k, j in res.columns.items()})
            break
    if not res.table:
        res.note("no header row with a device name column or from/to device columns")
    return res


def detect(path: Path) -> float:
    if path.is_dir() or path.suffix.lower() not in (".csv", ".tsv", ".txt"):
        return 0.0
    try:
        first = path.read_bytes()[:4000].decode("utf-8-sig", errors="ignore").splitlines()[:3]
    except OSError:
        return 0.0
    for line in first:
        cells = [c.strip().strip('"') for c in re.split(r"[,;\t]", line)]
        t = classify_header(cells)
        if t == "cables":
            return 0.7
        if t == "devices":
            # a plain "Name" column is weak evidence; console channel lists have one too
            strong = {"kind", "manufacturer", "model", "room", "serial", "ip", "template", "status", "rack"}
            hits = sum(1 for c in cells if norm_header(c).replace(" ", "_") in strong)
            return 0.7 if hits >= 2 else 0.2
    return 0.0


# --------------------------------------------------------------- helpers


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-") or "item"


def _num(s: str) -> Optional[float]:
    try:
        return float((s or "").replace(",", ".").strip())
    except ValueError:
        return None


def _intv(s: str) -> Optional[int]:
    m = re.match(r"^\s*-?\d+\s*$", s or "")
    return int(s) if m else None


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{h}"


def _diff(cur: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Keys of ``new`` whose value differs from ``cur`` (objects compared recursively)."""
    out: Dict[str, Any] = {}
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(cur.get(k), dict):
            sub = _diff(cur[k], v)
            if sub:
                out[k] = sub
        elif isinstance(v, float) and isinstance(cur.get(k), (int, float)) and not isinstance(cur.get(k), bool):
            if abs(float(cur[k]) - v) > 1e-6:
                out[k] = v
        elif cur.get(k) != v:
            out[k] = v
    return out


class _Lookup:
    def __init__(self, doc: Dict[str, Any]) -> None:
        self.doc = doc
        self.devices = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
        self.by_id = {d.get("id"): d for d in self.devices}
        self.by_name: Dict[str, Dict[str, Any]] = {}
        for d in self.devices:
            self.by_name.setdefault(_norm(d.get("name", "")), d)
            for a in d.get("aliases") or []:
                self.by_name.setdefault(_norm(a), d)
        self.rooms = {r.get("id"): r for r in doc.get("rooms") or []}
        self.room_names = {_norm(r.get("name", "")): r.get("id") for r in doc.get("rooms") or []}
        self.racks = doc.get("racks") or []

    def device(self, text: str) -> Optional[Dict[str, Any]]:
        t = (text or "").strip()
        if not t:
            return None
        return self.by_id.get(t) or self.by_name.get(_norm(t))

    def room(self, text: str) -> str:
        t = (text or "").strip()
        if t in self.rooms:
            return t
        return self.room_names.get(_norm(t), t)

    def rack(self, text: str) -> str:
        t = (text or "").strip()
        for r in self.racks:
            if r.get("id") == t or _norm(r.get("name", "")) == _norm(t):
                return str(r.get("id"))
        return ""


def _find_port(dev: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return None
    ports = dev.get("ports") or []
    for p in ports:
        if p.get("id") == t:
            return p
    key = _norm(t)
    for field in ("label", "name"):
        for p in ports:
            if _norm(p.get(field, "")) == key:
                return p
    for p in ports:
        if _slug(t) == p.get("id"):
            return p
    return None


# --------------------------------------------------------------- devices


def _device_values(row: Dict[str, str], lk: _Lookup, existing: Optional[Dict[str, Any]], warnings: List[str], rown: int) -> Dict[str, Any]:
    v: Dict[str, Any] = {}
    for k in ("name", "kind", "manufacturer", "model", "template", "location", "system", "status", "code"):
        if row.get(k):
            v[k] = row[k]
    if row.get("room"):
        v["room"] = lk.room(row["room"])
    if row.get("notes"):
        v["note"] = row["notes"]
    inv: Dict[str, Any] = {}
    for k in ("serial", "asset_tag", "firmware", "purchase_date", "warranty_until", "vendor"):
        if row.get(k):
            inv[k] = row[k]
    if row.get("cost"):
        c = _num(row["cost"].replace("$", ""))
        if c is not None:
            inv["cost"] = c
    if inv:
        v["inventory"] = inv
    iface: Dict[str, Any] = {}
    for k in ("ip", "mac", "hostname"):
        if row.get(k):
            iface[k] = row[k]
    if row.get("vlan") and _intv(row["vlan"]) is not None:
        iface["vlan"] = int(row["vlan"])
    if iface:
        cur = copy.deepcopy((existing or {}).get("interfaces") or [])
        prim = next((i for i in cur if i.get("id") == "primary"), None)
        if prim is None:
            prim = {"id": "primary", "role": "primary"}
            cur.insert(0, prim)
        changed = any(prim.get(k) != val for k, val in iface.items())
        prim.update(iface)
        if changed:
            v["interfaces"] = cur
    if row.get("rack"):
        rid = lk.rack(row["rack"])
        if not rid:
            warnings.append(f"row {rown}: rack '{row['rack']}' not found")
        else:
            rk: Dict[str, Any] = {"id": rid}
            if _intv(row.get("ru", "")) is not None:
                rk["u"] = int(row["ru"])
            if _intv(row.get("height", "")) is not None:
                rk["height"] = int(row["height"])
            if row.get("face"):
                rk["face"] = row["face"].lower()
            v["rack"] = rk
    dmx: Dict[str, Any] = {}
    for k in ("universe", "address", "footprint"):
        if _intv(row.get(k, "")) is not None:
            dmx[k] = int(row[k])
    if row.get("dmx_channel"):
        dmx["channel"] = row["dmx_channel"]
    if dmx:
        v["dmx"] = dmx
    return v


def _preview_devices(res: CsvTable, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    lk = _Lookup(doc)
    ops: List[Dict[str, Any]] = []
    warnings: List[str] = []
    summary = {"create": 0, "update": 0, "skip": 0}
    new_ids = set(lk.by_id)
    default_room = ctx.get("room") or ""
    for n, row in enumerate(res.rows, start=2):
        name = row.get("name", "").strip()
        existing = lk.by_id.get(row.get("id", "").strip()) if row.get("id") else None
        if existing is None and name:
            existing = lk.by_name.get(_norm(name))
        if not name and existing is None:
            summary["skip"] += 1
            continue
        vals = _device_values(row, lk, existing, warnings, n)
        if existing is not None:
            change = _diff(existing, vals)
            if change.get("status") == "installed" and not existing.get("status"):
                del change["status"]
            if change:
                ops.append({"op": "merge", "coll": "devices", "id": existing["id"], "value": change})
                summary["update"] += 1
            else:
                summary["skip"] += 1
            continue
        did = row.get("id", "").strip() or _slug(name)
        base, i = did, 2
        while did in new_ids:
            did = f"{base}-{i}"
            i += 1
        new_ids.add(did)
        dev: Dict[str, Any] = {}
        tid = vals.get("template", "")
        if tid:
            try:
                from ..library import get_template, instantiate

                t = get_template(tid, doc)
                if t:
                    dev = instantiate(t, device_id=did, name=name, room=vals.get("room", default_room))
                else:
                    warnings.append(f"row {n}: template '{tid}' not found")
            except Exception as exc:  # pragma: no cover
                warnings.append(f"row {n}: template '{tid}': {exc}")
        if not dev:
            dev = {"id": did, "name": name, "kind": vals.get("kind") or "other", "room": default_room, "ports": []}
        for k, val in vals.items():
            dev[k] = val
        dev["id"] = did
        dev.setdefault("ports", [])
        ops.append({"op": "put", "coll": "devices", "id": did, "value": dev})
        lk.by_name.setdefault(_norm(name), dev)
        summary["create"] += 1
    return {"ops": ops, "summary": summary, "warnings": warnings}


# ---------------------------------------------------------------- cables


def _length_m(row: Dict[str, str], warnings: List[str], n: int) -> Optional[float]:
    raw = (row.get("length") or "").strip()
    if not raw:
        return None
    m = re.match(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([a-zA-Z'\"]*)\s*$", raw)
    if not m:
        warnings.append(f"row {n}: length '{raw}' not understood")
        return None
    val = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or row.get("length_unit") or "m").strip().lower()
    factor = UNIT_M.get(unit)
    if factor is None:
        warnings.append(f"row {n}: unit '{unit}' not understood (m, ft, in, cm)")
        return None
    return round(val * factor, 4)


def _medium_key(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    try:
        from ..vocab import MEDIA
    except Exception:  # pragma: no cover
        return t
    if t in MEDIA:
        return t
    low = t.lower()
    for k, m in MEDIA.items():
        if low in (m["label"].lower(), m["short"].lower()):
            return k
    return low


def _preview_cables(res: CsvTable, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    lk = _Lookup(doc)
    cables = [c for c in doc.get("cables") or [] if isinstance(c, dict)]
    by_id = {c.get("id"): c for c in cables}
    by_tag = {c.get("tag"): c for c in cables if c.get("tag")}
    ops: List[Dict[str, Any]] = []
    warnings: List[str] = []
    summary = {"create": 0, "update": 0, "skip": 0}
    port_adds: Dict[str, List[Dict[str, Any]]] = {}
    used_ids = set(by_id)
    for n, row in enumerate(res.rows, start=2):
        cur = by_id.get(row.get("id", "").strip()) if row.get("id") else None
        if cur is None and row.get("tag"):
            cur = by_tag.get(row["tag"].strip())
        vals: Dict[str, Any] = {}
        for k in ("tag", "type", "color", "signal", "status"):
            if row.get(k):
                vals[k] = row[k].strip()
        if row.get("note"):
            vals["note"] = row["note"]
        if _intv(row.get("channels", "")) is not None:
            vals["channels"] = int(row["channels"])
        ln = _length_m(row, warnings, n)
        if ln is not None:
            vals["length_m"] = ln
        if cur is not None:
            change = _diff(cur, vals)
            if change.get("status") == "installed" and not cur.get("status"):
                del change["status"]  # installed is the default
            old_len = cur.get("length_m")
            if "length_m" in change and isinstance(old_len, (int, float)) and abs(float(old_len) - change["length_m"]) < 0.006:
                del change["length_m"]  # schedule CSVs round lengths (0.01 ft / 0.01 m)
            if change:
                ops.append({"op": "merge", "coll": "cables", "id": cur["id"], "value": change})
                summary["update"] += 1
            else:
                summary["skip"] += 1
            continue
        fd, td = lk.device(row.get("from_device", "")), lk.device(row.get("to_device", ""))
        if fd is None or td is None:
            missing = row.get("from_device") if fd is None else row.get("to_device")
            warnings.append(f"row {n}: device '{missing}' not found; row skipped")
            summary["skip"] += 1
            continue
        medium = _medium_key(row.get("medium", ""))
        ends = []
        for dev, ptext, side in ((fd, row.get("from_port", ""), "out"), (td, row.get("to_port", ""), "in")):
            ep: Dict[str, Any] = {"device": dev["id"]}
            if ptext.strip():
                p = _find_port(dev, ptext)
                if p is None:
                    p = next((q for q in port_adds.get(dev["id"], []) if q["name"] == ptext.strip()), None)
                if p is None:
                    taken = {q.get("id") for q in dev.get("ports") or []} | {q["id"] for q in port_adds.get(dev["id"], [])}
                    pid, base, i = _slug(ptext), _slug(ptext), 2
                    while pid in taken:
                        pid = f"{base}-{i}"
                        i += 1
                    p = {"id": pid, "name": ptext.strip(), "dir": side, "medium": medium or "other", "origin": "user"}
                    port_adds.setdefault(dev["id"], []).append(p)
                ep["port"] = p["id"]
                if not medium:
                    medium = p.get("medium") or ""
            ends.append(ep)
        cid = row.get("id", "").strip() or _stable_id("c-", str(n), row.get("tag", ""), ends[0]["device"], ends[0].get("port", ""), ends[1]["device"], ends[1].get("port", ""))
        while cid in used_ids:
            cid = _stable_id("c-", cid, str(n))
        used_ids.add(cid)
        cab = {"id": cid, "from": ends[0], "to": ends[1], "medium": medium or "analog"}
        cab.update(vals)
        ops.append({"op": "put", "coll": "cables", "id": cid, "value": cab})
        summary["create"] += 1
    port_ops = []
    for dev_id, adds in sorted(port_adds.items()):
        dev = lk.by_id[dev_id]
        port_ops.append({"op": "merge", "coll": "devices", "id": dev_id, "value": {"ports": copy.deepcopy(dev.get("ports") or []) + adds}})
        warnings.append(f"{dev.get('name', dev_id)}: {len(adds)} new port(s) created ({', '.join(a['name'] for a in adds)})")
    return {"ops": port_ops + ops, "summary": summary, "warnings": warnings}


def preview(result: CsvTable, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if result.table == "devices":
        return _preview_devices(result, doc, ctx or {})
    if result.table == "cables":
        return _preview_cables(result, doc, ctx or {})
    return {"ops": [], "summary": {"create": 0, "update": 0, "skip": len(result.rows)}, "warnings": list(result.notes) or ["not a device or cable CSV"]}
