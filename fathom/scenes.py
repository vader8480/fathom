"""Scenes (FR-SCN, SPEC §3.29 / §4.3.18): named variants of the *patch*
(``cables``, ``bundles``) and the *gear placement* (device ``room`` /
``location`` / ``rack`` / ``patch`` position, floor-plan markers) of a project.

Everything else in the doc is shared between scenes. Exactly one scene is
active at a time (``settings.scene``; absent or ``""`` = the implicit **Base**).
Switching scenes captures the current state into the scene being left and
applies the target's data, so it is a normal, undoable doc change.

Pure module: functions never mutate their inputs and touch no files.
"""

from __future__ import annotations

import copy
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]
SceneData = Dict[str, Any]

BASE = "base"
BASE_NAME = "Base"
#: the device fields a scene owns (§4.3.18)
PLACEMENT_FIELDS: Tuple[str, ...] = ("room", "location", "rack", "patch")
MAX_NAME = 80


def new_id() -> str:
    return "sc-" + secrets.token_hex(4)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _entities(doc: Doc, coll: str) -> List[Dict[str, Any]]:
    return [e for e in doc.get(coll) or [] if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"]]


def empty_data() -> SceneData:
    return {"cables": [], "bundles": [], "markers": {}, "devices": {}}


# ------------------------------------------------------------------ lookups


def scenes(doc: Doc) -> List[Dict[str, Any]]:
    """The ``scenes[]`` entries that are well-formed (dicts with an id)."""
    return _entities(doc, "scenes")


def base_entry(doc: Doc) -> Optional[Dict[str, Any]]:
    """The entry flagged ``base: true`` (holds Base while another scene is active), or None."""
    for s in scenes(doc):
        if s.get("base") is True:
            return s
    return None


def active_id(doc: Doc) -> str:
    """``settings.scene`` or ``"base"``."""
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    sid = settings.get("scene")
    return str(sid) if isinstance(sid, str) and sid else BASE


def is_base(doc: Doc, sid: str) -> bool:
    if sid == BASE:
        return True
    b = base_entry(doc)
    return b is not None and b.get("id") == sid


def find(doc: Doc, sid: str) -> Optional[Dict[str, Any]]:
    """Scene entry for ``sid`` (``"base"`` → the base entry, which may not exist yet)."""
    if sid == BASE:
        return base_entry(doc)
    for s in scenes(doc):
        if s.get("id") == sid:
            return s
    return None


def _require(doc: Doc, sid: str) -> Dict[str, Any]:
    s = find(doc, sid)
    if s is None:
        raise KeyError(sid)
    return s


def _data_of(entry: Optional[Dict[str, Any]]) -> SceneData:
    d = (entry or {}).get("data")
    out = empty_data()
    if isinstance(d, dict):
        if isinstance(d.get("cables"), list):
            out["cables"] = copy.deepcopy(d["cables"])
        if isinstance(d.get("bundles"), list):
            out["bundles"] = copy.deepcopy(d["bundles"])
        if isinstance(d.get("markers"), dict):
            out["markers"] = copy.deepcopy(d["markers"])
        if isinstance(d.get("devices"), dict):
            out["devices"] = copy.deepcopy(d["devices"])
    return out


def scene_data(doc: Doc, sid: str) -> SceneData:
    """Effective data of a scene: ``capture(doc)`` for the active one (its stored
    copy may be stale while active), the base entry's data for Base, else the
    stored data. ``KeyError`` for an unknown scene."""
    cur = active_id(doc)
    if is_base(doc, sid):
        if cur == BASE:
            return capture(doc)
        b = base_entry(doc)
        return _data_of(b) if b is not None else capture(doc)
    entry = _require(doc, sid)
    if sid == cur:
        return capture(doc)
    return _data_of(entry)


def scene_name(doc: Doc, sid: str) -> str:
    if is_base(doc, sid):
        b = base_entry(doc)
        return str((b or {}).get("name") or BASE_NAME)
    return str(_require(doc, sid).get("name") or sid)


# ------------------------------------------------------------- capture / apply


def capture(doc: Doc) -> SceneData:
    """Deep copies of ``cables``, ``bundles``, every floor plan's ``markers``
    (keyed by floor plan id) and, per device, its placement fields (only the
    keys present; a device without any gets ``{}``)."""
    data = empty_data()
    data["cables"] = copy.deepcopy(_entities(doc, "cables"))
    data["bundles"] = copy.deepcopy(_entities(doc, "bundles"))
    for fp in _entities(doc, "floorplans"):
        markers = fp.get("markers")
        data["markers"][fp["id"]] = copy.deepcopy(markers) if isinstance(markers, list) else []
    for d in _entities(doc, "devices"):
        data["devices"][d["id"]] = {k: copy.deepcopy(d[k]) for k in PLACEMENT_FIELDS if k in d}
    return data


def apply(doc: Doc, data: SceneData) -> Doc:
    """A deep-copied doc with ``cables`` / ``bundles`` replaced, each floor
    plan's ``markers`` replaced when its id is in ``data.markers`` (others keep
    theirs) and the placement fields of every device named in ``data.devices``
    set exactly to the entry (keys absent from the entry are removed; devices
    not named are left alone). Cables and markers pointing at devices that no
    longer exist are dropped so an old scene still applies cleanly."""
    data = _data_of({"data": data})
    out = copy.deepcopy(doc)
    dev_ids = {d["id"] for d in _entities(out, "devices")}

    def known(c: Dict[str, Any]) -> bool:
        for end in ("from", "to"):
            ep = c.get(end)
            if isinstance(ep, dict) and ep.get("device") and ep["device"] not in dev_ids:
                return False
        return True

    out["cables"] = [c for c in data["cables"] if not isinstance(c, dict) or known(c)]
    out["bundles"] = list(data["bundles"])
    for fp in _entities(out, "floorplans"):
        if fp["id"] in data["markers"]:
            lst = data["markers"][fp["id"]]
            fp["markers"] = [m for m in (lst if isinstance(lst, list) else [])
                             if not isinstance(m, dict) or not m.get("device") or m["device"] in dev_ids]
    for d in _entities(out, "devices"):
        entry = data["devices"].get(d["id"])
        if not isinstance(entry, dict):
            continue
        for k in PLACEMENT_FIELDS:
            if k in entry:
                d[k] = copy.deepcopy(entry[k])
            else:
                d.pop(k, None)
    return out


# ------------------------------------------------------------------- diff


def _changed_fields(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    return sorted(k for k in set(a) | set(b) if _canon(a.get(k)) != _canon(b.get(k)))


def _diff_coll(la: List[Any], lb: List[Any]) -> Dict[str, List[Any]]:
    ma = {e["id"]: e for e in la if isinstance(e, dict) and isinstance(e.get("id"), str)}
    mb = {e["id"]: e for e in lb if isinstance(e, dict) and isinstance(e.get("id"), str)}
    added = [copy.deepcopy(mb[i]) for i in mb if i not in ma]
    removed = [copy.deepcopy(ma[i]) for i in ma if i not in mb]
    changed = []
    for i, ea in ma.items():
        eb = mb.get(i)
        if eb is None:
            continue
        fields = _changed_fields(ea, eb)
        if fields:
            changed.append({"id": i, "before": copy.deepcopy(ea), "after": copy.deepcopy(eb), "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def _marker_map(markers: Dict[str, Any]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    out: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for fp, lst in (markers or {}).items():
        if not isinstance(lst, list):
            continue
        seen: Dict[str, int] = {}
        for m in lst:
            if not isinstance(m, dict):
                continue
            dev = str(m.get("device") or "")
            n = seen.get(dev, 0)
            seen[dev] = n + 1
            out[(str(fp), dev, n)] = m
    return out


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def diff(a: SceneData, b: SceneData) -> Dict[str, Any]:
    """What changes going from scene data ``a`` to ``b`` (added = only in ``b``)."""
    a = _data_of({"data": a})
    b = _data_of({"data": b})
    cables = _diff_coll(a["cables"], b["cables"])
    bundles = _diff_coll(a["bundles"], b["bundles"])
    moved = []
    for did in sorted(set(a["devices"]) | set(b["devices"])):
        pa = a["devices"].get(did) if isinstance(a["devices"].get(did), dict) else {}
        pb = b["devices"].get(did) if isinstance(b["devices"].get(did), dict) else {}
        fields = _changed_fields(pa, pb)
        if fields:
            moved.append({"id": did, "before": copy.deepcopy(pa), "after": copy.deepcopy(pb), "fields": fields})
    ma, mb = _marker_map(a["markers"]), _marker_map(b["markers"])
    m_added = [{"fp": k[0], "device": k[1], "after": copy.deepcopy(mb[k])} for k in mb if k not in ma]
    m_removed = [{"fp": k[0], "device": k[1], "before": copy.deepcopy(ma[k])} for k in ma if k not in mb]
    m_moved = [{"fp": k[0], "device": k[1], "before": copy.deepcopy(ma[k]), "after": copy.deepcopy(mb[k]),
                "fields": _changed_fields(ma[k], mb[k])}
               for k in ma if k in mb and _canon(ma[k]) != _canon(mb[k])]
    summary = {
        "cables_added": len(cables["added"]), "cables_removed": len(cables["removed"]), "cables_changed": len(cables["changed"]),
        "bundles_changed": len(bundles["added"]) + len(bundles["removed"]) + len(bundles["changed"]),
        "devices_moved": len(moved), "markers_changed": len(m_added) + len(m_removed) + len(m_moved),
    }
    return {"cables": cables, "bundles": bundles, "devices": {"moved": moved},
            "markers": {"added": m_added, "removed": m_removed, "moved": m_moved},
            "summary": summary, "text": summary_text(summary)}


def summary_text(summary: Dict[str, Any]) -> str:
    """``"+3 cables · −1 cable · 2 devices moved"`` (zero parts omitted; ``"No differences"`` when empty)."""
    parts: List[str] = []
    n = int(summary.get("cables_added") or 0)
    if n:
        parts.append("+" + _plural(n, "cable"))
    n = int(summary.get("cables_removed") or 0)
    if n:
        parts.append("\u2212" + _plural(n, "cable"))
    n = int(summary.get("cables_changed") or 0)
    if n:
        parts.append(_plural(n, "cable") + " changed")
    n = int(summary.get("bundles_changed") or 0)
    if n:
        parts.append(_plural(n, "bundle") + " changed")
    n = int(summary.get("devices_moved") or 0)
    if n:
        parts.append(_plural(n, "device") + " moved")
    n = int(summary.get("markers_changed") or 0)
    if n:
        parts.append(_plural(n, "marker") + " changed")
    return " \u00b7 ".join(parts) if parts else "No differences"


# ---------------------------------------------------------------- summaries


def _view(entry: Optional[Dict[str, Any]], sid: str, active: bool, d: Dict[str, Any]) -> Dict[str, Any]:
    e = entry or {}
    return {
        "id": sid, "name": str(e.get("name") or (BASE_NAME if sid == BASE else sid)), "note": str(e.get("note") or ""),
        "base": sid == BASE, "active": active, "created": str(e.get("created") or ""), "by": str(e.get("by") or ""),
        "updated": str(e.get("updated") or ""), "diff": d["summary"], "text": d["text"],
    }


def summarize(doc: Doc) -> List[Dict[str, Any]]:
    """One entry per scene, Base first (synthesised when no base entry exists).
    Scenes carry their diff against Base; Base carries the diff from the active
    state back to Base (zeros while Base is active). The active scene's data is
    the live doc; everything else is the stored data. Base is always listed
    under the id ``"base"``."""
    cur = active_id(doc)
    cur_data = capture(doc)
    b = base_entry(doc)
    base_data = cur_data if cur == BASE else (_data_of(b) if b is not None else cur_data)
    out = [_view(b, BASE, cur == BASE, diff(cur_data, base_data))]
    for s in scenes(doc):
        if s.get("base") is True:
            continue
        data = cur_data if s["id"] == cur else _data_of(s)
        out.append(_view(s, s["id"], s["id"] == cur, diff(base_data, data)))
    return out


def summary_for(doc: Doc, sid: str) -> Dict[str, Any]:
    """The :func:`summarize` entry of one scene (``KeyError`` when unknown)."""
    if is_base(doc, sid):
        sid = BASE
    for e in summarize(doc):
        if e["id"] == sid:
            return e
    raise KeyError(sid)


# --------------------------------------------------------------- operations


def _settings(doc: Doc) -> Dict[str, Any]:
    s = doc.get("settings")
    if not isinstance(s, dict):
        s = {}
        doc["settings"] = s
    return s


def _scenes_list(doc: Doc) -> List[Any]:
    lst = doc.get("scenes")
    if not isinstance(lst, list):
        lst = []
        doc["scenes"] = lst
    return lst


def activate(doc: Doc, sid: str, by: str = "") -> Tuple[Doc, Dict[str, Any]]:
    """Switch to scene ``sid`` (``"base"`` allowed): capture the current state
    into the scene being left (creating the Base entry on the first switch away
    from Base), apply the target's data, set ``settings.scene`` (``""`` for
    Base) and stamp ``updated`` on both. Returns ``(doc, {"from", "to", "diff"})``;
    a no-op when ``sid`` is already active. ``KeyError`` for an unknown scene."""
    cur = active_id(doc)
    target = BASE if is_base(doc, sid) else sid
    if target == cur:
        d = capture(doc)
        return doc, {"from": cur, "to": cur, "diff": diff(d, d)}
    if target != BASE:
        _require(doc, target)
    elif base_entry(doc) is None:
        raise KeyError(BASE)
    now = _now()
    cur_data = capture(doc)
    new = copy.deepcopy(doc)
    lst = _scenes_list(new)
    if cur == BASE:
        b = base_entry(new)
        if b is None:
            b = {"id": new_id(), "name": BASE_NAME, "base": True, "created": now}
            if by:
                b["by"] = by
            lst.insert(0, b)
        b["data"] = cur_data
        b["updated"] = now
    else:
        left = find(new, cur)
        if left is not None:
            left["data"] = cur_data
            left["updated"] = now
    target_entry = _require(new, target)
    target_data = _data_of(target_entry)
    new = apply(new, target_data)
    target_entry = _require(new, target)
    target_entry["updated"] = now
    _settings(new)["scene"] = "" if target == BASE else target
    return new, {"from": cur, "to": target, "diff": diff(cur_data, target_data)}


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("a scene needs a name")
    name = name.strip()
    if len(name) > MAX_NAME:
        raise ValueError(f"scene name is longer than {MAX_NAME} characters")
    return name


def create(doc: Doc, name: str, note: str = "", by: str = "", copy_from: Optional[str] = None) -> Tuple[Doc, Dict[str, Any]]:
    """Add a scene holding ``capture(doc)`` (or a copy of scene ``copy_from``'s
    data; the active scene always means the live state). Does not activate.
    ``ValueError`` for a bad name, ``KeyError`` for an unknown ``copy_from``."""
    name = _check_name(name)
    if copy_from:
        data = scene_data(doc, copy_from)
    else:
        data = capture(doc)
    now = _now()
    taken = {s["id"] for s in scenes(doc)}
    sid = new_id()
    while sid in taken:
        sid = new_id()
    scene: Dict[str, Any] = {"id": sid, "name": name, "created": now, "updated": now, "data": data}
    if note:
        scene["note"] = str(note)
    if by:
        scene["by"] = by
    new = copy.deepcopy(doc)
    _scenes_list(new).append(scene)
    return new, copy.deepcopy(scene)


def save_current(doc: Doc, sid: str) -> Doc:
    """Overwrite scene ``sid``'s data with the live state (``KeyError`` when unknown)."""
    _require(doc, sid)
    new = copy.deepcopy(doc)
    entry = _require(new, sid)
    entry["data"] = capture(doc)
    entry["updated"] = _now()
    return new


def delete(doc: Doc, sid: str) -> Doc:
    """Remove a scene; the active scene is left for Base first. ``ValueError`` for Base."""
    if is_base(doc, sid):
        raise ValueError("the Base scene cannot be deleted")
    _require(doc, sid)
    new = doc
    if active_id(doc) == sid:
        if base_entry(doc) is not None:
            new, _ = activate(doc, BASE)
        else:  # hand-edited doc without a Base entry: nothing to restore, just drop the pointer
            new = copy.deepcopy(doc)
            _settings(new)["scene"] = ""
    new = copy.deepcopy(new)
    new["scenes"] = [s for s in new.get("scenes") or [] if not (isinstance(s, dict) and s.get("id") == sid)]
    return new


def rename(doc: Doc, sid: str, name: Optional[str] = None, note: Optional[str] = None) -> Doc:
    """Change name and/or note (``None`` keeps). ``KeyError`` when unknown; ``ValueError`` for a bad name."""
    _require(doc, sid)
    new = copy.deepcopy(doc)
    entry = _require(new, sid)
    if name is not None:
        entry["name"] = _check_name(name)
    if note is not None:
        if str(note):
            entry["note"] = str(note)
        else:
            entry.pop("note", None)
    entry["updated"] = _now()
    return new
