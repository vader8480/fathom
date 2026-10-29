"""Church room starter templates (FR-ROOM-09/10/11, §5.6 *Starters*).

Each bundled starter is a one-room sample project under ``fathom/samples/church-*``
whose ids are all prefixed with its room id. ``list_starters`` describes them for
the New-project dialog and the Rooms view; ``merge_room`` copies one into an
existing doc as a new room, re-prefixing every id so the same starter can be
added more than once.

**User starters** (Phase 6 P6A, Knox "Save as template…") live under
``FATHOM_DATA/starters/<id>/`` as ``starter.json`` (the descriptor) plus
``project.json`` (a one-room normalized doc of the same shape as the bundled
samples). Their ids are ``user-<slug>``; ``room_to_starter_doc`` extracts a room
from a project, ``save_starter`` / ``delete_starter`` manage the folder under
``FATHOM_DATA/starters/.lock``, and every lookup (``get_starter``,
``load_starter_doc``, ``merge_room``, ``fathom new --template``) accepts user ids
transparently.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .project import SAMPLES_DIR, data_root

Doc = Dict[str, Any]

USER_PREFIX = "user-"
_USER_ID_RE = re.compile(r"^user-[a-z0-9][a-z0-9-]{0,79}$")
#: Tags offered by the Save-as-starter dialog; other short tags are kept as typed.
STARTER_TAGS: Tuple[str, ...] = ("audio", "video", "lighting", "network", "inventory")
MAX_LABEL = 80
MAX_BLURB = 500
MAX_TAGS = 10
#: ``device.inventory`` keys that describe one physical unit rather than the design (FR-ROOM-11).
_UNIT_INVENTORY_KEYS = ("serial", "asset_tag", "price", "cost")

STARTERS: List[Dict[str, Any]] = [
    {"id": "church-sanctuary", "label": "Sanctuary / auditorium", "room": "sanc", "tags": ["audio", "video", "lighting"],
     "blurb": "About 300 seats: digital FOH console with a Dante stage box, four wireless channels, IEMs, DSP and amps, two PTZ cameras "
              "into a switcher feeding two projectors and a confidence monitor, lighting console with a DMX node and eight fixtures, three racks."},
    {"id": "church-youth-room", "label": "Youth room / multipurpose", "room": "youth", "tags": ["audio", "video", "lighting"],
     "blurb": "Small digital mixer, two wireless mics, powered speakers, one projector behind an HDMI switcher, four LED pars on a small DMX controller, one wall rack."},
    {"id": "church-chapel", "label": "Chapel / traditional", "room": "chpl", "tags": ["audio", "video"],
     "blurb": "Analog and minimal: small mixer, lectern mic and two wireless channels, amplifier and two wall speakers, hearing-assist transmitter, one display."},
    {"id": "church-portable", "label": "Portable church (road cases)", "room": "port", "tags": ["audio", "video", "inventory"],
     "blurb": "Road cases as containers holding the console, stage box, wireless, speakers on stands and the cable trunk; every item has a load-in tag and a condition."},
    {"id": "church-broadcast", "label": "Broadcast / livestream booth", "room": "bcast", "tags": ["video", "audio", "network"],
     "blurb": "Three SDI cameras into a switcher, encoder and recorder, Dante audio feed from FOH, multiview and program monitors, intercom, broadcast rack with a stream VLAN."},
]

#: Collections copied from a starter into the target doc (in merge order).
_ROOM_COLLECTIONS = ("systems", "locations", "racks", "bundles", "devices", "cables", "floorplans", "pages")
_REF_RE = re.compile(r"\[\[(?P<kind>device|room|page):(?P<id>[^\]|\n]+?)(?P<rest>(?:\|[^\]\n]+)?\]\])")


class StarterError(ValueError):
    def __init__(self, message: str, code: str = "bad_enum") -> None:
        super().__init__(message)
        self.code = code


def starter_ids() -> List[str]:
    """Bundled starter ids in ``STARTERS`` order (user starters are listed by ``list_starters``)."""
    return [s["id"] for s in STARTERS]


def is_user_id(starter_id: Any) -> bool:
    return isinstance(starter_id, str) and bool(_USER_ID_RE.match(starter_id))


def starters_root() -> Path:
    """``FATHOM_DATA/starters`` (user starters; created on the first save)."""
    return data_root() / "starters"


def _user_dir(starter_id: str) -> Path:
    return starters_root() / starter_id


def _read_user_meta(starter_id: str) -> Optional[Dict[str, Any]]:
    """The ``starter.json`` descriptor of a user starter, or None when missing / corrupt / mismatched."""
    if not is_user_id(starter_id):
        return None
    path = _user_dir(starter_id) / "starter.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("id") != starter_id or not isinstance(raw.get("room"), str) or not raw.get("room"):
        return None
    meta = {
        "id": starter_id,
        "label": str(raw.get("label") or starter_id[len(USER_PREFIX):]),
        "blurb": str(raw.get("blurb") or ""),
        "room": str(raw["room"]),
        "tags": [str(t) for t in raw.get("tags") or [] if isinstance(t, str) and t],
        "created": str(raw.get("created") or ""),
        "created_by": str(raw.get("created_by") or ""),
        "source_project": str(raw.get("source_project") or ""),
        "source_room": str(raw.get("source_room") or ""),
        "source": "user",
    }
    return meta


def _user_ids() -> List[str]:
    root = starters_root()
    if not root.is_dir():
        return []
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    return [n for n in names if is_user_id(n)]


def get_starter(starter_id: str) -> Optional[Dict[str, Any]]:
    """Descriptor of a bundled (``"source": "bundled"``) or user (``"source": "user"``) starter; None when unknown."""
    for s in STARTERS:
        if s["id"] == starter_id:
            return dict(s, source="bundled")
    return _read_user_meta(starter_id)


def load_starter_doc(starter_id: str) -> Doc:
    """The starter's ``project.json`` (normalized); ``StarterError`` for an unknown id."""
    s = get_starter(starter_id)
    if s is None:
        raise StarterError(f"unknown starter '{starter_id}'", "not_found" if is_user_id(starter_id) else "bad_enum")
    path = (_user_dir(starter_id) if s.get("source") == "user" else SAMPLES_DIR / s["id"]) / "project.json"
    if not path.is_file():
        raise StarterError(f"starter '{starter_id}' is not installed", "not_found")
    from . import schema

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise StarterError(f"starter '{starter_id}' is corrupt: {exc}", "not_found")
    if not isinstance(raw, dict):
        raise StarterError(f"starter '{starter_id}' is corrupt", "not_found")
    return schema.normalize(raw)


def _room_of(doc: Doc, room_id: str) -> Optional[Dict[str, Any]]:
    for r in doc.get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == room_id:
            return r
    return None


def _entry(s: Dict[str, Any], doc: Doc) -> Dict[str, Any]:
    room = _room_of(doc, s["room"]) or {}
    entry = dict(s)
    entry.setdefault("source", "bundled")
    entry.update({
        "room_name": str(room.get("name") or s["label"]),
        "room_kind": str(room.get("kind") or ""),
        "devices": len(doc.get("devices") or []),
        "cables": len(doc.get("cables") or []),
        "racks": len(doc.get("racks") or []),
        "pages": len(doc.get("pages") or []),
        "description": str((doc.get("meta") or {}).get("description") or ""),
    })
    return entry


def starter_entry(starter_id: str) -> Dict[str, Any]:
    """One ``list_starters`` row (descriptor + counts); ``StarterError`` ``not_found`` when unknown or unreadable."""
    s = get_starter(starter_id)
    if s is None:
        raise StarterError(f"unknown starter '{starter_id}'", "not_found")
    try:
        doc = load_starter_doc(starter_id)
    except (OSError, ValueError) as exc:
        raise StarterError(f"starter '{starter_id}' is unreadable: {exc}", "not_found")
    return _entry(s, doc)


def list_starters() -> List[Dict[str, Any]]:
    """Starter rows with counts and the room name read from each doc: bundled starters in ``STARTERS``
    order, then user starters by id. Missing or corrupt starters are skipped."""
    out: List[Dict[str, Any]] = []
    for sid in starter_ids() + _user_ids():
        try:
            out.append(starter_entry(sid))
        except (StarterError, OSError, ValueError):
            continue
    return out


# ------------------------------------------------------------------ merge


def _all_ids(doc: Doc) -> Set[str]:
    from .schema import COLLECTIONS

    taken: Set[str] = set()
    for coll in COLLECTIONS:
        for e in doc.get(coll) or []:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                taken.add(e["id"])
    for p in doc.get("pages") or []:
        if isinstance(p, dict) and isinstance(p.get("slug"), str):
            taken.add(p["slug"])
    return taken


def _room_code(name: str, taken: Set[str]) -> str:
    from .cables import room_code

    base = room_code({"name": name}) or "ROOM"
    code = base[:8]
    n = 2
    while code in taken:
        suffix = str(n)
        code = base[: max(1, 8 - len(suffix))] + suffix
        n += 1
    return code


def merge_room(doc: Doc, starter_id: str, room_name: Optional[str] = None, prefix: Optional[str] = None) -> Tuple[Doc, Dict[str, Any]]:
    """Copy ``starter_id``'s room into ``doc`` as a new room.

    Returns ``(new_doc, info)`` where ``info = {"room", "name", "devices", "cables", "racks", "pages", "networks"}``.
    Every id of the starter's room, systems, locations, racks, bundles, devices, cables,
    floor plans and pages (and page slugs) is re-prefixed with ``prefix`` (default: the new
    room id, the slug of ``room_name``); networks and project templates are shared and kept
    by id when they already exist. Cable tags swap the starter's room code for the new
    room's. ``doc`` is not modified.
    """
    from . import schema
    from .model import slug

    s = get_starter(starter_id)
    if s is None:
        raise StarterError(f"unknown starter '{starter_id}'")
    src = load_starter_doc(starter_id)
    old_room = s["room"]
    src_room = _room_of(src, old_room)
    if src_room is None:
        raise StarterError(f"starter '{starter_id}' has no room '{old_room}'", "not_found")

    out: Doc = dict(doc)
    for coll in schema.COLLECTIONS:
        out[coll] = [copy.deepcopy(e) for e in (doc.get(coll) or []) if isinstance(e, dict)]
    taken = _all_ids(out)
    name = (room_name or "").strip() or str(src_room.get("name") or s["label"])
    new_room = schema._dedupe_id((prefix or "").strip() or slug(name), taken)
    taken.add(new_room)
    old_pre = old_room + "-"

    def rename(old_id: Any) -> Any:
        if not isinstance(old_id, str) or not old_id:
            return old_id
        tail = old_id[len(old_pre):] if old_id.startswith(old_pre) else old_id
        return f"{new_room}-{tail}"

    # ids that get renamed: everything in the room collections plus the room itself
    renamed: Dict[str, str] = {old_room: new_room}
    for coll in _ROOM_COLLECTIONS:
        for e in src.get(coll) or []:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                renamed[e["id"]] = schema._dedupe_id(rename(e["id"]), taken)
                taken.add(renamed[e["id"]])
    slugs: Dict[str, str] = {}
    for p in src.get("pages") or []:
        if isinstance(p, dict) and isinstance(p.get("slug"), str):
            slugs[p["slug"]] = schema._dedupe_id(rename(p["slug"]), taken)
            taken.add(slugs[p["slug"]])

    def ref(v: Any) -> Any:
        return renamed.get(v, v) if isinstance(v, str) else v

    def body(text: Any) -> Any:
        if not isinstance(text, str):
            return text

        def sub(m: "re.Match[str]") -> str:
            kind, rid = m.group("kind"), m.group("id")
            new = slugs.get(rid, rid) if kind == "page" else renamed.get(rid, rid)
            return f"[[{kind}:{new}{m.group('rest')}"

        return _REF_RE.sub(sub, text)

    # venue: the target's default (or first) venue; copy the starter's when the doc has none
    venues = [v for v in out.get("venues") or [] if isinstance(v, dict) and v.get("id")]
    default_room = _room_of(out, str((out.get("settings") or {}).get("default_room") or ""))
    venue_id = str((default_room or {}).get("venue") or (venues[0]["id"] if venues else ""))
    if not venue_id or venue_id not in {v["id"] for v in venues}:
        src_venue = next((v for v in src.get("venues") or [] if isinstance(v, dict) and v.get("id") == src_room.get("venue")), None)
        venue_id = schema._dedupe_id(rename(str((src_venue or {}).get("id") or "venue")), taken)
        taken.add(venue_id)
        nv = copy.deepcopy(src_venue) if src_venue else {"name": "Main venue"}
        nv["id"] = venue_id
        out["venues"] = venues + [nv]

    used_ips: Set[str] = set()
    for d in out.get("devices") or []:
        for itf in d.get("interfaces") or []:
            if isinstance(itf, dict) and itf.get("ip"):
                used_ips.add(str(itf["ip"]))

    room_codes = {str(r.get("code") or "") for r in out.get("rooms") or [] if isinstance(r, dict)}
    new_code = _room_code(name, room_codes)
    old_code = str(src_room.get("code") or "")

    room = copy.deepcopy(src_room)
    room.update({"id": new_room, "name": name, "venue": venue_id, "code": new_code,
                 "order": max([int(r.get("order") or 0) for r in out.get("rooms") or [] if isinstance(r, dict)] or [0]) + 1})
    for card in (room.get("flow") or {}).get("extra_cards") or []:
        if isinstance(card, dict):
            card["id"] = ref(card.get("id"))
            card["device"] = ref(card.get("device"))
    out["rooms"].append(room)

    # shared collections: keep existing entries by id
    have_net = {n.get("id") for n in out.get("networks") or []}
    for n in src.get("networks") or []:
        if isinstance(n, dict) and n.get("id") and n["id"] not in have_net:
            out["networks"].append(copy.deepcopy(n))
            have_net.add(n["id"])
    used_templates = {d.get("template") for d in src.get("devices") or [] if isinstance(d, dict)}
    have_tpl = {t.get("id") for t in out.get("templates") or []}
    for t in src.get("templates") or []:
        if isinstance(t, dict) and t.get("id") in used_templates and t["id"] not in have_tpl:
            out["templates"].append(copy.deepcopy(t))
            have_tpl.add(t["id"])

    counts = {"devices": 0, "cables": 0, "racks": 0, "pages": 0}
    for coll in _ROOM_COLLECTIONS:
        for e in src.get(coll) or []:
            if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                continue
            x = copy.deepcopy(e)
            x["id"] = renamed[e["id"]]
            if coll != "pages":
                for k in ("room", "system", "location", "container", "bundle"):
                    if k in x:
                        x[k] = ref(x[k])
                if "venue" in x:
                    x["venue"] = venue_id
            if coll == "devices":
                if isinstance(x.get("rack"), dict):
                    x["rack"]["id"] = ref(x["rack"].get("id"))
                for itf in x.get("interfaces") or []:
                    if not isinstance(itf, dict):
                        continue
                    if itf.get("switch"):
                        itf["switch"] = ref(itf["switch"])
                    # an address already used in the target is left for the editor to assign
                    if itf.get("ip") and str(itf["ip"]) in used_ips:
                        itf.pop("ip", None)
                    elif itf.get("ip"):
                        used_ips.add(str(itf["ip"]))
                x.pop("short_code", None)
            elif coll == "cables":
                for end in ("from", "to"):
                    if isinstance(x.get(end), dict):
                        x[end]["device"] = ref(x[end].get("device"))
                if old_code and isinstance(x.get("tag"), str) and x["tag"].startswith(old_code + "-"):
                    x["tag"] = new_code + x["tag"][len(old_code):]
            elif coll == "bundles":
                if old_code and isinstance(x.get("tag"), str) and x["tag"].startswith(old_code + "-"):
                    x["tag"] = new_code + x["tag"][len(old_code):]
            elif coll == "floorplans":
                for m in x.get("markers") or []:
                    if isinstance(m, dict):
                        m["device"] = ref(m.get("device"))
            elif coll == "pages":
                x["slug"] = slugs.get(e.get("slug"), x.get("slug"))
                x["parent"] = ref(x.get("parent")) if x.get("parent") else x.get("parent")
                x["rooms"] = [ref(r) for r in x.get("rooms") or []]
                x["devices"] = [ref(d) for d in x.get("devices") or []]
                x["body"] = body(x.get("body"))
                x["summary"] = body(x.get("summary"))
            out[coll].append(x)
            if coll in counts:
                counts[coll] += 1

    info = {"room": new_room, "name": name, "code": new_code, "starter": starter_id, "networks": len(out["networks"]) - len(doc.get("networks") or [])}
    info.update(counts)
    return out, info


# ------------------------------------------------------------------ extraction (FR-ROOM-11)


def _ids_of(items: Any) -> Set[str]:
    return {e["id"] for e in items or [] if isinstance(e, dict) and isinstance(e.get("id"), str)}


def _attachment_ref(v: Any) -> Optional[str]:
    """The attachment id a floor plan ``source`` / ``image`` points at (``None`` for inline or absent)."""
    if isinstance(v, dict) and v.get("attachment"):
        return str(v["attachment"])
    return None


def room_to_starter_doc(doc: Doc, room_id: str, blurb: str = "") -> Tuple[Doc, Dict[str, Any]]:
    """Extract ``room_id`` from ``doc`` as a one-room starter doc (same shape as the bundled samples).

    Returns ``(starter_doc, info)``; ``info = {"room", "name", "devices", "cables", "racks", "pages",
    "networks", "dropped_cables", "dropped_files"}``. Kept: the room and its venue, the room's
    systems / locations / racks (plus any a kept device or rack references, re-homed to the room),
    devices with ``room == room_id``, cables whose **both** ends are kept devices (others are dropped and
    counted in ``dropped_cables``), bundles with remaining members, floor plans of the room with the
    markers of kept devices, pages that list the room or a kept device, the networks and project
    templates kept devices use. Attachments are never copied: a floor plan whose image or source is a
    file is dropped whole, device photos and page attachments are detached — each attachment counts
    once in ``dropped_files``. Templates are not inventories: device ``status`` becomes ``planned`` and
    ``inventory.serial`` / ``asset_tag`` / ``price`` / ``cost``, ``code`` and ``short_code`` are removed.
    Ids are kept (``merge_room`` re-prefixes them on use). ``doc`` is not modified.
    """
    from . import schema
    from .model import slug

    room = _room_of(doc, room_id)
    if room is None:
        raise StarterError(f"room '{room_id}' not found", "not_found")
    name = str(room.get("name") or room_id)

    def rows(coll: str) -> List[Dict[str, Any]]:
        return [e for e in doc.get(coll) or [] if isinstance(e, dict) and isinstance(e.get("id"), str)]

    devices = [copy.deepcopy(d) for d in rows("devices") if d.get("room") == room_id]
    dev_ids = _ids_of(devices)
    racks = [copy.deepcopy(r) for r in rows("racks") if r.get("room") == room_id]
    rack_ids = _ids_of(racks)
    rack_by_id = {r["id"]: r for r in rows("racks")}
    for d in devices:
        rk = d.get("rack")
        rid = rk.get("id") if isinstance(rk, dict) else None
        if rid and rid not in rack_ids and rid in rack_by_id:
            racks.append(copy.deepcopy(rack_by_id[rid]))
            rack_ids.add(rid)
    for r in racks:
        r["room"] = room_id

    want_sys = {d.get("system") for d in devices if d.get("system")}
    systems = [copy.deepcopy(s) for s in rows("systems") if s.get("room") == room_id or s["id"] in want_sys]
    for s in systems:
        s["room"] = room_id
    want_loc = {d.get("location") for d in devices if d.get("location")} | {r.get("location") for r in racks if r.get("location")}
    locations = [copy.deepcopy(loc) for loc in rows("locations") if loc.get("room") == room_id or loc["id"] in want_loc]
    for loc in locations:
        if loc.get("room"):
            loc["room"] = room_id

    dropped_files: Set[str] = set()
    for a in rows("attachments"):
        if a.get("device") and a["device"] in dev_ids:
            dropped_files.add(a["id"])

    net_ids = _ids_of(doc.get("networks"))
    want_net: Set[str] = set()
    for d in devices:
        d["status"] = "planned"
        d.pop("code", None)
        d.pop("short_code", None)
        inv = d.get("inventory")
        if isinstance(inv, dict):
            for k in _UNIT_INVENTORY_KEYS:
                inv.pop(k, None)
            if not inv:
                d.pop("inventory", None)
        if d.get("container") and d["container"] not in dev_ids:
            d.pop("container", None)
        rk = d.get("rack")
        if isinstance(rk, dict) and rk.get("id") and rk["id"] not in rack_ids:
            d.pop("rack", None)
        if d.get("system") and d["system"] not in _ids_of(systems):
            d.pop("system", None)
        if d.get("location") and d["location"] not in _ids_of(locations):
            d.pop("location", None)
        for itf in d.get("interfaces") or []:
            if not isinstance(itf, dict):
                continue
            if itf.get("switch") and itf["switch"] not in dev_ids:
                itf.pop("switch", None)
                itf.pop("switch_port", None)
            if itf.get("network") and itf["network"] in net_ids:
                want_net.add(itf["network"])
    networks = [copy.deepcopy(n) for n in rows("networks") if n["id"] in want_net]

    cables: List[Dict[str, Any]] = []
    dropped_cables = 0
    for c in rows("cables"):
        ends = [c.get(end) for end in ("from", "to")]
        if all(isinstance(e, dict) and e.get("device") in dev_ids for e in ends):
            cables.append(copy.deepcopy(c))
        elif any(isinstance(e, dict) and e.get("device") in dev_ids for e in ends):
            dropped_cables += 1
    used_bundles = {c.get("bundle") for c in cables if c.get("bundle")}
    bundles = [copy.deepcopy(b) for b in rows("bundles") if b["id"] in used_bundles]
    bundle_ids = _ids_of(bundles)
    for c in cables:
        if c.get("bundle") and c["bundle"] not in bundle_ids:
            c.pop("bundle", None)

    floorplans: List[Dict[str, Any]] = []
    for f in rows("floorplans"):
        if f.get("room") != room_id:
            continue
        refs = [a for a in (_attachment_ref(f.get("source")), _attachment_ref(f.get("image"))) if a]
        if refs:
            dropped_files.update(refs)
            continue
        x = copy.deepcopy(f)
        x["markers"] = [m for m in x.get("markers") or [] if isinstance(m, dict) and m.get("device") in dev_ids]
        floorplans.append(x)

    pages: List[Dict[str, Any]] = []
    for p in rows("pages"):
        in_room = room_id in (p.get("rooms") or [])
        linked = any(d in dev_ids for d in p.get("devices") or [])
        if not (in_room or linked):
            continue
        x = copy.deepcopy(p)
        x["rooms"] = [room_id]
        x["devices"] = [d for d in x.get("devices") or [] if d in dev_ids]
        for a in x.get("attachments") or []:
            if isinstance(a, str) and a:
                dropped_files.add(a)
        x.pop("attachments", None)
        x.pop("completions", None)
        pages.append(x)
    page_ids = _ids_of(pages)
    for p in pages:
        if p.get("parent") and p["parent"] not in page_ids:
            p["parent"] = None

    used_templates = {d.get("template") for d in devices if d.get("template")}
    templates = [copy.deepcopy(t) for t in rows("templates") if t["id"] in used_templates]

    venues = [copy.deepcopy(v) for v in rows("venues") if v["id"] == room.get("venue")]
    new_room = copy.deepcopy(room)
    if not venues:
        venues = [{"id": "venue", "name": str((doc.get("meta") or {}).get("org") or "Main venue")}]
        new_room["venue"] = "venue"
    for loc in locations:
        if loc.get("venue"):
            loc["venue"] = venues[0]["id"]

    src_settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    settings = {k: copy.deepcopy(v) for k, v in src_settings.items() if k not in ("locked", "scene", "public_url", "default_room")}
    settings["default_room"] = room_id
    src_meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    meta = {
        "org": str(src_meta.get("org") or ""),
        "system": name,
        "title": name,
        "slug": slug(name),
        "description": (blurb or "").strip(),
    }
    if src_meta.get("footnote"):
        meta["footnote"] = str(src_meta["footnote"])

    out: Doc = {"fathom": 2, "revision": 0, "meta": meta, "settings": settings}
    out.update({c: [] for c in schema.COLLECTIONS})
    out.update({
        "venues": venues, "rooms": [new_room], "systems": systems, "locations": locations, "racks": racks,
        "networks": networks, "devices": devices, "cables": cables, "bundles": bundles, "floorplans": floorplans,
        "templates": templates, "pages": pages,
    })
    out = schema.normalize(out)
    info = {
        "room": room_id, "name": name, "devices": len(devices), "cables": len(cables), "racks": len(racks), "pages": len(pages),
        "networks": len(networks), "dropped_cables": dropped_cables, "dropped_files": len(dropped_files),
    }
    return out, info


# ------------------------------------------------------------------ user starters: save / delete


def _clean_tags(tags: Any) -> List[str]:
    out: List[str] = []
    for t in tags if isinstance(tags, (list, tuple)) else []:
        if not isinstance(t, str):
            continue
        s = re.sub(r"[^a-z0-9-]+", "-", t.strip().lower()).strip("-")[:24]
        if s and s not in out:
            out.append(s)
    return out[:MAX_TAGS]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def save_starter(doc: Doc, room_id: str, label: str, blurb: str = "", tags: Any = None, *, replace: bool = False,
                 dedupe: bool = False, starter_id: Optional[str] = None, author: str = "", source_project: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extract ``room_id`` from ``doc`` and write it as the user starter ``user-<slug(label)>``.

    Returns ``(entry, info)`` (the ``list_starters`` row and ``room_to_starter_doc``'s info).
    ``StarterError`` codes: ``missing_field`` (empty label), ``not_found`` (unknown room), ``bundled``
    (``starter_id`` names a bundled starter), ``bad_id`` (``starter_id`` is not ``user-…``), ``exists``
    (the id is taken and neither ``replace`` nor ``dedupe`` is set; ``dedupe`` appends ``-2``, ``-3``…).
    Both files are written atomically under ``FATHOM_DATA/starters/.lock``.
    """
    from .model import slug
    from .project import _atomic_write_json, project_lock

    label = (label or "").strip()[:MAX_LABEL]
    if not label:
        raise StarterError("a starter needs a label", "missing_field")
    blurb = (blurb or "").strip()[:MAX_BLURB]
    if starter_id:
        if any(s["id"] == starter_id for s in STARTERS):
            raise StarterError(f"'{starter_id}' is a bundled starter and cannot be replaced", "bundled")
        if not is_user_id(starter_id):
            raise StarterError(f"user starter ids look like user-<slug> (got {starter_id!r})", "bad_id")
        sid = starter_id
    else:
        sid = USER_PREFIX + slug(label)[:79]
    sdoc, info = room_to_starter_doc(doc, room_id, blurb)
    root = starters_root()
    with project_lock(root):
        if (root / sid).exists() and not replace:
            if not dedupe:
                raise StarterError(f"a starter '{sid}' already exists", "exists")
            taken = set(_user_ids())
            n = 2
            base = sid
            while sid in taken:
                sid = f"{base}-{n}"
                n += 1
        prev = _read_user_meta(sid) if replace else None
        meta = {
            "id": sid, "label": label, "blurb": blurb, "room": room_id, "tags": _clean_tags(tags),
            "created": (prev or {}).get("created") or _now(), "created_by": (author or "").strip(),
            "source_project": (source_project or "").strip(), "source_room": room_id,
        }
        if prev:
            meta["updated"] = _now()
        _atomic_write_json(root / sid / "project.json", sdoc)
        _atomic_write_json(root / sid / "starter.json", meta)
    entry = _entry(dict(_read_user_meta(sid) or dict(meta, source="user")), sdoc)
    return entry, info


def delete_starter(starter_id: str) -> None:
    """Remove a user starter folder; ``StarterError`` ``bundled`` for bundled ids, ``not_found`` otherwise."""
    from .project import project_lock

    if any(s["id"] == starter_id for s in STARTERS):
        raise StarterError(f"'{starter_id}' is a bundled starter and cannot be deleted", "bundled")
    if not is_user_id(starter_id):
        raise StarterError(f"unknown starter '{starter_id}'", "not_found")
    root = starters_root()
    with project_lock(root):
        target = root / starter_id
        if not target.is_dir():
            raise StarterError(f"unknown starter '{starter_id}'", "not_found")
        shutil.rmtree(target)


def new_project_from_starter(name_or_path: str, starter_id: str, org: str = "", force: bool = False) -> Path:
    """``fathom new <name> --template user-<slug>``: a blank project folder whose ``project.json`` is the
    starter doc (short codes assigned like a sample copy). ``SystemExit`` for an unknown starter."""
    from .project import _assign_codes_in_place, _atomic_write_json, new_project

    try:
        sdoc = load_starter_doc(starter_id)
    except StarterError as exc:
        ids = ", ".join(starter_ids() + _user_ids())
        raise SystemExit(f"error: {exc} (starters: {ids})")
    pdir = new_project(name_or_path, template="blank", org=org, force=force)
    if org:
        sdoc.setdefault("meta", {})["org"] = org
    _atomic_write_json(pdir / "project.json", sdoc)
    _assign_codes_in_place(pdir)
    return pdir
