"""ChamSys MagicQ patch (head list) CSV.

MagicQ does not document its ``.shw`` show file, but it writes the patch as a
head-list CSV in two ways, both read here:

* **Export Heads** (Patch → View Chans → EXPORT HEADS, older versions): fixed
  columns ``Headno, Headname, Dmxno, Headtype, Gel, Pinv, Tinv, Swap`` with
  ``Dmxno`` as ``<universe>-<address>`` (``1-001``) and ``Headtype`` as
  ``Manufacturer_Model`` (``Generic_Dimmer``).
* **Print Window → Create CSV** (Patch → View Heads, current versions): the
  user picks the columns, so headers vary. They are matched with the same
  synonyms MagicQ's own IMPORT HEADS accepts (case-insensitive): head number
  (``Head no``, ``Head``, ``Fixture ID`` …), name, ``Universe``, ``DMX``
  (absolute, in-universe with a Universe column, ``u-aaa``, ``u/a``, ``u.a``),
  manufacturer, head type, ``Mode``, gel, pan/tilt invert, swap, channel
  count and X/Y/Z position.

The delimiter is the first ``,`` / ``;`` / tab in the file, as on the console.
A head without an address (``virtual``, ``-``, blank) is listed in the notes
and skipped. :func:`contribute` matches heads to devices (``dmx.channel`` =
head number, then a unique head name) and creates overlay-only fixtures for
the rest, like the Eos importer.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import ParseResult, check_size, norm_header, read_text
from .eos import split_address

SHOW_MAGIC = b"\\ MagicQ Show File"

COLS: Dict[str, Tuple[str, ...]] = {
    "head": ("head no", "headno", "hdno", "headnum", "head num", "head number", "head", "hd no", "fixture id", "spot", "channel"),
    "name": ("head name", "headname", "hd name", "hdname", "name", "short name", "purpose"),
    "universe": ("universe", "uni", "dmx line"),
    "dmx": ("dmxno", "dmx no", "dmx", "dmx num", "dmx address", "dmx channel", "dmx patch", "patch address", "patch", "address"),
    "manufacturer": ("manufacturer", "man", "manuf"),
    "type": ("headtype", "head type", "hdtype", "hd type", "type", "fixture", "instrument type", "personality"),
    "mode": ("mode",),
    "gel": ("gel", "colour", "color", "filter"),
    "pinv": ("pinv", "p inv", "pan inv", "paninv", "pani", "pan i", "pan invert"),
    "tinv": ("tinv", "t inv", "tilt inv", "tiltinv", "tilti", "tilt i", "tilt invert"),
    "swap": ("swap", "flip"),
    "chans": ("chans", "num chans", "numchans", "of data channels", "num channels", "channel count", "channels"),
    "x": ("x", "x location", "x pos", "x position", "position x"),
    "y": ("y", "y location", "y pos", "y position", "position y"),
    "z": ("z", "z location", "z pos", "z position", "position z"),
}

#: headings only MagicQ writes (other lighting schedules use Channel / Address / Dimmer)
_MAGICQ_ONLY = {"headno", "hdno", "headnum", "head no", "head num", "head number", "head", "hd no", "headname", "hdname", "hd name",
                "head name", "dmxno", "dmx no", "headtype", "hdtype", "hd type", "head type", "pinv", "tinv", "p inv", "t inv"}
_UNPATCHED = {"", "-", "0", "virtual", "none", "unpatched", "n a", "na"}
_NO_GEL = {"", "no col", "no colour", "no color", "none", "n c", "nc", "open"}


class MagicQPatch(ParseResult):
    kind = "magicq"

    def __init__(self) -> None:
        super().__init__()
        self.format = ""  # export-heads | print-window
        self.heads: List[Dict[str, Any]] = []
        self.unpatched: List[str] = []
        #: set when nothing in the upload can be read; the server refuses the import with this message
        self.fatal = ""

    @property
    def fixtures(self) -> List[Dict[str, Any]]:
        return self.heads

    @property
    def universes(self) -> List[int]:
        return sorted({int(h["universe"]) for h in self.heads if h.get("universe")})

    def summary(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "format": self.format,
            "heads": len(self.heads),
            "unpatched": len(self.unpatched),
            "universes": self.universes,
            "head_types": sorted({h.get("type", "") for h in self.heads if h.get("type")}),
            "notes": list(self.notes),
        }


# ------------------------------------------------------------- reading


def first_delimiter(text: str) -> str:
    """MagicQ uses whichever of ``,`` / ``;`` comes first; tab-separated pastes are accepted too."""
    for ch in text:
        if ch in ",;\t":
            return ch
    return ","


def header_columns(header: List[str]) -> Dict[str, int]:
    cells = [norm_header(c) for c in header]
    out: Dict[str, int] = {}
    for key, syns in COLS.items():
        for s in syns:
            if s in cells and cells.index(s) not in out.values():
                out[key] = cells.index(s)
                break
    return out


def _is_header(row: List[str]) -> bool:
    cells = {norm_header(c) for c in row if c.strip()}
    cols = header_columns(row)
    return bool(cells & _MAGICQ_ONLY) and "dmx" in cols and ("head" in cols or "type" in cols)


def _rows(text: str) -> List[List[str]]:
    delim = first_delimiter(text)
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]


def _bool(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if t in ("yes", "y", "1", "true", "on", "inv", "inverted"):
        return True
    if t in ("no", "n", "0", "false", "off", ""):
        return False
    return None


def _head_no(text: str) -> str:
    t = (text or "").strip()
    return str(int(t)) if t.isdigit() else t


def _num(text: str) -> Optional[float]:
    try:
        return float((text or "").strip())
    except ValueError:
        return None


def split_type(head_type: str, manufacturer: str = "") -> Tuple[str, str]:
    """``'Martin_MacAura'`` → (``'Martin'``, ``'MacAura'``); a Manufacturer column wins."""
    t = (head_type or "").strip()
    if manufacturer:
        model = t
        pre = manufacturer.strip() + "_"
        if model.lower().startswith(pre.lower()):
            model = model[len(pre):]
        return manufacturer.strip(), model.replace("_", " ").strip()
    if "_" in t:
        man, model = t.split("_", 1)
        return man.strip(), model.replace("_", " ").strip()
    return "", t


def parse_text(text: str, res: MagicQPatch) -> None:
    rows = _rows(text)
    hi = next((i for i, r in enumerate(rows[:10]) if _is_header(r)), None)
    if hi is None:
        res.note("no MagicQ head-list header (Head no / Headno and DMX / Dmxno columns)")
        return
    cols = header_columns(rows[hi])
    cells = {norm_header(c) for c in rows[hi]}
    res.format = "export-heads" if {"headno", "dmxno"} <= cells else "print-window"

    def g(r: List[str], k: str) -> str:
        i = cols.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""

    for r in rows[hi + 1:]:
        head = _head_no(g(r, "head"))
        raw = g(r, "dmx")
        if not head and not raw and not g(r, "type"):
            continue
        uni = None
        if g(r, "universe").isdigit():
            uni = int(g(r, "universe"))
        addr = None
        if norm_header(raw) not in _UNPATCHED:
            in_uni = bool(uni) and raw.isdigit() and int(raw) <= 512
            addr = split_address(raw, universe=uni if in_uni else None)
            if addr is None:
                res.note(f"head {head or '?'}: DMX '{raw}' not understood; skipped")
                continue
        if addr is None:
            res.unpatched.append(head or g(r, "name") or "?")
            continue
        man, model = split_type(g(r, "type"), g(r, "manufacturer"))
        h: Dict[str, Any] = {"channel": head, "head": head, "universe": addr[0], "address": addr[1], "type": g(r, "type"), "label": g(r, "name")}
        if man:
            h["manufacturer"] = man
        if model:
            h["model"] = model
        if g(r, "mode"):
            h["mode"] = g(r, "mode")
        if norm_header(g(r, "gel")) not in _NO_GEL:
            h["color"] = g(r, "gel")
        for k in ("pinv", "tinv", "swap"):
            if _bool(g(r, k)):
                h[k] = True
        chans = g(r, "chans")
        if chans.isdigit() and int(chans) > 0:
            h["footprint"] = int(chans)
        xyz = [_num(g(r, k)) for k in ("x", "y", "z")]
        if any(v is not None for v in xyz):
            h["xyz"] = [v if v is not None else 0.0 for v in xyz]
        res.heads.append(h)
    if res.unpatched:
        res.note(f"{len(res.unpatched)} head(s) without a DMX address skipped (virtual or unpatched): {', '.join(res.unpatched[:10])}")
    _check_overlaps(res)


def _check_overlaps(res: MagicQPatch) -> None:
    taken: Dict[Tuple[int, int], str] = {}
    for h in res.heads:
        size = int(h.get("footprint") or 1)
        if h["address"] + size - 1 > 512:
            res.note(f"head {h['head']}: {h['universe']}-{h['address']:03d} with {size} channels runs past address 512")
        for a in range(h["address"], min(h["address"] + size, 513)):
            other = taken.get((h["universe"], a))
            if other is not None and other != h["head"]:
                res.note(f"heads {other} and {h['head']} overlap at {h['universe']}-{a:03d}")
                break
            taken[(h["universe"], a)] = h["head"]


def sniff(text: str) -> bool:
    return any(_is_header(r) for r in _rows(text[:20000])[:10])


def detect(path: Path) -> float:
    if path.is_dir():
        return 0.0
    try:
        head = path.read_bytes()[:20000]
    except OSError:
        return 0.0
    if head.startswith(SHOW_MAGIC):
        return 0.6  # claimed so the user gets "export the patch as CSV" rather than "unknown"
    if path.suffix.lower() not in (".csv", ".txt", ".tsv"):
        return 0.0
    text = head.decode("utf-8-sig", errors="ignore")
    rows = _rows(text)[:10]
    for r in rows:
        if _is_header(r):
            cells = {norm_header(c) for c in r}
            return 0.95 if {"headno", "dmxno"} & cells or {"headtype", "hdtype", "pinv", "tinv"} & cells else 0.85
    return 0.0


def parse_magicq(path: Path, **_opts: Any) -> MagicQPatch:
    res = MagicQPatch()
    files = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")) if path.is_dir() else [path]
    for f in files:
        check_size(f)
        res.source_files.append(str(f))
        if f.read_bytes()[:len(SHOW_MAGIC)] == SHOW_MAGIC:
            res.note(f"{f.name} is a MagicQ show file, which Fathom cannot read; export the patch instead: "
                     "Patch → View Heads → File → Print Window → Create CSV (older versions: Patch → View Chans → EXPORT HEADS)")
            continue
        text = read_text(f)
        if sniff(text):
            parse_text(text, res)
        elif not path.is_dir():
            res.note(f"{f.name}: not a MagicQ head list (Headno / Dmxno columns)")
    if not res.heads and not res.unpatched and res.notes:
        res.fatal = res.notes[0]
    return res


# ----------------------------------------------------------- contribute


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def contribute(result: MagicQPatch, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Match heads to devices; unmatched → overlay-only fixture devices (``source: magicq``)."""
    room = ctx.get("room") or ""
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
    by_chan: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for d in devices:
        ch = str(((d.get("dmx") or {}).get("channel")) or "").strip()
        if ch:
            by_chan.setdefault(_head_no(ch), d["id"])
        by_name.setdefault(_norm(d.get("name", "")), d["id"])
    name_counts: Dict[str, int] = {}
    for h in result.heads:
        n = _norm(h.get("label", ""))
        name_counts[n] = name_counts.get(n, 0) + 1
    used_ids = {d.get("id") for d in devices}
    claimed: set = set()
    out_devices: List[Dict[str, Any]] = []
    dmx: Dict[str, Dict[str, Any]] = {}
    detail: Dict[str, Dict[str, Any]] = {}
    matched = 0
    for h in result.heads:
        ch = h.get("head", "")
        n = _norm(h.get("label", ""))
        dev_id = by_chan.get(ch) if ch else None
        if dev_id is None and n and name_counts.get(n) == 1:
            dev_id = by_name.get(n)
        if dev_id in claimed:
            dev_id = None
        if dev_id:
            matched += 1
        else:
            base = "mq-" + (re.sub(r"[^a-z0-9]+", "-", ch.lower()).strip("-") or "head")
            dev_id, i = base, 2
            while dev_id in used_ids:
                dev_id = f"{base}-{i}"
                i += 1
            used_ids.add(dev_id)
            kind_label = h.get("model") or h.get("type") or "Head"
            name = h.get("label") or kind_label
            if ch:
                name = f"{name} · head {ch}"
            dev: Dict[str, Any] = {
                "id": dev_id, "name": name, "kind": "fixture", "room": room, "auto": True, "source": "magicq",
                "model": h.get("model", ""),
                "ports": [
                    {"id": "dmx-in", "name": "DMX In", "dir": "in", "medium": "dmx", "group": "DMX"},
                    {"id": "dmx-thru", "name": "DMX Thru", "dir": "out", "medium": "dmx", "group": "DMX"},
                ],
            }
            if h.get("manufacturer"):
                dev["manufacturer"] = h["manufacturer"]
            out_devices.append(dev)
        claimed.add(dev_id)
        row: Dict[str, Any] = {"universe": h["universe"], "address": h["address"], "channel": ch, "source": "magicq"}
        if h.get("footprint"):
            row["footprint"] = h["footprint"]
        if h.get("mode"):
            row["mode"] = h["mode"]
        dmx[dev_id] = row
        info = {k: h[k] for k in ("type", "manufacturer", "mode", "color", "label", "xyz", "pinv", "tinv", "swap") if h.get(k)}
        if info:
            detail[dev_id] = {"lighting": info}
    notes = [f"magicq: {len(result.heads)} heads ({matched} matched, {len(out_devices)} added to the overlay)"]
    return {"devices": out_devices, "dmx": dmx, "detail": detail, "notes": notes + [f"magicq: {n}" for n in result.notes]}
