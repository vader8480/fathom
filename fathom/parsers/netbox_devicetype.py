"""NetBox device-type YAML <-> Fathom equipment templates (§4.5).

``to_template(text)`` reads a device type from the NetBox devicetype-library
format (manufacturer, model, slug, part_number, u_height, is_full_depth,
airflow, weight + weight_unit, comments and the interfaces, console-ports,
power-ports, power-outlets, front-ports, rear-ports and port-mappings
component lists) and returns a template that passes
``fathom.library.validate_template``. Components become port groups (§4.4.3):
consecutive ports of the same type whose names end in consecutive numbers
collapse into one numbered group.

``from_template(t)`` writes the reverse. A port whose medium, direction or
connector the NetBox type cannot express carries a
``description: "fathom: medium=… dir=… connector=…"`` hint that
``to_template`` reads back, so template -> YAML -> template keeps the ports.

The interface-type table (``port_kind``) and the grouping (``port_groups``)
are shared with the Rackula importer.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from . import mini_yaml

__all__ = ["to_template", "from_template", "port_kind", "port_groups", "kind_from_keywords", "AIRFLOWS", "SIGNAL_MEDIUM"]

AIRFLOWS = ("front-to-rear", "rear-to-front", "left-to-right", "right-to-left", "side-to-rear", "passive", "mixed")
_EXTENSION_KEYS = ("full_depth", "airflow", "part_number", "rack_category")
_WEIGHT_KG = {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523125}
_MAX_TEXT = 2 * 1024 * 1024
_MAX_GROUP = 512

#: Default group names when a component's name is only a number.
_SECTION_GROUP = {
    "interfaces": "Port", "console-ports": "Console", "power-ports": "Power In", "power-outlets": "Outlet",
    "front-ports": "Front", "rear-ports": "Rear",
}
#: Prefix used to keep group names unique when two sections reuse a name.
_SECTION_PREFIX = {
    "interfaces": "Net", "console-ports": "Console", "power-ports": "Power", "power-outlets": "Outlet",
    "front-ports": "Front", "rear-ports": "Rear",
}

# ------------------------------------------------------- connector tables

_POWER_IN = {
    "iec-60320-c6": "IEC C6", "iec-60320-c8": "IEC C8", "iec-60320-c14": "IEC C14", "iec-60320-c16": "IEC C16",
    "iec-60320-c18": "IEC C18", "iec-60320-c20": "IEC C20", "iec-60320-c22": "IEC C22",
    "nema-5-15p": "Edison 5-15", "nema-5-20p": "Edison 5-20", "nema-l5-20p": "L5-20",
    "neutrik-powercon-20": "powerCON", "neutrik-powercon-32": "powerCON 32A", "neutrik-powercon-true1": "powerCON TRUE1",
    "neutrik-powercon-true1-top": "powerCON TRUE1 TOP", "hardwired": "hardwired",
}
_POWER_OUT = {
    "iec-60320-c5": "IEC C5", "iec-60320-c7": "IEC C7", "iec-60320-c13": "IEC C13", "iec-60320-c15": "IEC C15",
    "iec-60320-c17": "IEC C17", "iec-60320-c19": "IEC C19", "iec-60320-c21": "IEC C21",
    "nema-5-15r": "Edison 5-15", "nema-5-20r": "Edison 5-20", "nema-l5-20r": "L5-20",
    "neutrik-powercon-20a": "powerCON", "neutrik-powercon-32a": "powerCON 32A", "neutrik-powercon-true1": "powerCON TRUE1",
    "neutrik-powercon-true1-top": "powerCON TRUE1 TOP", "hardwired": "hardwired",
}
_USB = {
    "usb-a": "USB-A", "usb-b": "USB-B", "usb-c": "USB-C", "usb-mini-a": "USB mini-A", "usb-mini-b": "USB mini-B",
    "usb-micro-a": "USB micro-A", "usb-micro-b": "USB micro-B", "usb-micro-ab": "USB micro-AB", "usb-3-b": "USB-B",
    "usb-3-micro-b": "USB micro-B",
}
_CONSOLE = {"de-9": "DB9", "db-25": "DB25", "rj-11": "RJ11", "rj-12": "RJ12", "rj-45": "RJ45", "mini-din-8": "mini-DIN 8"}
_FIBER = {
    "lc": "LC", "sc": "SC", "st": "ST", "fc": "FC", "mpo": "MPO", "mtrj": "MT-RJ", "cs": "CS", "sn": "SN", "mu": "MU",
    "lsh": "LSH", "lx5": "LX.5", "mdc": "MDC", "sma-905": "SMA", "sma-906": "SMA",
}
#: Rackula (and NetBox) interface types beyond Ethernet: (medium, connector).
_AV_TYPES = {
    "xlr-3": ("analog", "XLR3"), "trs-1-4": ("analog", 'TRS 1/4"'), "ts-1-4": ("analog", 'TS 1/4"'),
    "rca": ("analog", "RCA"), "adat-optical": ("adat", "TOSLINK"), "midi-din": ("midi", "DIN5"), "bnc": ("sync", "BNC"),
    "db25-audio": ("analog", "DB25"), "phoenix": ("analog", "Phoenix"), "speakon": ("speaker", "NL4"),
    "xlr-5": ("dmx", "XLR5"), "dmx-xlr": ("dmx", "XLR5"), "displayport": ("displayport", "DP"), "hdmi": ("hdmi", "HDMI-A"),
    "sdi-bnc": ("sdi", "BNC"), "vga": ("video", "VGA"), "rs-232": ("rs232", "DB9"), "rs-422": ("rs422", "Phoenix"),
    "aes3": ("aes3", "XLR3"), "avb": ("avb", "etherCON"), "dante": ("dante", "RJ45"), "console": ("rs232", "RJ45"),
    "management": ("network", "RJ45"), "other": ("other", ""),
}
SIGNAL_MEDIUM = {
    "analog-audio-mic": "analog", "analog-audio-line": "analog", "analog-audio-speaker": "speaker",
    "digital-audio-aes3": "aes3", "digital-audio-dante": "dante", "digital-audio-avb": "avb",
    "digital-video-hdmi": "hdmi", "digital-video-sdi": "sdi", "clock-word": "sync", "control-midi": "midi",
}
_SKIP_INTERFACES = ("virtual", "lag", "bridge")
_IN_WORDS = frozenset({"in", "input", "inputs"})
_OUT_WORDS = frozenset({"out", "output", "outputs"})


def _sfp_connector(t: str) -> str:
    if "qsfp28" in t:
        return "QSFP28"
    if "qsfp" in t or "osfp" in t or "cfp" in t or "cdfp" in t:
        return "QSFP"
    if "sfp28" in t or "sfp56" in t or "sfp112" in t or "sfpdd" in t:
        return "SFP28"
    if "sfpp" in t or "xfp" in t or "xenpak" in t or "-x2" in t:
        return "SFP+"
    return "SFP"


def _xlr(connector: str, dir_: str) -> str:
    if connector in ("XLR3", "XLR5"):
        return connector + ("M" if dir_ == "out" else "F")
    return connector


def port_kind(section: str, ptype: str, dir_: str = "io") -> Optional[Tuple[str, str]]:
    """``(medium, connector)`` for a NetBox/Rackula component type, or None to skip it."""
    t = str(ptype or "").strip().lower()
    if section == "power-ports":
        if t == "dc-terminal" or t.startswith(("molex", "saf-")):
            return "power_dc", "terminal" if t == "dc-terminal" else ""
        if t in _USB:
            return "power_dc", _USB[t]
        return "power", _POWER_IN.get(t, t.upper() if t and t != "other" else "")
    if section == "power-outlets":
        if t == "dc-terminal" or t.startswith(("molex", "saf-")):
            return "power_dc", "terminal" if t == "dc-terminal" else ""
        if t in _USB:
            return "power_dc", _USB[t]
        return "power", _POWER_OUT.get(t, t.upper() if t and t != "other" else "")
    if section in ("console-ports", "console-server-ports"):
        if t in _USB:
            return "usb", _USB[t]
        return "rs232", _CONSOLE.get(t, "")
    if section in ("front-ports", "rear-ports"):
        if re.match(r"^\d+p\d+c$", t) or t in ("gg45", "mrj21") or t.startswith("tera-"):
            return "network", "RJ45" if t.startswith("8p") else ""
        if t == "110-punch":
            return "network", "terminal"
        if t == "bnc":
            return "sdi", "BNC"
        if t in ("f", "n"):
            return "rf", "F-type" if t == "f" else ""
        if t in _USB:
            return "usb", _USB[t]
        if t == "splice":
            return "fiber", ""
        base = t.split("-")[0]
        if base in _FIBER:
            return "fiber", _FIBER[base]
        if t in _AV_TYPES:
            m, c = _AV_TYPES[t]
            return m, _xlr(c, dir_)
        return "other", ""
    # interfaces (NetBox and Rackula)
    if not t or t in _SKIP_INTERFACES or t.startswith(("ieee802.11", "ieee802.15", "other-wireless", "gsm", "cdma", "lte", "4g", "5g")):
        return None if t else ("network", "RJ45")
    if t in _AV_TYPES:
        m, c = _AV_TYPES[t]
        return m, _xlr(c, dir_)
    if t in _USB:
        return "usb", _USB[t]
    if "-x-" in t or "sfp" in t or "qsfp" in t:
        return "fiber", _sfp_connector(t)
    if re.search(r"base-(t|tx|t1)$", t):
        return "network", "RJ45"
    if re.search(r"base-(cr|cx|cu|kx|kr)", t):
        return "network", ""
    if "base-" in t:
        return "fiber", "LC"
    if t.startswith(("xdsl", "docsis", "t1", "e1", "t3", "e3", "sonet", "pon", "gpon", "xg")):
        return "network", ""
    return "other", ""


def _name_dir(name: str) -> str:
    words = set(re.split(r"[^a-z0-9]+", (name or "").lower()))
    if words & _IN_WORDS and not words & _OUT_WORDS:
        return "in"
    if words & _OUT_WORDS and not words & _IN_WORDS:
        return "out"
    return "io"


# ------------------------------------------------------------ grouping

_NUM_RE = re.compile(r"^(.*?)[\s_./:-]*(\d+)$")


def _split_num(name: str) -> Tuple[str, Optional[int]]:
    m = _NUM_RE.match(name.strip())
    if not m or len(m.group(2)) > 6:
        return name.strip(), None
    return m.group(1).strip(), int(m.group(2))


def port_groups(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Port groups (§4.4.3) from ordered component entries.

    Each entry is ``{name, section, medium, dir, connector?, label?, channels?}``.
    Consecutive entries of one section, medium, direction and connector whose
    names share a prefix and end in consecutive numbers become one numbered
    group; anything else is a single-port group named after the entry. Group
    names are made unique across sections so the expanded port ids are too.
    """
    runs: List[Dict[str, Any]] = []
    for e in entries:
        name = str(e.get("name") or "").strip()
        prefix, num = _split_num(name) if name else ("", None)
        key = (e.get("section", ""), prefix, e["medium"], e.get("dir", "io"), e.get("connector") or "", int(e.get("channels") or 1))
        cur = runs[-1] if runs else None
        if (cur is not None and num is not None and cur["key"] == key and cur["nums"]
                and cur["nums"][-1] is not None and num == cur["nums"][-1] + 1 and len(cur["nums"]) < _MAX_GROUP):
            cur["nums"].append(num)
            cur["raw"].append(name)
            cur["labels"].append(e.get("label") or "")
            continue
        runs.append({"key": key, "name": name, "nums": [num], "raw": [name], "labels": [e.get("label") or ""], "section": e.get("section", "")})
    groups: List[Dict[str, Any]] = []
    for r in runs:
        section, prefix, medium, dir_, connector, channels = r["key"]
        g: Dict[str, Any] = {}
        nums = r["nums"]
        tail_names: List[str] = []
        if len(nums) > 1 and " " in prefix and all(rn == f"{prefix}{n}" for rn, n in zip(r["raw"], nums)):
            # "RF Out Ch1", "RF Out Ch2": group "RF Out", names "Ch1", "Ch2" keep the names and ids exact
            prefix, tail = prefix.rsplit(" ", 1)
            tail_names = [f"{tail}{n}" for n in nums]
        if len(nums) == 1 and nums[0] is not None:
            g["group"] = r["name"] if prefix else f"{_SECTION_GROUP.get(section, 'Port')} {nums[0]}"
            nums = [None]
        elif nums[0] is None:
            g["group"] = r["name"] or _SECTION_GROUP.get(section, "Port")
        else:
            g["group"] = prefix or _SECTION_GROUP.get(section, "Port")
        g["dir"] = dir_
        g["medium"] = medium
        if connector:
            g["connector"] = connector
        if nums[0] is not None:
            if tail_names:
                g["names"] = tail_names
            elif nums[0] == 0:
                g["names"] = [str(n) for n in nums]
            else:
                if len(nums) > 1:
                    g["count"] = len(nums)
                if nums[0] != 1 or len(nums) == 1:
                    g["start"] = nums[0]
        if channels > 1:
            g["channels"] = channels
        labels = r["labels"]
        if any(labels):
            if len(labels) == 1:
                g["label"] = labels[0]
            else:
                g["labels"] = labels
        g["_section"] = section
        groups.append(g)
    return _unique_groups(groups)


def _unique_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..library import expand_port_groups

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for g in groups:
        section = g.pop("_section", "")
        base = g["group"]
        candidates = [base]
        pre = _SECTION_PREFIX.get(section)
        if pre and not base.lower().startswith(pre.lower()):
            candidates.append(f"{pre} {base}")
        k = 2
        while True:
            for cand in candidates:
                g["group"] = cand
                ids = {p["id"] for p in expand_port_groups([g])}
                if not ids & seen:
                    break
            else:
                candidates = [f"{base} {k}"]
                k += 1
                continue
            break
        seen |= ids
        out.append(g)
    return out


# ------------------------------------------------------------ heuristics

_KEYWORD_KINDS: Tuple[Tuple[str, str], ...] = (
    (r"\batem\b|switcher|vision mixer", "video_switcher"),
    (r"videohub|video router|smartvideohub", "video_router"),
    (r"hyperdeck|recorder", "recorder"),
    (r"amplifier|\bamp\b|\bamps\b|power amp", "amp"),
    (r"\bdsp\b|processor", "processor"),
    (r"encoder|streaming|web presenter", "encoder"),
    (r"wireless receiver|\breceiver\b", "wireless_rx"),
)
_NETWORK_KEYWORDS = r"router|gateway|firewall|security appliance|\bfortigate\b"


def kind_from_keywords(text: str) -> str:
    """An AV kind from model keywords (ATEM -> video_switcher, …), or ''."""
    low = (text or "").lower()
    for pat, kind in _KEYWORD_KINDS:
        if re.search(pat, low):
            return kind
    return ""


def _kind(dt: Dict[str, Any], interfaces: int) -> str:
    words = " ".join(str(dt.get(k) or "") for k in ("model", "part_number", "slug", "description"))
    if dt.get("power-outlets"):
        return "power"
    av = kind_from_keywords(words)
    if av:
        return av
    if dt.get("front-ports"):
        return "patch_panel"
    if dt.get("rear-ports") and (dt.get("is_powered") is False or not dt.get("power-ports")):
        return "patch_panel"
    if re.search(_NETWORK_KEYWORDS, words.lower()):
        return "network"
    if interfaces >= 8:
        return "switch"
    return "other"


_RACK_CATEGORY = {
    "power": "power", "patch_panel": "patch-panel", "switch": "network", "network": "network", "computer": "server",
    "video_switcher": "av-media", "video_router": "av-media", "recorder": "av-media", "amp": "av-media",
    "processor": "av-media", "encoder": "av-media", "wireless_rx": "av-media", "video": "av-media",
}

_HINT_VAL = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
_HINT_RE = re.compile(r"fathom:\s*((?:\w+=" + _HINT_VAL + r"\s*)+)")


def _hint(desc: Any) -> Dict[str, str]:
    m = _HINT_RE.search(str(desc or ""))
    if not m:
        return {}
    out = {}
    for k, v in re.findall(r"(\w+)=(" + _HINT_VAL + ")", m.group(1)):
        out[k] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
    return out


def _hint_val(v: str) -> str:
    if v and not re.search(r"[\s\"']", v):
        return v
    return f"'{v}'" if '"' in v else f'"{v}"'


# ------------------------------------------------------------ to_template


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _entries(dt: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """Component entries in section order plus the count of physical data interfaces."""
    entries: List[Dict[str, Any]] = []
    n_if = 0
    mapped_rear: Dict[str, int] = {}
    for fp in _as_list(dt.get("front-ports")):
        if fp.get("rear_port"):
            mapped_rear[str(fp["rear_port"])] = mapped_rear.get(str(fp["rear_port"]), 0) + 1
    for pm in _as_list(dt.get("port-mappings")):
        if pm.get("rear_port"):
            mapped_rear[str(pm["rear_port"])] = mapped_rear.get(str(pm["rear_port"]), 0) + 1
    passive = bool(dt.get("front-ports"))
    for section in ("interfaces", "console-ports", "console-server-ports", "power-ports", "power-outlets", "front-ports", "rear-ports"):
        for c in _as_list(dt.get(section)):
            name = str(c.get("name") or "").strip()
            if section == "rear-ports" and passive and mapped_rear.get(name) == 1 and int(c.get("positions") or 1) <= 1:
                continue  # the far side of a straight-through front port: one Fathom port
            hint = _hint(c.get("description"))
            if section == "power-ports":
                dir_ = "in"
            elif section == "power-outlets":
                dir_ = "out"
            elif section in ("front-ports", "rear-ports") and not passive:
                dir_ = _name_dir(name)
            else:
                dir_ = "io"
            if hint.get("dir") in ("in", "out", "io"):
                dir_ = hint["dir"]
            pk = port_kind(section, str(c.get("type") or ""), dir_)
            if pk is None:
                continue
            medium, connector = pk
            if section == "interfaces" and not c.get("mgmt_only"):
                n_if += 1
            if hint.get("medium"):
                medium = hint["medium"]
            if "connector" in hint:
                connector = hint["connector"]
            e: Dict[str, Any] = {"name": name, "section": section, "medium": medium, "dir": dir_, "connector": connector}
            if c.get("label"):
                e["label"] = str(c["label"])
            if hint.get("channels", "").isdigit() and int(hint["channels"]) > 1:
                e["channels"] = int(hint["channels"])
            entries.append(e)
    return entries, n_if


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _template_id(dt: Dict[str, Any]) -> str:
    from ..library import ID_RE
    from ..model import slug

    for cand in (str(dt.get("slug") or ""), slug(f"{dt.get('manufacturer', '')} {dt.get('model', '')}")):
        cand = cand.strip().lower().replace("_", "-")[:80].strip("-")
        if ID_RE.match(cand):
            return cand
    return "netbox-" + slug(str(dt.get("model") or "device"))[:72]


def to_template(text: Any, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fathom template (§4.5) from NetBox device-type YAML (or an already parsed dict).
    ``warnings`` (a list) collects notes about what was approximated.
    Raises ValueError with a readable message when the input is not a device type."""
    from ..library import validate_template
    from ..model import slug
    from ..vocab import BRANDS

    notes = warnings if warnings is not None else []
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8-sig", errors="replace")
    if isinstance(text, str):
        if len(text) > _MAX_TEXT:
            raise ValueError("the device type file is too large")
        try:
            dt = mini_yaml.loads(text)
        except ValueError as exc:
            raise ValueError(f"not readable as YAML: {exc}")
    else:
        dt = text
    if not isinstance(dt, dict):
        raise ValueError("a NetBox device type is a YAML mapping with manufacturer, model and slug")
    manufacturer = str(dt.get("manufacturer") or "").strip()
    model = str(dt.get("model") or "").strip()
    if not manufacturer or not model:
        raise ValueError("a NetBox device type needs manufacturer and model")
    entries, n_if = _entries(dt)
    kind = _kind(dt, n_if)
    t: Dict[str, Any] = {"id": _template_id(dt), "manufacturer": manufacturer, "model": model, "name": model, "kind": kind}
    if slug(manufacturer) in BRANDS:
        t["brand"] = slug(manufacturer)
    if dt.get("part_number") not in (None, ""):
        t["part_number"] = str(dt["part_number"])
    uh = _num(dt.get("u_height"))
    if uh is not None and uh > 0:
        ru = int(math.ceil(uh - 1e-9))
        if ru > 60:
            notes.append(f"u_height {dt['u_height']} is above 60; capped")
            ru = 60
        if ru != uh:
            notes.append(f"u_height {dt['u_height']} rounded up to {ru}U")
        t["ru"] = ru
    if isinstance(dt.get("is_full_depth"), bool):
        t["full_depth"] = dt["is_full_depth"]
    if dt.get("airflow"):
        if dt["airflow"] in AIRFLOWS:
            t["airflow"] = dt["airflow"]
        else:
            notes.append(f"airflow {dt['airflow']!r} is not a NetBox value; dropped")
    w = _num(dt.get("weight"))
    if w is not None and w >= 0:
        unit = str(dt.get("weight_unit") or "kg").lower()
        if unit in _WEIGHT_KG:
            t["weight_kg"] = round(w * _WEIGHT_KG[unit], 2)
        else:
            notes.append(f"weight_unit {unit!r} unknown; weight dropped")
    draws = [_num(p.get("allocated_draw")) for p in _as_list(dt.get("power-ports"))]
    if any(d for d in draws if d):
        t["power_w"] = round(sum(d for d in draws if d), 1)
    if _RACK_CATEGORY.get(kind):
        t["rack_category"] = _RACK_CATEGORY[kind]
    t["ports"] = port_groups(entries)
    text_notes = [str(dt.get(k)).strip() for k in ("description", "comments") if str(dt.get(k) or "").strip()]
    if text_notes:
        t["notes"] = "\n\n".join(text_notes)
    t["tags"] = ["netbox"]
    for k in ("module-bays", "device-bays", "inventory-items"):
        if dt.get(k):
            notes.append(f"{k} are not imported")
    errs = validate_template(t)
    if errs:
        stripped = {k: v for k, v in t.items() if k not in _EXTENSION_KEYS}
        if not validate_template(stripped):
            notes.append("dropped " + ", ".join(k for k in _EXTENSION_KEYS if k in t) + " (not accepted by this library version)")
            return stripped
        raise ValueError("; ".join(errs))
    return t


# ---------------------------------------------------------- from_template

_POWER_IN_REV = {v: k for k, v in _POWER_IN.items()}
_POWER_OUT_REV = {v: k for k, v in _POWER_OUT.items()}
_USB_REV = {v: k for k, v in _USB.items() if not k.startswith("usb-3")}
_CONSOLE_REV = {v: k for k, v in _CONSOLE.items()}
_FIBER_REV = {v: k for k, v in _FIBER.items()}
_SFP_TYPES = {"SFP": "1000base-x-sfp", "SFP+": "10gbase-x-sfpp", "SFP28": "25gbase-x-sfp28", "QSFP": "40gbase-x-qsfpp", "QSFP28": "100gbase-x-qsfp28"}
_IP_MEDIA = ("network", "dante", "aes67", "avb", "qlan", "ndi", "st2110", "osc", "sacn", "artnet", "aes50", "snake", "hdbaset")


def _section_and_type(p: Dict[str, Any], kind: str, prev: str = "") -> Tuple[str, str]:
    medium, conn, d = p.get("medium", "other"), p.get("connector") or "", p.get("dir", "io")
    if medium == "power":
        if d == "out":
            return "power-outlets", _POWER_OUT_REV.get(conn, "iec-60320-c13" if not conn else "other")
        return "power-ports", _POWER_IN_REV.get(conn, "iec-60320-c14" if not conn else "other")
    if medium == "power_dc":
        t = _USB_REV.get(conn) or "dc-terminal"
        return ("power-outlets" if d == "out" else "power-ports"), t
    if medium == "rs232":
        return "console-ports", _CONSOLE_REV.get(conn, "rj-45" if not conn else "other")
    if medium == "usb":
        return "console-ports", _USB_REV.get(conn, "usb-c" if not conn else "other")
    if kind == "patch_panel":
        return "front-ports", _rear_type(medium, conn)
    if medium in _IP_MEDIA:
        if conn in _SFP_TYPES:
            return "interfaces", _SFP_TYPES[conn]
        return "interfaces", "1000base-t"
    if medium == "fiber" and conn in _SFP_TYPES:
        return "interfaces", _SFP_TYPES[conn]
    if medium == "other" and not conn:
        # both sections read type "other" back as medium other; keep the port's neighbours
        return ("rear-ports", "other") if prev == "rear-ports" else ("interfaces", "other")
    return "rear-ports", _rear_type(medium, conn)


def _rear_type(medium: str, conn: str) -> str:
    if conn in ("RJ45", "etherCON") or (medium == "network" and not conn):
        return "8p8c"
    if conn in ("BNC", "HD-BNC"):
        return "bnc"
    if conn == "F-type":
        return "f"
    if conn in _FIBER_REV:
        return _FIBER_REV[conn]
    if conn in _USB_REV:
        return _USB_REV[conn]
    if medium == "fiber":
        return "lc"
    return "other"


def from_template(t: Dict[str, Any]) -> str:
    """NetBox device-type YAML for a Fathom template (the subset ``to_template`` reads)."""
    from ..library import expand_port_groups

    if not isinstance(t, dict) or not t.get("id"):
        raise ValueError("not a template")
    kind = str(t.get("kind") or "other")
    out: Dict[str, Any] = {
        "manufacturer": t.get("manufacturer") or "Generic",
        "model": t.get("model") or t.get("name") or t["id"],
        "slug": t["id"],
    }
    if t.get("part_number"):
        out["part_number"] = str(t["part_number"])
    if isinstance(t.get("ru"), int) and not isinstance(t.get("ru"), bool):
        out["u_height"] = t["ru"]
    if isinstance(t.get("full_depth"), bool):
        out["is_full_depth"] = t["full_depth"]
    if t.get("airflow") in AIRFLOWS:
        out["airflow"] = t["airflow"]
    if _num(t.get("weight_kg")) is not None:
        out["weight"] = t["weight_kg"]
        out["weight_unit"] = "kg"
    if kind == "patch_panel":
        out["is_powered"] = False
    if t.get("notes"):
        out["comments"] = str(t["notes"])
    sections: Dict[str, List[Dict[str, Any]]] = {}
    power_ports: List[str] = []
    mappings: List[Dict[str, Any]] = []
    ports = expand_port_groups(t.get("ports") or [])
    section = ""
    for p in ports:
        section, ptype = _section_and_type(p, kind, section)
        c: Dict[str, Any] = {"name": p.get("name") or p["id"], "type": ptype}
        if p.get("label"):
            c["label"] = str(p["label"])
        if section in ("front-ports", "rear-ports"):
            c["positions"] = 1
        if section == "power-ports":
            power_ports.append(c["name"])
        if section == "interfaces" and re.search(r"\b(management|mgmt)\b", str(p.get("group", "")).lower()):
            c["mgmt_only"] = True
        # what the importer would infer, so only lossy ports carry a hint
        dir_guess = {"power-ports": "in", "power-outlets": "out"}.get(section, "io")
        if section in ("front-ports", "rear-ports") and kind != "patch_panel":
            dir_guess = _name_dir(c["name"])
        guess = port_kind(section, ptype, p.get("dir", "io"))
        hint: List[str] = []
        if guess is None or guess[0] != p.get("medium"):
            hint.append(f"medium={p.get('medium')}")
        if p.get("dir", "io") != dir_guess:
            hint.append(f"dir={p.get('dir', 'io')}")
        if guess is None or (guess[1] or "") != (p.get("connector") or ""):
            hint.append("connector=" + _hint_val(str(p.get("connector") or "")))
        if int(p.get("channels") or 1) > 1:
            hint.append(f"channels={int(p['channels'])}")
        if hint:
            c["description"] = "fathom: " + " ".join(hint)
        sections.setdefault(section, []).append(c)
        if section == "front-ports":
            rear = {"name": c["name"], "type": ptype, "positions": 1}
            sections.setdefault("rear-ports", []).append(rear)
            mappings.append({"front_port": c["name"], "front_port_position": 1, "rear_port": c["name"], "rear_port_position": 1})
    for o in sections.get("power-outlets", []):
        if len(power_ports) == 1:
            o["power_port"] = power_ports[0]
    pw = _num(t.get("power_w"))
    if pw and sections.get("power-ports"):
        sections["power-ports"][0]["allocated_draw"] = max(1, int(round(pw)))
    for section in ("interfaces", "console-ports", "power-ports", "power-outlets", "front-ports", "rear-ports"):
        if sections.get(section):
            out[section] = sections[section]
    if mappings:
        out["port-mappings"] = mappings
    return "---\n" + mini_yaml.dumps(out)
