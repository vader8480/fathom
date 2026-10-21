"""Equipment library: built-in templates, extension dirs, global custom, per project.

Precedence (later wins): built-in (``fathom/library/templates``) < extension
dirs (``FATHOM_LIBRARY`` + plugin-registered) < global custom
(``<data>/library/*.json``) < project (``doc["templates"]``). Template format:
§4.5 of docs/SPEC.md; port groups expand with the shared §4.4.3 algorithm.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]
Op = Dict[str, Any]

BUILTIN_DIR = Path(__file__).resolve().parent / "templates"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
UNVERIFIED_NOTE = "Port counts not verified against the datasheet; please check."

_TEMPLATE_KEYS = (
    "id", "manufacturer", "model", "name", "kind", "discipline", "brand", "ru", "width", "depth_mm", "power_w",
    "weight_kg", "cost", "currency", "dante", "routing", "dmx_footprint", "ports", "dante_channels", "checks",
    "tags", "source_url", "notes",
)

_cache: Dict[str, Any] = {"sig": None, "lib": {}}


# ------------------------------------------------------------ expansion

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s or "item"


_V1_DIRS = {"in": "in", "out": "out", "bi": "io", "io": "io"}


def _local_expand(groups: List[Dict[str, Any]], v1: bool = False) -> List[Dict[str, Any]]:
    """§4.4.3 port-group expansion (used when ``fathom.schema`` is unavailable)."""
    from ..vocab import NETWORK_MEDIA

    out: List[Dict[str, Any]] = []
    seen: set = set()

    def emit(port: Dict[str, Any]) -> None:
        pid, base, k = port["id"], port["id"], 0
        while pid in seen:
            pid = f"{base}-{chr(ord('b') + k)}"
            k += 1
        port["id"] = pid
        seen.add(pid)
        out.append(port)

    for g0 in groups or []:
        g = dict(g0)
        origin = "template"
        if v1:
            origin = "declared"
            g = {
                "group": g0.get("name", ""), "dir": _V1_DIRS.get(str(g0.get("direction", "io")).lower(), "io"),
                "medium": g0.get("medium", "analog"), "count": g0.get("count"),
            }
            if g0.get("labels"):
                g["names"] = list(g0["labels"])
            if g["medium"] in NETWORK_MEDIA and (g.get("count") or 1) > 1 and not g.get("names"):
                emit({"id": _slug(g["group"]), "name": g["group"], "dir": g["dir"], "medium": g["medium"], "group": g["group"], "index": 1, "channels": int(g["count"]), "origin": origin})
                continue
        name_g = str(g.get("group", ""))
        base = _slug(name_g)
        labels = g.get("labels") or []
        items: List[Tuple[str, str, int, Optional[str]]] = []  # id, name, index, name-key
        if g.get("names"):
            for i, nm in enumerate(g["names"], 1):
                items.append((base + "-" + _slug(str(nm)), f"{name_g} {nm}", i, str(nm)))
        elif int(g.get("count") or 1) > 1 or g.get("start"):
            s = int(g.get("start") or 1)
            for k in range(int(g.get("count") or 1)):
                n = s + k
                items.append((f"{base}-{n}", f"{name_g} {n}", n, None))
        else:
            items.append((base, name_g, 1, None))
        for pos, (pid, pname, idx, nm) in enumerate(items, 1):
            d = g.get("dir", "io")
            if nm is not None and isinstance(g.get("dirs"), dict) and nm in g["dirs"]:
                d = g["dirs"][nm]
            port: Dict[str, Any] = {"id": pid, "name": pname, "dir": d, "medium": g.get("medium", "other"), "group": name_g, "index": idx}
            if g.get("connector"):
                port["connector"] = g["connector"]
            if int(g.get("channels") or 1) > 1:
                port["channels"] = int(g["channels"])
            lab = labels[pos - 1] if labels and pos <= len(labels) else g.get("label")
            if lab:
                port["label"] = lab
            port["origin"] = origin
            emit(port)
    return out


def expand_port_groups(groups: List[Dict[str, Any]], v1: bool = False) -> List[Dict[str, Any]]:
    try:
        from .. import schema  # type: ignore

        fn = getattr(schema, "expand_port_groups", None)
        if fn is not None:
            return fn(groups, v1=v1)
    except Exception:
        pass
    return _local_expand(groups, v1=v1)


# --------------------------------------------------------------- loading


def _custom_dir() -> Path:
    from ..project import data_root

    return data_root() / "library"


def _dirs() -> List[Tuple[Path, str]]:
    dirs: List[Tuple[Path, str]] = [(BUILTIN_DIR, "builtin")]
    try:
        from ..plugins import template_dirs

        dirs += [(p, "extension") for p in template_dirs()]
    except Exception:
        pass
    dirs.append((_custom_dir(), "custom"))
    return dirs


def _signature(dirs: List[Tuple[Path, str]]) -> Tuple[Any, ...]:
    sig = []
    for d, src in dirs:
        try:
            st = d.stat()
            sig.append((str(d), src, st.st_mtime_ns))
        except OSError:
            sig.append((str(d), src, None))
    return tuple(sig)


def _read_dir(d: Path, source: str, into: Dict[str, Dict[str, Any]]) -> None:
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.json")):
        try:
            if f.stat().st_size > 2 * 1024 * 1024:
                continue
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = t if isinstance(t, list) else [t]
        for item in items:
            if isinstance(item, dict) and item.get("id") and not validate_template(item):
                item = dict(item)
                item["source"] = source
                into[item["id"]] = item


def load_library(refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """id → template (built-in + extension + global custom), later sources override."""
    dirs = _dirs()
    sig = _signature(dirs)
    if refresh or _cache["sig"] != sig:
        lib: Dict[str, Dict[str, Any]] = {}
        for d, src in dirs:
            _read_dir(d, src, lib)
        _cache["lib"] = dict(sorted(lib.items()))
        _cache["sig"] = sig
    return _cache["lib"]


def _merged(doc: Optional[Doc]) -> Dict[str, Dict[str, Any]]:
    lib = dict(load_library())
    for t in (doc or {}).get("templates") or []:
        if isinstance(t, dict) and t.get("id"):
            t2 = dict(t)
            t2["source"] = "project"
            lib[t["id"]] = t2
    return lib


def get_template(template_id: str, doc: Optional[Doc] = None) -> Optional[Dict[str, Any]]:
    t = _merged(doc).get(template_id or "")
    return copy.deepcopy(t) if t else None


def _discipline(t: Dict[str, Any]) -> str:
    if t.get("discipline"):
        return str(t["discipline"])
    from ..vocab import kind_discipline

    return kind_discipline(str(t.get("kind", "")))


def ports_summary(t: Dict[str, Any]) -> str:
    parts = []
    for g in t.get("ports") or []:
        n = len(g["names"]) if g.get("names") else int(g.get("count") or 1)
        parts.append(f"{n}× {g.get('group', '')}" if n > 1 else str(g.get("group", "")))
    return " · ".join(parts)


def summarize(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": t["id"], "manufacturer": t.get("manufacturer", ""), "model": t.get("model", ""),
        "name": t.get("name") or t.get("model", ""), "kind": t.get("kind", ""), "discipline": _discipline(t),
        "ru": t.get("ru"), "ports_summary": ports_summary(t), "source": t.get("source", "builtin"),
        "tags": list(t.get("tags") or []),
    }


def list_templates(q: str = "", discipline: str = "", kind: str = "", doc: Optional[Doc] = None) -> List[Dict[str, Any]]:
    words = [w for w in re.split(r"\s+", (q or "").lower().strip()) if w]
    out = []
    for t in _merged(doc).values():
        if discipline and _discipline(t) != discipline:
            continue
        if kind and t.get("kind") != kind:
            continue
        if words:
            hay = " ".join(str(x) for x in (t.get("id"), t.get("manufacturer"), t.get("model"), t.get("name"), t.get("kind"), " ".join(t.get("tags") or []))).lower()
            if not all(w in hay for w in words):
                continue
        out.append(summarize(t))
    out.sort(key=lambda s: (s["manufacturer"].lower(), s["model"].lower(), s["id"]))
    return out


# ------------------------------------------------------------ validation


def validate_template(t: Dict[str, Any]) -> List[str]:
    """Problems with a template (empty list = valid)."""
    from ..vocab import DISCIPLINES, KINDS, MEDIA, PORT_DIRS, ROUTING_MODES

    errs: List[str] = []
    if not isinstance(t, dict):
        return ["template must be an object"]
    tid = t.get("id")
    if not isinstance(tid, str) or not ID_RE.match(tid):
        errs.append(f"id {tid!r} must match {ID_RE.pattern}")
    for k in ("manufacturer", "model", "kind"):
        if not isinstance(t.get(k), str) or not t.get(k):
            errs.append(f"missing {k}")
    if t.get("kind") and t.get("kind") not in KINDS:
        errs.append(f"unknown kind {t.get('kind')!r}")
    if t.get("discipline") and t["discipline"] not in DISCIPLINES:
        errs.append(f"unknown discipline {t['discipline']!r}")
    if t.get("routing") and (t["routing"] if isinstance(t["routing"], str) else (t["routing"] or {}).get("mode")) not in ROUTING_MODES:
        errs.append(f"bad routing {t['routing']!r}")
    if t.get("width") and t["width"] not in ("full", "half"):
        errs.append("width must be full or half")
    if t.get("ru") is not None and (not isinstance(t["ru"], int) or isinstance(t["ru"], bool) or not 0 < t["ru"] <= 60):
        errs.append("ru must be an integer 1-60")
    for k in ("depth_mm", "power_w", "weight_kg", "cost", "dmx_footprint"):
        v = t.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
            errs.append(f"{k} must be a non-negative number or null")
    ports = t.get("ports")
    if not isinstance(ports, list):
        errs.append("ports must be a list of groups")
        return errs
    for i, g in enumerate(ports):
        if not isinstance(g, dict) or not g.get("group"):
            errs.append(f"ports[{i}]: group name required")
            continue
        if g.get("dir") not in PORT_DIRS:
            errs.append(f"ports[{i}] {g.get('group')}: dir must be in/out/io")
        if g.get("medium") not in MEDIA:
            errs.append(f"ports[{i}] {g.get('group')}: unknown medium {g.get('medium')!r}")
        if g.get("count") is not None and (not isinstance(g["count"], int) or g["count"] < 1 or g["count"] > 512):
            errs.append(f"ports[{i}] {g.get('group')}: count must be 1-512")
        if g.get("names") is not None and not (isinstance(g["names"], list) and g["names"]):
            errs.append(f"ports[{i}] {g.get('group')}: names must be a non-empty list")
        for v in (g.get("dirs") or {}).values():
            if v not in PORT_DIRS:
                errs.append(f"ports[{i}] {g.get('group')}: dirs values must be in/out/io")
    if not errs:
        ids = [p["id"] for p in expand_port_groups(ports)]
        if len(ids) != len(set(ids)):
            errs.append("expanded port ids are not unique")
    for c in t.get("checks") or []:
        if not isinstance(c, dict) or not c.get("id") or not c.get("text"):
            errs.append("checks need id and text")
    return errs


# -------------------------------------------------------- instantiation


def instantiate(t: Dict[str, Any], *, device_id: str, name: Optional[str] = None, room: str = "", count: Optional[int] = None) -> Dict[str, Any]:
    from ..vocab import kind_discipline

    dev: Dict[str, Any] = {"id": device_id, "name": name or t.get("name") or t.get("model") or device_id, "kind": t.get("kind", "other")}
    if t.get("discipline") and t["discipline"] != kind_discipline(dev["kind"]):
        dev["discipline"] = t["discipline"]
    for k in ("manufacturer", "model", "brand"):
        if t.get(k):
            dev[k] = t[k]
    dev["template"] = t["id"]
    dev["room"] = room
    if count and count > 1:
        dev["count"] = int(count)
    if t.get("dante"):
        dev["dante"] = True
    if t.get("dmx_footprint"):
        dev["dmx"] = {"footprint": t["dmx_footprint"]}
    dev["ports"] = expand_port_groups(t.get("ports") or [])
    return dev


def apply_template_ops(doc: Doc, device_id: str, t: Dict[str, Any]) -> List[Op]:
    """Add the template's missing ports (by id) to a device; never removes. Idempotent."""
    dev = next((d for d in doc.get("devices") or [] if d.get("id") == device_id), None)
    if dev is None:
        return []
    have = {p.get("id") for p in dev.get("ports") or []}
    missing = [p for p in expand_port_groups(t.get("ports") or []) if p["id"] not in have]
    value: Dict[str, Any] = {}
    if missing:
        value["ports"] = copy.deepcopy(dev.get("ports") or []) + missing
    if dev.get("template") != t.get("id"):
        value["template"] = t.get("id")
    for k in ("manufacturer", "model"):
        if t.get(k) and not dev.get(k):
            value[k] = t[k]
    return [{"op": "merge", "coll": "devices", "id": device_id, "value": value}] if value else []


def template_from_device(device: Dict[str, Any], template_id: str) -> Dict[str, Any]:
    """Template from a device: ports regrouped by ``group`` (numbered when possible)."""
    groups: List[Dict[str, Any]] = []
    order: List[str] = []
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for p in device.get("ports") or []:
        g = p.get("group") or p.get("name") or p.get("id")
        if g not in by_group:
            by_group[g] = []
            order.append(g)
        by_group[g].append(p)
    for g in order:
        ps = by_group[g]
        first = ps[0]
        grp: Dict[str, Any] = {"group": g, "dir": first.get("dir", "io"), "medium": first.get("medium", "other")}
        if first.get("connector"):
            grp["connector"] = first["connector"]
        chans = {int(p.get("channels") or 1) for p in ps}
        if len(chans) == 1 and max(chans) > 1:
            grp["channels"] = max(chans)
        dirs = {p.get("dir", "io") for p in ps}
        numbered = [re.match(r"^" + re.escape(g) + r" (\d+)$", p.get("name", "")) for p in ps]
        if len(ps) == 1 and ps[0].get("name") == g:
            pass
        elif all(numbered) and len(dirs) == 1:
            nums = [int(m.group(1)) for m in numbered if m]
            if nums == list(range(nums[0], nums[0] + len(nums))):
                grp["count"] = len(nums)
                if nums[0] != 1:
                    grp["start"] = nums[0]
            else:
                grp["names"] = [str(n) for n in nums]
        else:
            names = []
            for p in ps:
                nm = p.get("name", p.get("id", ""))
                names.append(nm[len(g) + 1:] if nm.startswith(g + " ") else nm)
            grp["names"] = names
            if len(dirs) > 1:
                grp["dirs"] = {n: p.get("dir", "io") for n, p in zip(names, ps)}
        groups.append(grp)
    t: Dict[str, Any] = {"id": template_id, "manufacturer": device.get("manufacturer") or "Custom", "model": device.get("model") or device.get("name", template_id), "kind": device.get("kind", "other")}
    if device.get("name"):
        t["name"] = device["name"]
    if device.get("brand"):
        t["brand"] = device["brand"]
    if device.get("dante"):
        t["dante"] = True
    if (device.get("routing") or {}).get("mode"):
        t["routing"] = device["routing"]["mode"]
    rk = device.get("rack") or {}
    if rk.get("height"):
        t["ru"] = int(rk["height"])
    if (device.get("dmx") or {}).get("footprint"):
        t["dmx_footprint"] = device["dmx"]["footprint"]
    t["cost"] = (device.get("inventory") or {}).get("cost")
    t["ports"] = groups
    return t


# ---------------------------------------------------------- custom store


def save_custom_template(t: Dict[str, Any], override: bool = False) -> Path:
    """Write ``<data>/library/<id>.json``. ValueError on problems; FileExistsError for a built-in id without override."""
    problems = validate_template(t)
    if problems:
        err = ValueError("; ".join(problems))
        err.problems = problems  # type: ignore[attr-defined]
        raise err
    if (BUILTIN_DIR / f"{t['id']}.json").is_file() and not override:
        raise FileExistsError(f"'{t['id']}' is a built-in template; save with override to shadow it")
    d = _custom_dir()
    d.mkdir(parents=True, exist_ok=True)
    clean = {k: t[k] for k in _TEMPLATE_KEYS if k in t}
    path = d / f"{t['id']}.json"
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    _cache["sig"] = None
    return path


def delete_custom_template(template_id: str) -> None:
    """Remove a global custom template. PermissionError for built-ins, FileNotFoundError if absent."""
    if not ID_RE.match(template_id or ""):
        raise FileNotFoundError(template_id)
    path = _custom_dir() / f"{template_id}.json"
    if not path.is_file():
        if (BUILTIN_DIR / f"{template_id}.json").is_file():
            raise PermissionError(f"'{template_id}' is a built-in template")
        raise FileNotFoundError(template_id)
    path.unlink()
    _cache["sig"] = None


__all__ = [
    "BUILTIN_DIR", "load_library", "list_templates", "get_template", "validate_template", "instantiate",
    "apply_template_ops", "template_from_device", "save_custom_template", "delete_custom_template",
    "expand_port_groups", "ports_summary", "summarize",
]
