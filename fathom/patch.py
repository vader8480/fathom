"""Patch sheet: per-device port tables (what feeds each input, where each output goes).

Rows come from three places: manual links (with optional ``from_port`` /
``to_port`` / ``signal``), Dante subscriptions (channel level) and the
console's input / output patch. The result is what an integrator calls a
patch sheet: one block per device, inputs then outputs, cable type on every
line.

v2: ``patch_table`` returns the PatchBlock[] structure of SPEC §6.6 (one block
per device, one section per consecutive port group, one row per port plus one
per extra cable), ``patch_table_csv`` its CSV (§5.8.2 ``patch`` columns) and
``patch_schedule`` the schedule columns/rows form.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .model import Node, Project


@dataclass
class PatchRow:
    port: str
    medium: str
    peer: str  # peer node label (or free text)
    peer_id: str
    peer_port: str
    signal: str
    source: str  # manual | dante | console | waves
    count: int = 1


@dataclass
class DeviceSheet:
    node: Node
    inputs: List[PatchRow] = field(default_factory=list)
    outputs: List[PatchRow] = field(default_factory=list)

    @property
    def declared_ports(self) -> List[str]:
        out = []
        for p in self.node.ports:
            name = str(p.get("name", "ports"))
            labels = p.get("labels")
            n = len(labels) if isinstance(labels, list) else int(p.get("count", 0) or 0)
            out.append(f"{name} ×{n}" if n else name)
        return out


def build_patch_sheet(project: Project) -> List[DeviceSheet]:
    sheets: Dict[str, DeviceSheet] = {n.id: DeviceSheet(node=n) for n in project.nodes if not n.ref}
    for l in project.links:
        a, b = project.node(l.source), project.node(l.target)
        if a is None or b is None:
            continue
        a, b = project.canonical(a), project.canonical(b)
        if a.id not in sheets or b.id not in sheets:
            continue
        cnt = l.count or 1
        sheets[a.id].outputs.append(PatchRow(l.from_port or "—", l.medium, b.label, b.id, l.to_port, l.signal or l.label, "auto" if l.auto else "manual", cnt))
        sheets[b.id].inputs.append(PatchRow(l.to_port or "—", l.medium, a.label, a.id, l.from_port, l.signal or l.label, "auto" if l.auto else "manual", cnt))
        if l.bidirectional:
            sheets[b.id].outputs.append(PatchRow(l.to_port or "—", l.medium, a.label, a.id, l.from_port, l.signal or l.label, "manual", cnt))
            sheets[a.id].inputs.append(PatchRow(l.from_port or "—", l.medium, b.label, b.id, l.to_port, l.signal or l.label, "manual", cnt))
    for r in project.patch_rows:
        sheet = sheets.get(project.canon_id(r.get("device", "")))
        if sheet is None:
            continue
        peer_node = project.node(r.get("peer", "")) if r.get("peer") else None
        peer_node = project.canonical(peer_node) if peer_node else None
        row = PatchRow(
            port=r.get("port", ""),
            medium=r.get("medium", "other"),
            peer=peer_node.label if peer_node else (r.get("peer_name") or ""),
            peer_id=peer_node.id if peer_node else "",
            peer_port=r.get("peer_port", ""),
            signal=r.get("signal", ""),
            source=r.get("source", "import"),
        )
        (sheet.inputs if r.get("dir") == "in" else sheet.outputs).append(row)
    ordered = []
    for n in project.nodes:
        if n.ref:
            continue
        s = sheets[n.id]
        if s.inputs or s.outputs or n.ports:
            ordered.append(s)
    return ordered


def patch_sheet_csv(project: Project) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["device", "direction", "port", "cable", "peer device", "peer port", "signal", "count", "source"])
    for sheet in build_patch_sheet(project):
        for r in sheet.inputs:
            w.writerow([sheet.node.label, "in", r.port, project.medium(r.medium)["label"], r.peer, r.peer_port, r.signal, r.count, r.source])
        for r in sheet.outputs:
            w.writerow([sheet.node.label, "out", r.port, project.medium(r.medium)["label"], r.peer, r.peer_port, r.signal, r.count, r.source])
    return buf.getvalue()


# ===================================================================== v2: patch table (SPEC §6.6)

Doc = Dict[str, Any]

PATCH_COLUMNS: List[Dict[str, str]] = [
    {"key": "room", "label": "Room"},
    {"key": "device", "label": "Device"},
    {"key": "section", "label": "Section"},
    {"key": "dir", "label": "Dir"},
    {"key": "port", "label": "Port"},
    {"key": "label", "label": "Label"},
    {"key": "peer_device", "label": "Peer device"},
    {"key": "peer_port", "label": "Peer port"},
    {"key": "cable_tag", "label": "Cable"},
    {"key": "medium", "label": "Medium"},
    {"key": "source", "label": "Source"},
]

_DIR_WORD = {"in": "In", "out": "Out", "io": "I/O"}


def _medium_short(medium: str) -> str:
    try:
        from . import vocab
        m = vocab.MEDIA.get(medium or "")
        if m and m.get("short"):
            return str(m["short"])
    except Exception:  # pragma: no cover - vocab not landed yet
        pass
    return (medium or "OTH").upper()


def _medium_discipline(medium: str) -> str:
    try:
        from . import vocab
        return vocab.medium_discipline(medium or "")
    except Exception:  # pragma: no cover
        return "other"


def _model_line(dev: Dict[str, Any]) -> str:
    m = f"{dev.get('manufacturer') or ''} {dev.get('model') or ''}".strip()
    return m or str(dev.get("sub") or "")


def _block_matches(dev: Dict[str, Any], room: str, discipline: str, query: str) -> bool:
    from .trace import device_discipline, device_ports
    if room not in ("*", None) and (dev.get("room") or "") != room:
        return False
    if discipline:
        if device_discipline(dev) != discipline and not any(_medium_discipline(p.get("medium", "")) == discipline for p in device_ports(dev)):
            return False
    if query:
        q = query.casefold().strip()
        hay = " ".join(str(dev.get(k) or "") for k in ("id", "name", "manufacturer", "model", "sub", "code")).casefold()
        if q not in hay:
            return False
    return True


def patch_table(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*", discipline: str = "", query: str = "", include_overlay: bool = False, only_patched: bool = False) -> List[Dict[str, Any]]:
    """PatchBlock[] (§6.6): blocks in device order, sections per consecutive port group."""
    from .trace import device_discipline, device_map, device_ports, find_port

    devs = device_map(doc, overlay)
    # (device, port|None) -> [(cable, other_end, my_side)] in cable order
    at: Dict[tuple, List[tuple]] = {}

    def end_key(end: Any) -> Optional[tuple]:
        if not isinstance(end, dict) or not end.get("device"):
            return None
        dev = devs.get(end["device"])
        port = end.get("port") or None
        if dev is not None and port and find_port(dev, port) is None:
            port = None
        return (end["device"], port)

    for c in doc.get("cables") or []:
        if not isinstance(c, dict):
            continue
        a, b = end_key(c.get("from")), end_key(c.get("to"))
        if a is None or b is None or a == b:
            continue
        at.setdefault(a, []).append((c, b, "out", c.get("medium") or "", "cable"))
        at.setdefault(b, []).append((c, a, "in", c.get("medium") or "", "cable"))
    if include_overlay and overlay:
        for r in overlay.get("routes") or []:
            if not isinstance(r, dict):
                continue
            a, b = end_key(r.get("from")), end_key(r.get("to"))
            if a is None or b is None or a == b:
                continue
            src = str(r.get("kind") or "import")
            at.setdefault(a, []).append((None, b, "out", r.get("medium") or "dante", src))
            at.setdefault(b, []).append((None, a, "in", r.get("medium") or "dante", src))

    def row(port: Optional[Dict[str, Any]], link: Optional[tuple]) -> Dict[str, Any]:
        r: Dict[str, Any] = {
            "port": port["id"] if port else None,
            "port_name": port.get("name") if port else None,
            "label": (port.get("label") or None) if port else None,
            "peer_device": None, "peer_name": None, "peer_port": None, "peer_port_name": None, "peer_label": None,
            "cable": None, "tag": None,
            "medium": port.get("medium") if port else None,
            "source": None,
        }
        if link is not None:
            cable, (pdev_id, pport_id), _side, medium, source = link
            pdev = devs.get(pdev_id)
            pport = find_port(pdev, pport_id)
            r.update({
                "peer_device": pdev_id,
                "peer_name": (pdev.get("name") or pdev_id) if pdev else pdev_id,
                "peer_port": pport_id,
                "peer_port_name": pport.get("name") if pport else None,
                "peer_label": (pport.get("label") or None) if pport else None,
                "cable": cable.get("id") if cable else None,
                "tag": (cable.get("tag") or None) if cable else None,
                "medium": medium or r["medium"],
                "source": source,
            })
        return r

    blocks: List[Dict[str, Any]] = []
    for dev in doc.get("devices") or []:
        if not isinstance(dev, dict) or not dev.get("id") or not _block_matches(dev, room, discipline, query):
            continue
        sections: List[Dict[str, Any]] = []
        cur_key: Optional[str] = None
        for p in device_ports(dev):
            title = p.get("group") or f"{_medium_short(p.get('medium', ''))} {_DIR_WORD.get(p.get('dir', ''), 'I/O')}"
            if cur_key != title or not sections:
                sections.append({"title": title, "dir": p.get("dir") or "io", "medium": p.get("medium") or "", "rows": []})
                cur_key = title
            sec = sections[-1]
            if sec["dir"] != (p.get("dir") or "io"):
                sec["dir"] = "io"
            links = at.get((dev["id"], p["id"]), [])
            if links:
                for link in links:
                    sec["rows"].append(row(p, link))
            else:
                sec["rows"].append(row(p, None))
        dev_links = at.get((dev["id"], None), [])
        if dev_links:
            dirs = {link[2] for link in dev_links}
            sec = {"title": "Device", "dir": dirs.pop() if len(dirs) == 1 else "io", "medium": dev_links[0][3], "rows": []}
            for link in dev_links:
                sec["rows"].append(row(None, link))
            sections.append(sec)
        if only_patched:
            for sec in sections:
                sec["rows"] = [r for r in sec["rows"] if r["peer_device"] is not None]
            sections = [s for s in sections if s["rows"]]
            if not sections:
                continue
        blocks.append({
            "device": dev["id"], "name": dev.get("name") or dev["id"], "model": _model_line(dev),
            "room": dev.get("room") or "", "discipline": device_discipline(dev), "kind": dev.get("kind") or "other",
            "sections": sections,
        })
    return blocks


def _csv_rows(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for b in blocks:
        for s in b.get("sections") or []:
            for r in s.get("rows") or []:
                out.append({
                    "room": b.get("room") or "",
                    "device": b.get("name") or b.get("device") or "",
                    "device_id": b.get("device") or "",
                    "section": s.get("title") or "",
                    "dir": s.get("dir") or "",
                    "port": r.get("label") or r.get("port_name") or "",
                    "port_id": r.get("port") or "",
                    "label": r.get("label") or "",
                    "peer_device": r.get("peer_name") or "",
                    "peer_device_id": r.get("peer_device") or "",
                    "peer_port": r.get("peer_label") or r.get("peer_port_name") or "",
                    "peer_port_id": r.get("peer_port") or "",
                    "cable_tag": r.get("tag") or "",
                    "cable_id": r.get("cable") or "",
                    "medium": r.get("medium") or "",
                    "source": r.get("source") or "",
                })
    return out


def patch_table_csv(blocks: List[Dict[str, Any]]) -> str:
    """CSV of PatchBlocks: §5.8.2 ``patch`` labels, RFC 4180 quoting, ``\\r\\n`` line endings."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([c["label"] for c in PATCH_COLUMNS])
    for r in _csv_rows(blocks):
        w.writerow([r[c["key"]] for c in PATCH_COLUMNS])
    return buf.getvalue()


def patch_schedule(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*", discipline: str = "") -> Dict[str, Any]:
    """Schedule form: ``{"kind", "columns", "rows", "problems"}`` (rows carry names and ``*_id`` keys)."""
    blocks = patch_table(doc, overlay, room=room, discipline=discipline)
    return {"kind": "patch", "columns": [dict(c) for c in PATCH_COLUMNS], "rows": _csv_rows(blocks), "problems": []}
