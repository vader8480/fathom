"""Search over a v2 doc (SPEC FR-SRCH, hit shape §5.11).

Ranking per field: exact (100) > prefix (80) > token (60) > substring (40) >
fuzzy, edit distance 1 on tokens of ≥ 4 chars (25). Ties: kind order
device, port, cable, interface, network, room, rack, floorplan, attachment, page, then title.
Every hit also carries ``status``: the device or page status, ``''`` for other kinds.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

Doc = Dict[str, Any]

KIND_ORDER: Tuple[str, ...] = ("device", "port", "cable", "interface", "network", "room", "rack", "floorplan", "attachment", "page")
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def _tokens(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.split(text) if t]


def _edit1(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` differ by at most one insert, delete or substitution."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def score_value(q: str, qtokens: List[str], value: str) -> int:
    v = _norm(value)
    if not v or not q:
        return 0
    if v == q:
        return 100
    if v.startswith(q):
        return 80
    vt = _tokens(v)
    if qtokens and all(t in vt for t in qtokens):
        return 60
    if q in v:
        return 40
    if qtokens:
        fuzzy = False
        for t in qtokens:
            if t in vt:
                continue
            if len(t) >= 4 and any(len(x) >= 4 and _edit1(t, x) for x in vt):
                fuzzy = True
                continue
            return 0
        if fuzzy:
            return 25
    return 0


class SearchIndex:
    """Flat list of searchable entries built from a doc (+ overlay)."""

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    def add(self, kind: str, id: str, title: str, subtitle: str = "", room: str = "", device: Optional[str] = None,
            port: Optional[str] = None, fields: Optional[List[Tuple[str, Any]]] = None, status: Any = "") -> None:
        fl = [(name, _norm(val)) for name, val in (fields or []) if val not in (None, "")]
        self.entries.append({"kind": kind, "id": id, "device": device, "port": port, "title": title, "subtitle": subtitle,
                             "room": room, "status": str(status or ""), "fields": [(n, v) for n, v in fl if v]})

    def __len__(self) -> int:
        return len(self.entries)


def _join(*parts: Any) -> str:
    return " · ".join(str(p) for p in parts if p)


def build_index(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> SearchIndex:
    from .trace import device_ports, doc_devices, find_port, medium_label, port_label

    ix = SearchIndex()
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    venues = {v.get("id"): v for v in doc.get("venues") or [] if isinstance(v, dict)}
    room_name = lambda rid: (rooms.get(rid) or {}).get("name") or ""  # noqa: E731
    devs = doc_devices(doc, overlay)
    byid = {d["id"]: d for d in devs}
    for d in devs:
        inv = d.get("inventory") if isinstance(d.get("inventory"), dict) else {}
        fields: List[Tuple[str, Any]] = [("name", d.get("name")), ("id", d["id"]), ("code", d.get("code")),
                                         ("dante_name", d.get("dante_name"))]
        fields += [("alias", a) for a in d.get("aliases") or []]
        fields += [("manufacturer", d.get("manufacturer")), ("model", d.get("model")), ("sub", d.get("sub")),
                   ("serial", inv.get("serial")), ("asset_tag", inv.get("asset_tag")), ("note", d.get("note"))]
        model = f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip() or d.get("sub") or ""
        rn = room_name(d.get("room") or "") if d.get("room") else "Shared inventory"
        ix.add("device", d["id"], str(d.get("name") or d["id"]), _join(model, rn), d.get("room") or "", d["id"], None, fields,
               d.get("status"))
        for p in device_ports(d):
            ix.add("port", f"{d['id']}:{p['id']}", _join(d.get("name") or d["id"], port_label(p)),
                   _join(p.get("name"), p.get("dir"), medium_label(p.get("medium", ""))), d.get("room") or "", d["id"], p["id"],
                   [("label", p.get("label")), ("name", p.get("name")), ("note", p.get("note"))])
        for itf in d.get("interfaces") or []:
            if isinstance(itf, dict) and itf.get("id"):
                _add_iface(ix, d, itf)
    if overlay:
        for dev_id, ifaces in (overlay.get("interfaces") or {}).items():
            d = byid.get(dev_id)
            if d is None:
                continue
            have = {i.get("id") for i in d.get("interfaces") or [] if isinstance(i, dict)}
            for itf in ifaces or []:
                if isinstance(itf, dict) and itf.get("id") and itf["id"] not in have:
                    _add_iface(ix, d, itf)
    for c in doc.get("cables") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        f, t = c.get("from") or {}, c.get("to") or {}
        fd, td = byid.get(f.get("device") or ""), byid.get(t.get("device") or "")

        def end(dev: Optional[Dict[str, Any]], e: Dict[str, Any]) -> str:
            name = (dev or {}).get("name") or e.get("device") or "?"
            p = find_port(dev, e.get("port"))
            return _join(name, port_label(p)) if p else str(name)

        ix.add("cable", c["id"], str(c.get("tag") or c["id"]), f"{end(fd, f)} → {end(td, t)}",
               (fd or {}).get("room") or "", f.get("device"), None,
               [("tag", c.get("tag")), ("label", c.get("label")), ("signal", c.get("signal")), ("note", c.get("note")), ("id", c["id"])])
    for n in doc.get("networks") or []:
        if isinstance(n, dict) and n.get("id"):
            vlan = n.get("vlan")
            vlan = "" if vlan is None or isinstance(vlan, bool) else str(vlan).strip()
            ix.add("network", str(n["id"]), str(n.get("name") or n["id"]), _join(f"VLAN {vlan}" if vlan else "", n.get("subnet")), "",
                   None, None, [("name", n.get("name")), ("id", n["id"]), ("vlan", vlan), ("subnet", n.get("subnet")),
                                ("protocol", n.get("protocol"))])
    for r in rooms.values():
        if r.get("id"):
            ix.add("room", r["id"], str(r.get("name") or r["id"]), (venues.get(r.get("venue")) or {}).get("name") or "", r["id"], None, None,
                   [("name", r.get("name")), ("code", r.get("code")), ("id", r["id"])])
    for k in doc.get("racks") or []:
        if isinstance(k, dict) and k.get("id"):
            ix.add("rack", k["id"], str(k.get("name") or k["id"]), _join(f"{k.get('units')}U" if k.get("units") else "", room_name(k.get("room") or "")),
                   k.get("room") or "", None, None, [("name", k.get("name")), ("id", k["id"]), ("note", k.get("notes"))])
    for fp in doc.get("floorplans") or []:
        if isinstance(fp, dict) and fp.get("id"):
            ix.add("floorplan", fp["id"], str(fp.get("name") or fp["id"]), room_name(fp.get("room") or ""), fp.get("room") or "", None, None,
                   [("name", fp.get("name")), ("id", fp["id"])])
    for a in doc.get("attachments") or []:
        if isinstance(a, dict) and a.get("id"):
            dev = byid.get(a.get("device") or "")
            ix.add("attachment", a["id"], str(a.get("name") or a["id"]), _join(a.get("kind"), (dev or {}).get("name")),
                   (dev or {}).get("room") or "", a.get("device") or None, None, [("name", a.get("name")), ("note", a.get("note"))])
    _add_pages(ix, doc, room_name)
    return ix


def _add_pages(ix: SearchIndex, doc: Doc, room_name: Any) -> None:
    """SOP pages: title, slug, tags, summary, headings and the body text (hit id = slug)."""
    try:
        from .markdown import headings, plain_text
    except ImportError:  # pragma: no cover
        return
    for p in doc.get("pages") or []:
        if not isinstance(p, dict) or not p.get("id") or not p.get("slug"):
            continue
        body = str(p.get("body") or "")
        fields: List[Tuple[str, Any]] = [("title", p.get("title")), ("slug", p.get("slug")), ("summary", p.get("summary"))]
        fields += [("tag", t) for t in p.get("tags") or []]
        fields += [("heading", h) for h in headings(body)]
        fields.append(("body", plain_text(body)))
        rooms = [r for r in p.get("rooms") or [] if isinstance(r, str)]
        sub = _join((p.get("kind") or "sop").replace("_", " "), room_name(rooms[0]) if rooms else "", "draft" if p.get("status") == "draft" else "")
        ix.add("page", str(p["slug"]), str(p.get("title") or p["slug"]), sub, rooms[0] if rooms else "", None, None, fields,
               p.get("status"))


def _add_iface(ix: SearchIndex, d: Dict[str, Any], itf: Dict[str, Any]) -> None:
    title = str(itf.get("ip") or itf.get("hostname") or itf.get("mac") or itf["id"])
    sub = _join(d.get("name") or d["id"], itf["id"] + (f" ({itf['role']})" if itf.get("role") else ""), itf.get("source") if itf.get("source") not in (None, "manual") else "")
    ix.add("interface", f"{d['id']}/{itf['id']}", title, sub, d.get("room") or "", d["id"], itf.get("port") or None,
           [("ip", itf.get("ip")), ("mac", itf.get("mac")), ("hostname", itf.get("hostname"))])


def search(index_or_doc: Union[SearchIndex, Doc], q: str, limit: int = 20, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Ranked hits (§5.11) for query ``q``; ``kinds`` restricts entry kinds."""
    ix = index_or_doc if isinstance(index_or_doc, SearchIndex) else build_index(index_or_doc)
    qn = _norm(q)
    if not qn:
        return []
    qt = _tokens(qn)
    want = set(kinds) if kinds else None
    hits = []
    for e in ix.entries:
        if want is not None and e["kind"] not in want:
            continue
        best, match = 0, ""
        for name, val in e["fields"]:
            s = score_value(qn, qt, val)
            if s > best:
                best, match = s, name
        if best:
            hits.append({"kind": e["kind"], "id": e["id"], "device": e["device"], "port": e["port"], "title": e["title"],
                         "subtitle": e["subtitle"], "room": e["room"], "score": best, "match": match, "status": e["status"]})
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    hits.sort(key=lambda h: (-h["score"], order.get(h["kind"], 99), h["title"].casefold(), h["id"]))
    return hits[:max(0, int(limit))]


__all__ = ["SearchIndex", "build_index", "search", "score_value", "KIND_ORDER"]
