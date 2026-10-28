"""Assistant proposals: typed changes → §4.9 ops the user confirms (SPEC §5.10 ``proposal``, §6.9.5a).

``to_ops(doc, changes)`` resolves names to ids, instantiates library templates
and presets for ``add_device``, allocates free ports, cable ids and cable tags
for ``connect``, and validates the resulting doc with ``schema.validate_doc``.
Nothing here writes: ``new_proposal`` caches the result for 15 minutes so
``POST …/assistant/apply`` can apply it by id (the full proposal is also
returned, so a stateless client can send it back).
"""

from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]
Op = Dict[str, Any]

ACTIONS = ("add_device", "remove_device", "connect", "disconnect", "move_device", "set_field")
PROPOSAL_TTL = 15 * 60
PROPOSAL_CACHE_MAX = 200
MAX_CHANGES = 50
DEVICE_FIELDS = {"name", "note", "notes", "status", "aliases", "manufacturer", "model", "location", "dante_name", "code"}
INVENTORY_FIELDS = {"serial", "asset_tag", "purchase_date", "warranty_until", "cost", "vendor", "condition"}
PORT_FIELDS = {"label", "note", "name"}
CABLE_FIELDS = {"tag", "type", "length_m", "color", "note", "status", "signal", "channels"}
ROOM_FIELDS = {"name", "note", "code"}
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_DIR_WORDS = {"input": "in", "in": "in", "inputs": "in", "output": "out", "out": "out", "outputs": "out", "ch": "in", "channel": "in"}


# ----------------------------------------------------------------------------- resolution helpers

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40] or "device"


def _devs(doc: Doc) -> List[Dict[str, Any]]:
    return [d for d in doc.get("devices") or [] if isinstance(d, dict) and isinstance(d.get("id"), str)]


def _name(dev: Optional[Dict[str, Any]]) -> str:
    return str((dev or {}).get("name") or (dev or {}).get("id") or "?")


def _find_device(doc: Doc, text: Any, problems: List[str], what: str = "device") -> Optional[Dict[str, Any]]:
    from . import trace as T
    from .model import norm_name

    if isinstance(text, dict):
        text = text.get("id") or text.get("name") or text.get("device")
    t = str(text or "").strip()
    if not t:
        problems.append(f"{what}: no device named")
        return None
    devs = _devs(doc)
    d = T._match_device(devs, t)
    if d is not None:
        return d
    key = norm_name(t)
    hits = [x for x in devs if key and (key in norm_name(str(x.get("name") or "")) or key in norm_name(x["id"])
                                        or key in norm_name(str(x.get("model") or "")))]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        problems.append(f"{what}: '{t}' is ambiguous ({', '.join(_name(x) for x in hits[:6])}); say which one")
        return None
    try:
        from . import search as S

        sh = [h for h in S.search(doc, t, limit=5, kinds=["device"]) if h.get("score", 0) >= 60]
    except Exception:
        sh = []
    if sh:
        top = [h for h in sh if h["score"] == sh[0]["score"]]
        if len(top) == 1:
            return next((x for x in devs if x["id"] == top[0]["id"]), None)
        problems.append(f"{what}: '{t}' is ambiguous ({', '.join(str(h.get('title')) for h in top[:6])}); say which one")
        return None
    problems.append(f"{what}: no device matches '{t}'")
    return None


def _find_room(doc: Doc, text: Any) -> Optional[str]:
    t = str(text or "").strip()
    if not t:
        return None
    rooms = [r for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]
    for r in rooms:
        if r["id"] == t:
            return str(r["id"])
    low = t.casefold()
    for r in rooms:
        if str(r.get("name") or "").casefold() == low or str(r.get("code") or "").casefold() == low:
            return str(r["id"])
    hits = [r for r in rooms if low in str(r.get("name") or "").casefold()]
    return str(hits[0]["id"]) if len(hits) == 1 else None


def _used_ports(doc: Doc) -> Dict[Tuple[str, str], int]:
    used: Dict[Tuple[str, str], int] = {}
    for c in doc.get("cables") or []:
        if not isinstance(c, dict):
            continue
        for end in ("from", "to"):
            e = c.get(end) or {}
            if e.get("device") and e.get("port"):
                used[(str(e["device"]), str(e["port"]))] = used.get((str(e["device"]), str(e["port"])), 0) + 1
    return used


def _port_dir_ok(p: Dict[str, Any], side: str) -> bool:
    d = p.get("dir") or "io"
    return d == "io" or (side == "out" and d == "out") or (side == "in" and d == "in")


def _resolve_port(doc: Doc, dev: Dict[str, Any], text: Any, side: str, medium: Optional[str], problems: List[str]) -> Optional[str]:
    """Port id from a label / name / id / ``input 5`` phrase; ``None`` (with a problem line) when nothing fits."""
    from . import trace as T
    from .model import norm_name

    t = str(text or "").strip()
    ports = T.device_ports(dev)
    if not ports:
        problems.append(f"{_name(dev)} has no ports")
        return None
    pid = T._match_port(dev, t) if t else None
    if pid:
        return pid
    m = re.match(r"^([a-z][a-z /-]*?)\s*#?\s*(\d+)$", t.casefold())
    if m:
        head, n = m.group(1).strip(), int(m.group(2))
        words = [w for w in re.split(r"[\s/-]+", head) if w]
        want = _DIR_WORDS.get(words[-1]) if words else None
        rest = norm_name(" ".join(words[:-1])) if want else norm_name(head)
        cands = [p for p in ports if _port_dir_ok(p, want or side)]
        if rest:
            cands = [p for p in cands if rest in norm_name(str(p.get("group") or "")) or rest in norm_name(str(p.get("name") or ""))]
        by_index = [p for p in cands if T._port_index(p, ports) == n or p.get("index") == n]
        if medium:
            pref = [p for p in by_index if p.get("medium") == medium]
            by_index = pref or by_index
        groups = {str(p.get("group") or p["id"]) for p in by_index}
        if len(by_index) == 1 or (by_index and len(groups) == 1):
            return by_index[0]["id"]
        if len(by_index) > 1:
            problems.append(f"'{t}' on {_name(dev)} is ambiguous ({', '.join(T.port_label(p) or p['id'] for p in by_index[:6])})")
            return None
    problems.append(f"no port '{t}' on {_name(dev)}" + (f" (ports: {', '.join((T.port_label(p) or p['id']) for p in ports[:12])}{'…' if len(ports) > 12 else ''})"))
    return None


def _free_port(doc: Doc, dev: Dict[str, Any], side: str, medium: Optional[str], problems: List[str]) -> Optional[str]:
    from . import trace as T

    used = _used_ports(doc)
    ports = [p for p in T.device_ports(dev) if _port_dir_ok(p, side) and p.get("medium") not in ("power", "rf")]
    if medium:
        same = [p for p in ports if p.get("medium") == medium]
        ports = same or ports
    free = [p for p in ports if (dev["id"], p["id"]) not in used]
    if free:
        return free[0]["id"]
    if ports:
        problems.append(f"every {side}put on {_name(dev)} is already patched; name the port to reuse")
    else:
        problems.append(f"{_name(dev)} has no {side}put ports")
    return None


def _next_cable_id(doc: Doc) -> str:
    n = 0
    for c in doc.get("cables") or []:
        m = re.match(r"^c-(\d+)$", str((c or {}).get("id") or "")) if isinstance(c, dict) else None
        if m:
            n = max(n, int(m.group(1)))
    return f"c-{n + 1:04d}"


def _dedupe_id(doc: Doc, base: str) -> str:
    taken = {d["id"] for d in _devs(doc)}
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def _template_for(doc: Doc, change: Dict[str, Any], problems: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Library template or preset (as template) for an ``add_device``; ``(None, kind)`` for a bare device."""
    from . import library, presets

    text = str(change.get("template") or "").strip()
    model = str(change.get("model") or "").strip()
    manu = str(change.get("manufacturer") or "").strip()
    queries = [q for q in (text, f"{manu} {model}".strip(), model) if q]
    for q in queries:
        t = library.get_template(q, doc)
        if t:
            return t, ""
    for q in queries:
        found = library.list_templates(q=q, doc=doc)
        if len(found) > 1:
            exact = [f for f in found if str(f.get("model") or "").casefold() == q.casefold() or f["id"] == q.casefold()]
            found = exact or found
        if len(found) == 1:
            t = library.get_template(found[0]["id"], doc)
            if t:
                return t, ""
        if len(found) > 1:
            problems.append(f"'{q}' matches several templates ({', '.join(f['id'] for f in found[:6])}); say which one")
            return None, "?"
    for q in queries + [str(change.get("kind") or "")]:
        p = presets.find_preset(q) if q else None
        if p:
            return presets.as_template(p), ""
    kind, preset_id = presets.resolve_kind(str(change.get("kind") or ""))
    if preset_id:
        p = presets.get_preset(preset_id)
        if p:
            return presets.as_template(p), ""
    if kind:
        return None, kind
    if queries:
        problems.append(f"no template or preset matches '{queries[0]}'; give a library template id or a kind")
    else:
        problems.append("add_device needs a template, model or kind")
    return None, "?"


# ----------------------------------------------------------------------------- actions

def _add_device(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    from . import library

    t, kind = _template_for(work, change, problems)
    if t is None and kind == "?":
        return []
    name = str(change.get("name") or "").strip()
    room = _find_room(work, change.get("room")) if change.get("room") else None
    if change.get("room") and room is None:
        problems.append(f"unknown room '{change.get('room')}'")
        return []
    if room is None:
        room = str((work.get("settings") or {}).get("default_room") or "")
    want_id = str(change.get("id") or "").strip()
    base = _slug(want_id or name or (t or {}).get("model") or (t or {}).get("name") or kind)
    dev_id = _dedupe_id(work, base)
    if t is not None:
        dev = library.instantiate(t, device_id=dev_id, name=name or None, room=room)
        if not name:
            same = [d for d in _devs(work) if str(d.get("name") or "").casefold() == str(dev["name"]).casefold()]
            if same:
                dev["name"] = f"{dev['name']} {len(same) + 1}"
    else:
        dev = {"id": dev_id, "name": name or kind.replace("_", " ").title(), "kind": kind, "room": room, "ports": []}
        for k in ("manufacturer", "model"):
            if change.get(k):
                dev[k] = str(change[k])
    for k in ("note", "status", "location"):
        if change.get(k):
            dev[k] = change[k]
    if dev.get("status") and dev["status"] not in ("installed", "planned", "spare", "retired"):
        dev.pop("status")
    where = f" in {_room_label(work, room)}" if room else " in shared inventory"
    summary.append(f"Add device **{dev['name']}** ({(t or {}).get('manufacturer', '')} {(t or {}).get('model', dev.get('kind'))}".strip() + f"){where} (id {dev_id})")
    return [{"op": "put", "coll": "devices", "id": dev_id, "value": dev}]


def _room_label(doc: Doc, rid: str) -> str:
    for r in doc.get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == rid:
            return str(r.get("name") or rid)
    return rid


def _remove_device(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    dev = _find_device(work, change.get("device") or change.get("id") or change.get("name"), problems, "remove_device")
    if dev is None:
        return []
    ops: List[Op] = []
    n = 0
    for c in work.get("cables") or []:
        if isinstance(c, dict) and (((c.get("from") or {}).get("device") == dev["id"]) or ((c.get("to") or {}).get("device") == dev["id"])):
            ops.append({"op": "del", "coll": "cables", "id": str(c.get("id"))})
            n += 1
    ops.append({"op": "del", "coll": "devices", "id": dev["id"]})
    summary.append(f"Remove device **{_name(dev)}**" + (f" and its {n} cable{'s' if n != 1 else ''}" if n else ""))
    return ops


def _end(work: Doc, spec: Any, side: str, medium: Optional[str], problems: List[str], label: str) -> Optional[Tuple[Dict[str, Any], str]]:
    if isinstance(spec, str):
        spec = {"device": spec}
    if not isinstance(spec, dict):
        problems.append(f"connect: '{label}' must be {{device, port}}")
        return None
    dev = _find_device(work, spec.get("device") or spec.get("name") or spec.get("id"), problems, f"connect {label}")
    if dev is None:
        return None
    port_text = spec.get("port")
    if port_text:
        pid = _resolve_port(work, dev, port_text, side, medium, problems)
    else:
        pid = _free_port(work, dev, side, medium, problems)
    if pid is None:
        return None
    return dev, pid


def _connect(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    from . import trace as T
    from .cables import assign_tags_ops

    medium = str(change.get("medium") or "").strip() or None
    to_spec = change.get("to")
    from_spec = change.get("from")
    # resolve the named end first so the free-port allocation on the other end can match its medium
    to_end = _end(work, to_spec, "in", medium, problems, "to") if isinstance(to_spec, dict) and to_spec.get("port") else None
    if to_end is not None and medium is None:
        medium = (T.find_port(to_end[0], to_end[1]) or {}).get("medium")
    from_end = _end(work, from_spec, "out", medium, problems, "from")
    if from_end is None:
        return []
    if medium is None:
        medium = (T.find_port(from_end[0], from_end[1]) or {}).get("medium")
    if to_end is None:
        to_end = _end(work, to_spec, "in", medium, problems, "to")
    if to_end is None:
        return []
    fdev, fpid = from_end
    tdev, tpid = to_end
    if fdev["id"] == tdev["id"] and fpid == tpid:
        problems.append("connect: both ends are the same port")
        return []
    for c in work.get("cables") or []:
        if isinstance(c, dict) and (c.get("from") or {}).get("device") == fdev["id"] and (c.get("from") or {}).get("port") == fpid \
                and (c.get("to") or {}).get("device") == tdev["id"] and (c.get("to") or {}).get("port") == tpid:
            problems.append(f"{_name(fdev)} · {T.port_label(T.find_port(fdev, fpid))} is already patched to {_name(tdev)} · {T.port_label(T.find_port(tdev, tpid))} ({c.get('tag') or c.get('id')})")
            return []
    cable: Dict[str, Any] = {"id": _next_cable_id(work), "from": {"device": fdev["id"], "port": fpid}, "to": {"device": tdev["id"], "port": tpid},
                             "medium": medium or "other"}
    for k in ("type", "length_m", "color", "note"):
        if change.get(k) not in (None, ""):
            cable[k] = change[k]
    if change.get("tag"):
        cable["tag"] = str(change["tag"])
    else:
        probe = dict(work, cables=list(work.get("cables") or []) + [cable])
        for op in assign_tags_ops(probe, scope="missing"):
            if op.get("coll") == "cables" and op.get("id") == cable["id"]:
                cable["tag"] = op["value"]["tag"]
    summary.append(f"Patch **{_name(fdev)} · {T.port_label(T.find_port(fdev, fpid))}** → **{_name(tdev)} · {T.port_label(T.find_port(tdev, tpid))}** "
                   f"({medium or 'other'}, cable {cable.get('tag') or cable['id']})")
    return [{"op": "put", "coll": "cables", "id": cable["id"], "value": cable}]


def _disconnect(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    from . import trace as T

    cables = [c for c in work.get("cables") or [] if isinstance(c, dict) and c.get("id")]
    names = {d["id"]: _name(d) for d in _devs(work)}
    ref = str(change.get("cable") or change.get("tag") or change.get("id") or "").strip()
    found: List[Dict[str, Any]] = []
    if ref:
        found = [c for c in cables if c.get("id") == ref or str(c.get("tag") or "").casefold() == ref.casefold()]
        if not found:
            problems.append(f"disconnect: no cable '{ref}'")
            return []
    else:
        ends = []
        for key, side in (("from", "out"), ("to", "in")):
            spec = change.get(key)
            if isinstance(spec, str):
                spec = {"device": spec}
            if not isinstance(spec, dict):
                ends.append(None)
                continue
            dev = _find_device(work, spec.get("device") or spec.get("name") or spec.get("id"), problems, f"disconnect {key}")
            if dev is None:
                return []
            pid = _resolve_port(work, dev, spec["port"], side, None, problems) if spec.get("port") else None
            if spec.get("port") and pid is None:
                return []
            ends.append((dev["id"], pid))
        if not any(ends):
            problems.append("disconnect needs a cable id / tag or from / to ends")
            return []

        def match(c: Dict[str, Any]) -> bool:
            for e, key in zip(ends, ("from", "to")):
                if e is None:
                    continue
                ce = c.get(key) or {}
                if ce.get("device") != e[0] or (e[1] and ce.get("port") != e[1]):
                    return False
            return True

        found = [c for c in cables if match(c)]
        if not found:  # either orientation
            ends.reverse()
            found = [c for c in cables if match(c)]
        if not found:
            problems.append("disconnect: no cable matches those ends")
            return []
    ops = []
    for c in found:
        f, t = c.get("from") or {}, c.get("to") or {}
        fd = next((d for d in _devs(work) if d["id"] == f.get("device")), None)
        td = next((d for d in _devs(work) if d["id"] == t.get("device")), None)
        summary.append(f"Unpatch **{names.get(f.get('device'), f.get('device'))} · {T.port_label(T.find_port(fd, f.get('port'))) or f.get('port') or '*'}** → "
                       f"**{names.get(t.get('device'), t.get('device'))} · {T.port_label(T.find_port(td, t.get('port'))) or t.get('port') or '*'}** (cable {c.get('tag') or c['id']})")
        ops.append({"op": "del", "coll": "cables", "id": str(c["id"])})
    return ops


def _move_device(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    dev = _find_device(work, change.get("device") or change.get("id") or change.get("name"), problems, "move_device")
    if dev is None:
        return []
    value: Dict[str, Any] = {}
    bits = []
    if "room" in change:
        room = _find_room(work, change.get("room")) if change.get("room") else ""
        if change.get("room") and room is None:
            problems.append(f"move_device: unknown room '{change.get('room')}'")
            return []
        value["room"] = room or ""
        bits.append(f"to {_room_label(work, room) if room else 'shared inventory'}")
    rack = change.get("rack")
    if rack is not None:
        if rack in ("", None, False):
            value["rack"] = None
            bits.append("out of its rack")
        else:
            if isinstance(rack, str):
                rack = {"id": rack}
            if not isinstance(rack, dict):
                problems.append("move_device: rack must be {id, u, face?}")
                return []
            racks = [r for r in work.get("racks") or [] if isinstance(r, dict) and r.get("id")]
            rid = next((r["id"] for r in racks if r["id"] == rack.get("id") or str(r.get("name") or "").casefold() == str(rack.get("id") or rack.get("name") or "").casefold()), None)
            if rid is None:
                problems.append(f"move_device: unknown rack '{rack.get('id') or rack.get('name')}'")
                return []
            try:
                u = int(rack.get("u")) if rack.get("u") is not None else None
            except (TypeError, ValueError):
                u = None
            cur = dev.get("rack") if isinstance(dev.get("rack"), dict) else {}
            if u is None:
                u = cur.get("u") if cur.get("id") == rid else None
            if u is None:
                problems.append("move_device: rack position needs u (the rack unit)")
                return []
            value["rack"] = {"id": rid, "u": u, "face": str(rack.get("face") or cur.get("face") or "front")}
            if rack.get("side"):
                value["rack"]["side"] = rack["side"]
            bits.append(f"into rack {next((r.get('name') or rid for r in racks if r['id'] == rid), rid)} U{u}")
    if "location" in change:
        loc = change.get("location")
        if loc:
            locs = [x for x in work.get("locations") or [] if isinstance(x, dict) and x.get("id")]
            lid = next((x["id"] for x in locs if x["id"] == loc or str(x.get("name") or "").casefold() == str(loc).casefold()), None)
            if lid is None:
                problems.append(f"move_device: unknown location '{loc}'")
                return []
            value["location"] = lid
            bits.append(f"at {next((x.get('name') or lid for x in locs if x['id'] == lid), lid)}")
        else:
            value["location"] = None
    if not value:
        problems.append("move_device needs a room, rack or location")
        return []
    summary.append(f"Move **{_name(dev)}** " + ", ".join(bits))
    return [{"op": "merge", "coll": "devices", "id": dev["id"], "value": value}]


def _set_field(work: Doc, change: Dict[str, Any], problems: List[str], summary: List[str]) -> List[Op]:
    from . import trace as T

    fld = str(change.get("field") or "").strip()
    val = change.get("value")
    if not fld:
        problems.append("set_field needs a field")
        return []
    if change.get("cable"):
        ref = str(change["cable"])
        c = next((x for x in work.get("cables") or [] if isinstance(x, dict) and (x.get("id") == ref or str(x.get("tag") or "").casefold() == ref.casefold())), None)
        if c is None:
            problems.append(f"set_field: no cable '{ref}'")
            return []
        if fld not in CABLE_FIELDS:
            problems.append(f"set_field: cable field must be one of {', '.join(sorted(CABLE_FIELDS))}")
            return []
        summary.append(f"Set cable {c.get('tag') or c['id']} {fld} = {val!r}")
        return [{"op": "merge", "coll": "cables", "id": str(c["id"]), "value": {fld: val}}]
    if change.get("room") and not change.get("device"):
        rid = _find_room(work, change["room"])
        if rid is None:
            problems.append(f"set_field: unknown room '{change['room']}'")
            return []
        if fld not in ROOM_FIELDS:
            problems.append(f"set_field: room field must be one of {', '.join(sorted(ROOM_FIELDS))}")
            return []
        summary.append(f"Set room {_room_label(work, rid)} {fld} = {val!r}")
        return [{"op": "merge", "coll": "rooms", "id": rid, "value": {fld: val}}]
    dev = _find_device(work, change.get("device") or change.get("id") or change.get("name"), problems, "set_field")
    if dev is None:
        return []
    if change.get("port"):
        pid = _resolve_port(work, dev, change["port"], "in", None, problems)
        if pid is None:
            return []
        if fld not in PORT_FIELDS:
            problems.append(f"set_field: port field must be one of {', '.join(sorted(PORT_FIELDS))}")
            return []
        ports = copy.deepcopy(dev.get("ports") or [])
        for p in ports:
            if isinstance(p, dict) and p.get("id") == pid:
                if val in (None, ""):
                    p.pop(fld, None)
                else:
                    p[fld] = str(val)
        summary.append(f"Set **{_name(dev)} · {T.port_label(T.find_port(dev, pid))}** {fld} = {val!r}")
        return [{"op": "merge", "coll": "devices", "id": dev["id"], "value": {"ports": ports}}]
    if fld in INVENTORY_FIELDS:
        summary.append(f"Set **{_name(dev)}** {fld} = {val!r}")
        return [{"op": "merge", "coll": "devices", "id": dev["id"], "value": {"inventory": {fld: val}}}]
    if fld not in DEVICE_FIELDS:
        problems.append(f"set_field: device field must be one of {', '.join(sorted(DEVICE_FIELDS | INVENTORY_FIELDS))} (or give a port)")
        return []
    if fld == "status" and val not in ("installed", "planned", "spare", "retired"):
        problems.append("set_field: status must be installed, planned, spare or retired")
        return []
    if fld == "aliases" and not isinstance(val, list):
        val = [s.strip() for s in str(val or "").split(",") if s.strip()]
    summary.append(f"Set **{_name(dev)}** {fld} = {val!r}")
    return [{"op": "merge", "coll": "devices", "id": dev["id"], "value": {fld: val}}]


_HANDLERS = {"add_device": _add_device, "remove_device": _remove_device, "connect": _connect, "disconnect": _disconnect,
             "move_device": _move_device, "set_field": _set_field}


# ----------------------------------------------------------------------------- public API

def to_ops(doc: Doc, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``{"ops", "summary", "problems", "applicable"}`` for a list of typed changes.
    Changes are resolved in order against a working copy, so later ones can refer to devices added earlier."""
    from . import schema

    ops: List[Op] = []
    summary: List[str] = []
    problems: List[str] = []
    work = copy.deepcopy(doc)
    if not isinstance(changes, list):
        return {"ops": [], "summary": [], "problems": ["changes must be a list"], "applicable": False}
    for i, ch in enumerate(changes[:MAX_CHANGES]):
        if not isinstance(ch, dict):
            problems.append(f"change {i + 1}: not an object")
            continue
        action = str(ch.get("action") or "").strip()
        fn = _HANDLERS.get(action)
        if fn is None:
            problems.append(f"change {i + 1}: unknown action '{action}' (use {', '.join(ACTIONS)})")
            continue
        try:
            new_ops = fn(work, ch, problems, summary)
        except Exception as e:  # a resolver bug must not break the answer
            problems.append(f"change {i + 1} ({action}) failed ({type(e).__name__})")
            continue
        if not new_ops:
            continue
        try:
            work = schema.apply_ops(work, new_ops)[0]
        except schema.SchemaError as e:
            problems.append(f"change {i + 1} ({action}): {e}")
            continue
        ops.extend(new_ops)
    if len(changes) > MAX_CHANGES:
        problems.append(f"only the first {MAX_CHANGES} changes were considered")
    applicable = bool(ops)
    if ops:
        try:
            def keys(d: Doc) -> List[Tuple[str, str, str]]:
                return [(str(p.get("code") or ""), str(p.get("ref") or ""), str(p.get("path") or ""))
                        for p in schema.errors(schema.validate_doc(schema.normalize(copy.deepcopy(d))))]
            before = set(keys(doc))
            after = schema.errors(schema.validate_doc(schema.normalize(copy.deepcopy(work))))
            errs = [p for p in after if (str(p.get("code") or ""), str(p.get("ref") or ""), str(p.get("path") or "")) not in before]
        except Exception as e:
            errs = [{"message": f"validation failed ({type(e).__name__})"}]
        if errs:  # only errors the proposal itself introduces (the commit path applies the same rule)
            applicable = False
            for p in errs[:10]:
                problems.append(f"validation: {p.get('message') or p}")
    return {"ops": ops, "summary": summary, "problems": problems, "applicable": applicable}


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def new_proposal(doc: Doc, changes: List[Dict[str, Any]], note: str = "", base_revision: Optional[int] = None) -> Dict[str, Any]:
    """Build, cache (15 min, bounded) and return a proposal (§5.10 ``proposal``)."""
    res = to_ops(doc, changes)
    now = time.time()
    prop = {"id": "pp-" + uuid.uuid4().hex[:8], "note": str(note or "")[:200], "summary": res["summary"], "ops": res["ops"],
            "applicable": res["applicable"], "problems": res["problems"], "expires": _iso(now + PROPOSAL_TTL),
            "base_revision": int(base_revision) if isinstance(base_revision, int) else int(doc.get("revision") or 0),
            "changes": [c for c in changes if isinstance(c, dict)][:MAX_CHANGES]}
    remember(prop, now)
    return prop


def remember(prop: Dict[str, Any], now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    with _CACHE_LOCK:
        for k in [k for k, (exp, _) in _CACHE.items() if exp <= now]:
            _CACHE.pop(k, None)
        while len(_CACHE) >= PROPOSAL_CACHE_MAX:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
        _CACHE[str(prop["id"])] = (now + PROPOSAL_TTL, copy.deepcopy(prop))


def get_proposal(pid: str) -> Optional[Dict[str, Any]]:
    """The cached proposal, or ``None`` when unknown / expired."""
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(str(pid or ""))
        if hit is None:
            return None
        exp, prop = hit
        if exp <= now:
            _CACHE.pop(str(pid), None)
            return None
        return copy.deepcopy(prop)


def check_proposal(prop: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """Validate a client-sent proposal body; ``(proposal, "")`` or ``(None, reason)``."""
    from . import schema

    if not isinstance(prop, dict):
        return None, "proposal must be an object"
    ops = prop.get("ops")
    if not isinstance(ops, list) or not ops:
        return None, "proposal has no ops"
    if len(ops) > 2000:
        return None, "too many ops"
    for op in ops:
        try:
            schema._check_op(op)
        except schema.SchemaError as e:
            return None, f"bad op: {e}"
    out = {"id": str(prop.get("id") or ""), "note": str(prop.get("note") or "")[:200], "ops": ops,
           "summary": [str(s) for s in prop.get("summary") or [] if isinstance(s, str)][:50]}
    return out, ""


__all__ = ["ACTIONS", "to_ops", "new_proposal", "get_proposal", "remember", "check_proposal", "PROPOSAL_TTL"]
