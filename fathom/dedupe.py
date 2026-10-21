"""Device de-duplication: duplicate suggestions and merge plans.

Not to be confused with :mod:`fathom.merge`, which folds *imports* into the
project overlay. This module answers two questions about devices that are
already in a project (or sit in its overlay):

* :func:`find_duplicates` – which devices probably describe the same box?
  Each suggestion carries a score, a confidence band and the reasons.
* :func:`merge_plan` – given a surviving device and its duplicates, which
  value wins per field, how are cables / markers / attachments re-pointed,
  and which change ops (§4.9) perform the merge as one revision?

A plan is pure data: computing it never writes. Applying ``plan["ops"]``
through :func:`fathom.project.apply_changes` records a single revision, so
the merge is transactional and can be undone with a history restore (or the
client's undo stack, which inverts the same ops).
"""
from __future__ import annotations

import copy
import difflib
import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .model import norm_name
from .schema import _clean, _letter_dedupe

Doc = Dict[str, Any]
Op = Dict[str, Any]


class MergeError(ValueError):
    def __init__(self, message: str, code: str = "bad_merge", details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


# ------------------------------------------------------------------ fields

# (key, label, rule). Rules: scalar (first non-empty wins), bool (any true),
# list (union), text (concatenate), object (first non-empty object wins),
# routing (mode from the winner, map unioned).
FIELDS: List[Tuple[str, str, str]] = [
    ("name", "Name", "scalar"),
    ("kind", "Kind", "scalar"),
    ("discipline", "Discipline", "scalar"),
    ("room", "Room", "scalar"),
    ("system", "System", "scalar"),
    ("location", "Location", "scalar"),
    ("template", "Template", "scalar"),
    ("manufacturer", "Manufacturer", "scalar"),
    ("model", "Model", "scalar"),
    ("code", "Code", "scalar"),
    ("sub", "Subtitle", "scalar"),
    ("brand", "Brand", "scalar"),
    ("count", "Count", "scalar"),
    ("suffix", "Suffix", "scalar"),
    ("icon", "Icon", "scalar"),
    ("dante_name", "Dante name", "scalar"),
    ("dante", "Dante", "bool"),
    ("status", "Status", "scalar"),
    ("aliases", "Aliases", "list"),
    ("tags", "Tags", "list"),
    ("lines", "Lines", "list"),
    ("note", "Note", "text"),
    ("inventory.serial", "Serial", "scalar"),
    ("inventory.asset_tag", "Asset tag", "scalar"),
    ("inventory.firmware", "Firmware", "scalar"),
    ("inventory.purchase_date", "Purchase date", "scalar"),
    ("inventory.warranty_until", "Warranty until", "scalar"),
    ("inventory.vendor", "Vendor", "scalar"),
    ("inventory.cost", "Cost", "scalar"),
    ("inventory.currency", "Currency", "scalar"),
    ("inventory.po", "PO", "scalar"),
    ("inventory.notes", "Inventory notes", "text"),
    ("dmx", "DMX", "object"),
    ("rack", "Rack position", "object"),
    ("flow", "Flow layout", "object"),
    ("patch", "Patch layout", "object"),
    ("routing", "Routing", "routing"),
]
_FIELD_KEYS = {k for k, _, _ in FIELDS}
# top-level keys handled elsewhere (never copied generically)
_SPECIAL = {"id", "auto", "source", "merged_from", "ports", "interfaces", "inventory"}


def _get(dev: Dict[str, Any], key: str) -> Any:
    cur: Any = dev
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set(dev: Dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    cur = dev
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    if _empty(value):
        cur.pop(parts[-1], None)
    else:
        cur[parts[-1]] = value


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return _canon(a) == _canon(b)


def _as_list(v: Any) -> List[Any]:
    if isinstance(v, list):
        return list(v)
    if _empty(v):
        return []
    return [v]


def _union(lists: List[List[Any]], loose: bool = False) -> List[Any]:
    out: List[Any] = []
    seen: Set[str] = set()
    for lst in lists:
        for item in lst:
            key = norm_name(str(item)) if loose and isinstance(item, str) else _canon(item)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _label(dev: Dict[str, Any]) -> str:
    return str(dev.get("name") or dev.get("id") or "?")


# ------------------------------------------------------------- candidates


def _overlay_devices(doc: Doc, overlay: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Overlay (auto) devices as self-contained dicts, enriched the same way
    the *promote* action would persist them."""
    if not overlay:
        return []
    from .merge import promote_ops

    persisted = {d.get("id") for d in doc.get("devices") or [] if isinstance(d, dict)}
    ids = [d.get("id") for d in overlay.get("devices") or [] if isinstance(d, dict) and d.get("id") and d.get("id") not in persisted]
    out: List[Dict[str, Any]] = []
    src = {d["id"]: d.get("source") for d in overlay.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    for op in promote_ops(doc, overlay, ids):
        dev = op["value"]
        dev["auto"] = True
        if src.get(dev["id"]):
            dev["source"] = src[dev["id"]]
        out.append(dev)
    return out


def device_pool(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Persisted devices followed by overlay-only devices (``auto: true``)."""
    pool = [copy.deepcopy(d) for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") and not d.get("auto")]
    pool.extend(_overlay_devices(doc, overlay))
    return pool


# ----------------------------------------------------------------- scoring

HIGH, MEDIUM = 0.85, 0.65


def _keys(dev: Dict[str, Any]) -> Dict[str, Set[str]]:
    inv = dev.get("inventory") if isinstance(dev.get("inventory"), dict) else {}
    ifs = [i for i in dev.get("interfaces") or [] if isinstance(i, dict)]
    rack = dev.get("rack") if isinstance(dev.get("rack"), dict) else {}
    names = {norm_name(str(dev.get("name") or "")), norm_name(str(dev.get("id") or ""))}
    aliases = {norm_name(str(a)) for a in dev.get("aliases") or [] if a}
    return {
        "name": {n for n in names if n},
        "aliases": {a for a in aliases if a},
        "dante_name": {norm_name(str(dev.get("dante_name") or ""))} - {""},
        "serial": {str(inv.get("serial") or "").strip().lower()} - {""},
        "asset_tag": {str(inv.get("asset_tag") or "").strip().lower()} - {""},
        "ip": {str(i.get("ip") or "").strip() for i in ifs} - {""},
        "mac": {str(i.get("mac") or "").replace("-", ":").strip().lower() for i in ifs} - {""},
        "hostname": {str(i.get("hostname") or "").strip().lower() for i in ifs} - {""},
        "rack": {str(rack.get("id") or "")} - {""},
        "rack_u": {f"{rack.get('id')}@{rack.get('u')}"} if rack.get("id") and rack.get("u") is not None else set(),
        "model": {norm_name(str(dev.get("model") or ""))} - {""},
        "manufacturer": {norm_name(str(dev.get("manufacturer") or ""))} - {""},
        "kind": {str(dev.get("kind") or "")} - {""},
        "room": {str(dev.get("room") or "")} - {""},
        "text": {norm_name(" ".join(str(dev.get(k) or "") for k in ("name", "sub", "dante_name", "model", "note")))},
    }


def _name_similarity(a: str, b: str) -> float:
    """0..1; token-aware so ``Lectern mic`` / ``Choir mic`` stay apart while
    ``FOH CL5`` / ``FOH CL5 console`` come out close."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    if sa == sb:
        return 1.0
    small = sa if len(sa) <= len(sb) else sb
    if (sa <= sb or sb <= sa) and (len(small) >= 2 or any(c.isdigit() for c in next(iter(small)))):
        return 0.85 + 0.15 * len(small) / max(len(sa), len(sb))
    chars = difflib.SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    jaccard = len(sa & sb) / len(sa | sb)
    return 0.5 * chars + 0.5 * jaccard


_SERIES = {"l", "r", "left", "right", "a", "b", "c", "d", "main", "backup", "pri", "sec", "primary", "secondary",
           "top", "bottom", "front", "rear", "upper", "lower", "odd", "even", "in", "out", "tx", "rx"}


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _series_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z]+|\d+", (text or "").lower())


def _siblings(a: str, b: str) -> bool:
    """``Lustr 1`` / ``Lustr 2`` or ``Mon L`` / ``Mon R``: a numbered series,
    not the same unit."""
    ta, tb = _series_tokens(a), _series_tokens(b)
    if ta == tb or len(ta) != len(tb) or len(ta) < 2:
        return False
    diff = [(x, y) for x, y in zip(ta, tb) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    series = lambda t: t.isdigit() or t in _SERIES  # noqa: E731
    return series(x) and series(y)


def _model_tokens(dev: Dict[str, Any]) -> Set[str]:
    """Alphanumeric tokens like ``cl5`` or ``rio3224d`` that usually name a model."""
    out: Set[str] = set()
    for k in ("name", "sub", "dante_name", "aliases"):
        v = dev.get(k)
        for text in (v if isinstance(v, list) else [v]):
            for t in _tokens(str(text or "")):
                if len(t) >= 3 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
                    out.add(t)
    return out


def score_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
    """Probability-ish score that ``a`` and ``b`` are the same physical
    device, plus the reasons (positive signals and penalties)."""
    ka, kb = _keys(a), _keys(b)
    reasons: List[Dict[str, Any]] = []

    def hit(signal: str, weight: float, text: str) -> None:
        reasons.append({"signal": signal, "weight": round(weight, 2), "text": text})

    def shared(key: str) -> Set[str]:
        return ka[key] & kb[key]

    if shared("serial"):
        hit("serial", 0.97, f"same serial number {next(iter(shared('serial')))}")
    if shared("mac"):
        hit("mac", 0.97, f"same MAC address {next(iter(shared('mac')))}")
    if shared("asset_tag"):
        hit("asset_tag", 0.9, f"same asset tag {next(iter(shared('asset_tag')))}")
    if shared("ip"):
        hit("ip", 0.9, f"same IP address {next(iter(shared('ip')))}")
    if shared("hostname"):
        hit("hostname", 0.85, f"same hostname {next(iter(shared('hostname')))}")
    all_a = ka["name"] | ka["aliases"] | ka["dante_name"]
    all_b = kb["name"] | kb["aliases"] | kb["dante_name"]
    if ka["dante_name"] & all_b or kb["dante_name"] & all_a:
        dn = (a.get("dante_name") or b.get("dante_name") or "")
        hit("dante_name", 0.95, f"Dante name {dn} matches the other device's name")
    elif (ka["aliases"] & all_b) or (kb["aliases"] & all_a):
        hit("alias", 0.85, "one device lists the other's name as an alias")
    elif ka["name"] & kb["name"]:
        hit("name", 0.8, "same name")
    else:
        best = _name_similarity(str(a.get("name") or a.get("id") or ""), str(b.get("name") or b.get("id") or ""))
        if best >= 0.8:
            hit("name_similar", 0.25 + (best - 0.8) * 1.5, f"names are {int(best * 100)}% similar")
        shared_models = _model_tokens(a) & _model_tokens(b)
        if shared_models:
            hit("name_token", 0.4, f"both names mention {', '.join(sorted(shared_models))}")
    if shared("model") and shared("manufacturer"):
        hit("model", 0.3, f"same manufacturer and model ({b.get('manufacturer')} {b.get('model')})")
    elif shared("model"):
        hit("model", 0.2, f"same model ({b.get('model')})")
    else:
        for x, kx, ky in ((a, ka, kb), (b, kb, ka)):
            model = next(iter(kx["model"]), "")
            text = next(iter(ky["text"]), "")
            if len(model) >= 3 and model in text:
                man = next(iter(kx["manufacturer"]), "")
                hit("model_in_name", 0.45 if man and man in text else 0.3, f"model {x.get('model')} appears in the other device's name or notes")
                break
    if shared("rack_u"):
        hit("rack", 0.6, "same rack and U position")
    elif shared("rack"):
        hit("rack", 0.15, "same rack")
    if not reasons:
        return 0.0, []
    score = 1.0
    for r in reasons:
        score *= 1.0 - r["weight"]
    score = 1.0 - score
    if shared("room"):
        score = min(1.0, score + 0.05)
        hit("room", 0.05, "same room")
    if shared("kind"):
        score = min(1.0, score + 0.05)
        hit("kind", 0.05, f"same kind ({next(iter(shared('kind')))})")
    # penalties
    strong = {"serial", "mac", "asset_tag", "ip", "hostname", "dante_name", "alias"}
    if not any(r["signal"] in strong for r in reasons) and _siblings(str(a.get("name") or ""), str(b.get("name") or "")):
        score *= 0.25
        hit("series", -0.75, "names look like a numbered series (1/2, L/R), not the same unit")
    if ka["kind"] and kb["kind"] and not shared("kind") and "other" not in (ka["kind"] | kb["kind"]):
        score *= 0.5
        hit("kind_differs", -0.5, f"different kinds ({a.get('kind')} vs {b.get('kind')})")
    ma, mb = next(iter(ka["model"]), ""), next(iter(kb["model"]), "")
    if ma and mb and ma != mb and ma not in mb and mb not in ma:
        score *= 0.3
        hit("model_differs", -0.7, f"different models ({a.get('model')} vs {b.get('model')})")
    if ka["serial"] and kb["serial"] and not shared("serial"):
        score *= 0.2
        hit("serial_differs", -0.8, "different serial numbers")
    if ka["room"] and kb["room"] and not shared("room"):
        score *= 0.85
        hit("room_differs", -0.15, "different rooms")
    return round(min(1.0, max(0.0, score)), 3), reasons


def _confidence(score: float) -> str:
    return "high" if score >= HIGH else ("medium" if score >= MEDIUM else "low")


def _richness(dev: Dict[str, Any]) -> int:
    n = 0
    for k, v in dev.items():
        if k in ("id", "auto", "source") or _empty(v):
            continue
        n += len(v) if isinstance(v, (list, dict)) else 1
    return n


def find_duplicates(doc: Doc, overlay: Optional[Dict[str, Any]] = None, device_id: str = "", min_score: float = 0.5) -> List[Dict[str, Any]]:
    """Likely duplicate pairs, best first. ``device_id`` limits the search to
    pairs involving that device. Overlay devices are never paired with each
    other (that is the importer's job) and are never suggested as survivor."""
    pool = device_pool(doc, overlay)
    if device_id:
        if not any(d["id"] == device_id for d in pool):
            raise MergeError(f"device '{device_id}' not found", "not_found")
    out: List[Dict[str, Any]] = []
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if device_id and device_id not in (a["id"], b["id"]):
                continue
            if a.get("auto") and b.get("auto"):
                continue
            score, reasons = score_pair(a, b)
            if score < min_score:
                continue
            if b.get("auto"):
                survivor = a["id"]
            elif a.get("auto"):
                survivor = b["id"]
            else:
                survivor = a["id"] if _richness(a) >= _richness(b) else b["id"]
            pair = [a, b] if survivor == a["id"] else [b, a]
            out.append({
                "devices": [{"id": d["id"], "name": _label(d), "auto": bool(d.get("auto")), "source": d.get("source") or "",
                             "kind": d.get("kind") or "", "room": d.get("room") or "", "model": d.get("model") or ""} for d in pair],
                "score": score,
                "confidence": _confidence(score),
                "reasons": reasons,
                "suggested_survivor": survivor,
            })
    out.sort(key=lambda s: (-s["score"], s["devices"][0]["id"], s["devices"][1]["id"]))
    return out


# ------------------------------------------------------------- merge plan


def _combine_field(key: str, rule: str, devs: List[Dict[str, Any]], choice: Optional[str]) -> Dict[str, Any]:
    order = [d["id"] for d in devs]
    values = {d["id"]: copy.deepcopy(_get(d, key)) for d in devs}
    present = [i for i in order if not _empty(values[i])]
    distinct = len({_canon(values[i]) for i in present}) > 1
    row: Dict[str, Any] = {"key": key, "rule": rule, "values": values, "conflict": distinct, "overridable": len(present) > 1}
    if choice and choice in order and (not _empty(values[choice]) or rule in ("list", "text")):
        row["winner"] = choice
        row["result"] = values[choice]
        row["reason"] = "chosen by you"
        if rule == "routing" and isinstance(row["result"], dict):
            row["result"] = copy.deepcopy(row["result"])
        return row
    if rule in ("scalar", "object"):
        win = present[0] if present else ""
        row["winner"] = win
        row["result"] = values.get(win)
        if not present:
            row["reason"] = "empty everywhere"
        elif win == order[0]:
            row["reason"] = "kept from the survivor" + (" (duplicate differs)" if distinct else "")
        else:
            row["reason"] = "survivor was blank; filled from duplicate"
    elif rule == "bool":
        row["winner"] = next((i for i in order if values[i] is True), present[0] if present else "")
        row["result"] = any(values[i] is True for i in order) or None
        row["reason"] = "on if any device has it on"
        row["conflict"] = False
    elif rule == "list":
        row["winner"] = "union"
        row["result"] = _union([_as_list(values[i]) for i in order], loose=(key == "aliases"))
        row["reason"] = "union of all devices"
        row["conflict"] = False
    elif rule == "text":
        parts: List[str] = []
        for i in order:
            v = str(values[i] or "").strip()
            if v and not any(v in p for p in parts):
                parts.append(v)
        row["winner"] = "union" if len(parts) > 1 else (present[0] if present else "")
        row["result"] = "\n\n".join(parts) or None
        row["reason"] = "texts concatenated" if len(parts) > 1 else ("kept as is" if parts else "empty everywhere")
        row["conflict"] = False
    elif rule == "routing":
        win = present[0] if present else ""
        res = copy.deepcopy(values.get(win)) if win else None
        if isinstance(res, dict):
            maps = [_as_list((values[i] or {}).get("map")) for i in order if isinstance(values[i], dict)]
            m = _union(maps)
            if m:
                res["map"] = m
        row["winner"] = win
        row["result"] = res
        row["reason"] = "mode from the survivor, routing map unioned" if present else "empty everywhere"
    return row


def _merge_ports(devs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], str], Dict[str, Any]]:
    """Union of ports by id. Returns (ports, remap[(device, old_port)] -> new_port, report)."""
    survivor = devs[0]
    ports: List[Dict[str, Any]] = []
    for p in survivor.get("ports") or []:
        if isinstance(p, dict) and p.get("id"):
            q = copy.deepcopy(p)
            q.pop("auto", None)
            ports.append(q)
    by_id = {p["id"]: p for p in ports}
    remap: Dict[Tuple[str, str], str] = {}
    report: Dict[str, Any] = {"kept": len(ports), "added": [], "unified": [], "renamed": []}
    for d in devs[1:]:
        for p in d.get("ports") or []:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            q = copy.deepcopy(p)
            q.pop("auto", None)
            pid = str(q["id"])
            cur = by_id.get(pid)
            if cur is None:
                by_id[pid] = q
                ports.append(q)
                report["added"].append({"device": d["id"], "port": pid})
                continue
            compatible = (not cur.get("dir") or not q.get("dir") or cur["dir"] == q["dir"]) and \
                         (not cur.get("medium") or not q.get("medium") or cur["medium"] == q["medium"])
            if compatible:
                for k, v in q.items():
                    if k != "id" and _empty(cur.get(k)) and not _empty(v):
                        cur[k] = v
                report["unified"].append({"device": d["id"], "port": pid})
                continue
            new_id = _letter_dedupe(pid, set(by_id))
            q["id"] = new_id
            by_id[new_id] = q
            ports.append(q)
            remap[(d["id"], pid)] = new_id
            report["renamed"].append({"device": d["id"], "port": pid, "to": new_id,
                                      "reason": f"{cur.get('dir')}/{cur.get('medium')} vs {q.get('dir')}/{q.get('medium')}"})
    return ports, remap, report


def _merge_interfaces(devs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {"kept": 0, "added": [], "unified": []}

    def keyset(i: Dict[str, Any]) -> Set[str]:
        ks = set()
        if i.get("ip"):
            ks.add("ip:" + str(i["ip"]).strip())
        if i.get("mac"):
            ks.add("mac:" + str(i["mac"]).replace("-", ":").strip().lower())
        return ks

    for n, d in enumerate(devs):
        for itf in d.get("interfaces") or []:
            if not isinstance(itf, dict):
                continue
            q = {k: copy.deepcopy(v) for k, v in itf.items() if k not in ("source", "auto")}
            if n == 0:
                out.append(q)
                report["kept"] += 1
                continue
            match = None
            for cur in out:
                if (q.get("id") and cur.get("id") == q.get("id")) or (keyset(cur) & keyset(q)):
                    match = cur
                    break
            if match is not None:
                for k, v in q.items():
                    if k != "id" and _empty(match.get(k)) and not _empty(v):
                        match[k] = v
                report["unified"].append({"device": d["id"], "interface": q.get("id") or q.get("ip") or ""})
                continue
            taken = {str(c.get("id")) for c in out if c.get("id")}
            if q.get("id") and str(q["id"]) in taken:
                q["id"] = _letter_dedupe(str(q["id"]), taken)
            out.append(q)
            report["added"].append({"device": d["id"], "interface": q.get("id") or q.get("ip") or ""})
    return out, report


def _port_label(dev: Dict[str, Any], pid: str) -> str:
    for p in dev.get("ports") or []:
        if isinstance(p, dict) and p.get("id") == pid:
            return str(p.get("name") or pid)
    return pid


def merge_plan(doc: Doc, survivor_id: str, duplicate_ids: List[str], choices: Optional[Dict[str, str]] = None,
               overlay: Optional[Dict[str, Any]] = None, author: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """Side-by-side plan plus the ops that merge ``duplicate_ids`` into
    ``survivor_id``. ``choices`` maps a field key to the id of the device
    whose value should win (or ``"union"`` for list / text fields)."""
    choices = dict(choices or {})
    pool = {d["id"]: d for d in device_pool(doc, overlay)}
    if survivor_id not in pool:
        raise MergeError(f"device '{survivor_id}' not found", "not_found")
    if pool[survivor_id].get("auto"):
        raise MergeError(f"'{_label(pool[survivor_id])}' comes from an import; promote it or pick the other device as survivor", "auto_survivor")
    dups: List[str] = []
    for did in duplicate_ids or []:
        did = str(did)
        if did == survivor_id:
            raise MergeError("a device cannot be merged into itself", "self_merge")
        if did not in pool:
            raise MergeError(f"device '{did}' not found", "not_found")
        if did not in dups:
            dups.append(did)
    if not dups:
        raise MergeError("pick at least one duplicate", "no_duplicates")
    devs = [pool[survivor_id]] + [pool[d] for d in dups]
    dup_set = set(dups)
    persisted_dups = [d for d in dups if not pool[d].get("auto")]
    warnings: List[str] = []

    # ---- fields
    merged: Dict[str, Any] = {k: copy.deepcopy(v) for k, v in devs[0].items() if k not in ("auto", "source")}
    rows: List[Dict[str, Any]] = []
    taken_from: Dict[str, List[str]] = {d: [] for d in dups}
    for key, label, rule in FIELDS:
        row = _combine_field(key, rule, devs, choices.get(key))
        row["label"] = label
        if key == "aliases":
            # names the merged device no longer carries become aliases, so
            # importers that matched a duplicate keep matching the survivor
            keep = {norm_name(str(merged.get(k) or "")) for k in ("name", "dante_name", "id")}
            extra = [str(c) for n, d in enumerate(devs) for c in (d.get("name"), d.get("dante_name"), d.get("id") if n else None)
                     if c and norm_name(str(c)) not in keep]
            if extra:
                row["result"] = _union([_as_list(row["result"]), extra], loose=True)
                row["reason"] = "union; duplicate names kept so imports still match"
        rows.append(row)
        _set(merged, key, copy.deepcopy(row["result"]))
        win = row.get("winner")
        if win in dup_set:
            taken_from[win].append(key)
        elif win == "union":
            for d in dups:
                if not _empty(row["values"].get(d)):
                    taken_from[d].append(key)
    rows = [r for r in rows if any(not _empty(v) for v in r["values"].values())]
    # extra (unknown) top-level keys: survivor wins, blanks filled
    for d in devs[1:]:
        for k, v in d.items():
            if k in _SPECIAL or k in _FIELD_KEYS or _empty(v) or "." in k:
                continue
            if _empty(merged.get(k)):
                merged[k] = copy.deepcopy(v)
                taken_from[d["id"]].append(k)

    # ---- ports and interfaces
    ports, remap, port_report = _merge_ports(devs)
    merged["ports"] = ports
    interfaces, itf_report = _merge_interfaces(devs)
    for itf in interfaces:
        if itf.get("switch") in dup_set:
            itf["switch"] = survivor_id
        if itf.get("switch") == survivor_id:
            itf.pop("switch", None)
            itf.pop("switch_port", None)
            warnings.append(f"an interface of '{_label(devs[0])}' pointed at a merged duplicate as its switch; the link was dropped")
    if interfaces:
        merged["interfaces"] = interfaces
    else:
        merged.pop("interfaces", None)
    for d in dups:
        if any(x["device"] == d for x in port_report["added"] + port_report["unified"] + port_report["renamed"]):
            taken_from[d].append("ports")
        if any(x["device"] == d for x in itf_report["added"] + itf_report["unified"]):
            taken_from[d].append("interfaces")

    # ---- provenance
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))
    prov: List[Dict[str, Any]] = [p for p in merged.get("merged_from") or [] if isinstance(p, dict)]
    for d in devs[1:]:
        for p in d.get("merged_from") or []:
            if isinstance(p, dict):
                prov.append(copy.deepcopy(p))
        entry = {"id": d["id"], "name": _label(d), "source": d.get("source") or "project", "at": stamp,
                 "fields": sorted(set(taken_from[d["id"]]))}
        if author:
            entry["by"] = author
        prov.append(entry)
    merged["merged_from"] = prov
    merged["id"] = survivor_id
    merged = _clean(merged, keep=("ports",))
    merged.setdefault("ports", [])

    # ---- references
    refs: Dict[str, Any] = {"cables": [], "self_loops": [], "markers": [], "markers_dropped": [], "attachments": [],
                            "imports": [], "extra_cards": [], "switch_links": []}
    ops: List[Op] = [{"op": "put", "coll": "devices", "id": survivor_id, "value": merged}]
    if persisted_dups:
        pset = set(persisted_dups)
        for c in doc.get("cables") or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            patch: Dict[str, Any] = {}
            for end in ("from", "to"):
                ep = c.get(end)
                if isinstance(ep, dict) and ep.get("device") in pset:
                    e: Dict[str, Any] = {"device": survivor_id}
                    old_port = str(ep.get("port") or "")
                    if old_port:
                        new_port = remap.get((str(ep["device"]), old_port), old_port)
                        if new_port != old_port:
                            e["port"] = new_port
                    patch[end] = e
            fl = c.get("flow")
            if isinstance(fl, dict):
                fpatch = {k: survivor_id for k in ("from_card", "to_card") if fl.get(k) in pset}
                if fpatch:
                    patch["flow"] = fpatch
            if not patch:
                continue
            ops.append({"op": "merge", "coll": "cables", "id": c["id"], "value": patch})
            refs["cables"].append(c["id"])
            ends = []
            for end in ("from", "to"):
                ep = c.get(end) if isinstance(c.get(end), dict) else {}
                dev = survivor_id if ep.get("device") in pset else ep.get("device")
                ends.append(dev)
            if ends[0] == survivor_id and ends[1] == survivor_id:
                refs["self_loops"].append(c["id"])
        if refs["self_loops"]:
            warnings.append(f"{len(refs['self_loops'])} cable(s) now start and end on '{_label(devs[0])}' (they linked the duplicates): " + ", ".join(refs["self_loops"][:5]))
        for r in doc.get("rooms") or []:
            if not isinstance(r, dict) or not isinstance(r.get("flow"), dict):
                continue
            cards = r["flow"].get("extra_cards")
            if not isinstance(cards, list) or not any(isinstance(x, dict) and x.get("device") in pset for x in cards):
                continue
            new_cards = []
            for x in cards:
                y = copy.deepcopy(x)
                if isinstance(y, dict) and y.get("device") in pset:
                    y["device"] = survivor_id
                    refs["extra_cards"].append(f"{r['id']}/{y.get('id')}")
                new_cards.append(y)
            ops.append({"op": "merge", "coll": "rooms", "id": r["id"], "value": {"flow": {"extra_cards": new_cards}}})
        for f in doc.get("floorplans") or []:
            if not isinstance(f, dict) or not isinstance(f.get("markers"), list):
                continue
            markers = f["markers"]
            if not any(isinstance(m, dict) and m.get("device") in pset for m in markers):
                continue
            has_survivor = any(isinstance(m, dict) and m.get("device") == survivor_id for m in markers)
            new_markers = []
            for m in markers:
                if isinstance(m, dict) and m.get("device") in pset:
                    if has_survivor:
                        refs["markers_dropped"].append(f"{f['id']}:{m['device']}")
                        continue
                    m = dict(m, device=survivor_id)
                    has_survivor = True
                    refs["markers"].append(f["id"])
                new_markers.append(m)
            ops.append({"op": "merge", "coll": "floorplans", "id": f["id"], "value": {"markers": new_markers}})
        if refs["markers_dropped"]:
            warnings.append(f"{len(refs['markers_dropped'])} floor-plan marker(s) of the duplicates were dropped because '{_label(devs[0])}' already has one on that plan")
        for coll, bucket in (("attachments", "attachments"), ("imports", "imports")):
            for a in doc.get(coll) or []:
                if isinstance(a, dict) and a.get("id") and a.get("device") in pset:
                    ops.append({"op": "merge", "coll": coll, "id": a["id"], "value": {"device": survivor_id}})
                    refs[bucket].append(a["id"])
        for d in doc.get("devices") or []:
            if not isinstance(d, dict) or d.get("id") in pset or d.get("id") == survivor_id or d.get("auto"):
                continue
            ifs = d.get("interfaces")
            if not isinstance(ifs, list) or not any(isinstance(i, dict) and i.get("switch") in pset for i in ifs):
                continue
            new_ifs = [dict(i, switch=survivor_id) if isinstance(i, dict) and i.get("switch") in pset else copy.deepcopy(i) for i in ifs]
            ops.append({"op": "merge", "coll": "devices", "id": d["id"], "value": {"interfaces": new_ifs}})
            refs["switch_links"].append(d["id"])
        for d in persisted_dups:
            ops.append({"op": "del", "coll": "devices", "id": d})
    for d in dups:
        if pool[d].get("auto"):
            warnings.append(f"'{_label(pool[d])}' comes from the {pool[d].get('source') or 'import'} import and is not deleted; "
                            f"its name is kept as an alias so the import attaches to '{_label(devs[0])}' from now on")
    rack_row = next((r for r in rows if r["key"] == "rack"), None)
    if rack_row and rack_row["conflict"]:
        warnings.append("the devices sit in different rack positions; only the winning position is kept")

    names = [_label(pool[d]) for d in dups]
    if len(names) == 1:
        summary = f"Merged '{names[0]}' into '{_label(devs[0])}'"
    else:
        summary = f"Merged {len(names)} devices into '{_label(devs[0])}'"
    return {
        "survivor": survivor_id,
        "duplicates": dups,
        "devices": [{"id": d["id"], "name": _label(d), "auto": bool(d.get("auto")), "source": d.get("source") or "",
                     "kind": d.get("kind") or "", "room": d.get("room") or ""} for d in devs],
        "fields": rows,
        "ports": port_report,
        "interfaces": itf_report,
        "references": refs,
        "warnings": warnings,
        "result": merged,
        "ops": ops,
        "summary": summary,
    }
