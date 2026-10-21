"""Generic device / cable CSV, one-shot (``preview`` returns ops, never writes).

Detected by headers (§5.7.4): a devices CSV has a ``name`` column (device,
device name, label) and no ``from_device`` column; a cables CSV has
``from_device`` and ``to_device`` (from/source device/start device,
to/destination device/end device). The cable schedule CSV (``fathom schedule
cables --csv``) re-imports through the same path (FR-CAB-06).

Rows match existing entities by ``id``; else devices by normalised name and
cables by ``tag``. Matched rows become ``merge`` ops with only the cells that
change something; new rows become ``put`` ops.

Every row is validated first (kind, status, medium, IP / MAC / VLAN, DMX
range, dates, numbers, rooms, duplicates). A row with a problem is skipped
and reported in ``errors`` as ``{"row", "column", "value", "message"}``
(``row`` is the spreadsheet row number); the other rows still preview.
:func:`template_csv` writes an editable example file per table that
re-imports cleanly (``TEMPLATES`` documents its columns).
"""

from __future__ import annotations

import copy
import csv
import difflib
import hashlib
import io
import ipaddress
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import ParseResult, check_size, header_map, norm_header, read_text, sniff_delimiter

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
        self.lines: List[int] = []  # spreadsheet row number of each entry in ``rows``
        self.extra_cells: List[int] = []  # rows with more cells than the header

    def summary(self) -> Dict[str, object]:
        return {"kind": self.kind, "table": self.table, "rows": len(self.rows), "columns": sorted(self.columns), "notes": list(self.notes)}

    def column_label(self, key: str) -> str:
        """The header text the user wrote for canonical column ``key``."""
        i = self.columns.get(key)
        return self.header[i] if i is not None and i < len(self.header) else key


def _has(cells: List[str], key: str, syns: Tuple[str, ...]) -> bool:
    return any(norm_header(c) in cells for c in (key,) + syns)


def classify_header(header: List[str]) -> str:
    cells = [norm_header(c) for c in header]
    if _has(cells, "from_device", CABLE_COLS["from_device"]) and _has(cells, "to_device", CABLE_COLS["to_device"]):
        return "cables"
    if _has(cells, "name", DEVICE_COLS["name"]):
        return "devices"
    return ""


def _numbered_rows(path: Path) -> List[Tuple[int, List[str]]]:
    """Non-blank rows with the spreadsheet row number each one starts on."""
    text = read_text(path)
    reader = csv.reader(io.StringIO(text), delimiter=sniff_delimiter(text))
    out: List[Tuple[int, List[str]]] = []
    start = 1
    for row in reader:
        cells = [c.strip() for c in row]
        if any(cells):
            out.append((start, cells))
        start = reader.line_num + 1
    return out


def parse_csv(path: Path, **_opts: Any) -> CsvTable:
    res = CsvTable()
    check_size(path)
    res.source_files.append(str(path))
    rows = _numbered_rows(path)
    for i, (_, r) in enumerate(rows[:5]):
        t = classify_header(r)
        if t:
            res.table, res.header = t, r
            spec = CABLE_COLS if t == "cables" else DEVICE_COLS
            res.columns = header_map(r, spec)
            known = {norm_header(c) for k, syns in spec.items() for c in (k,) + syns}
            unknown = [c for c in r if c and norm_header(c) not in known]
            if unknown:
                res.note(f"column(s) not recognised and ignored: {', '.join(unknown)}")
            width = len(r)
            for line, data in rows[i + 1:]:
                res.rows.append({k: (data[j].strip() if j < len(data) else "") for k, j in res.columns.items()})
                res.lines.append(line)
                if len(data) > width and any(data[width:]):
                    res.extra_cells.append(line)
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


# ------------------------------------------------------------ validation

_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}|[0-9A-Fa-f]{12})$")
_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _vocab() -> Tuple[Dict[str, Any], Dict[str, Any], Tuple[str, ...]]:
    from ..vocab import KINDS, MEDIA, STATUSES

    return KINDS, MEDIA, STATUSES


def kind_key(text: str) -> str:
    """``'Video switcher'`` / ``'video-switcher'`` → ``'video_switcher'`` when that is a known kind, else ``''``."""
    kinds = _vocab()[0]
    t = (text or "").strip()
    if t in kinds:
        return t
    k = re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")
    if k in kinds:
        return k
    for key, meta in kinds.items():
        if _norm(meta.get("label", "")) in (_norm(t), _norm(t) + "s"):
            return key
    return ""


def _unknown(what: str, value: str, choices: List[str]) -> str:
    """``unknown kind; did you mean 'switch'?`` or, with no close match, the full list."""
    low = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    hits = [w for w in reversed(low.split("_")) if w in choices]
    hits += [h for h in difflib.get_close_matches(low, choices, n=2, cutoff=0.6) if h not in hits]
    if hits:
        return f"unknown {what}; did you mean {' or '.join(repr(h) for h in hits[:2])}?"
    return f"unknown {what}; use one of " + ", ".join(choices)


def _rows(res: CsvTable) -> List[Tuple[int, Dict[str, str]]]:
    lines = res.lines if len(res.lines) == len(res.rows) else list(range(2, len(res.rows) + 2))
    return list(zip(lines, res.rows))


class _Errors:
    """Collects ``{"row", "column", "value", "message"}`` problems for one table."""

    def __init__(self, res: CsvTable) -> None:
        self.res = res
        self.items: List[Dict[str, Any]] = []

    def add(self, row: int, key: str, value: str, message: str) -> None:
        self.items.append({"row": row, "column": self.res.column_label(key) if key else "", "value": value, "message": message})

    def has(self, row: int) -> bool:
        return any(e["row"] == row for e in self.items)

    def as_warnings(self) -> List[str]:
        out = []
        for e in self.items:
            where = f"row {e['row']}" + (f", {e['column']}" if e["column"] else "")
            out.append(f"{where}: {e['message']}")
        return out


def _int_in(row: Dict[str, str], key: str, lo: int, hi: Optional[int], n: int, errs: _Errors, what: str) -> Optional[int]:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    v = _intv(raw)
    if v is None or v < lo or (hi is not None and v > hi):
        rng = f"{lo}–{hi}" if hi is not None else f"{lo} or more"
        errs.add(n, key, raw, f"{what} must be a whole number {rng}")
        return None
    return v


def _validate_device(row: Dict[str, str], n: int, lk: "_Lookup", errs: _Errors, seen: Dict[str, int]) -> None:
    kinds, _media, statuses = _vocab()
    name = (row.get("name") or "").strip()
    if not name and not (row.get("id") and row["id"].strip() in lk.by_id):
        errs.add(n, "name", "", "name is required (every device needs one)")
    elif name:
        key = _norm(name)
        if key in seen:
            errs.add(n, "name", name, f"duplicate of row {seen[key]}; each device name may appear once")
        else:
            seen[key] = n
    if row.get("kind") and not kind_key(row["kind"]):
        errs.add(n, "kind", row["kind"], _unknown("kind", row["kind"], sorted(kinds)))
    if row.get("status") and row["status"].strip().lower() not in statuses:
        errs.add(n, "status", row["status"], "status must be one of " + ", ".join(statuses))
    if row.get("room") and lk.rooms and lk.room(row["room"]) not in lk.rooms:
        names = ", ".join(str(r.get("name") or r.get("id")) for r in lk.rooms.values())
        errs.add(n, "room", row["room"], f"room not found; use a room id or name ({names})")
    if row.get("ip"):
        try:
            ipaddress.ip_address(row["ip"].strip())
        except ValueError:
            errs.add(n, "ip", row["ip"], "not a valid IP address (e.g. 192.168.1.20)")
    if row.get("mac") and not _MAC_RE.match(row["mac"].strip()):
        errs.add(n, "mac", row["mac"], "not a valid MAC address (e.g. 00:1D:C1:0A:2B:3C)")
    _int_in(row, "vlan", 1, 4094, n, errs, "VLAN")
    _int_in(row, "ru", 1, 60, n, errs, "rack unit")
    _int_in(row, "height", 1, 60, n, errs, "height (RU)")
    if row.get("face") and row["face"].strip().lower() not in ("front", "rear"):
        errs.add(n, "face", row["face"], "face must be front or rear")
    _int_in(row, "universe", 1, 63999, n, errs, "universe")
    addr = _int_in(row, "address", 1, 512, n, errs, "DMX address")
    fp = _int_in(row, "footprint", 1, 512, n, errs, "footprint")
    if addr is not None and fp is not None and addr + fp - 1 > 512:
        errs.add(n, "footprint", row["footprint"], f"address {addr} + {fp} channels runs past 512")
    if row.get("cost") and _num(row["cost"].replace("$", "").replace(" ", "")) is None:
        errs.add(n, "cost", row["cost"], "cost must be a number (e.g. 1299.00)")
    for k in ("purchase_date", "warranty_until"):
        if row.get(k) and not _DATE_RE.match(row[k].strip()):
            errs.add(n, k, row[k], "date must be YYYY-MM-DD")


def _validate_cable(row: Dict[str, str], n: int, existing: bool, errs: _Errors, seen: Dict[str, int]) -> None:
    _kinds, media, statuses = _vocab()
    if not existing:
        for k in ("from_device", "to_device"):
            if not (row.get(k) or "").strip():
                errs.add(n, k, "", f"{k.replace('_', ' ')} is required for a new cable")
    tag = (row.get("tag") or "").strip()
    if tag:
        if tag in seen:
            errs.add(n, "tag", tag, f"duplicate of row {seen[tag]}; each cable tag may appear once")
        else:
            seen[tag] = n
    if row.get("medium") and _medium_key(row["medium"]) not in media:
        errs.add(n, "medium", row["medium"], _unknown("medium", row["medium"], sorted(media)))
    if row.get("status") and row["status"].strip().lower() not in statuses:
        errs.add(n, "status", row["status"], "status must be one of " + ", ".join(statuses))
    _int_in(row, "channels", 1, None, n, errs, "channels")


# --------------------------------------------------------------- devices


def _device_values(row: Dict[str, str], lk: _Lookup, existing: Optional[Dict[str, Any]], warnings: List[str], rown: int) -> Dict[str, Any]:
    v: Dict[str, Any] = {}
    for k in ("name", "kind", "manufacturer", "model", "template", "location", "system", "status", "code"):
        if row.get(k):
            v[k] = row[k]
    if v.get("kind"):
        v["kind"] = kind_key(v["kind"]) or v["kind"]
    if v.get("status"):
        v["status"] = v["status"].strip().lower()
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
                rk["face"] = row["face"].strip().lower()
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
    errs = _Errors(res)
    seen: Dict[str, int] = {}
    for n, row in _rows(res):
        _validate_device(row, n, lk, errs, seen)
        if errs.has(n):
            summary["skip"] += 1
            continue
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
    return _result(res, ops, summary, warnings, errs)


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
    errs = _Errors(res)
    seen: Dict[str, int] = {}
    for n, row in _rows(res):
        cur = by_id.get(row.get("id", "").strip()) if row.get("id") else None
        if cur is None and row.get("tag"):
            cur = by_tag.get(row["tag"].strip())
        _validate_cable(row, n, cur is not None, errs, seen)
        len_problems: List[str] = []
        ln = _length_m(row, len_problems, n)
        for p in len_problems:
            errs.add(n, "length", row.get("length", ""), p.split(": ", 1)[-1])
        if cur is None and not errs.has(n):
            for k in ("from_device", "to_device"):
                if lk.device(row.get(k, "")) is None:
                    errs.add(n, k, row.get(k, ""), "device not found in the project; check the spelling or import the devices first")
        if errs.has(n):
            summary["skip"] += 1
            continue
        vals: Dict[str, Any] = {}
        for k in ("tag", "type", "color", "signal", "status"):
            if row.get(k):
                vals[k] = row[k].strip()
        if vals.get("status"):
            vals["status"] = vals["status"].lower()
        if row.get("note"):
            vals["note"] = row["note"]
        if _intv(row.get("channels", "")) is not None:
            vals["channels"] = int(row["channels"])
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
        if fd is None or td is None:  # pragma: no cover - reported as an error above
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
    return _result(res, port_ops + ops, summary, warnings, errs)


def _result(res: CsvTable, ops: List[Dict[str, Any]], summary: Dict[str, int], warnings: List[str], errs: _Errors) -> Dict[str, Any]:
    notes = list(res.notes) + [f"row {n}: more cells than header columns; the extra cells were ignored" for n in res.extra_cells]
    return {"ops": ops, "summary": summary, "warnings": notes + errs.as_warnings() + warnings, "errors": errs.items}


def preview(result: CsvTable, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if result.table == "devices":
        return _preview_devices(result, doc, ctx or {})
    if result.table == "cables":
        return _preview_cables(result, doc, ctx or {})
    return {"ops": [], "summary": {"create": 0, "update": 0, "skip": len(result.rows)}, "errors": [],
            "warnings": list(result.notes) or ["not a device or cable CSV"]}


# ------------------------------------------------------------- templates

#: column guide for the downloadable templates: (column, required, help)
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "devices": {
        "label": "Devices",
        "columns": [
            ("name", True, "Device name; an existing device with this name is updated, otherwise one is created"),
            ("kind", False, "Device kind; blank = other"),
            ("manufacturer", False, "e.g. Yamaha"),
            ("model", False, "e.g. CL5"),
            ("template", False, "Equipment library id (e.g. yamaha-cl5) to create the device with its real ports"),
            ("room", False, "Room id or name; blank = the room chosen on the import card"),
            ("status", False, "installed, planned, spare or retired"),
            ("serial", False, "Serial number"),
            ("asset_tag", False, "Asset tag"),
            ("ip", False, "IPv4 / IPv6 address of the primary interface"),
            ("mac", False, "00:1D:C1:0A:2B:3C, 00-1D-… or 001d.c10a.2b3c"),
            ("vlan", False, "1–4094"),
            ("hostname", False, ""),
            ("rack", False, "Rack id or name (must exist)"),
            ("ru", False, "Lowest rack unit, 1–60"),
            ("universe", False, "DMX universe (1 or more)"),
            ("address", False, "DMX start address, 1–512"),
            ("footprint", False, "DMX channels used; address + footprint − 1 must be ≤ 512"),
            ("dmx_channel", False, "Console channel / head number"),
            ("purchase_date", False, "YYYY-MM-DD"),
            ("cost", False, "Number, e.g. 1299.00"),
            ("notes", False, ""),
            ("id", False, "Leave blank for new devices; keep it to update an existing one"),
        ],
    },
    "cables": {
        "label": "Cables",
        "columns": [
            ("tag", False, "Cable label; an existing cable with this tag is updated"),
            ("from_device", True, "Device name or id the cable starts at"),
            ("from_port", False, "Port name or id; created on the device when missing"),
            ("to_device", True, "Device name or id the cable ends at"),
            ("to_port", False, "Port name or id; created on the device when missing"),
            ("medium", False, "Signal type; blank = taken from the port"),
            ("type", False, "Cable product, e.g. Cat6A"),
            ("length", False, "Number, optionally with a unit (10, 3.5 m, 25ft)"),
            ("length_unit", False, "m (default), ft, in or cm"),
            ("color", False, ""),
            ("signal", False, ""),
            ("status", False, "installed, planned, spare or retired"),
            ("note", False, ""),
            ("id", False, "Leave blank for new cables"),
        ],
    },
}


def _allowed(key: str) -> List[str]:
    kinds, media, statuses = _vocab()
    return {"kind": sorted(kinds), "medium": sorted(media), "status": list(statuses), "face": ["front", "rear"],
            "length_unit": ["m", "ft", "in", "cm"]}.get(key, [])


def template_info() -> List[Dict[str, Any]]:
    """Template metadata for ``/api/v2/meta``: name, label, columns (key, required, help, allowed values)."""
    out = []
    for name, spec in TEMPLATES.items():
        cols = []
        for c, req, hlp in spec["columns"]:
            col: Dict[str, Any] = {"key": c, "required": req, "help": hlp}
            if _allowed(c):
                col["allowed"] = _allowed(c)
            cols.append(col)
        out.append({"name": name, "label": spec["label"], "columns": cols})
    return out


def _room_name(doc: Optional[Dict[str, Any]]) -> str:
    rooms = [r for r in (doc or {}).get("rooms") or [] if isinstance(r, dict)]
    want = ((doc or {}).get("settings") or {}).get("default_room")
    room = next((r for r in rooms if r.get("id") == want), rooms[0] if rooms else None)
    return str(room.get("name") or room.get("id")) if room else ""


def template_csv(table: str, doc: Optional[Dict[str, Any]] = None) -> str:
    """An example CSV for ``table`` (devices | cables) that previews without errors.

    The cables example connects the devices of the devices example, so
    importing both in order yields a working pair.
    """
    if table not in TEMPLATES:
        raise KeyError(table)
    cols = [c for c, _, _ in TEMPLATES[table]["columns"]]
    room = _room_name(doc)
    if table == "devices":
        examples = [
            {"name": "FOH Console", "kind": "console", "manufacturer": "Yamaha", "model": "CL5", "template": "yamaha-cl5", "room": room,
             "status": "installed", "serial": "CL5-001234", "asset_tag": "AV-0001", "ip": "192.168.1.10", "vlan": "10",
             "hostname": "foh-cl5", "notes": "Example row: edit or delete"},
            {"name": "Stage Box 1", "kind": "stage_io", "manufacturer": "Yamaha", "model": "Rio3224-D2", "template": "yamaha-rio3224-d2",
             "room": room, "status": "installed", "serial": "RIO-004321", "ip": "192.168.1.21", "mac": "00:1D:C1:0A:2B:3C", "vlan": "10"},
            {"name": "Wash 1", "kind": "fixture", "manufacturer": "Chauvet Professional", "model": "Maverick Storm 2 Profile",
             "template": "chauvet-maverick-storm-2-profile", "room": room, "status": "planned", "universe": "1", "address": "1",
             "footprint": "16", "dmx_channel": "101", "purchase_date": "2026-01-15", "cost": "4999.00"},
        ]
    else:
        examples = [
            {"tag": "D-001", "from_device": "Stage Box 1", "from_port": "Dante Primary", "to_device": "FOH Console",
             "to_port": "Dante Primary", "medium": "dante", "type": "Cat6A", "length": "45", "length_unit": "m", "color": "blue",
             "status": "installed", "note": "Example row: edit or delete"},
            {"tag": "D-002", "from_device": "Stage Box 1", "from_port": "Dante Secondary", "to_device": "FOH Console",
             "to_port": "Dante Secondary", "medium": "dante", "type": "Cat6A", "length": "150", "length_unit": "ft", "color": "red",
             "status": "installed"},
        ]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for ex in examples:
        w.writerow([ex.get(c, "") for c in cols])
    return buf.getvalue()
