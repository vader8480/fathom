"""Data model v2: the project *doc* (plain dicts), migration from v1, the flow
adapter back to v1 ``Project`` objects, validation and change ops.

A doc is a JSON object with root objects (``meta``, ``settings``, ``media``)
and collections (arrays of entities with unique ``id``). See docs/SPEC.md §4.
Everything here is pure: functions never mutate their inputs.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .model import (
    DEFAULT_COLUMNS,
    DEFAULT_FOOTNOTE,
    DEFAULT_INTRO,
    Project,
    norm_name,
    project_from_dict,
    slug,
)

Doc = Dict[str, Any]
Op = Dict[str, Any]
Problem = Dict[str, Any]

SCHEMA_VERSION: int = 2
COLLECTIONS: Tuple[str, ...] = (
    "venues", "rooms", "systems", "locations", "racks", "networks", "devices",
    "cables", "bundles", "floorplans", "attachments", "templates", "imports", "pages", "problems", "scenes",
)
ROOTS: Tuple[str, ...] = ("meta", "settings", "media")

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
PAGE_KINDS: Tuple[str, ...] = ("sop", "troubleshooting", "checklist", "reference")
PAGE_STATUSES: Tuple[str, ...] = ("draft", "published", "archived")
PROBLEM_STATUSES: Tuple[str, ...] = ("open", "resolved")
STATUSES: Tuple[str, ...] = ("installed", "planned", "spare", "retired")
PORT_DIRS: Tuple[str, ...] = ("in", "out", "io")
NETWORK_MEDIA = frozenset({"dante", "avb", "aes67", "aes50", "madi", "snake", "network", "qlan"})
GENERIC_PREFIXES = frozenset({"", "in", "input", "inputs", "out", "output", "outputs", "ch", "channel"})
ROUTING_MODES: Tuple[str, ...] = ("matrix", "passthrough", "none", "explicit", "indexed")
#: §4.3.7 rack fields and accessory items (RackItem)
RACK_WIDTHS: Tuple[int, ...] = (10, 19, 21, 23)
RACK_FORM_FACTORS: Tuple[str, ...] = ("cabinet", "open_frame", "two_post", "four_post", "wall_mount", "road_case")
RACK_ITEM_TYPES: Tuple[str, ...] = ("blank", "vent", "shelf", "drawer", "cable_manager", "brush", "lacing_bar", "other")
RACK_FACES: Tuple[str, ...] = ("front", "rear")
RACK_DEPTHS: Tuple[str, ...] = ("full", "half")
#: §4.3.17 console internals (fallback copies of ``vocab.CHANNEL_*``)
CHANNEL_KINDS: Tuple[str, ...] = ("input", "stereo_input", "mix", "aux", "group", "matrix", "stereo", "mono", "dca", "mute_group",
                                  "rack", "monitor", "cue", "talkback", "oscillator")
CHANNEL_LINK_KINDS: Tuple[str, ...] = ("input_patch", "send", "output_patch", "direct_out", "insert_send", "insert_return", "dca", "mute")
CHANNEL_SOURCES: Tuple[str, ...] = ("user", "yamaha", "clf", "dante", "csv")
DEFAULT_SETTINGS: Dict[str, Any] = {
    "default_room": "main", "units": "metric", "cable_tag_pattern": "{D}-{n:03}", "currency": "USD", "autosave": True,
}
#: ``device.inventory.condition`` (fallback copy of ``vocab.CONDITIONS``, FR-INV-06)
CONDITIONS: Tuple[str, ...] = ("new", "good", "fair", "poor", "broken")
#: ``device.short_code``: 8 chars, no 0 / 1 / I / O so codes survive handwriting and OCR (FR-INV-09)
SHORT_CODE_ALPHABET: str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SHORT_CODE_RE = re.compile(r"^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$")
#: ``device.inventory.fields`` limits (custom fields)
MAX_CUSTOM_FIELDS = 32
MAX_CUSTOM_FIELD_KEY = 40
MAX_CUSTOM_FIELD_VALUE = 500


class SchemaError(ValueError):
    """Bad doc or bad op. ``code`` is a machine code (``bad_op``, ``missing_entity`` ...)."""

    def __init__(self, message: str, code: str = "invalid", ref: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.ref = ref


# ------------------------------------------------------------------ vocab
# Minimal copy of Appendix A (discipline / side / routing per kind; discipline /
# carries per medium) used only when ``fathom.vocab`` (W2) is not importable.

_FALLBACK_KINDS = {
    "source": ("audio", "left", "none"), "stage_io": ("audio", "left", "matrix"), "computer": ("audio", "left", "matrix"),
    "console": ("audio", "right", "matrix"), "iem": ("audio", "right", "matrix"), "pa": ("audio", "right", "matrix"),
    "network": ("network", "right", "matrix"), "video": ("video", "left", "matrix"), "other": ("other", "right", "matrix"),
    "mic": ("audio", "left", "none"), "wireless_rx": ("audio", "left", "matrix"), "processor": ("audio", "right", "matrix"),
    "amp": ("audio", "right", "matrix"), "speaker": ("audio", "right", "passthrough"), "recorder": ("audio", "right", "matrix"),
    "intercom": ("audio", "right", "matrix"), "camera": ("video", "left", "matrix"), "video_source": ("video", "left", "matrix"),
    "video_switcher": ("video", "right", "matrix"), "video_router": ("video", "right", "matrix"), "converter": ("video", "right", "matrix"),
    "encoder": ("video", "right", "matrix"), "stream": ("network", "right", "none"), "display": ("video", "right", "passthrough"),
    "projector": ("video", "right", "none"), "lighting_console": ("lighting", "left", "matrix"), "dmx_node": ("lighting", "right", "matrix"),
    "dimmer": ("lighting", "right", "matrix"), "fixture": ("lighting", "right", "passthrough"), "switch": ("network", "right", "matrix"),
    "control": ("control", "right", "matrix"), "touch_panel": ("control", "left", "none"), "power": ("power", "right", "matrix"),
    "patch_panel": ("other", "right", "passthrough"),
    "container": ("other", "right", "none"),
}
_A, _V, _L, _N, _C, _P = "audio", "video", "lighting", "network", "control", "power"
_FALLBACK_MEDIA = {
    "dante": (_A, (_A, _N)), "analog": (_A, (_A,)), "aes3": (_A, (_A,)), "aes50": (_A, (_A, _C)), "madi": (_A, (_A,)),
    "avb": (_A, (_A, _N)), "speaker": (_A, (_A,)), "iem_wired": (_A, (_A,)), "iem_wireless": (_A, (_A,)), "rf": (_A, (_A,)),
    "usb": ("other", (_A, _V, _C)), "video": (_V, (_V, _A)), "network": (_N, (_N, _C, _A, _V, _L)),
    "other": ("other", (_A, _V, _L, _C, _N, _P)), "aes67": (_A, (_A, _N)), "qlan": (_A, (_A, _V, _C, _N)),
    "snake": (_A, (_A, _C)), "adat": (_A, (_A,)), "speaker_70v": (_A, (_A,)), "intercom": (_A, (_A, _C)),
    "sdi": (_V, (_V, _A)), "hdmi": (_V, (_V, _A)), "displayport": (_V, (_V, _A)), "hdbaset": (_V, (_V, _A, _C)),
    "fiber": ("other", (_A, _V, _N, _C, _L)), "ndi": (_V, (_V, _A, _N)), "st2110": (_V, (_V, _A, _N)),
    "dmx": (_L, (_L,)), "rdm": (_L, (_L, _C)), "sacn": (_L, (_L, _N)), "artnet": (_L, (_L, _N)),
    "rs232": (_C, (_C,)), "rs422": (_C, (_C,)), "ir": (_C, (_C,)), "gpio": (_C, (_C,)), "osc": (_C, (_C, _N)),
    "midi": (_C, (_C,)), "timecode": (_C, (_C,)), "sync": ("other", (_C,)), "power": (_P, (_P,)), "power_dc": (_P, (_P,)),
}
_FALLBACK_DISCIPLINES = {"audio": "A", "video": "V", "lighting": "L", "network": "N", "control": "C", "power": "P", "other": "X"}


def _vocab() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """(KINDS, MEDIA, DISCIPLINES) from ``fathom.vocab`` or the built-in fallback."""
    try:
        from . import vocab  # type: ignore

        kinds = getattr(vocab, "KINDS", None)
        media = getattr(vocab, "MEDIA", None)
        disc = getattr(vocab, "DISCIPLINES", None)
        if kinds and media and disc and all("discipline" in v for v in kinds.values()):
            return kinds, media, disc
    except Exception:  # pragma: no cover - vocab missing or broken
        pass
    kinds = {k: {"discipline": d, "side": s, "routing": r} for k, (d, s, r) in _FALLBACK_KINDS.items()}
    media = {k: {"discipline": d, "carries": list(c)} for k, (d, c) in _FALLBACK_MEDIA.items()}
    disc = {k: {"letter": v} for k, v in _FALLBACK_DISCIPLINES.items()}
    return kinds, media, disc


def kind_info(kind: str) -> Dict[str, Any]:
    kinds = _vocab()[0]
    return kinds.get(kind) or kinds.get("other") or {}


def medium_carries(medium: str) -> Tuple[str, ...]:
    media = _vocab()[1]
    m = media.get(medium) or media.get("other") or {}
    return tuple(m.get("carries") or ())


def medium_discipline(medium: str) -> str:
    m = _vocab()[1].get(medium)
    return str(m.get("discipline", "other")) if m else "other"


def discipline_of(device: Dict[str, Any]) -> str:
    """``device.discipline`` or the kind's discipline or ``other`` (§4.4.2)."""
    if device.get("discipline"):
        return str(device["discipline"])
    k = _vocab()[0].get(str(device.get("kind") or ""))
    return str(k.get("discipline") or "other") if k else "other"


def default_routing(kind: str) -> str:
    k = _vocab()[0].get(kind)
    r = (k or {}).get("routing") or "matrix"
    return r if r in ROUTING_MODES else "matrix"


# ------------------------------------------------------------- helpers


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _dedupe_id(base: str, taken: Set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _letter_dedupe(base: str, taken: Set[str]) -> str:
    if base not in taken:
        return base
    i = 0
    while True:
        suffix = ""
        k = i
        while True:
            suffix = chr(ord("b") + k % 25) + suffix
            k = k // 25 - 1
            if k < 0:
                break
        cand = f"{base}-{suffix}"
        if cand not in taken:
            return cand
        i += 1


def _clean(value: Any, keep: Iterable[str] = ()) -> Any:
    """Drop ``None`` and empty strings / lists / dicts from dicts (recursively)."""
    keep = set(keep)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            v2 = _clean(v)
            if k in keep:
                out[k] = v2 if v2 is not None else v
                continue
            if v2 is None or v2 == "" or v2 == [] or v2 == {}:
                continue
            out[k] = v2
        return out
    if isinstance(value, list):
        return [_clean(x) if isinstance(x, (dict, list)) else x for x in value]
    return value


# ------------------------------------------------------------ new / detect


def new_doc(org: str = "") -> Doc:
    """Minimal valid v2 doc (§4.12)."""
    from .project import blank_project_dict

    blank = blank_project_dict(org)
    return {
        "fathom": 2,
        "revision": 0,
        "meta": dict(blank["meta"]),
        "settings": dict(DEFAULT_SETTINGS),
        "venues": [{"id": "main", "name": org or "Main venue"}],
        "rooms": [{
            "id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "auditorium",
            "flow": {
                "columns": [dict(c) for c in DEFAULT_COLUMNS],
                "groups": [dict(g) for g in blank["groups"]],
                "spine": {"label": "Dante network", "show": True},
                "options": dict(blank["options"]),
            },
        }],
        **{c: [] for c in COLLECTIONS if c not in ("venues", "rooms")},
    }


def doc_version(d: Dict[str, Any]) -> int:
    """2 for v2 docs, 1 for v1 (``fathom: 1``, ``signalflow``, or v1 keys), 0 for empty."""
    if not isinstance(d, dict):
        raise SchemaError("project must be a JSON object", "bad_type")
    v = d.get("fathom")
    if isinstance(v, int) and not isinstance(v, bool) and v > SCHEMA_VERSION:
        raise SchemaError(f"project written by a newer Fathom (schema {v})", "newer_schema")
    if v == 2:
        return 2
    if v == 1 or "signalflow" in d:
        return 1
    if any(k in d for k in ("nodes", "links", "groups", "columns")):
        return 1
    if not d:
        return 0
    return 1


def load_any(d: Dict[str, Any]) -> Doc:
    """Migrate v0/v1 dicts, normalize v2 docs."""
    if doc_version(d) == 2:
        return normalize(d)
    return migrate(d)


# ------------------------------------------------------------ normalize


def normalize(doc: Doc) -> Doc:
    """New doc: ``fathom: 2`` first, every collection present, overlay-only
    (``auto``) entities and ports stripped, empty optional fields dropped.
    Idempotent; applied before every save (§4.4.1)."""
    src = doc or {}
    out: Doc = {"fathom": 2}
    rev = _as_int(src.get("revision"))
    out["revision"] = rev if rev is not None and rev >= 0 else 0
    for key in ROOTS:
        v = src.get(key)
        if key == "media":
            if isinstance(v, dict) and v:
                out["media"] = copy.deepcopy(v)
            continue
        out[key] = copy.deepcopy(v) if isinstance(v, dict) else ({} if v is None else copy.deepcopy(v))
    for coll in COLLECTIONS:
        items = src.get(coll)
        if items is None:
            out[coll] = []
            continue
        if not isinstance(items, list):
            out[coll] = copy.deepcopy(items)  # validate_doc reports bad_type
            continue
        lst = []
        for ent in items:
            if not isinstance(ent, dict):
                lst.append(copy.deepcopy(ent))
                continue
            if ent.get("auto") is True:
                continue
            e = _clean(copy.deepcopy(ent), keep=("ports",) if coll == "devices" else ())
            if coll == "scenes" and isinstance(ent.get("data"), dict):
                e["data"] = copy.deepcopy(ent["data"])  # §4.3.18: empty lists / {} inside scene data are meaningful
            if coll == "devices":
                ports = e.get("ports")
                if ports is None:
                    e["ports"] = []
                elif isinstance(ports, list):
                    e["ports"] = [p for p in ports if not (isinstance(p, dict) and p.get("auto") is True)]
                _normalize_device_extras(e)
            if coll == "floorplans" and not isinstance(e.get("paths"), list):
                e["paths"] = []  # FR-PLAN-14: shared paths always present (never a route when absent)
            lst.append(e)
        out[coll] = lst
    for k, v in src.items():
        if k not in out and k not in COLLECTIONS and k not in ROOTS:
            out[k] = copy.deepcopy(v)
    return out


def _conditions() -> Tuple[str, ...]:
    try:
        from . import vocab  # type: ignore

        return tuple(getattr(vocab, "CONDITIONS", None) or CONDITIONS)
    except Exception:  # pragma: no cover
        return CONDITIONS


def _normalize_device_extras(e: Dict[str, Any]) -> None:
    """In place, on an already-copied device: FR-INV-06..09 fields
    (``inventory.condition``, ``inventory.fields``, ``container``, ``short_code``)."""
    inv = e.get("inventory")
    if isinstance(inv, dict):
        cond = inv.get("condition")
        if cond is not None and (not isinstance(cond, str) or cond not in _conditions()):
            inv.pop("condition", None)
        fields = inv.get("fields")
        if fields is not None:
            clean = normalize_custom_fields(fields)
            if clean:
                inv["fields"] = clean
            else:
                inv.pop("fields", None)
        if not inv:
            e.pop("inventory", None)
    cont = e.get("container")
    if cont is not None and (not isinstance(cont, str) or not cont.strip()):
        e.pop("container", None)
    elif isinstance(cont, str):
        e["container"] = cont.strip()
    if "short_code" in e:
        code = parse_short_code(e.get("short_code"))
        if code:
            e["short_code"] = code
        else:
            e.pop("short_code", None)


def normalize_custom_fields(fields: Any) -> Dict[str, str]:
    """``inventory.fields`` → str→str: ≤ 32 keys, keys trimmed to ≤ 40 chars,
    values stringified and cut to ≤ 500 chars, empty keys dropped."""
    out: Dict[str, str] = {}
    if not isinstance(fields, dict):
        return out
    for k, v in fields.items():
        key = str(k).strip()[:MAX_CUSTOM_FIELD_KEY].strip()
        if not key or key in out:
            continue
        if v is None:
            val = ""
        elif isinstance(v, bool):
            val = "true" if v else "false"
        elif isinstance(v, (int, float, str)):
            val = str(v)
        else:
            val = json.dumps(v, ensure_ascii=False)
        out[key] = val[:MAX_CUSTOM_FIELD_VALUE]
        if len(out) >= MAX_CUSTOM_FIELDS:
            break
    return out


# ------------------------------------------------------- short codes (FR-INV-09)


def parse_short_code(text: Any) -> Optional[str]:
    """``"abcd-2345"`` / ``" ABCD2345 "`` → ``"ABCD2345"``; ``None`` when it is not a valid code."""
    if not isinstance(text, str):
        return None
    code = text.strip().replace("-", "").replace(" ", "").upper()
    return code if SHORT_CODE_RE.match(code) else None


def format_short_code(code: Any) -> str:
    """``"ABCD2345"`` → ``"ABCD-2345"`` (anything else is returned stripped)."""
    c = parse_short_code(code)
    if c is None:
        return str(code or "").strip()
    return c[:4] + "-" + c[4:]


def new_short_code(taken: Optional[Set[str]] = None) -> str:
    """A random code (``secrets.choice`` over the 32-char alphabet) not in ``taken``."""
    import secrets

    taken = taken or set()
    while True:
        code = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(8))
        if code not in taken:
            return code


def short_codes_enabled(doc: Doc) -> bool:
    """``settings.short_codes`` is not ``False`` (an opt-out for golden-file projects)."""
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    return settings.get("short_codes") is not False


def ensure_short_codes(doc: Doc) -> int:
    """Assign a ``short_code`` to every device lacking one, unique within the doc.
    Mutates ``doc`` in place (the one deliberate exception to this module's
    purity, since callers want the count); returns how many were assigned.
    Not part of :func:`normalize`: ``project.save_doc`` / ``apply_changes``,
    project creation and ``fathom codes backfill`` call it."""
    devs = doc.get("devices")
    if not isinstance(devs, list):
        return 0
    taken: Set[str] = set()
    for d in devs:
        if isinstance(d, dict):
            code = parse_short_code(d.get("short_code"))
            if code:
                taken.add(code)
    seen: Set[str] = set()
    n = 0
    for d in devs:
        if not isinstance(d, dict) or d.get("auto") is True:
            continue
        code = parse_short_code(d.get("short_code"))
        if code and code not in seen:
            seen.add(code)  # the first holder keeps it; a duplicate further down gets a fresh one
            continue
        code = new_short_code(taken)
        d["short_code"] = code
        taken.add(code)
        seen.add(code)
        n += 1
    return n


def container_contents(doc: Doc) -> Dict[str, List[str]]:
    """``{container_id: [device_id, …]}`` from ``device.container`` links (doc order;
    computed, never persisted)."""
    out: Dict[str, List[str]] = {}
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        c = d.get("container")
        if isinstance(c, str) and c:
            out.setdefault(c, []).append(str(d["id"]))
    return out


# ------------------------------------------------------- port expansion


def _emit(out: List[Dict[str, Any]], ids: Set[str], port: Dict[str, Any]) -> None:
    port["id"] = _letter_dedupe(port["id"], ids)
    ids.add(port["id"])
    out.append(port)


def expand_port_groups(groups: List[Dict[str, Any]], v1: bool = False) -> List[Dict[str, Any]]:
    """Port-group expansion (§4.4.3). ``v1=True`` reads v1 ``ports`` declarations."""
    out: List[Dict[str, Any]] = []
    ids: Set[str] = set()
    dir_map = {"in": "in", "out": "out", "bi": "io", "io": "io"}
    for raw in groups or []:
        if not isinstance(raw, dict):
            continue
        g = dict(raw)
        origin = "template"
        if v1:
            origin = "declared"
            g = {
                "group": str(raw.get("name") or raw.get("group") or "Ports"),
                "dir": dir_map.get(str(raw.get("direction") or raw.get("dir") or "io").lower(), "io"),
                "medium": str(raw.get("medium") or "other"),
                "count": raw.get("count"),
                "names": [str(x) for x in (raw.get("labels") or [])],
            }
            if raw.get("connector"):
                g["connector"] = raw.get("connector")
            cnt = _as_int(g["count"]) or 1
            if g["medium"] in NETWORK_MEDIA and cnt > 1 and not g["names"]:
                _emit(out, ids, _port(slug(g["group"]), g["group"], g, 1, origin, channels=cnt))
                continue
        group = str(g.get("group") or "Ports")
        base = slug(group)
        names = g.get("names") or []
        count = _as_int(g.get("count")) or 1
        start = _as_int(g.get("start"))
        dirs = g.get("dirs") if isinstance(g.get("dirs"), dict) else None
        labels = g.get("labels") if isinstance(g.get("labels"), list) else None
        if names:
            for i, nm in enumerate(names, 1):
                nm = str(nm)
                p = _port(base + "-" + slug(nm), group + " " + nm, g, i, origin)
                if dirs and nm in dirs:
                    p["dir"] = dirs[nm]
                _label(p, g, labels, i)
                _emit(out, ids, p)
        elif count > 1 or start:
            s = start or 1
            for k in range(count):
                n = s + k
                p = _port(base + "-" + str(n), group + " " + str(n), g, n, origin)
                _label(p, g, labels, k + 1)
                _emit(out, ids, p)
        else:
            p = _port(base, group, g, 1, origin)
            _label(p, g, labels, 1)
            _emit(out, ids, p)
    return out


def _port(pid: str, name: str, g: Dict[str, Any], index: int, origin: str, channels: Optional[int] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"id": pid, "name": name, "dir": str(g.get("dir") or "io"), "medium": str(g.get("medium") or "other")}
    if g.get("connector"):
        p["connector"] = g["connector"]
    p["group"] = str(g.get("group") or "Ports")
    p["index"] = index
    ch = channels if channels is not None else _as_int(g.get("channels"))
    if ch and ch > 1:
        p["channels"] = ch
    p["origin"] = origin
    return p


def _label(p: Dict[str, Any], g: Dict[str, Any], labels: Optional[List[Any]], i: int) -> None:
    if labels and i <= len(labels) and labels[i - 1]:
        p["label"] = str(labels[i - 1])
    elif g.get("label"):
        p["label"] = str(g["label"])


# ------------------------------------------------------ port text parsing

_RANGE_RE = re.compile(r"^(?P<prefix>.*?)\s*(?P<a>[0-9]+)\s*[-\u2013]\s*(?P<b>[0-9]+)$")
_INDEX_RE = re.compile(r"^(?P<prefix>.*?)\s*(?P<n>[0-9]+)$")
#: a number right after one of these is part of an opaque name ("AES 1/2", "×4")
_OPAQUE_BEFORE = "/.:&\u00d7"


def parse_port_text(text: str) -> Tuple[str, str, int, int]:
    """``("range"|"index"|"opaque", prefix_or_text, a, b)`` (§4.6.4)."""
    t = (text or "").strip()
    m = _RANGE_RE.match(t)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        if 1 <= a <= b:
            return ("range", m.group("prefix"), a, b)
    m = _INDEX_RE.match(t)
    if m:
        start = m.start("n")
        before = t[start - 1] if start > 0 else ""
        n = int(m.group("n"))
        if before not in _OPAQUE_BEFORE and n >= 1:
            return ("index", m.group("prefix"), n, n)
    return ("opaque", t, 0, 0)


# ------------------------------------------------------------ migration


class _PortBook:
    """Per-device port bookkeeping during migration."""

    def __init__(self, device: Dict[str, Any]) -> None:
        self.device = device
        self.ports: List[Dict[str, Any]] = device["ports"]

    def ids(self) -> Set[str]:
        return {p["id"] for p in self.ports}

    def by_name(self, text: str) -> Optional[Dict[str, Any]]:
        key = norm_name(text)
        for p in self.ports:
            if norm_name(p.get("name", "")) == key:
                return p
        return None

    def numbered_groups(self, side: str) -> List[Tuple[str, List[Dict[str, Any]]]]:
        order: List[str] = []
        members: Dict[str, List[Dict[str, Any]]] = {}
        for p in self.ports:
            g = p.get("group") or ""
            if not g:
                continue
            if g not in members:
                order.append(g)
                members[g] = []
            members[g].append(p)
        out = []
        for g in order:
            ps = members[g]
            if len(ps) >= 2 and _dir_ok(ps[0].get("dir", "io"), side):
                out.append((g, ps))
        return out

    def group_ports(self, name: str) -> List[Dict[str, Any]]:
        return [p for p in self.ports if p.get("group") == name]

    def extend_generated(self, name: str, upto: int, side: str, medium: str) -> List[Dict[str, Any]]:
        existing = self.group_ports(name)
        base = slug(name)
        taken = self.ids()
        for n in range(len(existing) + 1, upto + 1):
            pid = _letter_dedupe(f"{base}-{n}", taken)
            taken.add(pid)
            p = {"id": pid, "name": f"{name} {n}", "dir": side, "medium": medium, "group": name, "index": n, "origin": "link"}
            self.ports.append(p)
        return self.group_ports(name)


def _dir_ok(port_dir: str, side: str) -> bool:
    if side == "io":
        return True
    if side == "out":
        return port_dir in ("out", "io")
    return port_dir in ("in", "io")


def _resolve_structured(book: _PortBook, parsed: Tuple[str, str, int, int], side: str, medium: str) -> Optional[List[str]]:
    _, prefix, a, b = parsed
    npre = norm_name(prefix)
    groups = book.numbered_groups(side)
    g = None
    for name, ps in groups:
        ng = norm_name(name)
        if npre in GENERIC_PREFIXES or npre in ng or ng in npre:
            g = (name, ps)
            break
    if g is not None:
        name, ps = g
        if b <= len(ps):
            return [p["id"] for p in ps[a - 1:b]]
        if all(p.get("origin") == "link" for p in ps):
            ps = book.extend_generated(name, b, ps[0].get("dir", side), ps[0].get("medium", medium))
            return [p["id"] for p in ps[a - 1:b]]
        return None
    if not groups:
        name = prefix.strip()
        if norm_name(name) in GENERIC_PREFIXES:
            name = {"out": "Out", "in": "In"}.get(side, "I/O")
        ps = book.extend_generated(name, b, side, medium)
        return [p["id"] for p in ps[a - 1:b]]
    return None


def _resolve_opaque(book: _PortBook, text: str, side: str, medium: str, count: Optional[int], k: int) -> List[str]:
    existing = book.by_name(text)
    if existing:
        return [existing["id"]]
    if "," not in text and "&" not in text:
        toks = text.split()
        tok = toks[-1] if toks else ""
        cands = [p for p in book.ports if _dir_ok(p.get("dir", "io"), side) and p.get("medium") == medium
                 and (p.get("name", "").split() or [""])[-1] == tok]
        if len(cands) == 1:
            return [cands[0]["id"]]
    taken = book.ids()
    if k > 1:
        parts = [x.strip() for x in text.split(",")]
        parts = [x for x in parts if x]
        out = []
        if len(parts) == k:
            for i, part in enumerate(parts, 1):
                pid = _letter_dedupe(slug(part), taken)
                taken.add(pid)
                book.ports.append({"id": pid, "name": part, "dir": side, "medium": medium, "group": text, "index": i, "origin": "link"})
                out.append(pid)
        else:
            for i in range(1, k + 1):
                pid = _letter_dedupe(f"{slug(text)}-{i}", taken)
                taken.add(pid)
                book.ports.append({"id": pid, "name": f"{text} {i}", "dir": side, "medium": medium, "group": text, "index": i, "origin": "link"})
                out.append(pid)
        return out
    pid = _letter_dedupe(slug(text), taken)
    book.ports.append({"id": pid, "name": text, "dir": side, "medium": medium, "channels": max(1, count or 1), "origin": "link"})
    return [pid]


def _resolve_empty(book: _PortBook, side_name: str, side: str, medium: str, k: int, cabled: Set[Tuple[str, str]]) -> List[str]:
    if k <= 1:
        return []
    name = "Out" if side_name == "from" else "In"
    dev = book.device["id"]
    free = [p["id"] for p in book.group_ports(name) if (dev, p["id"]) not in cabled]
    while len(free) < k:
        have = len(book.group_ports(name))
        ps = book.extend_generated(name, have + (k - len(free)), side, medium)
        free = [p["id"] for p in ps if (dev, p["id"]) not in cabled]
    return free[:k]


def migrate(v1: Dict[str, Any]) -> Doc:
    """v1 (or v0 empty) dict → normalized v2 doc (§4.6)."""
    raw = dict(v1 or {})
    version = doc_version(raw)
    if version == 2:
        return normalize(raw)
    p = project_from_dict(raw)
    meta = dict(raw.get("meta") or {}) if isinstance(raw.get("meta"), dict) else {}

    # ---- id remap (ids that fail the §4.2 regex)
    remap: Dict[str, str] = {}
    taken: Set[str] = set()
    for n in p.nodes:
        if ID_RE.match(n.id) and n.id not in taken:
            taken.add(n.id)
    for n in p.nodes:
        if not ID_RE.match(n.id):
            new = _dedupe_id(slug(n.id), taken)
            taken.add(new)
            remap[n.id] = new

    def rid(x: str) -> str:
        return remap.get(x, x)

    by_id = {n.id: n for n in p.nodes}

    def canonical(nid: str) -> str:
        seen: Set[str] = set()
        cur = nid
        while cur in by_id and by_id[cur].ref and cur not in seen:
            seen.add(cur)
            nxt = by_id[cur].ref
            if nxt not in by_id:
                break
            cur = nxt
        return rid(cur)

    flow: Dict[str, Any] = {
        "columns": [c.to_dict() for c in p.columns],
        "groups": [g.to_dict() for g in p.groups if not g.auto],
    }
    if isinstance(raw.get("spine"), dict):
        flow["spine"] = dict(raw["spine"])
    if isinstance(raw.get("options"), dict):
        flow["options"] = dict(raw["options"])

    devices: List[Dict[str, Any]] = []
    dev_by_id: Dict[str, Dict[str, Any]] = {}
    extra_cards: List[Dict[str, Any]] = []
    pending_ports: List[Tuple[str, List[Dict[str, Any]]]] = []
    for seq, n in enumerate(p.nodes):
        new_id = rid(n.id)
        aliases = list(n.aliases)
        if n.id in remap:
            aliases.append(n.id)
        is_ref = bool(n.ref) and n.ref in by_id and canonical(n.id) != new_id
        if is_ref:
            card: Dict[str, Any] = {"id": new_id, "device": canonical(n.id), "seq": seq, "name": n.label}
            for k in ("sub", "kind", "brand", "group", "column", "suffix", "icon", "note"):
                v = getattr(n, k)
                if v:
                    card[k] = v
            if n.lines:
                card["lines"] = list(n.lines)
            if n.order:
                card["order"] = n.order
            if n.dante:
                card["dante"] = True
            if n.count is not None:
                card["count"] = n.count
            if aliases:
                card["aliases"] = aliases
            extra_cards.append(card)
            if n.ports:
                pending_ports.append((card["device"], n.ports))
            continue
        dev: Dict[str, Any] = {"id": new_id, "name": n.label, "kind": n.kind, "room": "main", "system": "main-audio"}
        for k in ("sub",):
            if n.sub:
                dev[k] = n.sub
        if n.lines:
            dev["lines"] = list(n.lines)
        for k in ("brand", "suffix", "icon", "note"):
            v = getattr(n, k)
            if v:
                dev[k] = v
        if n.count is not None:
            dev["count"] = n.count
        if aliases:
            dev["aliases"] = aliases
        if n.dante:
            dev["dante"] = True
        if n.dante_name:
            dev["dante_name"] = n.dante_name
        fl: Dict[str, Any] = {}
        if n.group:
            fl["group"] = n.group
        if n.column:
            fl["column"] = n.column
        if n.order:
            fl["order"] = n.order
        fl["seq"] = seq
        dev["flow"] = fl
        dev["ports"] = expand_port_groups(n.ports, v1=True)
        devices.append(dev)
        dev_by_id[new_id] = dev
    for dev_id, ports in pending_ports:
        dev = dev_by_id.get(dev_id)
        if dev is None:
            continue
        have = {x["id"] for x in dev["ports"]}
        for port in expand_port_groups(ports, v1=True):
            if port["id"] not in have:
                dev["ports"].append(port)
                have.add(port["id"])
    if extra_cards:
        flow["extra_cards"] = extra_cards

    # ---- links → cables / bundles
    books = {d["id"]: _PortBook(d) for d in devices}
    cabled: Set[Tuple[str, str]] = set()
    cables: List[Dict[str, Any]] = []
    bundles: List[Dict[str, Any]] = []
    for seq, link in enumerate(p.links):
        src_card, dst_card = rid(link.source), rid(link.target)
        src, dst = canonical(link.source), canonical(link.target)
        medium = link.medium or "analog"
        bidir = bool(link.bidirectional)
        sides = {"from": ("io" if bidir else "out", src, link.from_port.strip()),
                 "to": ("io" if bidir else "in", dst, link.to_port.strip())}
        parsed = {k: (parse_port_text(v[2]) if v[2] else ("empty", "", 0, 0)) for k, v in sides.items()}
        res: Dict[str, Optional[List[str]]] = {"from": None, "to": None}
        for k in ("from", "to"):
            side, dev_id, text = sides[k]
            if parsed[k][0] in ("range", "index") and dev_id in books:
                res[k] = _resolve_structured(books[dev_id], parsed[k], side, medium)
        for k in ("from", "to"):
            if res[k] is not None:
                continue
            other = res["to" if k == "from" else "from"]
            kk = len(other) if other else 1
            side, dev_id, text = sides[k]
            if dev_id not in books:
                res[k] = []
            elif not text:
                res[k] = _resolve_empty(books[dev_id], k, side, medium, kk, cabled)
            else:
                res[k] = _resolve_opaque(books[dev_id], text, side, medium, link.count, kk)
        F, T = res["from"] or [], res["to"] or []
        fl = {"seq": seq}
        if src_card != src:
            fl["from_card"] = src_card
        if dst_card != dst:
            fl["to_card"] = dst_card
        if len(F) == len(T) and len(F) > 1:
            bid = "b-%04d" % (len(bundles) + 1)
            b: Dict[str, Any] = {"id": bid, "kind": "link", "medium": medium}
            if link.label:
                b["label"] = link.label
            if link.count is not None:
                b["count"] = link.count
            if link.from_port:
                b["from_text"] = link.from_port
            if link.to_port:
                b["to_text"] = link.to_port
            if link.signal:
                b["signal"] = link.signal
            if link.note:
                b["note"] = link.note
            if bidir:
                b["bidirectional"] = True
            b["flow"] = fl
            bundles.append(b)
            for fp, tp in zip(F, T):
                c: Dict[str, Any] = {"id": "c-%04d" % (len(cables) + 1), "from": {"device": src, "port": fp},
                                     "to": {"device": dst, "port": tp}, "medium": medium, "bundle": bid}
                if bidir:
                    c["bidirectional"] = True
                c["flow"] = {"seq": seq}
                cables.append(c)
                cabled.add((src, fp))
                cabled.add((dst, tp))
        else:
            fe: Dict[str, Any] = {"device": src}
            te: Dict[str, Any] = {"device": dst}
            if F:
                fe["port"] = F[0]
                cabled.add((src, F[0]))
            if T:
                te["port"] = T[0]
                cabled.add((dst, T[0]))
            c = {"id": "c-%04d" % (len(cables) + 1), "from": fe, "to": te, "medium": medium}
            if link.label:
                c["label"] = link.label
            if link.count is not None:
                c["count"] = link.count
            if link.from_port:
                c["from_text"] = link.from_port
            if link.to_port:
                c["to_text"] = link.to_port
            if link.signal:
                c["signal"] = link.signal
            if link.note:
                c["note"] = link.note
            if bidir:
                c["bidirectional"] = True
            c["flow"] = fl
            cables.append(c)

    imports = []
    for i, spec in enumerate(p.imports):
        imp: Dict[str, Any] = {"id": "imp-%04d" % (i + 1), "kind": spec.kind, "path": spec.path}
        if spec.label:
            imp["label"] = spec.label
        if spec.node:
            imp["device"] = canonical(spec.node) if spec.node in by_id else rid(spec.node)
        imp["room"] = "main"
        imports.append(imp)

    doc: Doc = {
        "fathom": 2,
        "revision": 0,
        "meta": meta,
        "settings": dict(DEFAULT_SETTINGS),
    }
    if p.media_overrides:
        doc["media"] = {k: dict(v) for k, v in p.media_overrides.items()}
    doc.update({
        "venues": [{"id": "main", "name": meta.get("org") or "Main venue"}],
        "rooms": [{"id": "main", "venue": "main", "name": "Main room", "code": "MAIN", "kind": "other", "flow": flow}],
        "systems": [{"id": "main-audio", "room": "main", "discipline": "audio", "name": meta.get("system") or "Audio system"}],
        "locations": [], "racks": [], "networks": [],
        "devices": devices, "cables": cables, "bundles": bundles,
        "floorplans": [], "attachments": [], "templates": [], "imports": imports,
    })
    return normalize(doc)


# --------------------------------------------------------- state filter


def _status_ok(status: str, state: str) -> bool:
    status = status or "installed"
    if state == "everything":
        return True
    if state == "as_built":
        return status == "installed"
    if state == "planned":
        return status in ("installed", "planned")
    return status != "retired"  # "all" (default)


def filter_state(doc: Doc, state: str) -> Doc:
    """Copy of ``doc`` with devices / cables outside ``state`` removed (§4.4.6)."""
    state = state or "all"
    out = dict(doc)
    devs = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
    kept = [d for d in devs if _status_ok(str(d.get("status") or "installed"), state)]
    all_ids = {d.get("id") for d in devs}
    kept_ids = {d.get("id") for d in kept}
    out["devices"] = kept

    def endpoint_ok(ep: Any) -> bool:
        dev = (ep or {}).get("device") if isinstance(ep, dict) else None
        return dev not in all_ids or dev in kept_ids

    out["cables"] = [c for c in doc.get("cables") or [] if isinstance(c, dict)
                     and _status_ok(str(c.get("status") or "installed"), state)
                     and endpoint_ok(c.get("from")) and endpoint_ok(c.get("to"))]
    return out


# --------------------------------------------------------- flow adapter


def _room(doc: Doc, room_id: Optional[str]) -> Optional[Dict[str, Any]]:
    rooms = [r for r in doc.get("rooms") or [] if isinstance(r, dict)]
    if not rooms:
        return None
    rid_ = room_id or (doc.get("settings") or {}).get("default_room") or rooms[0].get("id")
    for r in rooms:
        if r.get("id") == rid_:
            return r
    if room_id:
        raise KeyError(f"room '{room_id}' not found")
    return rooms[0]


def default_room_id(doc: Doc) -> str:
    r = _room(doc, None)
    return str(r.get("id")) if r else ""


def _v1_ports(device: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rebuild v1 ``ports`` groups from ports with ``origin == "declared"``."""
    order: List[str] = []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in device.get("ports") or []:
        if not isinstance(p, dict) or p.get("origin") != "declared":
            continue
        g = str(p.get("group") or p.get("name") or "")
        if g not in groups:
            order.append(g)
            groups[g] = []
        groups[g].append(p)
    out = []
    rev_dir = {"in": "in", "out": "out", "io": "bi"}
    for g in order:
        ps = groups[g]
        first = ps[0]
        d: Dict[str, Any] = {"name": g, "direction": rev_dir.get(str(first.get("dir")), "bi"), "medium": first.get("medium", "other")}
        base = slug(g)
        numbered = all(p.get("id") == f"{base}-{p.get('index')}" or p.get("name") == f"{g} {p.get('index')}" for p in ps)
        if len(ps) == 1 and str(first.get("name")) == g:
            ch = _as_int(first.get("channels")) or 1
            d["count"] = ch if (first.get("medium") in NETWORK_MEDIA and ch > 1) else 1
        elif numbered:
            d["count"] = len(ps)
        else:
            pre = g + " "
            d["labels"] = [str(p.get("name", ""))[len(pre):] if str(p.get("name", "")).startswith(pre) else str(p.get("name", "")) for p in ps]
        out.append(d)
    return out


def _port_name(doc_idx: "DocIndex", ep: Dict[str, Any]) -> str:
    port = ep.get("port")
    if not port:
        return ""
    p = doc_idx.port(str(ep.get("device") or ""), str(port))
    return str(p.get("name") or port) if p else str(port)


def flow_project(doc: Doc, room_id: Optional[str] = None, state: str = "all") -> Project:
    """v1 ``Project`` for the signal-flow map of one room (§4.6.6)."""
    room = _room(doc, room_id)
    rid_ = str(room.get("id")) if room else ""
    default_rid = default_room_id(doc)
    flow = dict((room or {}).get("flow") or {})
    sdoc = filter_state(doc, state)
    idx = index(doc)

    meta = dict(doc.get("meta") or {})
    for k in ("title", "intro", "footnote"):
        if flow.get(k):
            meta[k] = flow[k]
    if flow.get("system"):
        meta["system"] = flow["system"]
    elif room is not None and rid_ != default_rid:
        meta["system"] = room.get("name") or meta.get("system")

    in_room: List[Tuple[Tuple[int, int, int], Dict[str, Any]]] = []
    room_dev_ids: Set[str] = set()
    for i, d in enumerate(sdoc.get("devices") or []):
        if d.get("auto"):
            continue
        if room is not None and str(d.get("room") or "") != rid_:
            continue
        fl = d.get("flow") or {}
        if fl.get("show") is False:
            continue
        seq = _as_int(fl.get("seq"))
        n: Dict[str, Any] = {"id": d.get("id"), "label": d.get("name") or d.get("id")}
        for k in ("sub", "lines", "kind", "brand", "dante", "dante_name", "aliases", "count", "suffix", "icon", "note"):
            if k in d:
                n[k] = d[k]
        for k in ("group", "column", "order"):
            if k in fl:
                n[k] = fl[k]
        ports = _v1_ports(d)
        if ports:
            n["ports"] = ports
        in_room.append(((seq if seq is not None else 1_000_000 + i, 0, i), n))
        room_dev_ids.add(str(d.get("id")))
    for i, card in enumerate(flow.get("extra_cards") or []):
        if not isinstance(card, dict) or str(card.get("device")) not in room_dev_ids:
            continue
        seq = _as_int(card.get("seq"))
        dev = idx.device(str(card.get("device"))) or {}
        n = {"id": card.get("id"), "label": card.get("name") or dev.get("name") or card.get("id"), "ref": card.get("device")}
        for k in ("sub", "lines", "kind", "brand", "group", "column", "order", "dante", "count", "suffix", "icon", "note", "aliases"):
            if k in card:
                n[k] = card[k]
        if "kind" not in n and dev.get("kind"):
            n["kind"] = dev["kind"]
        in_room.append(((seq if seq is not None else 1_000_000 + i, 1, i), n))
    in_room.sort(key=lambda t: t[0])
    nodes = [n for _, n in in_room]

    # ---- links (bundles + unbundled cables touching this room)
    kept_cables = sdoc.get("cables") or []
    members: Dict[str, List[Dict[str, Any]]] = {}
    for c in kept_cables:
        if c.get("bundle"):
            members.setdefault(str(c["bundle"]), []).append(c)
    items: List[Tuple[Tuple[int, int], Dict[str, Any], str]] = []
    pos = 0
    for b in doc.get("bundles") or []:
        if not isinstance(b, dict) or b.get("auto") or str(b.get("id")) not in members:
            continue
        seq = _as_int((b.get("flow") or {}).get("seq"))
        items.append(((0, seq) if seq is not None else (1, pos), b, "bundle"))
        pos += 1
    known_bundles = {str(b.get("id")) for b in doc.get("bundles") or [] if isinstance(b, dict)}
    for c in kept_cables:
        if c.get("auto") or (c.get("bundle") and str(c["bundle"]) in known_bundles):
            continue
        seq = _as_int((c.get("flow") or {}).get("seq"))
        items.append(((0, seq) if seq is not None else (1, pos), c, "cable"))
        pos += 1
    items.sort(key=lambda t: t[0])

    links: List[Dict[str, Any]] = []
    externals: List[str] = []
    for _, ent, typ in items:
        first = members[str(ent["id"])][0] if typ == "bundle" else ent
        fdev = str((first.get("from") or {}).get("device") or "")
        tdev = str((first.get("to") or {}).get("device") or "")
        if room is not None:
            f_in, t_in = fdev in room_dev_ids, tdev in room_dev_ids
            if not f_in and not t_in:
                continue
            for dev_id, inside in ((fdev, f_in), (tdev, t_in)):
                if not inside and dev_id not in externals and idx.device(dev_id) is not None:
                    externals.append(dev_id)
        fl = ent.get("flow") or {}
        lk: Dict[str, Any] = {"from": fl.get("from_card") or fdev, "to": fl.get("to_card") or tdev,
                              "medium": ent.get("medium") or first.get("medium") or "analog"}
        for k in ("label", "note", "signal"):
            if ent.get(k):
                lk[k] = ent[k]
        if ent.get("bidirectional"):
            lk["bidirectional"] = True
        if _as_int(fl.get("seq")) is not None:
            if ent.get("count") is not None:
                lk["count"] = ent.get("count")
            lk["from_port"] = ent.get("from_text") or ""
            lk["to_port"] = ent.get("to_text") or ""
        else:
            if typ == "bundle":
                lk["count"] = len(members[str(ent["id"])])
                lk["from_port"] = ent.get("from_text") or ""
                lk["to_port"] = ent.get("to_text") or ""
            else:
                ch = _as_int(ent.get("channels"))
                if ch and ch > 1:
                    lk["count"] = ch
                lk["from_port"] = ent.get("from_text") or _port_name(idx, ent.get("from") or {})
                lk["to_port"] = ent.get("to_text") or _port_name(idx, ent.get("to") or {})
        links.append(lk)

    imports = []
    for imp in doc.get("imports") or []:
        if not isinstance(imp, dict) or not imp.get("path"):
            continue
        if room is not None and str(imp.get("room") or default_rid) != rid_:
            continue
        spec = {"kind": imp.get("kind") or "auto", "path": imp.get("path")}
        if imp.get("device"):
            spec["node"] = imp["device"]
        if imp.get("label"):
            spec["label"] = imp["label"]
        imports.append(spec)

    v1: Dict[str, Any] = {"fathom": 1, "meta": meta, "nodes": nodes, "links": links, "imports": imports}
    if "spine" in flow:
        v1["spine"] = flow["spine"]
    if flow.get("columns"):
        v1["columns"] = flow["columns"]
    if flow.get("groups"):
        v1["groups"] = [g for g in flow["groups"] if isinstance(g, dict) and not g.get("auto")]
    if "options" in flow:
        v1["options"] = flow["options"]
    if doc.get("media"):
        v1["media"] = doc["media"]
    project = project_from_dict(v1)

    if externals:
        from .model import Node

        kinds = _vocab()[0]
        for dev_id in externals:
            dev = idx.device(dev_id) or {}
            kind = str(dev.get("kind") or "other")
            side = str((kinds.get(kind) or {}).get("side") or "right")
            side = side if side in ("left", "right") else "right"
            gid = f"ext-{side}"
            project.ensure_group(gid, "Other rooms", side, auto=True)
            cols = project.columns_for_side(side)
            other_room = idx.room(str(dev.get("room") or ""))
            sub = f"in {other_room.get('name') or other_room.get('id')}" if other_room else "in shared inventory"
            project.nodes.append(Node(id=dev_id, label=str(dev.get("name") or dev_id), sub=sub, kind=kind if kind in _model_kinds() else "other",
                                      group=gid, column=cols[-1].id if side == "left" and cols else (cols[0].id if cols else ""),
                                      dante=bool(dev.get("dante")), auto=True))
    # renderers and merge read device status / room membership from the doc (not serialized by to_dict)
    project.doc = doc  # type: ignore[attr-defined]
    project.room_id = rid_  # type: ignore[attr-defined]
    return project


def _model_kinds() -> Dict[str, Any]:
    from .model import KINDS

    return KINDS


# ------------------------------------------------------ v1 expressible


def is_v1_expressible(doc: Doc) -> bool:
    """True when the doc can round-trip through the v1 format (§4.6.7)."""
    if len(doc.get("venues") or []) > 1 or len(doc.get("rooms") or []) > 1:
        return False
    for c in ("racks", "networks", "floorplans", "attachments", "templates", "locations", "pages", "problems", "scenes"):
        if doc.get(c):
            return False
    if len(doc.get("systems") or []) > 1:
        return False
    for d in doc.get("devices") or []:
        if not isinstance(d, dict):
            return False
        for k in ("inventory", "rack", "interfaces", "dmx", "template", "routing", "patch", "tags", "channels", "channel_links", "container"):
            if d.get(k):
                return False
        if d.get("weight_kg") is not None or d.get("power_w") is not None:
            return False
        if str(d.get("status") or "installed") != "installed":
            return False
        for p in d.get("ports") or []:
            if not isinstance(p, dict) or p.get("origin") not in ("declared", "link") or p.get("label") or p.get("note"):
                return False
    for c in doc.get("cables") or []:
        if not isinstance(c, dict) or any(c.get(k) not in (None, "") for k in ("tag", "type", "length_m", "color", "status")):
            return False
    for b in doc.get("bundles") or []:
        if not isinstance(b, dict) or any(b.get(k) not in (None, "") for k in ("tag", "type", "length_m")):
            return False
    return True


def to_v1_dict(doc: Doc) -> Dict[str, Any]:
    """``flow_project(doc).to_dict()`` (default room, declared ports)."""
    return flow_project(doc).to_dict()


to_v1 = to_v1_dict


# ------------------------------------------------------------- index


class DocIndex:
    """Lookups over a doc. Built once per doc; do not mutate the doc meanwhile."""

    def __init__(self, doc: Doc) -> None:
        self.doc = doc
        self.by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for coll in COLLECTIONS:
            m: Dict[str, Dict[str, Any]] = {}
            for e in doc.get(coll) or []:
                if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"] not in m:
                    m[e["id"]] = e
            self.by_id[coll] = m
        self.ports: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for did, d in self.by_id["devices"].items():
            pm: Dict[str, Dict[str, Any]] = {}
            for p in d.get("ports") or []:
                if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"] not in pm:
                    pm[p["id"]] = p
            self.ports[did] = pm
        self._by_dev: Dict[str, List[Dict[str, Any]]] = {}
        self._by_port: Dict[str, List[Dict[str, Any]]] = {}
        for c in doc.get("cables") or []:
            if not isinstance(c, dict):
                continue
            for end in ("from", "to"):
                ep = c.get(end) if isinstance(c.get(end), dict) else {}
                dev = str(ep.get("device") or "")
                lst = self._by_dev.setdefault(dev, [])
                if not lst or lst[-1] is not c:
                    lst.append(c)
                if ep.get("port"):
                    self._by_port.setdefault(f"{dev}:{ep['port']}", []).append(c)
        self.template_ids = set(self.by_id["templates"])

    def device(self, device_id: str) -> Optional[Dict[str, Any]]:
        return self.by_id["devices"].get(device_id)

    def port(self, device_id: str, port_id: str) -> Optional[Dict[str, Any]]:
        return self.ports.get(device_id, {}).get(port_id)

    def channel(self, device_id: str, channel_id: str) -> Optional[Dict[str, Any]]:
        """Persisted console channel (§4.3.17) of a device, by id."""
        dev = self.device(device_id)
        for c in (dev or {}).get("channels") or []:
            if isinstance(c, dict) and c.get("id") == channel_id:
                return c
        return None

    def cables_of(self, device_id: str) -> List[Dict[str, Any]]:
        return list(self._by_dev.get(device_id, []))

    def cables_at(self, device_id: str, port_id: str) -> List[Dict[str, Any]]:
        return list(self._by_port.get(f"{device_id}:{port_id}", []))

    def room(self, room_id: str) -> Optional[Dict[str, Any]]:
        return self.by_id["rooms"].get(room_id)

    def rack(self, rack_id: str) -> Optional[Dict[str, Any]]:
        return self.by_id["racks"].get(rack_id)

    def get(self, coll: str, entity_id: str) -> Optional[Dict[str, Any]]:
        return self.by_id.get(coll, {}).get(entity_id)


def index(doc: Doc) -> DocIndex:
    return DocIndex(doc)


# ------------------------------------------------------------ change ops


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7396 JSON Merge Patch; returns a new value."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge_patch(out.get(k), v)
    return out


def _op_ref(op: Op) -> str:
    if op.get("op") == "root":
        return str(op.get("key"))
    return f"{op.get('coll')}/{op.get('id')}"


def touched_refs(ops: List[Op]) -> Set[str]:
    return {_op_ref(op) for op in ops or [] if isinstance(op, dict)}


def _check_op(op: Any) -> None:
    if not isinstance(op, dict):
        raise SchemaError("op must be an object", "bad_op")
    kind = op.get("op")
    if kind == "root":
        if op.get("key") not in ROOTS:
            raise SchemaError(f"root op key must be one of {', '.join(ROOTS)}", "bad_op", str(op.get("key")))
        if not isinstance(op.get("value"), dict):
            raise SchemaError("root op value must be an object", "bad_op", str(op.get("key")))
        return
    if kind not in ("put", "merge", "del", "move"):
        raise SchemaError(f"unknown op {kind!r}", "bad_op")
    if op.get("coll") not in COLLECTIONS:
        raise SchemaError(f"unknown collection {op.get('coll')!r}", "bad_op")
    if not isinstance(op.get("id"), str) or not op.get("id"):
        raise SchemaError("op needs an id", "bad_op")
    ref = _op_ref(op)
    if kind == "put":
        v = op.get("value")
        if not isinstance(v, dict) or v.get("id") != op["id"]:
            raise SchemaError("put value must be an object whose id equals the op id", "bad_op", ref)
    if kind == "merge" and not isinstance(op.get("value"), dict):
        raise SchemaError("merge value must be an object", "bad_op", ref)


def _find(lst: List[Any], eid: str) -> int:
    for i, e in enumerate(lst):
        if isinstance(e, dict) and e.get("id") == eid:
            return i
    return -1


def apply_ops(doc: Doc, ops: List[Op]) -> Tuple[Doc, Set[str]]:
    """Apply ops (§4.9) to a copy of ``doc``; returns ``(new_doc, touched)``.
    Raises :class:`SchemaError` (``bad_op`` / ``missing_entity``)."""
    if not isinstance(ops, list):
        raise SchemaError("ops must be a list", "bad_op")
    new = dict(doc)
    copied: Set[str] = set()
    touched: Set[str] = set()
    for op in ops:
        _check_op(op)
        kind = op["op"]
        if kind == "root":
            key = op["key"]
            if op.get("replace"):
                new[key] = copy.deepcopy(op["value"])
            else:
                new[key] = merge_patch(new.get(key) if isinstance(new.get(key), dict) else {}, op["value"])
            touched.add(key)
            continue
        coll, eid = op["coll"], op["id"]
        if coll not in copied:
            cur = new.get(coll)
            new[coll] = list(cur) if isinstance(cur, list) else []
            copied.add(coll)
        lst = new[coll]
        i = _find(lst, eid)
        ref = f"{coll}/{eid}"
        if kind == "put":
            v = copy.deepcopy(op["value"])
            if i >= 0:
                lst[i] = v
            else:
                lst.append(v)
        elif kind == "merge":
            if i < 0:
                raise SchemaError(f"{ref} does not exist", "missing_entity", ref)
            merged = merge_patch(lst[i], op["value"])
            merged["id"] = eid
            lst[i] = merged
        elif kind == "del":
            if i >= 0:
                del lst[i]
        elif kind == "move":
            if i < 0:
                raise SchemaError(f"{ref} does not exist", "missing_entity", ref)
            ent = lst.pop(i)
            before = op.get("before")
            j = _find(lst, before) if isinstance(before, str) else -1
            if j < 0:
                lst.append(ent)
            else:
                lst.insert(j, ent)
        touched.add(ref)
    return new, touched


def invert_ops(doc: Doc, ops: List[Op]) -> List[Op]:
    """Ops that undo ``ops`` when applied to ``apply_ops(doc, ops)[0]``."""
    work = doc
    inverse: List[Op] = []
    for op in ops or []:
        _check_op(op)
        kind = op["op"]
        if kind == "root":
            key = op["key"]
            old = work.get(key)
            inverse.append({"op": "root", "key": key, "value": copy.deepcopy(old) if isinstance(old, dict) else {}, "replace": True})
        else:
            coll, eid = op["coll"], op["id"]
            lst = work.get(coll) if isinstance(work.get(coll), list) else []
            i = _find(lst, eid)
            if kind == "move":
                nxt = None
                if i >= 0 and i + 1 < len(lst) and isinstance(lst[i + 1], dict):
                    nxt = lst[i + 1].get("id")
                inverse.append({"op": "move", "coll": coll, "id": eid, "before": nxt})
            elif i >= 0:
                inverse.append({"op": "put", "coll": coll, "id": eid, "value": copy.deepcopy(lst[i])})
            else:
                inverse.append({"op": "del", "coll": coll, "id": eid})
        work = apply_ops(work, [op])[0]
    inverse.reverse()
    return inverse


def diff_docs(a: Doc, b: Doc) -> List[Op]:
    """Ops turning ``a`` into ``b`` (dels, puts for new/changed entities, root replaces)."""
    ops: List[Op] = []
    for key in ROOTS:
        va, vb = a.get(key), b.get(key)
        if key == "media":
            va, vb = va or {}, vb or {}
        if _canon(va) != _canon(vb):
            ops.append({"op": "root", "key": key, "value": copy.deepcopy(vb) if isinstance(vb, dict) else {}, "replace": True})
    for coll in COLLECTIONS:
        la = [e for e in a.get(coll) or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]
        lb = [e for e in b.get(coll) or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]
        ma = {e["id"]: e for e in la}
        mb = {e["id"]: e for e in lb}
        for e in la:
            if e["id"] not in mb:
                ops.append({"op": "del", "coll": coll, "id": e["id"]})
        seen: Set[str] = set()
        for e in lb:
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            old = ma.get(e["id"])
            if old is None or _canon(old) != _canon(e):
                ops.append({"op": "put", "coll": coll, "id": e["id"], "value": copy.deepcopy(e)})
    return ops


# ------------------------------------------------------------ validation


def _prob(level: str, code: str, ref: str, path: str, message: str) -> Problem:
    return {"level": level, "code": code, "ref": ref, "path": path, "message": message}


def errors(problems: List[Problem]) -> List[Problem]:
    return [p for p in problems or [] if p.get("level") == "error"]


_REQUIRED: Dict[str, Tuple[str, ...]] = {
    "venues": ("name",), "rooms": ("name", "venue"), "systems": ("room", "discipline", "name"),
    "locations": ("name",), "racks": ("name", "units"), "networks": ("name",),
    "devices": ("name", "kind"), "cables": ("from", "to", "medium"), "bundles": (),
    "floorplans": ("name", "room", "source", "image"), "attachments": ("name", "file", "mime"),
    "templates": (), "imports": ("kind", "path"), "pages": ("slug", "title"), "problems": ("text",), "scenes": ("name",),
}
#: §4.3.18 scene name length cap and the device fields a scene owns
MAX_SCENE_NAME = 80
SCENE_PLACEMENT_FIELDS: Tuple[str, ...] = ("room", "location", "rack", "patch")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_doc(doc: Doc) -> List[Problem]:
    """Problems per §4.7. Errors block writes; warnings are informational."""
    P: List[Problem] = []
    if not isinstance(doc, dict):
        return [_prob("error", "bad_type", "", "", "doc must be an object")]
    kinds, media, discs = _vocab()
    for key in ("meta", "settings"):
        if not isinstance(doc.get(key), dict):
            P.append(_prob("error", "bad_type" if key in doc else "missing_field", key, key, f"{key} must be an object"))
    if "media" in doc and not isinstance(doc.get("media"), dict):
        P.append(_prob("error", "bad_type", "media", "media", "media must be an object"))
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    if settings.get("units") not in (None, "metric", "imperial"):
        P.append(_prob("error", "bad_enum", "settings", "settings/units", "units must be metric or imperial"))
    if "locked" in settings and not isinstance(settings.get("locked"), bool):
        P.append(_prob("error", "bad_type", "settings", "settings/locked", "locked must be true or false"))
    for key in ("locked_by", "locked_at"):
        if settings.get(key) is not None and not isinstance(settings.get(key), str):
            P.append(_prob("error", "bad_type", "settings", f"settings/{key}", f"{key} must be a string"))
    if settings.get("suggest_url") is not None:
        url = settings.get("suggest_url")
        if not isinstance(url, str):
            P.append(_prob("error", "bad_type", "settings", "settings/suggest_url", "suggest_url must be a string"))
        elif url and not re.match(r"^https?://[^\s/?#]+", url, re.I):
            P.append(_prob("error", "bad_enum", "settings", "settings/suggest_url", "suggest_url must be an http(s) URL"))
    if settings.get("scene") is not None and not isinstance(settings.get("scene"), str):
        P.append(_prob("error", "bad_type", "settings", "settings/scene", "scene must be a scene id string"))

    colls: Dict[str, List[Dict[str, Any]]] = {}
    for coll in COLLECTIONS:
        v = doc.get(coll, [])
        if not isinstance(v, list):
            P.append(_prob("error", "bad_type", "", coll, f"{coll} must be a list"))
            colls[coll] = []
            continue
        ents = []
        seen: Set[str] = set()
        for i, e in enumerate(v):
            if not isinstance(e, dict):
                P.append(_prob("error", "bad_type", "", f"{coll}/{i}", f"{coll}[{i}] must be an object"))
                continue
            eid = e.get("id")
            ref = f"{coll}/{eid}"
            if not isinstance(eid, str) or not eid:
                P.append(_prob("error", "missing_field", "", f"{coll}/{i}/id", f"{coll}[{i}] has no id"))
                continue
            rx = TEMPLATE_ID_RE if coll == "templates" else ID_RE
            if not rx.match(eid) and not (coll == "templates" and ID_RE.match(eid)):
                P.append(_prob("error", "bad_id", ref, f"{coll}/{eid}/id", f"bad id {eid!r}"))
            if eid in seen:
                P.append(_prob("error", "duplicate_id", ref, f"{coll}/{eid}", f"duplicate id {eid!r} in {coll}"))
            seen.add(eid)
            for f in _REQUIRED.get(coll, ()):
                val = e.get(f)
                if val is None or val == "" or val == {} or val == []:
                    P.append(_prob("error", "missing_field", ref, f"{coll}/{eid}/{f}", f"{ref}: {f} is required"))
            ents.append(e)
        colls[coll] = ents

    ids = {c: {e["id"] for e in colls[c]} for c in COLLECTIONS}
    dev_ids = ids["devices"]
    idx = index(doc)

    def dangling(ref: str, path: str, what: str, target: Any, coll: str) -> None:
        if target and target not in ids[coll]:
            P.append(_prob("error", "dangling_ref", ref, path, f"{ref}: {what} '{target}' does not exist"))

    for r in colls["rooms"]:
        ref = f"rooms/{r['id']}"
        dangling(ref, ref + "/venue", "venue", r.get("venue"), "venues")
        fl = r.get("flow")
        if fl is not None and not isinstance(fl, dict):
            P.append(_prob("error", "bad_type", ref, ref + "/flow", "flow must be an object"))
            continue
        for j, card in enumerate((fl or {}).get("extra_cards") or []):
            if not isinstance(card, dict) or not card.get("id"):
                P.append(_prob("error", "missing_field", ref, f"{ref}/flow/extra_cards/{j}", "extra card needs an id"))
                continue
            cid = str(card["id"])
            if cid in dev_ids:
                P.append(_prob("error", "duplicate_id", ref, f"{ref}/flow/extra_cards/{j}", f"extra card id {cid!r} is also a device id"))
            if not card.get("device"):
                P.append(_prob("error", "missing_field", ref, f"{ref}/flow/extra_cards/{j}/device", "extra card needs a device"))
            else:
                dangling(ref, f"{ref}/flow/extra_cards/{j}/device", "device", card.get("device"), "devices")
    for s in colls["systems"]:
        ref = f"systems/{s['id']}"
        dangling(ref, ref + "/room", "room", s.get("room"), "rooms")
        if s.get("discipline") and s.get("discipline") not in discs:
            P.append(_prob("warning", "unknown_discipline", ref, ref + "/discipline", f"unknown discipline '{s.get('discipline')}'"))
    for r in colls["racks"]:
        ref = f"racks/{r['id']}"
        u = r.get("units")
        if u is not None and (not isinstance(u, int) or isinstance(u, bool) or not 1 <= u <= 60):
            P.append(_prob("error", "bad_enum", ref, ref + "/units", "units must be an integer 1-60"))
        if r.get("numbering") not in (None, "bottom_up", "top_down"):
            P.append(_prob("error", "bad_enum", ref, ref + "/numbering", "numbering must be bottom_up or top_down"))
        P.extend(_rack_field_problems(r, ref))

    # ---- devices and ports
    for d in colls["devices"]:
        ref = f"devices/{d['id']}"
        if d.get("kind") and d["kind"] not in kinds:
            P.append(_prob("warning", "unknown_kind", ref, ref + "/kind", f"unknown kind '{d['kind']}' (drawn as other)"))
        if d.get("discipline") and d["discipline"] not in discs:
            P.append(_prob("warning", "unknown_discipline", ref, ref + "/discipline", f"unknown discipline '{d['discipline']}'"))
        if d.get("status") not in (None, *STATUSES):
            P.append(_prob("error", "bad_enum", ref, ref + "/status", f"status must be one of {', '.join(STATUSES)}"))
        rk = d.get("rack")
        if isinstance(rk, dict):
            for f, allowed in (("face", ("front", "rear")), ("side", ("full", "left", "right")), ("depth", ("full", "half"))):
                if rk.get(f) not in (None, *allowed):
                    P.append(_prob("error", "bad_enum", ref, f"{ref}/rack/{f}", f"rack {f} must be one of {', '.join(allowed)}"))
        P.extend(_device_rack_field_problems(d, ref))
        rt = d.get("routing")
        if isinstance(rt, dict) and rt.get("mode") not in (None, *ROUTING_MODES):
            P.append(_prob("error", "bad_enum", ref, ref + "/routing/mode", f"routing mode must be one of {', '.join(ROUTING_MODES)}"))
        ports = d.get("ports", [])
        if not isinstance(ports, list):
            P.append(_prob("error", "bad_type", ref, ref + "/ports", "ports must be a list"))
            continue
        pseen: Set[str] = set()
        for j, p in enumerate(ports):
            path = f"{ref}/ports/{j}"
            if not isinstance(p, dict):
                P.append(_prob("error", "bad_type", ref, path, "port must be an object"))
                continue
            pid = p.get("id")
            if not isinstance(pid, str) or not pid:
                P.append(_prob("error", "missing_field", ref, path + "/id", "port needs an id"))
                continue
            if not ID_RE.match(pid):
                P.append(_prob("error", "bad_id", ref, path + "/id", f"bad port id {pid!r}"))
            if pid in pseen:
                P.append(_prob("error", "duplicate_port", ref, path + "/id", f"duplicate port id {pid!r}"))
            pseen.add(pid)
            if not p.get("name"):
                P.append(_prob("error", "missing_field", ref, path + "/name", f"port {pid} needs a name"))
            if p.get("dir") not in PORT_DIRS:
                P.append(_prob("error", "bad_enum", ref, path + "/dir", f"port {pid}: dir must be in, out or io"))
            if not p.get("medium"):
                P.append(_prob("error", "missing_field", ref, path + "/medium", f"port {pid} needs a medium"))
            elif p["medium"] not in media:
                P.append(_prob("warning", "unknown_medium", ref, path + "/medium", f"unknown medium '{p['medium']}' (drawn as other)"))
        inv = d.get("inventory")
        if isinstance(inv, dict):
            for f in ("purchase_date", "warranty_until"):
                if inv.get(f) and not _valid_date(inv.get(f)):
                    P.append(_prob("warning", "bad_date", ref, f"{ref}/inventory/{f}", f"{f} must be YYYY-MM-DD"))
            cond = inv.get("condition")
            if cond not in (None, "", *_conditions()):
                P.append(_prob("warning", "bad_condition", ref, f"{ref}/inventory/condition", f"unknown condition '{cond}' (one of {', '.join(_conditions())})"))
        P.extend(_channel_problems(d, ref, pseen))
    P.extend(_container_problems(colls["devices"]))

    # ---- cables and bundles
    bundle_ids = ids["bundles"]
    in_use: Dict[str, int] = {}
    tags: Dict[str, List[str]] = {}
    for c in colls["cables"]:
        ref = f"cables/{c['id']}"
        if c.get("status") not in (None, *STATUSES):
            P.append(_prob("error", "bad_enum", ref, ref + "/status", f"status must be one of {', '.join(STATUSES)}"))
        if c.get("medium") and c["medium"] not in media:
            P.append(_prob("warning", "unknown_medium", ref, ref + "/medium", f"unknown medium '{c['medium']}' (drawn as other)"))
        if c.get("bundle") and c["bundle"] not in bundle_ids:
            P.append(_prob("error", "dangling_ref", ref, ref + "/bundle", f"{ref}: bundle '{c['bundle']}' does not exist"))
        if c.get("tag"):
            tags.setdefault(str(c["tag"]), []).append(ref)
        ends: Dict[str, Optional[Dict[str, Any]]] = {}
        for end in ("from", "to"):
            ep = c.get(end)
            if ep is None:
                continue
            if not isinstance(ep, dict):
                P.append(_prob("error", "bad_type", ref, f"{ref}/{end}", f"{end} must be an object"))
                continue
            dev = ep.get("device")
            if not dev:
                P.append(_prob("error", "missing_field", ref, f"{ref}/{end}/device", f"{end} needs a device"))
                continue
            if dev not in dev_ids:
                P.append(_prob("error", "dangling_ref", ref, f"{ref}/{end}/device", f"{ref}: device '{dev}' does not exist"))
                continue
            port = ep.get("port")
            ends[end] = None
            if port:
                pobj = idx.port(str(dev), str(port))
                if pobj is None:
                    P.append(_prob("warning", "dangling_port", ref, f"{ref}/{end}/port", f"{ref}: port '{dev}:{port}' does not exist (drawn device-level)"))
                else:
                    ends[end] = pobj
        fp, tp = ends.get("from"), ends.get("to")
        if fp is not None and fp.get("dir") == "in":
            P.append(_prob("warning", "bad_direction", ref, f"{ref}/from", f"{ref} starts at an input port"))
        if tp is not None and tp.get("dir") == "out":
            P.append(_prob("warning", "bad_direction", ref, f"{ref}/to", f"{ref} ends at an output port"))
        if fp is not None and tp is not None and fp.get("medium") and tp.get("medium") and fp["medium"] != tp["medium"]:
            shared = set(medium_carries(fp["medium"])) & set(medium_carries(tp["medium"]))
            code = "medium_mismatch" if shared else "medium_incompatible"
            P.append(_prob("warning", code, ref, ref, f"{fp['medium']} → {tp['medium']}: needs a converter?"))
        if tp is not None and tp.get("dir") == "in":
            key = f"{c['to']['device']}:{c['to']['port']}"
            in_use[key] = in_use.get(key, 0) + 1
            if in_use[key] > (_as_int(tp.get("channels")) or 1):
                P.append(_prob("warning", "port_overuse", ref, f"{ref}/to", f"input {key} has more cables than channels"))
    for b in colls["bundles"]:
        ref = f"bundles/{b['id']}"
        if b.get("medium") and b["medium"] not in media:
            P.append(_prob("warning", "unknown_medium", ref, ref + "/medium", f"unknown medium '{b['medium']}'"))
        if b.get("tag"):
            tags.setdefault(str(b["tag"]), []).append(ref)
    for tag, refs in tags.items():
        if len(refs) > 1:
            for r in refs[1:]:
                P.append(_prob("warning", "tag_duplicate", r, r + "/tag", f"tag '{tag}' is used {len(refs)} times"))

    # ---- floor plans, attachments, imports
    for f in colls["floorplans"]:
        ref = f"floorplans/{f['id']}"
        dangling(ref, ref + "/room", "room", f.get("room"), "rooms")
        for j, m in enumerate(f.get("markers") or []):
            if not isinstance(m, dict):
                continue
            dangling(ref, f"{ref}/markers/{j}/device", "device", m.get("device"), "devices")
            for k in ("x", "y"):
                v = m.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and not 0 <= v <= 1:
                    P.append(_prob("warning", "marker_out_of_bounds", ref, f"{ref}/markers/{j}/{k}", "marker outside the plan"))
        P.extend(_path_problems(f, ref))
    P.extend(_route_problems(colls))
    for a in colls["attachments"]:
        ref = f"attachments/{a['id']}"
        dangling(ref, ref + "/device", "device", a.get("device"), "devices")
    for imp in colls["imports"]:
        ref = f"imports/{imp['id']}"
        dangling(ref, ref + "/device", "device", imp.get("device"), "devices")

    # ---- SOP pages (§4.3.15)
    P.extend(_page_problems(colls, ids))
    P.extend(_problem_report_problems(colls, ids))
    P.extend(_scene_problems(settings, colls, ids, idx))

    # ---- helpers owned by other units (skipped when not importable)
    P.extend(_helper_problems(doc, colls))
    return P


def _is_int(v: Any, lo: Optional[int] = None, hi: Optional[int] = None) -> bool:
    if not isinstance(v, int) or isinstance(v, bool):
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def _is_num(v: Any, lo: Optional[float] = None) -> bool:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
        return False
    return lo is None or v >= lo


def _typed_problems(obj: Dict[str, Any], ref: str, path: str, ints: Tuple[Tuple[str, int, Optional[int]], ...] = (),
                    nums: Tuple[str, ...] = (), strs: Tuple[str, ...] = ()) -> List[Problem]:
    """``bad_type`` for optional fields that are set to the wrong type (``None`` counts as unset)."""
    out: List[Problem] = []
    for f, lo, hi in ints:
        v = obj.get(f)
        if v is not None and not _is_int(v, lo, hi):
            rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
            out.append(_prob("error", "bad_type", ref, f"{path}/{f}", f"{f} must be an integer {rng}"))
    for f in nums:
        v = obj.get(f)
        if v is not None and not _is_num(v, 0):
            out.append(_prob("error", "bad_type", ref, f"{path}/{f}", f"{f} must be a number >= 0"))
    for f in strs:
        v = obj.get(f)
        if v is not None and not isinstance(v, str):
            out.append(_prob("error", "bad_type", ref, f"{path}/{f}", f"{f} must be a string"))
    return out


def _enum_problem(obj: Dict[str, Any], f: str, allowed: Tuple[Any, ...], ref: str, path: str, what: str) -> List[Problem]:
    v = obj.get(f)
    if v is None or (not isinstance(v, bool) and v in allowed):
        return []
    return [_prob("error", "bad_enum", ref, f"{path}/{f}", f"{what} must be one of {', '.join(str(a) for a in allowed)}")]


def _rack_field_problems(r: Dict[str, Any], ref: str) -> List[Problem]:
    """Errors for the optional §4.3.7 rack fields and accessory ``items``. Placement warnings
    (overlap, range, shelves, load) come from ``racks.validate_racks``."""
    P = _enum_problem(r, "width_in", RACK_WIDTHS, ref, ref, "width_in")
    P += _enum_problem(r, "form_factor", RACK_FORM_FACTORS, ref, ref, "form_factor")
    P += _typed_problems(r, ref, ref, ints=(("start_u", 0, None),), nums=("weight_kg", "max_load_kg", "power_limit_w"), strs=("row",))
    items = r.get("items")
    if items is None:
        return P
    if not isinstance(items, list):
        P.append(_prob("error", "bad_type", ref, ref + "/items", "items must be a list"))
        return P
    seen: Set[str] = set()
    for i, it in enumerate(items):
        path = f"{ref}/items/{i}"
        if not isinstance(it, dict):
            P.append(_prob("error", "bad_type", ref, path, "rack item must be an object"))
            continue
        iid = it.get("id")
        if iid is None or iid == "":
            P.append(_prob("error", "missing_field", ref, path + "/id", "rack item needs an id"))
        elif not isinstance(iid, str):
            P.append(_prob("error", "bad_type", ref, path + "/id", "rack item id must be a string"))
        else:
            if iid in seen:
                P.append(_prob("error", "duplicate_id", ref, path + "/id", f"duplicate item id {iid!r} in {ref}"))
            seen.add(iid)
        if it.get("type") is None or it.get("type") == "":
            P.append(_prob("error", "missing_field", ref, path + "/type", "rack item needs a type"))
        else:
            P += _enum_problem(it, "type", RACK_ITEM_TYPES, ref, path, "item type")
        ints: Tuple[Tuple[str, int, Optional[int]], ...] = (("height", 1, None), ("slots", 1, 4))
        if it.get("u") is None or it.get("u") == "":
            P.append(_prob("error", "missing_field", ref, path + "/u", "rack item needs a u"))
        else:
            ints = (("u", 1, None),) + ints
        P += _typed_problems(it, ref, path, ints=ints, nums=("weight_kg",), strs=("label", "color", "notes"))
        P += _enum_problem(it, "face", RACK_FACES, ref, path, "item face")
        P += _enum_problem(it, "depth", RACK_DEPTHS, ref, path, "item depth")
    return P


def _device_rack_field_problems(d: Dict[str, Any], ref: str) -> List[Problem]:
    """Errors for device ``weight_kg``/``power_w`` and the shelf/slot/colour/image placement fields."""
    P = _typed_problems(d, ref, ref, nums=("weight_kg", "power_w"))
    rk = d.get("rack")
    if isinstance(rk, dict):
        P += _typed_problems(rk, ref, ref + "/rack", ints=(("slot", 0, None),), strs=("shelf", "color", "image_front", "image_rear"))
    return P


#: FR-PLAN-14 shared path kinds and FR-PLAN-15 route modes (`fathom/runs.py`)
PATH_KINDS: Tuple[str, ...] = ("tray", "catwalk", "trench", "conduit", "floor", "other")
ROUTE_MODES: Tuple[str, ...] = ("auto", "manual")


def _is_point(v: Any) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v))


def _path_problems(fp: Dict[str, Any], ref: str) -> List[Problem]:
    """``floorplan.paths[]`` (§4.3.11): ``paths`` must be a list (error ``bad_type``);
    a path whose ``points`` is not a list of ≥ 2 ``[x, y]`` number pairs is an error
    ``path_bad_points``; a point outside [0, 1] is the same code as a warning."""
    P: List[Problem] = []
    paths = fp.get("paths")
    if paths is None:
        return P
    if not isinstance(paths, list):
        return [_prob("error", "bad_type", ref, ref + "/paths", "paths must be a list")]
    seen: Set[str] = set()
    for j, p in enumerate(paths):
        path = f"{ref}/paths/{j}"
        if not isinstance(p, dict):
            P.append(_prob("error", "bad_type", ref, path, "path must be an object"))
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not pid:
            P.append(_prob("error", "missing_field", ref, path + "/id", "path needs an id"))
        elif not ID_RE.match(pid):
            P.append(_prob("error", "bad_id", ref, path + "/id", f"bad path id {pid!r}"))
        elif pid in seen:
            P.append(_prob("error", "duplicate_id", ref, path + "/id", f"duplicate path id {pid!r}"))
        else:
            seen.add(pid)
        pts = p.get("points")
        if not isinstance(pts, list) or len(pts) < 2 or not all(_is_point(q) for q in pts):
            P.append(_prob("error", "path_bad_points", ref, path + "/points", "path points must be at least two [x, y] number pairs"))
        elif any(not (0 <= q[0] <= 1 and 0 <= q[1] <= 1) for q in pts):
            P.append(_prob("warning", "path_bad_points", ref, path + "/points", "path point outside the plan"))
        for k in ("elevation_m",):
            v = p.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                P.append(_prob("error", "bad_type", ref, f"{path}/{k}", f"{k} must be a number"))
    return P


def _route_problems(colls: Dict[str, List[Dict[str, Any]]]) -> List[Problem]:
    """``cable.route`` / ``bundle.route`` (§4.3.10): wrong type is an error; a
    ``plan`` that is not a floor plan is a warning ``route_wrong_plan``; a ``via``
    entry naming no path on that plan is a warning ``route_dangling_path``
    (the run then falls back to a straight line). A run is advisory: a missing
    marker is not reported here (``runs.plan_runs`` lists it under ``unplaced``)."""
    P: List[Problem] = []
    plans = {f["id"]: {str(p.get("id")) for p in (f.get("paths") or []) if isinstance(p, dict)} for f in colls["floorplans"]}
    for coll in ("cables", "bundles"):
        for e in colls[coll]:
            route = e.get("route")
            if route is None:
                continue
            ref = f"{coll}/{e['id']}"
            if not isinstance(route, dict):
                P.append(_prob("error", "bad_type", ref, ref + "/route", "route must be an object"))
                continue
            if route.get("mode") not in (None, *ROUTE_MODES):
                P.append(_prob("error", "bad_enum", ref, ref + "/route/mode", f"route mode must be one of {', '.join(ROUTE_MODES)}"))
            for k in ("slack_m", "drop_m"):
                v = route.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                    P.append(_prob("error", "bad_type", ref, f"{ref}/route/{k}", f"{k} must be a number"))
            pts = route.get("points")
            if pts is not None and (not isinstance(pts, list) or not all(_is_point(q) for q in pts)):
                P.append(_prob("error", "bad_type", ref, ref + "/route/points", "route points must be [x, y] number pairs"))
            plan = route.get("plan")
            if plan is not None and plan not in plans:
                P.append(_prob("warning", "route_wrong_plan", ref, ref + "/route/plan", f"{ref}: route plan '{plan}' is not a floor plan (route ignored)"))
            via = route.get("via")
            if via is not None and not isinstance(via, list):
                P.append(_prob("error", "bad_type", ref, ref + "/route/via", "route via must be a list of path ids"))
                continue
            known = plans[plan] if plan in plans else (set().union(*plans.values()) if plans else set())
            for j, pid in enumerate(via or []):
                if pid not in known:
                    P.append(_prob("warning", "route_dangling_path", ref, f"{ref}/route/via/{j}", f"{ref}: path '{pid}' does not exist on the plan (straight run instead)"))
    return P


def _container_problems(devices: List[Dict[str, Any]]) -> List[Problem]:
    """``device.container`` links (FR-INV-08): target missing, target not a
    ``container`` kind, or a loop when following the links — all warnings."""
    P: List[Problem] = []
    by_id = {d["id"]: d for d in devices if isinstance(d.get("id"), str)}
    for d in devices:
        c = d.get("container")
        if not c:
            continue
        ref = f"devices/{d['id']}"
        path = ref + "/container"
        if not isinstance(c, str):
            P.append(_prob("warning", "container_missing", ref, path, f"{ref}: container must be a device id"))
            continue
        target = by_id.get(c)
        if target is None:
            P.append(_prob("warning", "container_missing", ref, path, f"{ref}: container '{c}' does not exist"))
            continue
        if target.get("kind") != "container":
            P.append(_prob("warning", "container_not_container", ref, path, f"{ref}: '{c}' is not a container (kind {target.get('kind') or '?'})"))
        hops: Set[str] = {d["id"]}
        cur: Any = c
        while isinstance(cur, str) and cur in by_id:
            if cur in hops:
                P.append(_prob("warning", "container_cycle", ref, path, f"{ref}: container chain loops back through '{cur}'"))
                break
            hops.add(cur)
            cur = by_id[cur].get("container")
    return P


def _page_problems(colls: Dict[str, List[Dict[str, Any]]], ids: Dict[str, Set[str]]) -> List[Problem]:
    """Slug shape and uniqueness, enums, parent existence and cycles (errors);
    links to missing rooms / devices / attachments are warnings so deleting a
    device never makes its procedures unsaveable."""
    P: List[Problem] = []
    pages = colls.get("pages") or []
    page_ids = ids.get("pages") or set()
    by_id = {p["id"]: p for p in pages}
    slugs: Dict[str, str] = {}
    for p in pages:
        ref = f"pages/{p['id']}"
        slug_ = p.get("slug")
        if isinstance(slug_, str) and slug_:
            if not SLUG_RE.match(slug_):
                P.append(_prob("error", "bad_slug", ref, ref + "/slug", f"bad slug {slug_!r} (lowercase letters, digits and dashes)"))
            elif slug_ in slugs:
                P.append(_prob("error", "duplicate_slug", ref, ref + "/slug", f"slug '{slug_}' is also used by {slugs[slug_]}"))
            else:
                slugs[slug_] = ref
        if p.get("kind") not in (None, *PAGE_KINDS):
            P.append(_prob("error", "bad_enum", ref, ref + "/kind", f"kind must be one of {', '.join(PAGE_KINDS)}"))
        if p.get("status") not in (None, *PAGE_STATUSES):
            P.append(_prob("error", "bad_enum", ref, ref + "/status", f"status must be one of {', '.join(PAGE_STATUSES)}"))
        if p.get("body") is not None and not isinstance(p.get("body"), str):
            P.append(_prob("error", "bad_type", ref, ref + "/body", "body must be a string"))
        parent = p.get("parent")
        if parent:
            if parent == p["id"]:
                P.append(_prob("error", "page_cycle", ref, ref + "/parent", f"{ref} is its own parent"))
            elif parent not in page_ids:
                P.append(_prob("error", "dangling_ref", ref, ref + "/parent", f"{ref}: parent page '{parent}' does not exist"))
            else:
                seen = {p["id"]}
                cur = by_id.get(parent)
                while cur is not None and cur.get("parent"):
                    if cur["id"] in seen:
                        P.append(_prob("error", "page_cycle", ref, ref + "/parent", f"{ref}: parent chain loops"))
                        break
                    seen.add(cur["id"])
                    cur = by_id.get(cur["parent"])
        for field, coll in (("rooms", "rooms"), ("devices", "devices"), ("attachments", "attachments")):
            vals = p.get(field)
            if vals is None:
                continue
            if not isinstance(vals, list):
                P.append(_prob("error", "bad_type", ref, f"{ref}/{field}", f"{field} must be a list of ids"))
                continue
            for j, v in enumerate(vals):
                if v and v not in ids[coll]:
                    P.append(_prob("warning", "dangling_link", ref, f"{ref}/{field}/{j}", f"{ref}: {coll[:-1]} '{v}' does not exist"))
        if p.get("review_due") and not _valid_date(p.get("review_due")):
            P.append(_prob("warning", "bad_date", ref, ref + "/review_due", "review_due must be YYYY-MM-DD"))
    return P


def _problem_report_problems(colls: Dict[str, List[Dict[str, Any]]], ids: Dict[str, Set[str]]) -> List[Problem]:
    """Problem reports (§4.3.16): text required, status enum; links to missing devices/pages are warnings."""
    P: List[Problem] = []
    slugs = {p.get("slug") for p in colls.get("pages") or []}
    for r in colls.get("problems") or []:
        ref = f"problems/{r['id']}"
        if not isinstance(r.get("text"), str) or not r.get("text", "").strip():
            P.append(_prob("error", "missing_field", ref, ref + "/text", "a problem report needs a text"))
        if r.get("status") not in (None, *PROBLEM_STATUSES):
            P.append(_prob("error", "bad_enum", ref, ref + "/status", f"status must be one of {', '.join(PROBLEM_STATUSES)}"))
        if r.get("device") and r["device"] not in ids["devices"]:
            P.append(_prob("warning", "dangling_link", ref, ref + "/device", f"{ref}: device '{r['device']}' does not exist"))
        if r.get("page") and r["page"] not in slugs:
            P.append(_prob("warning", "dangling_link", ref, ref + "/page", f"{ref}: page '{r['page']}' does not exist"))
        if r.get("attachment") and r["attachment"] not in ids["attachments"]:
            P.append(_prob("warning", "dangling_link", ref, ref + "/attachment", f"{ref}: attachment '{r['attachment']}' does not exist"))
    return P


def _scene_problems(settings: Dict[str, Any], colls: Dict[str, List[Dict[str, Any]]], ids: Dict[str, Set[str]], idx: "DocIndex") -> List[Problem]:
    """Scenes (§4.3.18): name shape, one ``base`` entry at most (error ``bad_enum``), typed ``data``
    (errors ``bad_type``); duplicate names, a ``settings.scene`` that names no scene and scene cables /
    markers / device entries pointing at devices or ports that no longer exist are warnings
    (``duplicate_name`` / ``dangling_link``) — a deleted device must never make a scene unsaveable."""
    P: List[Problem] = []
    scenes_ = colls.get("scenes") or []
    names: Dict[str, str] = {}
    base_refs: List[str] = []
    dev_ids = ids.get("devices") or set()
    fp_ids = ids.get("floorplans") or set()
    for s in scenes_:
        ref = f"scenes/{s['id']}"
        name = s.get("name")
        if name is not None and not isinstance(name, str):
            P.append(_prob("error", "bad_type", ref, ref + "/name", "name must be a string"))
        elif isinstance(name, str):
            if len(name) > MAX_SCENE_NAME:
                P.append(_prob("error", "bad_enum", ref, ref + "/name", f"name is longer than {MAX_SCENE_NAME} characters"))
            key = name.strip().casefold()
            if key and key in names:
                P.append(_prob("warning", "duplicate_name", ref, ref + "/name", f"scene name '{name}' is also used by {names[key]}"))
            elif key:
                names[key] = ref
        if "base" in s and not isinstance(s.get("base"), bool):
            P.append(_prob("error", "bad_type", ref, ref + "/base", "base must be true or false"))
        if s.get("base") is True:
            base_refs.append(ref)
        if s.get("note") is not None and not isinstance(s.get("note"), str):
            P.append(_prob("error", "bad_type", ref, ref + "/note", "note must be a string"))
        data = s.get("data")
        if data is None:
            continue
        if not isinstance(data, dict):
            P.append(_prob("error", "bad_type", ref, ref + "/data", "data must be an object"))
            continue
        for key in ("cables", "bundles"):
            lst = data.get(key)
            if lst is not None and not isinstance(lst, list):
                P.append(_prob("error", "bad_type", ref, f"{ref}/data/{key}", f"data.{key} must be a list"))
        for key in ("markers", "devices"):
            obj = data.get(key)
            if obj is not None and not isinstance(obj, dict):
                P.append(_prob("error", "bad_type", ref, f"{ref}/data/{key}", f"data.{key} must be an object"))
        for j, c in enumerate(data.get("cables") if isinstance(data.get("cables"), list) else []):
            if not isinstance(c, dict):
                continue
            cid = c.get("id") or j
            for end in ("from", "to"):
                ep = c.get(end)
                if not isinstance(ep, dict) or not ep.get("device"):
                    continue
                dev = str(ep["device"])
                if dev not in dev_ids:
                    P.append(_prob("warning", "dangling_link", ref, f"{ref}/data/cables/{j}/{end}/device", f"{ref}: cable {cid}: device '{dev}' does not exist"))
                elif ep.get("port") and idx.port(dev, str(ep["port"])) is None:
                    P.append(_prob("warning", "dangling_link", ref, f"{ref}/data/cables/{j}/{end}/port", f"{ref}: cable {cid}: port '{dev}:{ep['port']}' does not exist"))
        markers = data.get("markers") if isinstance(data.get("markers"), dict) else {}
        for fp, lst in markers.items():
            if fp not in fp_ids:
                P.append(_prob("warning", "dangling_link", ref, f"{ref}/data/markers/{fp}", f"{ref}: floor plan '{fp}' does not exist"))
            if not isinstance(lst, list):
                P.append(_prob("error", "bad_type", ref, f"{ref}/data/markers/{fp}", "markers must be a list"))
                continue
            for j, m in enumerate(lst):
                if isinstance(m, dict) and m.get("device") and m["device"] not in dev_ids:
                    P.append(_prob("warning", "dangling_link", ref, f"{ref}/data/markers/{fp}/{j}/device", f"{ref}: device '{m['device']}' does not exist"))
        devices = data.get("devices") if isinstance(data.get("devices"), dict) else {}
        for did, entry in devices.items():
            if not isinstance(entry, dict):
                P.append(_prob("error", "bad_type", ref, f"{ref}/data/devices/{did}", "device placement must be an object"))
                continue
            if did not in dev_ids:
                P.append(_prob("warning", "dangling_link", ref, f"{ref}/data/devices/{did}", f"{ref}: device '{did}' does not exist"))
    if len(base_refs) > 1:
        for ref in base_refs[1:]:
            P.append(_prob("error", "bad_enum", ref, ref + "/base", f"only one scene may be the base ({base_refs[0]} already is)"))
    active = settings.get("scene")
    if isinstance(active, str) and active and active != "base" and active not in (ids.get("scenes") or set()):
        P.append(_prob("warning", "dangling_link", "settings", "settings/scene", f"active scene '{active}' does not exist"))
    return P


def _channel_vocab() -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    try:
        from . import vocab  # type: ignore

        return tuple(vocab.CHANNEL_KINDS), tuple(vocab.CHANNEL_LINK_KINDS), tuple(vocab.CHANNEL_SOURCES)
    except Exception:  # pragma: no cover - vocab missing
        return CHANNEL_KINDS, CHANNEL_LINK_KINDS, CHANNEL_SOURCES


def _channel_problems(d: Dict[str, Any], ref: str, port_ids: Set[str]) -> List[Problem]:
    """§4.3.17 console internals: channel ids unique and well-formed (errors), link endpoints
    name an existing channel (error) or port (warning, like dangling cable ports), enums warn."""
    P: List[Problem] = []
    kinds, link_kinds, sources = _channel_vocab()
    chans = d.get("channels")
    links = d.get("channel_links")
    if chans is None and links is None:
        return P
    ids: Set[str] = set()
    if chans is not None and not isinstance(chans, list):
        P.append(_prob("error", "bad_type", ref, ref + "/channels", "channels must be a list"))
        chans = []
    for j, c in enumerate(chans or []):
        path = f"{ref}/channels/{j}"
        if not isinstance(c, dict):
            P.append(_prob("error", "bad_type", ref, path, "channel must be an object"))
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            P.append(_prob("error", "missing_field", ref, path + "/id", "channel needs an id"))
            continue
        if not ID_RE.match(cid):
            P.append(_prob("error", "bad_id", ref, path + "/id", f"bad channel id {cid!r}"))
        if cid in ids:
            P.append(_prob("error", "duplicate_channel", ref, path + "/id", f"duplicate channel id {cid!r}"))
        ids.add(cid)
        if not c.get("kind"):
            P.append(_prob("error", "missing_field", ref, path + "/kind", f"channel {cid} needs a kind"))
        elif c["kind"] not in kinds:
            P.append(_prob("warning", "unknown_channel_kind", ref, path + "/kind", f"unknown channel kind '{c['kind']}'"))
        if c.get("source") not in (None, *sources):
            P.append(_prob("warning", "bad_enum", ref, path + "/source", f"channel source should be one of {', '.join(sources)}"))
    if links is not None and not isinstance(links, list):
        P.append(_prob("error", "bad_type", ref, ref + "/channel_links", "channel_links must be a list"))
        links = []
    for j, ln in enumerate(links or []):
        path = f"{ref}/channel_links/{j}"
        if not isinstance(ln, dict):
            P.append(_prob("error", "bad_type", ref, path, "channel link must be an object"))
            continue
        if not ln.get("kind"):
            P.append(_prob("error", "missing_field", ref, path + "/kind", "channel link needs a kind"))
        elif ln["kind"] not in link_kinds:
            P.append(_prob("warning", "unknown_link_kind", ref, path + "/kind", f"unknown channel link kind '{ln['kind']}'"))
        if ln.get("source") not in (None, *sources):
            P.append(_prob("warning", "bad_enum", ref, path + "/source", f"link source should be one of {', '.join(sources)}"))
        for end in ("from", "to"):
            ep = ln.get(end)
            if not isinstance(ep, dict):
                P.append(_prob("error", "missing_field" if ep is None else "bad_type", ref, f"{path}/{end}", f"channel link needs a {end} endpoint"))
                continue
            if ep.get("channel"):
                if ep["channel"] not in ids:
                    P.append(_prob("error", "dangling_channel", ref, f"{path}/{end}/channel", f"{ref}: channel '{ep['channel']}' does not exist"))
            elif ep.get("port"):
                if ep["port"] not in port_ids:
                    P.append(_prob("warning", "dangling_port", ref, f"{path}/{end}/port", f"{ref}: port '{ep['port']}' does not exist (link kept as text)"))
            elif not ep.get("text"):
                P.append(_prob("error", "missing_field", ref, f"{path}/{end}", f"{end} endpoint needs a channel, a port or a text"))
            ch = ep.get("ch")
            if ch is not None and (not isinstance(ch, int) or isinstance(ch, bool) or ch < 1):
                P.append(_prob("error", "bad_enum", ref, f"{path}/{end}/ch", "ch must be a positive integer"))
        ins = ln.get("insert")
        if ins is not None and ins not in (1, 2):
            P.append(_prob("error", "bad_enum", ref, path + "/insert", "insert must be 1 or 2"))
    return P


def _valid_date(v: Any) -> bool:
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _helper_problems(doc: Doc, colls: Dict[str, List[Dict[str, Any]]]) -> List[Problem]:
    out: List[Problem] = []
    try:
        from .racks import validate_racks  # type: ignore
    except Exception:
        validate_racks = None
    if validate_racks is not None:
        try:
            out.extend(validate_racks(doc) or [])
        except Exception:
            pass
    else:
        out.extend(_fallback_rack_problems(colls))
    try:
        from .network import network_problems  # type: ignore
    except Exception:
        network_problems = None
    if network_problems is not None:
        try:
            out.extend(network_problems(doc) or [])
        except Exception:
            pass
    else:
        out.extend(_fallback_network_problems(colls))
    try:
        from .dmx import dmx_problems  # type: ignore
    except Exception:
        dmx_problems = None
    if dmx_problems is not None:
        try:
            out.extend(dmx_problems(doc) or [])
        except Exception:
            pass
    else:
        out.extend(_fallback_dmx_problems(colls))
    return out


def _fallback_rack_problems(colls: Dict[str, List[Dict[str, Any]]]) -> List[Problem]:
    out: List[Problem] = []
    racks = {r["id"]: r for r in colls["racks"]}
    for d in colls["devices"]:
        rk = d.get("rack")
        if not isinstance(rk, dict) or not rk.get("id"):
            continue
        ref = f"devices/{d['id']}"
        rack = racks.get(rk["id"])
        if rack is None:
            out.append(_prob("warning", "rack_unknown", ref, ref + "/rack/id", f"rack '{rk['id']}' does not exist"))
            continue
        u, h = _as_int(rk.get("u")), _as_int(rk.get("height")) or 1
        units = _as_int(rack.get("units")) or 0
        if u is not None and (u < 1 or u + h - 1 > units):
            out.append(_prob("warning", "rack_out_of_range", ref, ref + "/rack/u", f"U{u} (+{h}) is outside the {units}U rack"))
    return out


def _fallback_network_problems(colls: Dict[str, List[Dict[str, Any]]]) -> List[Problem]:
    out: List[Problem] = []
    for n in colls["networks"]:
        ref = f"networks/{n['id']}"
        if n.get("subnet"):
            try:
                ipaddress.ip_network(str(n["subnet"]), strict=False)
            except ValueError:
                out.append(_prob("warning", "bad_subnet", ref, ref + "/subnet", f"bad subnet '{n['subnet']}'"))
        if n.get("gateway"):
            try:
                ipaddress.ip_address(str(n["gateway"]))
            except ValueError:
                out.append(_prob("warning", "bad_ip", ref, ref + "/gateway", f"bad gateway '{n['gateway']}'"))
    for d in colls["devices"]:
        for j, itf in enumerate(d.get("interfaces") or []):
            if not isinstance(itf, dict):
                continue
            ref = f"devices/{d['id']}"
            for k in ("ip", "gateway"):
                if itf.get(k):
                    try:
                        ipaddress.ip_address(str(itf[k]))
                    except ValueError:
                        out.append(_prob("warning", "bad_ip", ref, f"{ref}/interfaces/{j}/{k}", f"bad IP '{itf[k]}'"))
    return out


def _fallback_dmx_problems(colls: Dict[str, List[Dict[str, Any]]]) -> List[Problem]:
    out: List[Problem] = []
    for d in colls["devices"]:
        dmx = d.get("dmx")
        if not isinstance(dmx, dict):
            continue
        ref = f"devices/{d['id']}"
        for k, lo, hi in (("universe", 1, 63999), ("address", 1, 512), ("footprint", 1, 512)):
            v = dmx.get(k)
            if v is None:
                continue
            iv = _as_int(v)
            if iv is None or not lo <= iv <= hi:
                out.append(_prob("warning", "dmx_range", ref, f"{ref}/dmx/{k}", f"DMX {k} {v} outside {lo}-{hi}"))
    return out


# ------------------------------------------------------------ JSON Schema


def _obj(props: Dict[str, Any], required: Tuple[str, ...] = ()) -> Dict[str, Any]:
    s: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": True}
    if required:
        s["required"] = list(required)
    return s


_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_ID = {"type": "string", "pattern": ID_RE.pattern}
_STRS = {"type": "array", "items": _STR}
_STATUS = {"type": "string", "enum": list(STATUSES)}
_ENDPOINT = _obj({"device": _ID, "port": _ID}, ("device",))
_KG = {"type": "number", "minimum": 0}
_RACK_ITEM = _obj({
    "id": _STR, "type": {"type": "string", "enum": list(RACK_ITEM_TYPES)}, "u": {"type": "integer", "minimum": 1},
    "height": {"type": "integer", "minimum": 1}, "face": {"type": "string", "enum": list(RACK_FACES)},
    "depth": {"type": "string", "enum": list(RACK_DEPTHS)}, "label": _STR, "color": _STR,
    "slots": {"type": "integer", "minimum": 1, "maximum": 4}, "weight_kg": _KG, "notes": _STR,
}, ("id", "type", "u"))


def _arr(item: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": item}


_PORT = _obj({
    "id": _ID, "name": _STR, "dir": {"type": "string", "enum": list(PORT_DIRS)}, "medium": _STR, "connector": _STR,
    "group": _STR, "index": _INT, "channels": _INT, "label": _STR, "note": _STR,
    "origin": {"type": "string", "enum": ["template", "declared", "link", "user"]},
}, ("id", "name", "dir", "medium"))
_INTERFACE = _obj({
    "id": _ID, "role": {"type": "string", "enum": ["primary", "secondary", "control", "management", "media"]},
    "ip": _STR, "prefix": _INT, "gateway": _STR, "vlan": _INT, "mac": _STR, "hostname": _STR, "dhcp": _BOOL,
    "protocol": _STR, "network": _STR, "switch": _STR, "switch_port": _STR, "port": _STR, "note": _STR,
}, ("id",))
_CHANNEL = _obj({
    "id": _ID, "kind": _STR, "index": _INT, "side": {"type": "string", "enum": ["L", "R"]}, "name": _STR, "color": _STR,
    "icon": _STR, "rack": _STR, "label": _STR, "note": _STR, "source": _STR,
}, ("id", "kind"))
#: one end of a channel link: a console channel, a (sub-channel of a) device port, or free text when unmapped
_CH_ENDPOINT = _obj({"channel": _ID, "tag": _STR, "port": _ID, "ch": {"type": "integer", "minimum": 1}, "text": _STR})
_CHANNEL_LINK = _obj({
    "from": _CH_ENDPOINT, "to": _CH_ENDPOINT, "kind": _STR, "insert": {"type": "integer", "enum": [1, 2]},
    "level": _STR, "source": _STR, "note": _STR,
}, ("from", "to", "kind"))

_POINT = {"type": "array", "items": _NUM, "minItems": 2, "maxItems": 2}
#: §4.3.11 shared path on a floor plan (FR-PLAN-14)
_PATH = _obj({
    "id": _ID, "name": _STR, "kind": {"type": "string", "enum": list(PATH_KINDS)}, "points": {"type": "array", "items": _POINT, "minItems": 2},
    "color": _STR, "elevation_m": _NUM, "note": _STR,
}, ("id", "points"))
#: §4.3.10 advisory route of a cable / bundle on one plan (FR-PLAN-15)
_ROUTE = _obj({
    "plan": _ID, "points": _arr(_POINT), "via": _arr(_ID), "slack_m": _NUM, "drop_m": _NUM,
    "mode": {"type": "string", "enum": list(ROUTE_MODES)},
})

JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://fathom.local/api/v2/schema.json",
    "title": "Fathom project doc (schema 2)",
    "type": "object",
    "additionalProperties": True,
    "required": ["fathom", "revision", "meta", "settings", *[c for c in COLLECTIONS if c not in ("pages", "problems", "scenes")]],  # pages/problems/scenes: added in 0.4, optional on disk
    "properties": {
        "fathom": {"type": "integer", "const": 2},
        "revision": {"type": "integer", "minimum": 0},
        "meta": _obj({k: _STR for k in ("org", "system", "title", "intro", "footnote", "slug", "version", "author", "description")}),
        "settings": _obj({
            "default_room": _STR, "units": {"type": "string", "enum": ["metric", "imperial"]}, "cable_tag_pattern": _STR,
            "currency": _STR, "public_url": _STR, "autosave": _BOOL, "problem_email": _STR, "short_codes": _BOOL,
            "locked": _BOOL, "locked_by": _STR, "locked_at": _STR, "suggest_url": _STR, "scene": _STR,
            "labels": _obj({"cols": _INT, "rows": _INT, "width_in": _NUM, "height_in": _NUM, "page": {"type": "string", "enum": ["letter", "a4"]}}),
            "assistant": _obj({"llm": _BOOL}),
        }),
        "media": {"type": "object", "additionalProperties": {"type": "object"}},
        "venues": _arr(_obj({"id": _ID, "name": _STR, "address": _STR, "notes": _STR, "order": _INT}, ("id", "name"))),
        "rooms": _arr(_obj({
            "id": _ID, "name": _STR, "venue": _ID, "code": {"type": "string", "pattern": "^[A-Z0-9-]{1,8}$"}, "kind": _STR,
            "order": _INT, "notes": _STR,
            "flow": _obj({
                "title": _STR, "intro": _STR, "footnote": _STR, "system": _STR,
                "columns": _arr(_obj({"id": _STR, "label": _STR, "side": {"type": "string", "enum": ["left", "spine", "right"]}}, ("id",))),
                "groups": _arr(_obj({"id": _STR, "label": _STR, "side": {"type": "string", "enum": ["left", "right"]}, "note": _STR, "order": _INT}, ("id",))),
                "spine": _obj({"label": _STR, "show": _BOOL}),
                "options": {"type": "object"},
                "extra_cards": _arr(_obj({"id": _ID, "device": _ID, "seq": _INT}, ("id", "device"))),
            }),
        }, ("id", "name", "venue"))),
        "systems": _arr(_obj({"id": _ID, "room": _ID, "discipline": _STR, "name": _STR, "notes": _STR}, ("id", "room", "discipline", "name"))),
        "locations": _arr(_obj({"id": _ID, "name": _STR, "venue": _STR, "room": _STR,
                                "kind": {"type": "string", "enum": ["booth", "stage", "rack_room", "storage", "catwalk", "closet", "other"]},
                                "notes": _STR}, ("id", "name"))),
        "racks": _arr(_obj({"id": _ID, "name": _STR, "room": _STR, "location": _STR, "units": {"type": "integer", "minimum": 1, "maximum": 60},
                            "numbering": {"type": "string", "enum": ["bottom_up", "top_down"]}, "faces": _STRS, "depth_mm": _NUM,
                            "order": _INT, "notes": _STR, "width_in": {"type": "integer", "enum": list(RACK_WIDTHS)},
                            "form_factor": {"type": "string", "enum": list(RACK_FORM_FACTORS)},
                            "start_u": {"type": "integer", "minimum": 0}, "weight_kg": _KG, "max_load_kg": _KG,
                            "power_limit_w": _KG, "row": _STR, "items": _arr(_RACK_ITEM)}, ("id", "name", "units"))),
        "networks": _arr(_obj({"id": _ID, "name": _STR, "vlan": {"type": "integer", "minimum": 1, "maximum": 4094}, "subnet": _STR,
                               "gateway": _STR, "protocol": _STR, "dhcp_range": _STR, "notes": _STR}, ("id", "name"))),
        "devices": _arr(_obj({
            "id": _ID, "name": _STR, "kind": _STR, "discipline": _STR, "room": _STR, "system": _STR, "location": _STR,
            "template": _STR, "manufacturer": _STR, "model": _STR, "code": _STR, "sub": _STR, "lines": _STRS, "brand": _STR,
            "count": _INT, "suffix": _STR, "icon": _STR, "note": _STR, "aliases": _STRS, "dante": _BOOL, "dante_name": _STR,
            "status": _STATUS, "tags": _STRS, "weight_kg": _KG, "power_w": _KG,
            "routing": _obj({"mode": {"type": "string", "enum": list(ROUTING_MODES)}, "map": _arr(_arr(_STR))}),
            "ports": _arr(_PORT),
            "flow": _obj({"group": _STR, "column": _STR, "order": _INT, "seq": _INT, "show": _BOOL}),
            "patch": _obj({"x": _NUM, "y": _NUM, "collapsed": _BOOL}),
            "rack": _obj({"id": _STR, "u": _INT, "height": _INT, "face": {"type": "string", "enum": ["front", "rear"]},
                          "side": {"type": "string", "enum": ["full", "left", "right"]}, "depth": {"type": "string", "enum": ["full", "half"]},
                          "shelf": _STR, "slot": {"type": "integer", "minimum": 0}, "color": _STR,
                          "image_front": _STR, "image_rear": _STR}),
            "inventory": _obj({"serial": _STR, "asset_tag": _STR, "firmware": _STR, "purchase_date": _STR, "warranty_until": _STR,
                               "vendor": _STR, "cost": _NUM, "currency": _STR, "po": _STR, "notes": _STR,
                               "condition": {"type": "string", "enum": list(CONDITIONS)},
                               "fields": {"type": "object", "additionalProperties": _STR, "maxProperties": MAX_CUSTOM_FIELDS}}),
            "container": _ID,
            "short_code": {"type": "string", "pattern": SHORT_CODE_RE.pattern},
            "interfaces": _arr(_INTERFACE),
            "dmx": _obj({"universe": _INT, "address": _INT, "footprint": _INT, "mode": _STR, "channel": _STR,
                         "protocol": {"type": "string", "enum": ["dmx", "sacn", "artnet"]}, "port": _STR}),
            "channels": _arr(_CHANNEL),
            "channel_links": _arr(_CHANNEL_LINK),
        }, ("id", "name", "kind", "ports"))),
        "cables": _arr(_obj({
            "id": _ID, "from": _ENDPOINT, "to": _ENDPOINT, "medium": _STR, "tag": _STR, "type": _STR, "length_m": _NUM,
            "color": _STR, "channels": _INT, "status": _STATUS, "bidirectional": _BOOL, "bundle": _STR, "label": _STR,
            "signal": _STR, "note": _STR, "count": _INT, "from_text": _STR, "to_text": _STR,
            "flow": _obj({"seq": _INT, "from_card": _STR, "to_card": _STR}),
            "route": _ROUTE,
        }, ("id", "from", "to", "medium"))),
        "bundles": _arr(_obj({
            "id": _ID, "kind": {"type": "string", "enum": ["multicore", "loom", "snake", "link"]}, "tag": _STR, "type": _STR,
            "length_m": _NUM, "medium": _STR, "label": _STR, "signal": _STR, "note": _STR, "count": _INT,
            "from_text": _STR, "to_text": _STR, "bidirectional": _BOOL, "flow": _obj({"seq": _INT, "from_card": _STR, "to_card": _STR}),
            "route": _ROUTE,
        }, ("id",))),
        "floorplans": _arr(_obj({
            "id": _ID, "name": _STR, "room": _STR,
            "source": _obj({"attachment": _STR, "kind": _STR, "page": _INT}),
            "image": _obj({"attachment": _STR, "kind": _STR, "width": _NUM, "height": _NUM}),
            "layers": _arr(_obj({"name": _STR, "color": _STR, "visible": _BOOL, "count": _INT})),
            "hidden_layers": _STRS,
            "calibration": _obj({"p1": _arr(_NUM), "p2": _arr(_NUM), "distance": _NUM, "unit": {"type": "string", "enum": ["m", "ft"]}}),
            "units": {"type": "object"},
            "markers": _arr(_obj({"device": _STR, "x": _NUM, "y": _NUM, "rotation": _NUM, "label": _STR}, ("device", "x", "y"))),
            "paths": _arr(_PATH),
            "order": _INT, "notes": _STR,
        }, ("id", "name", "room", "source", "image"))),
        "attachments": _arr(_obj({
            "id": _ID, "name": _STR, "file": _STR, "mime": _STR, "size": _INT, "sha256": _STR, "device": _STR,
            "kind": {"type": "string", "enum": ["photo", "document", "floorplan", "floorplan-source", "other"]},
            "uploaded": _STR, "by": _STR, "note": _STR,
        }, ("id", "name", "file", "mime"))),
        "templates": _arr(_obj({"id": {"type": "string"}, "manufacturer": _STR, "model": _STR, "kind": _STR, "ports": {"type": "array"}}, ("id",))),
        "imports": _arr(_obj({"id": _ID, "kind": _STR, "path": _STR, "device": _STR, "room": _STR, "label": _STR,
                              "options": {"type": "object"}, "added": _STR, "by": _STR}, ("id", "kind", "path"))),
        "pages": _arr(_obj({
            "id": _ID, "slug": {"type": "string", "pattern": SLUG_RE.pattern}, "title": _STR, "parent": {"type": ["string", "null"]},
            "order": _INT, "kind": {"type": "string", "enum": list(PAGE_KINDS)}, "body": _STR, "summary": _STR, "tags": _STRS,
            "rooms": _STRS, "devices": _STRS, "attachments": _STRS, "status": {"type": "string", "enum": list(PAGE_STATUSES)},
            "owner": _STR, "created": _STR, "updated": _STR, "updated_by": _STR, "review_due": _STR,
            "completions": _arr(_obj({"at": _STR, "by": _STR}, ("at",))),
        }, ("id", "slug", "title"))),
        "problems": _arr(_obj({
            "id": _ID, "text": _STR, "device": _STR, "room": _STR, "page": _STR, "status": {"type": "string", "enum": list(PROBLEM_STATUSES)},
            "created": _STR, "by": _STR, "via": {"type": "string", "enum": ["app", "public", "share"]}, "attachment": _STR,
            "resolved": _STR, "resolved_by": _STR, "note": _STR, "kind": {"type": "string", "enum": ["problem", "suggestion"]},
        }, ("id", "text"))),
        "scenes": _arr(_obj({
            "id": _ID, "name": {"type": "string", "maxLength": MAX_SCENE_NAME}, "note": _STR, "base": _BOOL,
            "created": _STR, "by": _STR, "updated": _STR,
            "data": _obj({
                "cables": {"type": "array", "items": {"type": "object"}}, "bundles": {"type": "array", "items": {"type": "object"}},
                "markers": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "object"}}},
                "devices": {"type": "object", "additionalProperties": _obj({
                    "room": _STR, "location": _STR, "rack": {"type": "object"}, "patch": {"type": "object"}})},
            }),
        }, ("id", "name"))),
    },
}
