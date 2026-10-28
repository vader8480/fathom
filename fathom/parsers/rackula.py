"""Rackula layouts -> Fathom racks, rack items and devices (preview + ops).

``preview(doc, payload)`` reads a Rackula layout and returns what importing it
into ``doc`` would create, plus the ops (§4.9) that do it::

    {layout, racks, devices, items, warnings, ops}

``payload`` is one of:

- ``{"text": ...}``: a ``.rackula.yaml`` / ``.yaml`` / ``.json`` layout, the
  minimal share JSON, or a share link pasted as text;
- ``{"zip_b64": ...}``: a ``.Rackula.zip`` (base64, a ``data:`` URL is fine);
  the layout YAML inside is read and ``assets/`` are ignored;
- ``{"url": ...}``: a share link (``https://count.racku.la/?l=…``) or just its
  encoded ``l`` value (lz-string, or the older zlib/gzip + base64url form).

Optional ``room`` names the room for new racks and devices (default: the
document's first room). Unparseable input raises ``ValueError`` with a
readable message; anything imported approximately is listed in ``warnings``.
Collisions after import are warnings, not refusals.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import re
import zipfile
import zlib
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from . import mini_yaml

__all__ = ["preview", "read_layout", "decode_share", "lz_decompress_uri", "KIND_BY_CATEGORY", "FORM_FACTORS", "UNITS_PER_U"]

Doc = Dict[str, Any]

#: Rackula stores rail positions in 1/6 U (U1 = 6).
UNITS_PER_U = 6
MAX_ENCODED = 64 * 1024
MAX_DECOMPRESSED = 8 * 1024 * 1024
MAX_TEXT = 16 * 1024 * 1024
MAX_ZIP = 48 * 1024 * 1024
MAX_UNITS = 60
_NEWEST_MAJOR = 2

FORM_FACTORS = {
    "2-post": "two_post", "4-post": "four_post", "4-post-cabinet": "cabinet",
    "wall-mount": "wall_mount", "open-frame": "open_frame",
}
KIND_BY_CATEGORY = {
    "server": "computer", "storage": "computer", "kvm": "computer", "chassis": "computer",
    "network": "switch", "firewall": "network", "patch-panel": "patch_panel", "power": "power",
    "av-media": "video", "cooling": "other", "shelf": "other", "blank": "other",
    "cable-management": "other", "other": "other",
}
#: Share-link category abbreviations.
CATEGORY_ABBREV = {
    "s": "server", "n": "network", "r": "firewall", "p": "patch-panel", "w": "power", "t": "storage",
    "k": "kvm", "a": "av-media", "l": "cooling", "f": "shelf", "b": "blank", "c": "cable-management",
    "h": "chassis", "o": "other",
}
_ITEM_CATEGORIES = ("blank", "cable-management", "shelf")
#: Contract B ITEM_TYPES (height, face, depth), used when ``fathom.racks`` has no table yet.
_ITEM_DEFAULTS = {
    "blank": (1, "front", "half"), "vent": (1, "front", "half"), "shelf": (1, "front", "full"),
    "drawer": (2, "front", "full"), "cable_manager": (1, "front", "half"), "brush": (1, "front", "half"),
    "lacing_bar": (1, "rear", "half"), "other": (1, "front", "half"),
}
_MAX_SHELF_SLOTS = 4
_WEIGHT_KG = {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "lbs": 0.45359237, "oz": 0.028349523125}
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_SCHEMA_VERSION_RE = re.compile(r"^\d+\.\d+$")
_NETWORK_KEYWORDS = re.compile(r"router|gateway|firewall|security appliance|dream machine|\budm\b")
_LZ_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"
_LZ_INDEX = {c: i for i, c in enumerate(_LZ_ALPHABET)}
_SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9+\-$_]{16,}$")


# ------------------------------------------------------------ share links


def lz_decompress_uri(encoded: str) -> Optional[str]:
    """lz-string ``decompressFromEncodedURIComponent``; None when ``encoded`` is not lz-string.
    Raises ValueError when the output would exceed ``MAX_DECOMPRESSED``."""
    if not encoded:
        return None
    vals: List[int] = []
    for ch in encoded.replace(" ", "+"):
        v = _LZ_INDEX.get(ch)
        if v is None:
            return None
        vals.append(v)
    length = len(vals)
    reset = 32
    val, pos, index = vals[0], reset, 1

    def bits(n: int) -> int:
        nonlocal val, pos, index
        out, power = 0, 1
        for _ in range(n):
            b = val & pos
            pos >>= 1
            if pos == 0:
                pos = reset
                val = vals[index] if index < length else 0
                index += 1
            if b:
                out |= power
            power <<= 1
        return out

    first = bits(2)
    if first == 2:
        return ""
    if first not in (0, 1):
        return None
    c = chr(bits(8 if first == 0 else 16))
    dictionary: List[str] = ["", "", "", c]
    w = c
    out = [c]
    total = 1
    enlarge, num_bits = 4, 3
    while True:
        if index > length:
            return ""
        code = bits(num_bits)
        if code in (0, 1):
            dictionary.append(chr(bits(8 if code == 0 else 16)))
            code = len(dictionary) - 1
            enlarge -= 1
        elif code == 2:
            text = "".join(out)
            return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1
        if code < len(dictionary):
            entry = dictionary[code]
        elif code == len(dictionary):
            entry = w + w[0]
        else:
            return None
        out.append(entry)
        total += len(entry)
        if total > MAX_DECOMPRESSED:
            raise ValueError("the share link expands past the size limit")
        dictionary.append(w + entry[0])
        enlarge -= 1
        w = entry
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1


def _inflate_b64url(encoded: str) -> str:
    s = encoded.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    raw = base64.b64decode(s, validate=True)
    d = zlib.decompressobj(47)  # zlib or gzip header, as pako.Inflate detects
    out = d.decompress(raw, MAX_DECOMPRESSED + 1)
    if len(out) > MAX_DECOMPRESSED or d.unconsumed_tail:
        raise ValueError("the share link expands past the size limit")
    if not d.eof:
        raise zlib.error("truncated stream")
    return out.decode("utf-8")


def _share_code(value: str) -> str:
    s = str(value or "").strip()
    m = re.search(r"(?:^|[?&#])l=([^&#\s]*)", s)
    if m:
        return unquote(m.group(1))
    if "://" in s or s.startswith("?"):
        raise ValueError("the link has no ?l= layout in it")
    return s


def decode_share(value: str) -> Dict[str, Any]:
    """The minimal share JSON of a share link or its bare ``l`` value."""
    code = _share_code(value)
    if not code:
        raise ValueError("the share link is empty")
    if len(code) > MAX_ENCODED:
        raise ValueError("the share link is too large")
    try:
        text = lz_decompress_uri(code)
        if text:
            return json.loads(text)
    except (ValueError, RecursionError) as exc:
        if "size limit" in str(exc):
            raise
    try:
        return json.loads(_inflate_b64url(code))
    except ValueError as exc:
        if "size limit" in str(exc):
            raise
    except (binascii.Error, zlib.error, UnicodeDecodeError, RecursionError):
        pass
    raise ValueError("not a readable Rackula share link")


# ------------------------------------------------------------ input formats


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _str(v: Any) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _js_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def _cmp_versions(a: str, b: str) -> int:
    def parts(v: str) -> List[int]:
        out = []
        for p in re.split(r"[-+]", v.strip())[0].split("."):
            m = re.match(r"\d+", p)
            out.append(int(m.group(0)) if m else 0)
        return out

    pa, pb = parts(a), parts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x != y:
            return -1 if x < y else 1
    return 0


def _dict_list(v: Any) -> List[Dict[str, Any]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _from_minimal(m: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """Normalize the minimal share JSON (v1 ``r`` or v2 ``rs``) to the file shape."""
    if not isinstance(m, dict) or not isinstance(m.get("dt"), list):
        raise ValueError("the share link does not hold a Rackula layout")
    if isinstance(m.get("rs"), list):
        racks_in = _dict_list(m["rs"])
    elif isinstance(m.get("r"), dict):
        racks_in = [m["r"]]
    else:
        raise ValueError("the share link does not hold any racks")
    types: List[Dict[str, Any]] = []
    for t in _dict_list(m["dt"]):
        dt: Dict[str, Any] = {"slug": _str(t.get("s")), "u_height": t.get("h"), "colour": t.get("c"),
                              "category": CATEGORY_ABBREV.get(_str(t.get("x")), "other")}
        if t.get("mf"):
            dt["manufacturer"] = t["mf"]
        if t.get("m"):
            dt["model"] = t["m"]
        if isinstance(t.get("sl"), list):
            dt["slots"] = [{"id": _str(s.get("id")), "position": {"row": s.get("r"), "col": s.get("cl")}}
                           for s in _dict_list(t["sl"])]
        types.append(dt)
    racks: List[Dict[str, Any]] = []
    short: Dict[str, str] = {}
    for idx, r in enumerate(racks_in):
        rid = f"share-{idx}"
        short[_str(r.get("i")) or str(idx)] = rid
        w, wx = r.get("w"), r.get("wx")
        width = wx if wx in (21, 23) and w == 19 else (10 if w == 10 else 19)
        devs_in = _dict_list(r.get("d"))
        devices = []
        for j, d in enumerate(devs_in):
            p = _num(d.get("p")) or 0.0
            dev: Dict[str, Any] = {"id": f"{rid}-d{j}", "device_type": _str(d.get("t")), "face": d.get("f")}
            if d.get("n"):
                dev["name"] = d["n"]
            ci = d.get("ci")
            parent = devs_in[ci] if isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(devs_in) and ci != j else None
            if parent is not None and d.get("si") is not None and parent.get("ci") is None:
                dev["container_id"] = f"{rid}-d{ci}"
                dev["slot_id"] = _str(d.get("si"))
                dev["position"] = p
            else:
                dev["position"] = _js_round(p * UNITS_PER_U)
            devices.append(dev)
        racks.append({"id": rid, "name": r.get("n"), "height": r.get("h"), "width": width,
                      "form_factor": "4-post-cabinet", "desc_units": False, "starting_unit": 1,
                      "position": idx, "devices": devices})
    groups = []
    for i, g in enumerate(_dict_list(m.get("rg"))):
        ids = [short[_str(x)] for x in (g.get("rs") or []) if _str(x) in short]
        groups.append({"id": f"group-{i + 1}", "name": _str(g.get("n")) or f"Group {i + 1}", "rack_ids": ids})
    return {"name": _str(m.get("n")), "version": _str(m.get("v")), "format": fmt, "racks": racks,
            "rack_groups": groups, "device_types": types, "migrate": False}


def _from_file(data: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    sv = meta.get("schema_version")
    if isinstance(sv, (int, float)) and not isinstance(sv, bool):
        sv = repr(float(sv))
    if isinstance(sv, str):
        if not _SCHEMA_VERSION_RE.match(sv.strip()):
            raise ValueError(f"the layout has an unreadable data format ({sv})")
        if int(sv.strip().split(".")[0]) > _NEWEST_MAJOR:
            raise ValueError(f"the layout was made by a newer Rackula (format {sv.strip()})")
    if isinstance(data.get("racks"), list) and data["racks"]:
        racks = _dict_list(data["racks"])
    elif isinstance(data.get("rack"), dict):
        racks = [data["rack"]]
    else:
        racks = []
    if not racks:
        raise ValueError("the layout has no racks")
    if not isinstance(data.get("device_types", []), list):
        raise ValueError("device_types must be a list")
    version = _str(data.get("version"))
    rack_level = [d for r in racks for d in _dict_list(r.get("devices")) if not d.get("container_id")]
    migrate = (not version or _cmp_versions(version, "0.7.0") < 0
               or any(1 <= (_num(d.get("position")) or 0) < UNITS_PER_U for d in rack_level))
    out_racks = []
    for i, r in enumerate(racks):
        rr = dict(r)
        rr["id"] = _str(r.get("id")) or f"rack-{i + 1}"
        devices = []
        for d in _dict_list(r.get("devices")):
            dd = dict(d)
            p = _num(d.get("position"))
            if not d.get("container_id"):
                p = p or 0.0
                dd["position"] = max(1, _js_round(p)) * UNITS_PER_U if migrate else p
            else:
                dd["position"] = p or 0.0
            devices.append(dd)
        rr["devices"] = devices
        out_racks.append(rr)
    groups = []
    for i, g in enumerate(_dict_list(data.get("rack_groups"))):
        groups.append({"id": _str(g.get("id")) or f"group-{i + 1}", "name": _str(g.get("name")),
                       "rack_ids": [_str(x) for x in (g.get("rack_ids") or []) if _str(x)]})
    return {"name": _str(data.get("name")) or _str(meta.get("name")), "version": version, "format": fmt,
            "racks": out_racks, "rack_groups": groups, "device_types": _dict_list(data.get("device_types")),
            "migrate": migrate}


def _from_data(data: Any, fmt: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("a Rackula layout is a mapping with racks and device_types")
    if "rs" in data or ("r" in data and "dt" in data):
        return _from_minimal(data, "share")
    if "racks" not in data and "rack" not in data:
        raise ValueError("not a Rackula layout (no racks)")
    return _from_file(data, fmt)


def _looks_like_share(s: str) -> bool:
    if any(ch.isspace() for ch in s):
        return False
    return "://" in s or s.startswith(("?", "l=")) or bool(_SHARE_CODE_RE.match(s))


def _from_text(text: Any, fmt_hint: str = "", allow_share: bool = True) -> Dict[str, Any]:
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8-sig", errors="replace")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if len(text) > MAX_TEXT:
        raise ValueError("the layout is too large")
    text = text.lstrip("\ufeff")
    s = text.strip()
    if not s:
        raise ValueError("the layout is empty")
    if allow_share and _looks_like_share(s):
        return _from_minimal(decode_share(s), "share")
    if s[0] in "{[" or fmt_hint == "json":
        try:
            data = json.loads(s)
        except ValueError as exc:
            raise ValueError(f"not valid JSON: {exc}")
        return _from_data(data, "json")
    try:
        data = mini_yaml.loads(text)
    except ValueError as exc:
        raise ValueError(f"not readable as a Rackula layout: {exc}")
    return _from_data(data, "yaml")


def _from_zip(b64: Any, warnings: List[str]) -> Dict[str, Any]:
    s = str(b64 or "").strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    s = re.sub(r"\s+", "", s)
    if len(s) > MAX_ZIP * 4 // 3 + 4:
        raise ValueError("the archive is too large")
    try:
        raw = base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("zip_b64 is not base64")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        infos = z.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError):
        raise ValueError("not a zip archive")
    cands = []
    for info in infos:
        name = info.filename.replace("\\", "/")
        parts = [p for p in name.split("/") if p]
        if info.is_dir() or not parts or not parts[-1].lower().endswith((".yaml", ".yml", ".json")):
            continue
        if any(p.lower() in ("assets", "images", "__macosx") for p in parts[:-1]) or parts[-1].startswith("._"):
            continue
        stem = re.sub(r"(\.rackula)?\.(ya?ml|json)$", "", parts[-1].lower())
        named = len(parts) >= 2 and parts[-2].lower().startswith(stem)
        cands.append((len(parts), 0 if named else 1, name, info))
    if not cands:
        raise ValueError("no layout YAML in the archive")
    cands.sort(key=lambda c: c[:3])
    tops = {c[2].split("/")[0] for c in cands if "/" in c[2]}
    info = cands[0][3]
    if len(tops) > 1:
        warnings.append(f"the archive holds {len(tops)} layouts; imported {cands[0][2]}")
    if info.file_size > MAX_TEXT:
        raise ValueError("the layout in the archive is too large")
    try:
        with z.open(info) as fh:
            data = fh.read(MAX_TEXT + 1)
    except (RuntimeError, zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError):
        raise ValueError("the layout in the archive cannot be read (encrypted or damaged)")
    if len(data) > MAX_TEXT:
        raise ValueError("the layout in the archive is too large")
    layout = _from_text(data, "json" if info.filename.lower().endswith(".json") else "", allow_share=False)
    layout["format"] = "zip"
    return layout


def read_layout(payload: Dict[str, Any], warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Normalize a payload to ``{name, version, format, racks, rack_groups, device_types, migrate}``.
    Rack-level positions are in internal units (U1 = 6) after legacy migration."""
    notes = warnings if warnings is not None else []
    if not isinstance(payload, dict):
        raise ValueError("the import body must be an object")
    if payload.get("zip_b64"):
        return _from_zip(payload["zip_b64"], notes)
    if payload.get("url"):
        if not isinstance(payload["url"], str):
            raise ValueError("url must be a string")
        return _from_minimal(decode_share(payload["url"]), "share")
    if payload.get("text"):
        return _from_text(payload["text"])
    raise ValueError("send a Rackula layout as text, zip_b64 or url")


# ------------------------------------------------------------ mapping


def _item_defaults() -> Dict[str, Tuple[int, str, str]]:
    try:
        from .. import racks

        table = getattr(racks, "ITEM_TYPES", None)
        if isinstance(table, dict) and table:
            out = {}
            for k, v in table.items():
                d = _ITEM_DEFAULTS.get(k, (1, "front", "half"))
                if isinstance(v, dict):
                    d = (int(v.get("height") or d[0]), str(v.get("face") or d[1]), str(v.get("depth") or d[2]))
                out[k] = d
            return {**_ITEM_DEFAULTS, **out}
    except Exception:
        pass
    return dict(_ITEM_DEFAULTS)


def _template(slug_: str, doc: Doc) -> Optional[Dict[str, Any]]:
    if not slug_:
        return None
    try:
        from ..library import get_template

        t = get_template(slug_, doc)
    except Exception:
        return None
    return t if isinstance(t, dict) else None


def _kinds() -> Set[str]:
    try:
        from ..vocab import KINDS

        return set(KINDS)
    except Exception:
        return set(KIND_BY_CATEGORY.values())


def _words(dt: Dict[str, Any], placed: Dict[str, Any]) -> str:
    return " ".join(_str(x) for x in (dt.get("manufacturer"), dt.get("model"), dt.get("slug"), placed.get("name"))).lower()


def _kind(dt: Dict[str, Any], placed: Dict[str, Any], tpl: Optional[Dict[str, Any]], kinds: Set[str]) -> str:
    from .netbox_devicetype import kind_from_keywords

    if tpl and tpl.get("kind") in kinds:
        return str(tpl["kind"])
    cat = _str(dt.get("category")) or "other"
    words = _words(dt, placed)
    if cat in ("av-media", "other"):
        kw = kind_from_keywords(words)
        if kw in kinds:
            return kw
    if re.search(r"patch[ -]?panel|keystone", words) and "patch_panel" in kinds:
        return "patch_panel"
    if cat == "network" and _NETWORK_KEYWORDS.search(words):
        return "network"
    kind = KIND_BY_CATEGORY.get(cat, "other")
    return kind if kind in kinds else "other"


def _item_type(cat: str, words: str, container: bool) -> str:
    if container:
        return "shelf"
    if cat == "blank":
        return "vent" if re.search(r"\bvent", words) else "blank"
    if cat == "cable-management":
        if "brush" in words:
            return "brush"
        if "lacing" in words:
            return "lacing_bar"
        return "cable_manager"
    return "drawer" if "drawer" in words else "shelf"


def _colour(v: Any) -> str:
    s = _str(v)
    if not _HEX_RE.match(s):
        return ""
    if len(s) == 4:
        s = "#" + "".join(ch * 2 for ch in s[1:])
    return s.lower()


def _weight_kg(dt: Dict[str, Any]) -> Optional[float]:
    w = _num(dt.get("weight"))
    unit = _str(dt.get("weight_unit")).lower() or "kg"
    if w is None or w < 0 or unit not in _WEIGHT_KG:
        return None
    return round(w * _WEIGHT_KG[unit], 2)


def _u_height(dt: Dict[str, Any], tpl: Optional[Dict[str, Any]]) -> int:
    h = _num(dt.get("u_height"))
    if h is None and tpl and isinstance(tpl.get("ru"), int):
        h = float(tpl["ru"])
    return max(1, int(math.ceil((h or 1) - 1e-9)))


def _cells(dt: Dict[str, Any]) -> List[str]:
    slots = _dict_list(dt.get("slots"))

    def key(s: Dict[str, Any]) -> Tuple[float, float]:
        p = s.get("position") if isinstance(s.get("position"), dict) else {}
        return (_num(p.get("row")) or 0.0, _num(p.get("col")) or 0.0)

    out: List[str] = []
    for s in sorted(slots, key=key):
        out.append(_str(s.get("id")))
    return out


def _ports(dt: Dict[str, Any], placed: Dict[str, Any], tpl: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..library import expand_port_groups
    from .netbox_devicetype import SIGNAL_MEDIUM, port_groups, port_kind

    interfaces = _dict_list(dt.get("interfaces"))
    if not interfaces:
        interfaces = [{"name": p.get("template_name") or p.get("name"), "type": p.get("type"), "direction": p.get("direction"),
                       "signal_type": p.get("signal_type")} for p in _dict_list(placed.get("ports"))]
    entries: List[Dict[str, Any]] = []
    for c in interfaces:
        dir_ = {"input": "in", "output": "out"}.get(_str(c.get("direction")), "io")
        pk = port_kind("interfaces", _str(c.get("type")), dir_)
        if pk is None:
            continue
        medium = SIGNAL_MEDIUM.get(_str(c.get("signal_type")), pk[0])
        entries.append({"name": _str(c.get("name")), "section": "interfaces", "medium": medium, "dir": dir_, "connector": pk[1]})
    if not entries and tpl and tpl.get("ports"):
        return expand_port_groups(tpl["ports"])
    for section, key, dir_ in (("power-ports", "power_ports", "in"), ("power-outlets", "power_outlets", "out")):
        for c in _dict_list(dt.get(key)):
            pk = port_kind(section, _str(c.get("type")), dir_)
            if pk:
                entries.append({"name": _str(c.get("name")), "section": section, "medium": pk[0], "dir": dir_, "connector": pk[1]})
    if not entries:
        return []
    ports = expand_port_groups(port_groups(entries))
    for p in ports:
        p["origin"] = "user"
    return ports


def _power_w(dt: Dict[str, Any]) -> Optional[float]:
    draws = [_num(p.get("allocated_draw")) for p in _dict_list(dt.get("power_ports"))]
    total = sum(d for d in draws if d and d > 0)
    return round(total, 1) if total else None


def _unique(base: str, used: Set[str], limit: int = 100) -> str:
    base = base[:limit].strip("-") or "item"
    cand, n = base, 2
    while cand in used:
        cand = f"{base[:limit - 1 - len(str(n))]}-{n}"
        n += 1
    used.add(cand)
    return cand


def _room(doc: Doc, payload: Dict[str, Any]) -> str:
    rooms = {r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict)}
    want = _str(payload.get("room"))
    if want and want in rooms:
        return want
    try:
        from ..schema import default_room_id

        return default_room_id(doc) or ""
    except Exception:
        return next((str(r) for r in rooms if r), "")


def _cells_of(face: str, depth: str, side: str) -> List[Tuple[str, str]]:
    faces = ("front", "rear") if depth == "full" else (face,)
    sides = ("left", "right") if side == "full" else (side,)
    return [(f, s) for f in faces for s in sides]


def _collisions(rack_name: str, units: int, blocks: List[Dict[str, Any]], warnings: List[str]) -> None:
    taken: Dict[Tuple[int, str, str], str] = {}
    seen: Set[Tuple[str, str, str]] = set()
    for b in blocks:
        for u in range(b["u"], b["u"] + b["height"]):
            for face, side in _cells_of(b["face"], b["depth"], b["side"]):
                other = taken.get((u, face, side))
                if other is None:
                    taken[(u, face, side)] = b["label"]
                elif other != b["label"] and (other, b["label"], face) not in seen:
                    seen.add((other, b["label"], face))
                    warnings.append(f"{rack_name}: {other} and {b['label']} overlap at U{u} ({face})")


def _build(doc: Doc, layout: Dict[str, Any], payload: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    from ..model import norm_name, slug

    kinds = _kinds()
    item_defaults = _item_defaults()
    types: Dict[str, Dict[str, Any]] = {}
    for dt in layout["device_types"]:
        s = _str(dt.get("slug"))
        if s and s not in types:
            types[s] = dt
    room = _room(doc, payload)
    doc_racks = [r for r in doc.get("racks") or [] if isinstance(r, dict)]
    rack_ids = {str(r.get("id")) for r in doc_racks}
    rack_names = {norm_name(_str(r.get("name"))) for r in doc_racks}
    orders = [o for o in (_num(r.get("order")) for r in doc_racks) if o is not None]
    order_base = int(max(orders)) + 1 if orders else 0
    dev_ids = {str(d.get("id")) for d in doc.get("devices") or [] if isinstance(d, dict)}
    reusable: Dict[str, List[Dict[str, Any]]] = {}
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id") and not (isinstance(d.get("rack"), dict) and d["rack"].get("id")):
            reusable.setdefault(norm_name(_str(d.get("name"))), []).append(d)
    row_of: Dict[str, str] = {}
    for g in layout["rack_groups"]:
        for rid in g["rack_ids"]:
            row_of.setdefault(rid, g["name"] or g["id"])

    rack_ops: List[Dict[str, Any]] = []
    dev_ops: List[Dict[str, Any]] = []
    out_racks: List[Dict[str, Any]] = []
    out_devices: List[Dict[str, Any]] = []
    out_items: List[Dict[str, Any]] = []
    missing_types: Set[str] = set()

    racks_sorted = sorted(enumerate(layout["racks"]), key=lambda x: (_num(x[1].get("position")) if _num(x[1].get("position")) is not None else x[0], x[0]))
    for ordinal, (idx, r) in enumerate(racks_sorted):
        name = _str(r.get("name")) or f"Rack {idx + 1}"
        rid = _unique("rk-" + slug(name)[:56], rack_ids, 64)
        if norm_name(name) in rack_names:
            warnings.append(f"a rack named {name!r} already exists; the import adds another")
        height = r.get("height")
        if not isinstance(height, int) or isinstance(height, bool) or height < 1:
            hf = _num(height)
            height = int(hf) if hf and hf >= 1 else 42
            warnings.append(f"{name}: height {r.get('height')!r} is not a whole number of U; using {height}")
        units = min(height, MAX_UNITS)
        if height > MAX_UNITS:
            warnings.append(f"{name}: {height}U is taller than Fathom's {MAX_UNITS}U limit; clamped to {MAX_UNITS}U")
        rack: Dict[str, Any] = {"id": rid, "name": name, "units": units,
                                "numbering": "top_down" if r.get("desc_units") is True else "bottom_up"}
        if room:
            rack["room"] = room
        su = r.get("starting_unit")
        rack["start_u"] = su if isinstance(su, int) and not isinstance(su, bool) and su >= 0 else 1
        width = r.get("width")
        if width in (10, 19, 21, 23):
            rack["width_in"] = int(width)
        else:
            rack["width_in"] = 19
            if width is not None:
                warnings.append(f"{name}: width {width!r} is not 10, 19, 21 or 23 inches; using 19")
        ff = _str(r.get("form_factor"))
        rack["form_factor"] = FORM_FACTORS.get(ff, "cabinet")
        if ff and ff not in FORM_FACTORS:
            warnings.append(f"{name}: form factor {ff!r} is unknown; using cabinet")
        depth = _num(r.get("depth_mm"))
        if depth and depth > 0:
            rack["depth_mm"] = int(depth) if depth == int(depth) else depth
        bw = _num(r.get("base_weight"))
        if bw and bw > 0:
            rack["weight_kg"] = bw
        if _str(r.get("notes")):
            rack["notes"] = _str(r.get("notes"))
        rack["order"] = order_base + ordinal
        row = row_of.get(_str(r.get("id")), "")
        if row:
            rack["row"] = row

        placed_all = r["devices"]
        by_src = {_str(d.get("id")): d for d in placed_all if _str(d.get("id"))}
        items: List[Dict[str, Any]] = []
        shelf_of: Dict[str, Dict[str, Any]] = {}
        blocks: List[Dict[str, Any]] = []
        shelf_cells: Dict[Tuple[str, int], str] = {}
        rack_devices = 0

        def place(d: Dict[str, Any], dt: Dict[str, Any], tpl: Optional[Dict[str, Any]], label: str) -> Tuple[int, int]:
            h = _u_height(dt, tpl)
            pos = _num(d.get("position")) or 0.0
            u = max(1, int(pos // UNITS_PER_U))
            if h > units:
                warnings.append(f"{name}: {label} is {h}U, taller than the {units}U rack")
                h = units
            if u + h - 1 > units:
                nu = max(1, units - h + 1)
                warnings.append(f"{name}: {label} at U{u} runs past the top of the rack; moved to U{nu}")
                u = nu
            return u, h

        def face_depth(d: Dict[str, Any], dt: Dict[str, Any], default_depth: str, default_face: str = "front") -> Tuple[str, str]:
            f = _str(d.get("face"))
            if f == "both":
                return "front", "full"
            face = f if f in ("front", "rear") else default_face
            if dt.get("is_full_depth") is False:
                return face, "half"
            if dt.get("is_full_depth") is True:
                return face, "full"
            return face, default_depth

        # rack-level accessories first, so their children can find them
        for d in placed_all:
            if d.get("container_id"):
                continue
            slug_ = _str(d.get("device_type"))
            dt = types.get(slug_)
            if dt is None:
                continue
            cat = _str(dt.get("category"))
            cells = _cells(dt)
            if not cells and cat not in _ITEM_CATEGORIES:
                continue
            words = _words(dt, d)
            itype = _item_type(cat, words, bool(cells))
            dh, dface, ddepth = item_defaults.get(itype, (1, "front", "half"))
            label = _str(d.get("name")) or _str(dt.get("model")) or slug_
            u, h = place(d, dt, None, label)
            face, depth = face_depth(d, dt, ddepth, dface)
            item: Dict[str, Any] = {"id": f"ri-{len(items) + 1}", "type": itype, "u": u, "height": h, "face": face, "depth": depth}
            if label:
                item["label"] = label
            colour = _colour(d.get("colour_override"))
            if colour:
                item["color"] = colour
            if itype == "shelf" and cells:
                item["slots"] = min(len(cells), _MAX_SHELF_SLOTS)
                if len(cells) > _MAX_SHELF_SLOTS:
                    warnings.append(f"{name}: {label} has {len(cells)} cells; Fathom shelves hold {_MAX_SHELF_SLOTS}")
            w = _weight_kg(dt)
            if w:
                item["weight_kg"] = w
            if _str(d.get("notes")):
                item["notes"] = _str(d.get("notes"))
            items.append(item)
            if itype == "shelf":
                shelf_of[_str(d.get("id"))] = {"item": item, "cells": cells}
            blocks.append({"u": u, "height": h, "face": face, "depth": depth, "side": "full", "label": label or item["id"]})
            out_items.append({"rack": rid, "id": item["id"], "type": itype, "u": u, "height": h, "face": face,
                              "depth": depth, "label": item.get("label", ""), "slots": item.get("slots")})

        for d in placed_all:
            slug_ = _str(d.get("device_type"))
            dt = types.get(slug_)
            if d.get("container_id") is None or d.get("container_id") == "":
                if dt is not None and (_cells(dt) or _str(dt.get("category")) in _ITEM_CATEGORIES):
                    continue
            tpl = _template(slug_, doc)
            if dt is None:
                if slug_ not in missing_types:
                    missing_types.add(slug_)
                    warnings.append(f"device type {slug_!r} is not in the layout" + ("; using the library template" if tpl else ""))
                dt = {"slug": slug_, "model": (tpl or {}).get("model") or slug_, "manufacturer": (tpl or {}).get("manufacturer"),
                      "u_height": (tpl or {}).get("ru"), "category": _str((tpl or {}).get("rack_category")) or "other"}
            label = _str(d.get("name")) or _str(dt.get("model")) or slug_ or "Device"
            dev_name = label
            rk: Optional[Dict[str, Any]] = None
            colour = _colour(d.get("colour_override"))
            container = _str(d.get("container_id"))
            if container:
                shelf = shelf_of.get(container)
                if shelf is None:
                    what = "is not a container" if container in by_src else "is missing"
                    warnings.append(f"{name}: {label} sits in a container that {what}; left unracked")
                else:
                    item, cells = shelf["item"], shelf["cells"]
                    sid = _str(d.get("slot_id"))
                    slot = cells.index(sid) if sid in cells else -1
                    if slot < 0:
                        slot = next((i for i in range(len(cells)) if (item["id"], i) not in shelf_cells), 0)
                        warnings.append(f"{name}: {label} names an unknown cell {sid!r}; put in cell {slot + 1}")
                    if slot >= int(item.get("slots") or 2):
                        warnings.append(f"{name}: {label} is in cell {slot + 1} of {item.get('label', item['id'])}, past its {item.get('slots')} slots; left unracked")
                    else:
                        if (item["id"], slot) in shelf_cells:
                            warnings.append(f"{name}: {label} and {shelf_cells[(item['id'], slot)]} share cell {slot + 1} of {item.get('label', item['id'])}")
                        else:
                            shelf_cells[(item["id"], slot)] = label
                        rk = {"id": rid, "u": item["u"], "height": 1, "face": item["face"], "side": "full",
                              "shelf": item["id"], "slot": slot}
            else:
                u, h = place(d, dt, tpl, label)
                face, depth = face_depth(d, dt, "full")
                side = _str(d.get("slot_position"))
                side = side if side in ("left", "right") else "full"
                rk = {"id": rid, "u": u, "height": h, "face": face, "depth": depth, "side": side}
                blocks.append({"u": u, "height": h, "face": face, "depth": depth, "side": side, "label": label})
            if rk is not None and colour:
                rk["color"] = colour
            if rk is not None:
                rack_devices += 1
            existing = None
            pool = reusable.get(norm_name(dev_name))
            if pool and norm_name(dev_name):
                existing = pool.pop(0)
            if existing is not None:
                did = str(existing["id"])
                patch: Dict[str, Any] = {"rack": rk}
                for k, v in (("manufacturer", _str(dt.get("manufacturer"))), ("model", _str(dt.get("model"))),
                             ("template", (tpl or {}).get("id") if tpl else "")):
                    if v and not existing.get(k):
                        patch[k] = v
                if rk is not None:
                    dev_ops.append({"op": "merge", "coll": "devices", "id": did, "value": patch})
                kind = str(existing.get("kind") or "other")
                model = _str(existing.get("model")) or _str(dt.get("model"))
                manufacturer = _str(existing.get("manufacturer")) or _str(dt.get("manufacturer"))
                tid = str(existing.get("template") or patch.get("template") or "")
            else:
                did = _unique(slug(dev_name), dev_ids)
                kind = _kind(dt, d, tpl, kinds)
                manufacturer, model = _str(dt.get("manufacturer")), _str(dt.get("model"))
                tid = str(tpl["id"]) if tpl and tpl.get("id") else ""
                dev: Dict[str, Any] = {"id": did, "name": dev_name, "kind": kind}
                if room:
                    dev["room"] = room
                if manufacturer:
                    dev["manufacturer"] = manufacturer
                if model:
                    dev["model"] = model
                if tid:
                    dev["template"] = tid
                dev["ports"] = _ports(dt, d, tpl)
                if rk is not None:
                    dev["rack"] = rk
                w = _weight_kg(dt)
                if w:
                    dev["weight_kg"] = w
                pw = _power_w(dt)
                if pw:
                    dev["power_w"] = pw
                if _str(d.get("notes")):
                    dev["note"] = _str(d.get("notes"))
                dev_ops.append({"op": "put", "coll": "devices", "id": did, "value": dev})
            out_devices.append({
                "id": did, "name": dev_name, "kind": kind, "manufacturer": manufacturer, "model": model, "template": tid,
                "rack": rid if rk else "", "u": (rk or {}).get("u"), "height": (rk or {}).get("height"),
                "face": (rk or {}).get("face", ""), "shelf": (rk or {}).get("shelf", ""), "slot": (rk or {}).get("slot"),
                "new": existing is None,
            })
        if items:
            rack["items"] = items
        _collisions(name, units, blocks, warnings)
        rack_ops.append({"op": "put", "coll": "racks", "id": rid, "value": rack})
        out_racks.append({"id": rid, "name": name, "units": units, "width_in": rack["width_in"],
                          "form_factor": rack["form_factor"], "row": rack.get("row", ""), "order": rack["order"],
                          "devices": rack_devices, "items": len(items), "source": _str(r.get("id"))})
    ops = rack_ops + dev_ops
    _check_ops(doc, ops, warnings)
    return {
        "layout": {"name": layout["name"], "version": layout["version"], "format": layout["format"]},
        "racks": out_racks, "devices": out_devices, "items": out_items, "warnings": warnings, "ops": ops,
    }


def _check_ops(doc: Doc, ops: List[Dict[str, Any]], warnings: List[str]) -> None:
    try:
        from ..schema import apply_ops, validate_doc
    except Exception:
        return
    try:
        new, touched = apply_ops(doc, ops)
    except Exception as exc:
        warnings.append(f"the import does not apply cleanly: {exc}")
        return
    for p in validate_doc(new):
        if p.get("level") == "error" and p.get("ref") in touched:
            warnings.append(f"{p.get('ref')}: {p.get('message')}")


def preview(doc: Doc, payload: Dict[str, Any]) -> Dict[str, Any]:
    """What importing the Rackula layout in ``payload`` into ``doc`` creates:
    ``{layout, racks, devices, items, warnings, ops}``. Raises ValueError on unreadable input."""
    warnings: List[str] = []
    layout = read_layout(payload, warnings)
    if layout.get("migrate"):
        warnings.append(f"layout version {layout['version'] or '(none)'} uses whole-U positions; converted")
    return _build(doc if isinstance(doc, dict) else {}, layout, payload, warnings)
