#!/usr/bin/env python3
"""Build Fathom's Rackula device catalog from a Rackula checkout.

Data and images come from Rackula (https://github.com/RackulaLives/Rackula,
MIT licence, Copyright (c) 2026 Gareth Evans). Rackula's device types are
taken from the NetBox community devicetype-library (CC0 1.0), and most of its
device images come from vastoholic/draw-io ("freely shareable"). See
THIRD_PARTY_NOTICES.md and fathom/static/rack-images/README.md.

Usage (stdlib only):

    git clone https://github.com/RackulaLives/Rackula /tmp/rackula
    git -C /tmp/rackula checkout 9c7af6dd28209a776aebdb92080bcf2916cd29e6
    python tools/rackula_catalog.py --src /tmp/rackula

It reads ``src/lib/data/brandPacks/*.ts`` and ``src/lib/data/starterLibrary.ts``
(TypeScript object literals, read with a small literal parser, not executed),
``src/lib/data/bundledImages.ts`` (slug -> image file) and the WebP files
under ``src/lib/assets/device-images/``, and writes
``fathom/library/rackula/catalog.json`` plus the images under
``fathom/static/rack-images/<vendor>/``.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PINNED_COMMIT = "9c7af6dd28209a776aebdb92080bcf2916cd29e6"
SOURCE = "https://github.com/RackulaLives/Rackula"
LICENSE = "MIT (Rackula) / CC0 (NetBox devicetype-library data)"
OUT_JSON = ROOT / "fathom" / "library" / "rackula" / "catalog.json"
OUT_IMAGES = ROOT / "fathom" / "static" / "rack-images"
TEMPLATES_DIR = ROOT / "fathom" / "library" / "templates"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
IMAGE_VENDORS = (
    "_generic", "apc", "eaton", "ac-infinity", "ubiquiti", "netgear", "cisco", "tp-link",
    "mikrotik", "synology", "qnap", "dell", "apple", "lenovo", "supermicro",
)
IMAGE_BUDGET = int(4.5 * 1024 * 1024)
SKIP_CATEGORIES = ("blank", "shelf", "cable-management")
AIRFLOWS = ("front-to-rear", "rear-to-front", "left-to-right", "right-to-left", "side-to-rear", "passive", "mixed")
STARTER_MANUFACTURER = "Generic"

KIND_BY_CATEGORY = {
    "server": "computer", "storage": "computer", "kvm": "computer", "chassis": "computer",
    "network": "switch", "firewall": "network", "patch-panel": "patch_panel", "power": "power",
    "cooling": "other", "other": "other", "av-media": "video",
}
#: Model keywords that win over the Rackula category, first match wins. Rackula
#: files some devices under the brand's main category (a keystone panel under
#: network, KVM switches and console servers under power).
_MODEL_RULES: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"patch\s*panel|keystone", re.I), "patch_panel"),
    # Tripp Lite B096/B097 and Vertiv (Avocent) ACS 8000 are serial console servers.
    (re.compile(r"console server|\bb09[67]-\d|\bacs\d{4}", re.I), "network"),
    # Tripp Lite B040 (console KVM), B064 and B072 (IP KVM).
    (re.compile(r"\bkvm\b|\bb0(?:40|64|72)-\d", re.I), "computer"),
)
_ROUTER_RE = re.compile(
    r"router|gateway|controller|cloud ?key|\budm\b|\budm-|\buxg\b|\buxg-|\busg\b|\busg-|\bccr\d|\brb\d|\bisr\d|\basr\d"
    # Ubiquiti EdgeRouter (ER-X, ER-12, ERPro-8), TP-Link Omada ER routers and OC
    # controllers, TP-Link TD-W DSL modem routers.
    r"|\ber-?\d|\ber-x\b|\berpro|\boc\d{3}\b|\btd-w\d", re.I)
#: Rack servers that Rackula files under network (UniFi Application Server).
_SERVER_RE = re.compile(r"\bserver\b", re.I)
#: Supermicro SSE- Ethernet switches, filed under server.
_SWITCH_IN_SERVER_RE = re.compile(r"\bsse-[a-z]\d", re.I)
#: av-media model keywords, first match wins.
_AV_RULES: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"\batem\b|switcher", re.I), "video_switcher"),
    (re.compile(r"videohub|router", re.I), "video_router"),
    (re.compile(r"hyperdeck|recorder", re.I), "recorder"),
    # An AV receiver is an amplifier with input switching, not a wireless receiver.
    (re.compile(r"amplifier|\bamp\b|\bav receiver\b", re.I), "amp"),
    (re.compile(r"processor|\bdsp\b", re.I), "processor"),
    (re.compile(r"encoder|streaming", re.I), "encoder"),
    (re.compile(r"receiver", re.I), "wireless_rx"),
)

#: Rackula interface type -> (medium, connector for in/io, connector for out, default group label).
_IFACE: Dict[str, Tuple[str, str, str, str]] = {
    "1000base-t": ("network", "RJ45", "RJ45", "Port"),
    "management": ("network", "RJ45", "RJ45", "Management"),
    "xlr-3": ("analog", "XLR3F", "XLR3M", "Analog"),
    "speakon": ("speaker", "NL4", "NL4", "Speaker"),
    "hdmi": ("hdmi", "HDMI-A", "HDMI-A", "HDMI"),
    "sdi-bnc": ("sdi", "BNC", "BNC", "SDI"),
    "dante": ("dante", "RJ45", "RJ45", "Dante"),
    "rs-232": ("rs232", "DB9", "DB9", "RS-232"),
    "aes3": ("aes3", "XLR3F", "XLR3M", "AES3"),
    "rca": ("analog", "RCA", "RCA", "RCA"),
    "trs-1-4": ("analog", 'TRS 1/4"', 'TRS 1/4"', "Analog"),
    "displayport": ("displayport", "DP", "DP", "DisplayPort"),
    "vga": ("video", "VGA", "VGA", "VGA"),
}
_IN_RE = re.compile(r"\b(in|input|inputs)\b", re.I)
_OUT_RE = re.compile(r"\b(out|output|outputs|speaker)\b", re.I)
_NUM_TAIL_RE = re.compile(r"^(.*?)\s*(\d+)$")


# ------------------------------------------------------- TS literal reader

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<line>//[^\n]*)
  | (?P<block>/\*.*?\*/)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\$]|\\.)*`)
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<ident>[A-Za-z_$][\w$]*)
  | (?P<punct>[{}\[\](),:.])
""", re.S | re.X)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _unquote(s: str) -> str:
    body = s[1:-1]
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        n = body[i + 1]
        if n == "u":
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        elif n == "x":
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        else:
            out.append(_ESCAPES.get(n, n))
            i += 2
    return "".join(out)


class LiteralReader:
    """Reads the JS/TS literal value that starts at ``pos`` in ``text``.

    Supports objects (identifier, string or number keys), arrays, strings,
    numbers, true/false/null/undefined, trailing commas, comments, member
    references into ``env`` (``CATEGORY_COLOURS.power``,
    ``CATEGORY_COLOURS["av-media"]``) and calls of functions in ``funcs``.
    Anything else (spreads, expressions, type assertions) is an error.
    """

    def __init__(self, text: str, env: Optional[Dict[str, Any]] = None, funcs: Optional[Dict[str, Any]] = None, name: str = "") -> None:
        self.text = text
        self.env = env or {}
        self.funcs = funcs or {}
        self.name = name
        self.pos = 0
        self.ahead: Optional[Tuple[str, str, int]] = None

    def _lex(self) -> Tuple[str, str, int]:
        n = len(self.text)
        while self.pos < n:
            m = _TOKEN_RE.match(self.text, self.pos)
            if not m:
                self._fail("unexpected character %r" % self.text[self.pos], self.pos)
            start, self.pos = self.pos, m.end()
            kind = m.lastgroup or ""
            if kind not in ("ws", "line", "block"):
                return (kind, m.group(), start)
        return ("eof", "", n)

    def _fail(self, msg: str, pos: int) -> None:
        line = self.text.count("\n", 0, pos) + 1
        raise ValueError("%s:%d: %s" % (self.name or "<ts>", line, msg))

    def _peek(self) -> Tuple[str, str, int]:
        if self.ahead is None:
            self.ahead = self._lex()
        return self.ahead

    def _next(self) -> Tuple[str, str, int]:
        t = self._peek()
        self.ahead = None
        return t

    def _expect(self, val: str) -> None:
        t = self._next()
        if t[1] != val:
            self._fail("expected %r, got %r" % (val, t[1]), t[2])

    def read(self, pos: int) -> Any:
        self.pos, self.ahead = pos, None
        return self._value()

    def _value(self) -> Any:
        kind, val, pos = self._next()
        if val == "{":
            return self._object()
        if val == "[":
            return self._array()
        if kind == "str":
            if val.startswith("`") and "${" in val:
                self._fail("template literal with substitutions", pos)
            return _unquote(val)
        if kind == "num":
            f = float(val)
            return int(f) if re.fullmatch(r"-?\d+", val) else f
        if kind == "ident":
            if val == "true":
                return True
            if val == "false":
                return False
            if val in ("null", "undefined"):
                return None
            return self._reference(val, pos)
        self._fail("unexpected token %r" % val, pos)

    def _reference(self, name: str, pos: int) -> Any:
        if self._peek()[1] == "(":
            fn = self.funcs.get(name)
            if fn is None:
                self._fail("unsupported call %s()" % name, pos)
            self._next()
            args = []
            while self._peek()[1] != ")":
                args.append(self._value())
                if self._peek()[1] == ",":
                    self._next()
            self._next()
            return fn(*args)
        if name not in self.env:
            self._fail("unsupported identifier %r" % name, pos)
        cur = self.env[name]
        while self._peek()[1] in (".", "["):
            if self._next()[1] == ".":
                k, key, kpos = self._next()
                if k != "ident":
                    self._fail("bad member name %r" % key, kpos)
            else:
                key = self._value()
                self._expect("]")
            if not isinstance(cur, dict) or key not in cur:
                self._fail("unknown member %r of %s" % (key, name), pos)
            cur = cur[key]
        return cur

    def _object(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        while True:
            kind, key, pos = self._next()
            if key == "}":
                return out
            if kind == "str":
                key = _unquote(key)
            elif kind not in ("ident", "num"):
                self._fail("bad object key %r" % key, pos)
            self._expect(":")
            out[key] = self._value()
            sep = self._next()
            if sep[1] == "}":
                return out
            if sep[1] != ",":
                self._fail("expected ',' or '}', got %r" % sep[1], sep[2])

    def _array(self) -> List[Any]:
        out: List[Any] = []
        while True:
            if self._peek()[1] == "]":
                self._next()
                return out
            out.append(self._value())
            sep = self._next()
            if sep[1] == "]":
                return out
            if sep[1] != ",":
                self._fail("expected ',' or ']', got %r" % sep[1], sep[2])


def _brace_end(text: str, start: int) -> int:
    """Index just past the ``{...}`` that opens at ``start`` (strings and comments skipped)."""
    depth, i = 0, start
    while i < len(text):
        m = _TOKEN_RE.match(text, i)
        if not m:
            i += 1
            continue
        if m.group() == "{":
            depth += 1
        elif m.group() == "}":
            depth -= 1
            if depth == 0:
                return m.end()
        i = m.end()
    raise ValueError("unbalanced braces")


def read_const_object(text: str, name: str, env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    m = re.search(r"\bconst\s+%s\b[^=]*=\s*\{" % re.escape(name), text)
    if not m:
        raise ValueError("const %s not found" % name)
    return LiteralReader(text, env, name=name).read(m.end() - 1)


def read_device_arrays(text: str, env: Dict[str, Any], funcs: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    """Every ``const <xDevices|STARTER_DEVICES>: T[] = [...]`` array in ``text``."""
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r"\bconst\s+(\w*(?:Devices|DEVICES))\s*:\s*[\w<>]+\[\]\s*=\s*\[", text):
        arr = LiteralReader(text, env, funcs, name=name).read(m.end() - 1)
        out.extend(d for d in arr if isinstance(d, dict))
    return out


def _port_interfaces(count: int, type_: str) -> List[Dict[str, Any]]:
    return [{"name": str(i + 1), "type": type_} for i in range(int(count))]


# ------------------------------------------------------------ the source


def read_source(src: Path) -> Dict[str, Any]:
    data = src / "src" / "lib" / "data"
    colours = read_const_object((src / "src" / "lib" / "types" / "constants.ts").read_text("utf-8"), "CATEGORY_COLOURS")
    env = {"CATEGORY_COLOURS": colours}
    funcs = {"portInterfaces": _port_interfaces}
    devices: List[Tuple[str, Dict[str, Any]]] = []
    starter = data / "starterLibrary.ts"
    for d in read_device_arrays(starter.read_text("utf-8"), env, funcs, starter.name):
        devices.append(("starter", d))
    for f in sorted((data / "brandPacks").glob("*.ts")):
        if f.name == "index.ts":
            continue
        for d in read_device_arrays(f.read_text("utf-8"), env, funcs, f.name):
            devices.append((f.stem, d))
    return {"devices": devices, "images": read_bundled_images(data / "bundledImages.ts"), "colours": colours}


def read_bundled_images(path: Path) -> Dict[str, Dict[str, str]]:
    """slug -> {"front"|"rear": path relative to src/lib/assets/device-images/}."""
    text = path.read_text("utf-8")
    imports = dict(re.findall(r'^import\s+(\w+)\s+from\s+"\$lib/assets/device-images/([^"]+)";', text, re.M))
    m = re.search(r"\bconst\s+BUNDLED_IMAGES\b[^=]*=\s*\{", text)
    if not m:
        raise ValueError("BUNDLED_IMAGES not found in %s" % path)
    body = text[m.end() - 1:_brace_end(text, m.end() - 1)]
    out: Dict[str, Dict[str, str]] = {}
    for key, faces in re.findall(r'(?:"([^"]+)"|\b[\w-]+)\s*:\s*\{([^{}]*)\}', body):
        if not key:
            continue
        entry = {}
        for face, var in re.findall(r"\b(front|rear)\s*:\s*(\w+)", faces):
            if var not in imports:
                raise ValueError("bundledImages: %s.%s refers to unknown import %s" % (key, face, var))
            entry[face] = imports[var]
        out[key] = entry
    return out


# --------------------------------------------------------------- mapping


def sanitize_id(slug: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", str(slug).lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:80].rstrip("-")


def reserved_ids() -> set:
    ids = set()
    for f in TEMPLATES_DIR.glob("*.json"):
        ids.add(f.stem)
        try:
            ids.add(json.loads(f.read_text("utf-8")).get("id") or f.stem)
        except (OSError, ValueError):
            pass
    from fathom import presets

    ids.update(p["id"] for p in presets.all_presets())
    return ids


def kind_for(category: str, model: str) -> str:
    for rx, kind in _MODEL_RULES:
        if rx.search(model):
            return kind
    if category == "network":
        if _ROUTER_RE.search(model):
            return "network"
        if _SERVER_RE.search(model):
            return "computer"
    if category == "server" and _SWITCH_IN_SERVER_RE.search(model):
        return "switch"
    if category == "av-media":
        for rx, kind in _AV_RULES:
            if rx.search(model):
                return kind
    return KIND_BY_CATEGORY.get(category, "other")


def _dir_for(name: str) -> str:
    if _IN_RE.search(name):
        return "in"
    if _OUT_RE.search(name):
        return "out"
    return "io"


def ports_from_interfaces(interfaces: Any) -> List[Dict[str, Any]]:
    """Fathom port groups from Rackula interface templates.

    Consecutive interfaces of one type, direction and base name (the name
    without its trailing number) form one group: ``count`` (+ ``start``) when
    the numbers run consecutively, else ``names``.
    """
    if not isinstance(interfaces, list):
        return []
    runs: List[Dict[str, Any]] = []
    for itf in interfaces:
        if not isinstance(itf, dict):
            continue
        name = str(itf.get("name") or "").strip()
        typ = str(itf.get("type") or "").lower()
        medium, conn_in, conn_out, label = _IFACE.get(typ) or (
            ("fiber", "SFP", "SFP", "SFP") if "sfp" in typ else
            ("network", "RJ45", "RJ45", "Port") if re.search(r"base-t\b", typ) else
            ("other", "", "", "Port"))
        dir_ = _dir_for(name)
        m = _NUM_TAIL_RE.match(name)
        base, num = (m.group(1).strip(), int(m.group(2))) if m else (name, None)
        key = (typ, dir_, base)
        if runs and runs[-1]["key"] == key and num is not None and runs[-1]["nums"][-1] is not None:
            runs[-1]["nums"].append(num)
            runs[-1]["names"].append(name)
            continue
        runs.append({"key": key, "base": base or label, "medium": medium, "dir": dir_,
                     "connector": conn_out if dir_ == "out" else conn_in, "nums": [num], "names": [name]})
    groups: List[Dict[str, Any]] = []
    seen: Counter = Counter()
    for r in runs:
        group = r["base"]
        seen[group] += 1
        if seen[group] > 1:
            group = "%s %d" % (group, seen[group])
        g: Dict[str, Any] = {"group": group, "dir": r["dir"], "medium": r["medium"]}
        if r["connector"]:
            g["connector"] = r["connector"]
        nums = r["nums"]
        if nums[0] is not None and nums == list(range(nums[0], nums[0] + len(nums))):
            if len(nums) > 1 or nums[0] != 1:
                g["count"] = len(nums)
            if nums[0] != 1:
                g["start"] = nums[0]
        elif len(nums) > 1:
            g["names"] = [str(n) for n in nums]
        groups.append(g)
    return groups


def weight_kg(dev: Dict[str, Any]) -> Optional[float]:
    w = dev.get("weight")
    if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
        return None
    factor = {"lb": 0.4536, "lbs": 0.4536, "kg": 1.0, "g": 0.001, "oz": 0.02835}.get(str(dev.get("weight_unit") or "kg").lower())
    if factor is None:
        return None
    return round(w * factor, 1)


def build(src: Path, images_out: Optional[Path] = None) -> Dict[str, Any]:
    """Map the Rackula source to catalog templates; copy images when ``images_out`` is set."""
    from fathom.library import validate_template
    from fathom.vocab import KINDS

    source = read_source(src)
    reserved = reserved_ids()
    img_root = src / "src" / "lib" / "assets" / "device-images"
    skipped: Counter = Counter()
    seen_slugs: set = set()
    seen_ids: set = set()
    renamed: List[str] = []
    copies: Dict[str, Path] = {}
    templates: List[Dict[str, Any]] = []

    starter_models = Counter(d.get("model") for pack, d in source["devices"] if pack == "starter")

    for pack, dev in source["devices"]:
        slug = str(dev.get("slug") or "")
        if not slug or slug in seen_slugs:
            skipped["duplicate slug"] += 1
            continue
        seen_slugs.add(slug)
        category = str(dev.get("category") or "other")
        if category in SKIP_CATEGORIES:
            skipped["category " + category] += 1
            continue
        u = dev.get("u_height")
        if isinstance(u, bool) or not isinstance(u, (int, float)) or u < 1 or int(u) != u:
            skipped["sub-U or fractional height"] += 1
            continue
        tid = sanitize_id(slug)
        if tid in reserved:
            tid = sanitize_id(tid[:77]) + "-rk"
            renamed.append(slug)
        if not ID_RE.match(tid) or tid in seen_ids:
            skipped["bad or duplicate id"] += 1
            continue
        manufacturer = str(dev.get("manufacturer") or STARTER_MANUFACTURER).strip()
        model = str(dev.get("model") or slug).strip()
        if pack == "starter" and starter_models[dev.get("model")] > 1:
            model = "%s (%dU)" % (model, int(u))
        t: Dict[str, Any] = {"id": tid, "manufacturer": manufacturer, "model": model, "name": model}
        if dev.get("part_number"):
            t["part_number"] = str(dev["part_number"])
        t["kind"] = kind_for(category, model)
        t["ru"] = int(u)
        if dev.get("slot_width") == 1:
            t["width"] = "half"
        t["full_depth"] = dev.get("is_full_depth") is not False
        if dev.get("airflow") in AIRFLOWS:
            t["airflow"] = dev["airflow"]
        w = weight_kg(dev)
        if w is not None:
            t["weight_kg"] = w
        t["rack_category"] = category
        for face in ("front", "rear"):
            rel = (source["images"].get(slug) or {}).get(face)
            if not rel:
                continue
            parts = rel.split("/")
            if parts[0] not in IMAGE_VENDORS:
                skipped["image (vendor not bundled)"] += 1
                continue
            target = "%s/%s" % (parts[0], parts[-1])
            if target in copies and copies[target] != img_root / rel:
                raise ValueError("image name clash: %s" % target)
            copies[target] = img_root / rel
            t["image_" + face] = target
        t["ports"] = ports_from_interfaces(dev.get("interfaces"))
        t["tags"] = ["rackula"]
        if t["kind"] not in KINDS:
            raise ValueError("%s: kind %s not in KINDS" % (tid, t["kind"]))
        errs = validate_template(t)
        if errs:
            raise ValueError("%s: %s" % (tid, "; ".join(errs)))
        seen_ids.add(tid)
        templates.append(t)

    templates.sort(key=lambda t: (t["manufacturer"].lower(), t["model"].lower(), t["id"]))
    total = 0
    for target, path in sorted(copies.items()):
        total += path.stat().st_size
    if total > IMAGE_BUDGET:
        raise ValueError("images total %d bytes > budget %d" % (total, IMAGE_BUDGET))
    if images_out is not None:
        write_images(images_out, copies)
    return {"templates": templates, "skipped": skipped, "renamed": renamed, "images": copies, "image_bytes": total}


def write_images(out: Path, copies: Dict[str, Path]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(copies)
    for old in out.glob("*/*.webp"):
        if old.relative_to(out).as_posix() not in wanted:
            old.unlink()
    for target, path in sorted(copies.items()):
        dest = out / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or dest.read_bytes() != path.read_bytes():
            shutil.copyfile(str(path), str(dest))
    for d in out.iterdir():
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


def source_commit(src: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return PINNED_COMMIT


def render_catalog(templates: List[Dict[str, Any]], commit: str, generated: str) -> str:
    head = {"source": SOURCE, "license": LICENSE, "commit": commit, "generated": generated, "count": len(templates)}
    lines = ["{"]
    for k, v in head.items():
        lines.append("  %s: %s," % (json.dumps(k), json.dumps(v, ensure_ascii=False)))
    lines.append('  "templates": [')
    rows = [json.dumps(t, ensure_ascii=False) for t in templates]
    lines.extend("    " + r + ("," if i < len(rows) - 1 else "") for i, r in enumerate(rows))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default="/tmp/rackula", help="Rackula checkout (default /tmp/rackula)")
    ap.add_argument("--out", default=str(OUT_JSON), help="catalog.json path")
    ap.add_argument("--images", default=str(OUT_IMAGES), help="rack-images directory")
    ap.add_argument("--date", default="", help="generated date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    src = Path(args.src)
    if not (src / "src" / "lib" / "data").is_dir():
        ap.error("%s is not a Rackula checkout" % src)
    commit = source_commit(src)
    if commit != PINNED_COMMIT:
        print("warning: %s is at %s, not the pinned %s" % (src, commit, PINNED_COMMIT), file=sys.stderr)
    res = build(src, Path(args.images))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    generated = args.date or datetime.date.today().isoformat()
    out.write_text(render_catalog(res["templates"], commit, generated), encoding="utf-8")

    kinds = Counter(t["kind"] for t in res["templates"])
    print("templates: %d -> %s" % (len(res["templates"]), out))
    for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  kind %-15s %d" % (k, n))
    for why, n in sorted(res["skipped"].items()):
        print("  skipped %-30s %d" % (why, n))
    print("  renamed (-rk): %s" % (", ".join(res["renamed"]) or "none"))
    print("images: %d files, %.2f MB -> %s" % (len(res["images"]), res["image_bytes"] / 1048576.0, args.images))
    return 0


if __name__ == "__main__":
    sys.exit(main())
