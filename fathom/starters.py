"""Church room starter templates (FR-ROOM-09/10, §5.6 *Starters*).

Each starter is a bundled one-room sample project under ``fathom/samples/church-*``
whose ids are all prefixed with its room id. ``list_starters`` describes them for
the New-project dialog and the Rooms view; ``merge_room`` copies one into an
existing doc as a new room, re-prefixing every id so the same starter can be
added more than once.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .project import SAMPLES_DIR

Doc = Dict[str, Any]

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
    return [s["id"] for s in STARTERS]


def get_starter(starter_id: str) -> Optional[Dict[str, Any]]:
    for s in STARTERS:
        if s["id"] == starter_id:
            return s
    return None


def load_starter_doc(starter_id: str) -> Doc:
    """The starter's sample ``project.json`` (normalized); ``StarterError`` for an unknown id."""
    s = get_starter(starter_id)
    if s is None:
        raise StarterError(f"unknown starter '{starter_id}'")
    path = SAMPLES_DIR / s["id"] / "project.json"
    if not path.is_file():
        raise StarterError(f"starter '{starter_id}' is not installed", "not_found")
    from . import schema

    return schema.normalize(json.loads(path.read_text(encoding="utf-8")))


def _room_of(doc: Doc, room_id: str) -> Optional[Dict[str, Any]]:
    for r in doc.get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == room_id:
            return r
    return None


def list_starters() -> List[Dict[str, Any]]:
    """Starter descriptors with counts and the room name read from each sample (missing samples are skipped)."""
    out: List[Dict[str, Any]] = []
    for s in STARTERS:
        try:
            doc = load_starter_doc(s["id"])
        except (StarterError, OSError, ValueError):
            continue
        room = _room_of(doc, s["room"]) or {}
        entry = dict(s)
        entry.update({
            "room_name": str(room.get("name") or s["label"]),
            "room_kind": str(room.get("kind") or ""),
            "devices": len(doc.get("devices") or []),
            "cables": len(doc.get("cables") or []),
            "racks": len(doc.get("racks") or []),
            "pages": len(doc.get("pages") or []),
            "description": str((doc.get("meta") or {}).get("description") or ""),
        })
        out.append(entry)
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
