"""Lighting patch imports: ETC Eos CSV, USITT ASCII 3.0, Lightwright / Vectorworks text.

* **Eos CSV export** (File → Export → CSV): blocks ``START_<NAME>`` … ``END_<NAME>``,
  each with a title row. The patch comes from ``CHANNELS`` (alias ``PATCH``):
  ``CHANNEL, FIXTURE_TYPE, ADDRESS, LABEL`` (``PROPORTION``/``CURVE`` ignored);
  ``FIXTURES`` gives a footprint per ``FIXTURE_TYPE_NAME`` as
  ``max(PARAMETER_ADDRESS_OFFSET) + 1``. ``ADDRESS`` is absolute (``1025``),
  ``u/a`` or ``u.a``.
* **USITT ASCII** (``.asc``): one record per line, delimiters tab, space and
  ``, / ; < = > @``; keywords matched on their first 10 characters,
  case-insensitive; ``PATCH page chan<dim@level …``; channel 0 = unpatched;
  dimmer = absolute DMX address; ``ENDDATA`` stops; ``$``/``$$`` records and
  ``!`` comments are ignored.
* **Lightwright / Vectorworks instrument schedule** (tab or comma text with a
  header row, columns in any order).

All three produce a :class:`LightingPatch`; :func:`contribute` matches the
fixtures to devices (``dmx.channel`` then name) and creates overlay-only
fixtures for the rest (FR-IMP-03…06).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import ParseResult, check_size, norm_header, read_text, sniff_delimiter


class LightingPatch(ParseResult):
    kind = "eos"

    def __init__(self) -> None:
        super().__init__()
        self.format = ""  # eos-csv | usitt | lightwright
        self.fixtures: List[Dict[str, Any]] = []
        self.footprints: Dict[str, int] = {}

    @property
    def universes(self) -> List[int]:
        return sorted({int(f["universe"]) for f in self.fixtures if f.get("universe")})

    def summary(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "format": self.format,
            "fixtures": len(self.fixtures),
            "universes": self.universes,
            "fixture_types": sorted({f.get("type", "") for f in self.fixtures if f.get("type")}),
            "notes": list(self.notes),
        }


# ------------------------------------------------------------ addresses


def split_address(text: str, universe: Optional[int] = None) -> Optional[Tuple[int, int]]:
    """``'1025'`` → (3, 1); ``'2/17'`` / ``'2.17'`` → (2, 17); with ``universe`` the number is in-universe."""
    t = (text or "").strip()
    if not t or t in ("-", "0"):
        return None
    m = re.match(r"^\s*(\d+)\s*[/.:\-]\s*(\d+)\s*$", t)
    if m:
        u, a = int(m.group(1)), int(m.group(2))
        return (u, a) if u >= 1 and 1 <= a <= 512 else None
    m = re.match(r"^\s*(\d+)\s*$", t)
    if not m:
        return None
    n = int(m.group(1))
    if n <= 0:
        return None
    if universe:
        return (universe, n) if n <= 512 else None
    return ((n - 1) // 512 + 1, (n - 1) % 512 + 1)


def _int(text: Any) -> Optional[int]:
    m = re.search(r"\d+", str(text or ""))
    return int(m.group(0)) if m else None


# ------------------------------------------------------------- Eos CSV


def _blocks(text: str) -> Dict[str, List[List[str]]]:
    out: Dict[str, List[List[str]]] = {}
    cur: Optional[str] = None
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        first = cells[0].upper()
        if first.startswith("START_"):
            cur = first[6:]
            out.setdefault(cur, [])
            continue
        if first.startswith("END_"):
            cur = None
            continue
        if cur is not None:
            out[cur].append(cells)
    return out


def _table(rows: List[List[str]]) -> List[Dict[str, str]]:
    if not rows:
        return []
    head = [norm_header(c).replace(" ", "_") for c in rows[0]]
    return [{head[i]: (r[i] if i < len(r) else "") for i in range(len(head))} for r in rows[1:]]


def parse_eos_csv(text: str, res: LightingPatch) -> None:
    res.format = "eos-csv"
    blocks = _blocks(text)
    for row in _table(blocks.get("FIXTURES", [])):
        name = row.get("fixture_type_name") or row.get("fixture_type") or ""
        off = _int(row.get("parameter_address_offset"))
        if name and off is not None:
            res.footprints[name] = max(res.footprints.get(name, 0), off + 1)
    chans = blocks.get("CHANNELS") or blocks.get("PATCH") or []
    if not chans:
        res.note("no START_CHANNELS / START_PATCH block found")
    for row in _table(chans):
        ch = (row.get("channel") or "").strip()
        addr = split_address(row.get("address") or row.get("dmx") or "")
        if not ch or addr is None:
            continue
        ftype = row.get("fixture_type") or row.get("fixture_model") or row.get("type") or ""
        fx: Dict[str, Any] = {"channel": ch, "universe": addr[0], "address": addr[1], "type": ftype, "label": row.get("label", "")}
        if row.get("part"):
            fx["part"] = row["part"]
        if ftype in res.footprints:
            fx["footprint"] = res.footprints[ftype]
        res.fixtures.append(fx)


# --------------------------------------------------------------- USITT

_USITT_SPLIT = re.compile(r"[\t ,/;<=>@]+")


def _kw(token: str, keyword: str) -> bool:
    t = token.upper()[:10]
    return bool(t) and keyword.upper()[:10] == t


def parse_usitt(text: str, res: LightingPatch) -> None:
    res.format = "usitt"
    by_chan: Dict[str, Dict[str, Any]] = {}
    for raw in text.splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line or line.startswith("$"):
            continue
        toks = [t for t in _USITT_SPLIT.split(line) if t]
        if not toks:
            continue
        if _kw(toks[0], "ENDDATA"):
            break
        if not _kw(toks[0], "PATCH"):
            continue
        nums = toks[2:]  # toks[1] = page
        for i in range(0, len(nums) - 1, 3):
            chan, dim = _int(nums[i]), _int(nums[i + 1])
            if not chan or not dim:
                continue
            addr = split_address(str(dim))
            if addr is None:
                continue
            fx = by_chan.get(str(chan))
            if fx is None:
                fx = {"channel": str(chan), "universe": addr[0], "address": addr[1], "type": "", "label": ""}
                by_chan[str(chan)] = fx
                res.fixtures.append(fx)
            else:
                fx.setdefault("extra_dimmers", []).append(dim)
    if not res.fixtures:
        res.note("no PATCH records found")


# ----------------------------------------------------------- Lightwright

_LW_COLS: Dict[str, Tuple[str, ...]] = {
    "channel": ("channel", "chan", "ch"),
    "absolute": ("dimmer", "address", "absolute address", "dmx", "dmx address"),
    "universe": ("universe", "univ"),
    "u_address": ("u address", "universe address offset", "u addr"),
    "ua": ("universe address", "u a"),
    "type": ("instrument type", "fixture type", "type"),
    "position": ("position",),
    "unit": ("unit", "unit number", "unit #"),
    "purpose": ("purpose", "focus"),
    "color": ("color", "colour"),
    "mode": ("mode",),
    "footprint": ("footprint", "dmx footprint", "channels"),
    "label": ("label", "name"),
}


def _lw_header(header: List[str]) -> Dict[str, int]:
    cells = [norm_header(c) for c in header]
    out: Dict[str, int] = {}
    for key, syns in _LW_COLS.items():
        for s in syns:
            n = norm_header(s)
            if n in cells and cells.index(n) not in out.values():
                out[key] = cells.index(n)
                break
    return out


def parse_lightwright(text: str, res: LightingPatch) -> None:
    res.format = "lightwright"
    delim = "\t" if "\t" in text.split("\n", 1)[0] else sniff_delimiter(text)
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    hi = None
    for i, r in enumerate(rows[:10]):
        cols = _lw_header(r)
        if "channel" in cols and ("absolute" in cols or "ua" in cols or "u_address" in cols):
            hi = i
            break
    if hi is None:
        res.note("no header row with Channel and Dimmer/Address columns")
        return
    cols = _lw_header(rows[hi])

    def g(r: List[str], k: str) -> str:
        i = cols.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""

    for r in rows[hi + 1:]:
        ch = g(r, "channel")
        uni = _int(g(r, "universe"))
        addr = None
        if g(r, "ua"):
            addr = split_address(g(r, "ua"))
        if addr is None and g(r, "u_address") and uni:
            addr = split_address(g(r, "u_address"), universe=uni)
        if addr is None and g(r, "absolute"):
            addr = split_address(g(r, "absolute"), universe=uni if (uni and "/" not in g(r, "absolute") and (_int(g(r, "absolute")) or 0) <= 512) else None)
        if not ch or addr is None:
            continue
        fx: Dict[str, Any] = {"channel": ch, "universe": addr[0], "address": addr[1], "type": g(r, "type"), "label": g(r, "label")}
        for k in ("position", "unit", "purpose", "color", "mode"):
            if g(r, k):
                fx[k] = g(r, k)
        fp = _int(g(r, "footprint"))
        if fp:
            fx["footprint"] = fp
        res.fixtures.append(fx)


# --------------------------------------------------------------- driver


def sniff_format(text: str) -> str:
    up = text[:20000].upper()
    if re.search(r"^\s*START_(CHANNELS|PATCH|FIXTURES|TARGETS|SHOW)", up, re.M):
        return "eos-csv"
    lines = [ln.strip() for ln in up.splitlines() if ln.strip() and not ln.strip().startswith("!")]
    if lines and (lines[0].startswith("IDENT") or any(ln.startswith("PATCH ") for ln in lines[:400]) and any(ln.startswith(("ENDDATA", "IDENT", "CLEAR", "MANUFACTURER", "CONSOLE")) for ln in lines)):
        return "usitt"
    first = text.split("\n", 1)[0]
    cols = _lw_header([c.strip() for c in re.split(r"[\t,]", first)])
    if "channel" in cols and ("absolute" in cols or "ua" in cols or "u_address" in cols):
        return "lightwright"
    return ""


def detect(path: Path) -> float:
    if path.is_dir():
        return 0.0
    if path.suffix.lower() in (".asc",):
        return 0.9
    try:
        head = path.read_bytes()[:20000].decode("utf-8", errors="ignore")
    except OSError:
        return 0.0
    fmt = sniff_format(head)
    if fmt == "eos-csv":
        return 0.95
    if fmt == "usitt":
        return 0.9
    if fmt == "lightwright":
        cols = _lw_header([c.strip() for c in re.split(r"[\t,]", head.split("\n", 1)[0])])
        return 0.75 if any(k in cols for k in ("position", "purpose", "type", "unit")) else 0.5
    return 0.0


def parse_eos(path: Path, **_opts: Any) -> LightingPatch:
    res = LightingPatch()
    files = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")) if path.is_dir() else [path]
    for f in files:
        check_size(f)
        res.source_files.append(str(f))
        text = read_text(f)
        fmt = sniff_format(text) or ("usitt" if f.suffix.lower() == ".asc" else "")
        if fmt == "eos-csv":
            parse_eos_csv(text, res)
        elif fmt == "usitt":
            parse_usitt(text, res)
        elif fmt == "lightwright":
            parse_lightwright(text, res)
        elif not path.is_dir():
            res.note(f"{f.name}: not an Eos CSV, USITT ASCII or Lightwright schedule")
    if path.is_dir() and len(files) > 1:
        res.format = "mixed" if res.format else ""
    return res


# ----------------------------------------------------------- contribute


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def contribute(result: LightingPatch, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Match fixtures to devices; unmatched → overlay-only fixture devices (FR-IMP-06)."""
    room = ctx.get("room") or ""
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
    by_chan: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for d in devices:
        ch = str(((d.get("dmx") or {}).get("channel")) or "").strip()
        if ch:
            by_chan.setdefault(ch, d["id"])
        by_name.setdefault(_norm(d.get("name", "")), d["id"])
    used_ids = {d.get("id") for d in devices}
    out_devices: List[Dict[str, Any]] = []
    dmx: Dict[str, Dict[str, Any]] = {}
    detail: Dict[str, Dict[str, Any]] = {}
    matched = 0
    for fx in result.fixtures:
        ch = str(fx.get("channel", "")).strip()
        dev_id = by_chan.get(ch) or (by_name.get(_norm(fx.get("label", ""))) if fx.get("label") else None)
        if dev_id:
            matched += 1
        else:
            base = "eos-" + re.sub(r"[^a-z0-9]+", "-", ch.lower()).strip("-")
            dev_id, i = base, 2
            while dev_id in used_ids:
                dev_id = f"{base}-{i}"
                i += 1
            used_ids.add(dev_id)
            name = fx.get("label") or (f"{fx['type']} · ch {ch}" if fx.get("type") else f"Channel {ch}")
            out_devices.append({
                "id": dev_id, "name": name, "kind": "fixture", "room": room, "auto": True, "source": "eos",
                "model": fx.get("type", ""),
                "ports": [
                    {"id": "dmx-in", "name": "DMX In", "dir": "in", "medium": "dmx", "group": "DMX"},
                    {"id": "dmx-thru", "name": "DMX Thru", "dir": "out", "medium": "dmx", "group": "DMX"},
                ],
            })
        row: Dict[str, Any] = {"universe": fx["universe"], "address": fx["address"], "channel": ch, "source": "eos"}
        if fx.get("footprint"):
            row["footprint"] = fx["footprint"]
        if fx.get("mode"):
            row["mode"] = fx["mode"]
        dmx[dev_id] = row
        info = {k: fx[k] for k in ("type", "position", "unit", "purpose", "color", "label") if fx.get(k)}
        if info:
            detail[dev_id] = {"lighting": info}
    notes = [f"eos: {len(result.fixtures)} fixtures ({matched} matched, {len(out_devices)} added to the overlay)"]
    return {"devices": out_devices, "dmx": dmx, "detail": detail, "notes": notes + [f"eos: {n}" for n in result.notes]}
