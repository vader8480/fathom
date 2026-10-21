"""Merge parsed exports into the project model.

Order: Dante preset first (device inventory + routing), then the console CSV
(channel names and patch, resolved against Dante subscriptions), then Waves
(racks on the FOH computer). Everything added here is flagged ``auto`` so it
never overwrites manual entry and is not written back to project.json.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .model import BRANDS, Link, Node, Project, norm_name, slug
from .parsers import parse_any
from .parsers.common import compress_ranges
from .parsers.dante import DanteDevice, DanteNetwork
from .parsers.waves import WavesSession
from .parsers.yamaha import ConsoleData, describe_patch_source

# ------------------------------------------------------------ inference

#: most specific first: an "AM2" is IEM gear even though it is also "RedNet"
_KIND_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("iem", ("psm", "p10t", "p9t", "sr2050", "iem", "am2", "headphone", "hp amp", "lectrosonics", "in-ear", "inear", "r400", "r500", "duet", "wisycom")),
    ("console", ("cl1", "cl3", "cl5", "ql1", "ql5", "dm3", "dm7", "tf1", "tf3", "tf5", "tf-rack", "rivage", "pm3", "pm5", "pm7", "pm10", "sq-5", "sq5", "sq6", "sq7", "dlive", "avantis", "x32", "m32", "wing", "sd5", "sd7", "sd9", "sd10", "sd12", "s21", "s31", "quantum", "mixer", "console", "desk")),
    ("computer", ("dante virtual soundcard", "dvs", "dante via", "virtual soundcard", "macbook", "mac mini", "mac pro", "pc", "laptop", "ableton", "pro tools", "protools", "qlab", "playback", "tracks", "cg", "ultrix", "ross", "tricaster", "hyperdeck", "atem")),
    ("stage_io", ("rio", "tio", "ri8", "ro8", "rmio", "1073opx", "mp8r", "a16r", "a8r", "d16r", "d64r", "hd32r", "stagebox", "stage box", "s16", "s32", "dl16", "dl32", "dl153", "dl155", "sd-rack", "sd rack", "d-rack", "ar2412", "ar84", "dx168", "dt168", "gx4816", "mi8", "mo8", "ao8", "ai8", "ulxd4", "qlxd4", "ad4", "axt400", "ur4", "ulxd", "qlxd", "ew-dx", "em 6000", "6000 em", "slx-d", "slxd4", "rednet")),
    ("pa", ("la7", "la4x", "la12x", "la8", "amp", "d80", "d40", "d20", "x4", "x8", "powersoft", "quattrocanali", "duecanali", "ottocanali", "crown", "dci", "cdi", "pld", "cxd", "galaxy", "galileo", "p1 ", "lake", "lm 44", "processor", "dsp", "speaker", "sub", "monitor amp", "qsc core", "q-sys")),
    ("video", ("video", "camera", "ptz", "decimator", "sdi", "hdmi")),
]

#: where an auto-created card goes when the project already has a group for it
_GROUP_HINTS: Dict[str, Tuple[str, ...]] = {
    "console": ("mix", "console", "foh"),
    "pa": ("pa", "zones", "speaker", "amp"),
    "iem": ("iem", "monitor", "ear"),
    "stage_io": ("wired", "stage", "input", "i/o"),
    "source": ("wired", "input", "source"),
    "computer": ("computer", "playback", "video"),
    "video": ("video", "playback", "computer"),
}

_BRAND_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("yamaha", ("yamaha",)),
    ("shure", ("shure",)),
    ("focusrite", ("focusrite", "rednet")),
    ("neve", ("neve", "ams neve", "ams-neve")),
    ("ross", ("ross", "ross video")),
    ("genelec", ("genelec",)),
    ("waves", ("waves",)),
    ("ableton", ("ableton",)),
    ("avid", ("avid", "digidesign")),
    ("l-acoustics", ("l-acoustics", "l acoustics", "lacoustics")),
    ("lectrosonics", ("lectrosonics",)),
    ("behringer", ("behringer",)),
    ("midas", ("midas",)),
    ("sennheiser", ("sennheiser",)),
    ("allen-heath", ("allen", "a&h", "allen & heath", "allen&heath")),
    ("digico", ("digico",)),
    ("qsc", ("qsc",)),
    ("powersoft", ("powersoft",)),
    ("d&b", ("d&b", "audiotechnik")),
    ("meyer", ("meyer",)),
    ("blackmagic", ("blackmagic",)),
    ("apple", ("apple",)),
    ("microsoft", ("microsoft",)),
]

_LEFT_KINDS = {"source", "stage_io", "computer", "video"}


def infer_kind(dev: DanteDevice) -> str:
    text = f"{dev.manufacturer} {dev.model} {dev.name} {dev.default_name}".lower()
    for kind, words in _KIND_RULES:
        for w in words:
            if w in text:
                return kind
    if dev.rx and not dev.tx:
        return "pa"
    if dev.tx and not dev.rx:
        return "stage_io"
    return "other"


def infer_brand(*texts: str) -> str:
    text = " ".join(t for t in texts if t).lower()
    for brand, words in _BRAND_RULES:
        for w in words:
            if w in text:
                return brand if brand in BRANDS else ""
    return ""


def unique_id(project: Project, base: str) -> str:
    base = slug(base)
    if project.node(base) is None:
        return base
    i = 2
    while project.node(f"{base}-{i}") is not None:
        i += 1
    return f"{base}-{i}"


def _side_of(project: Project, node: Node) -> str:
    g = project.group(node.group) if node.group else None
    if g:
        return g.side
    col = project.column(node.column) if node.column else None
    if col and col.side in ("left", "right"):
        return col.side
    return "left" if node.kind in _LEFT_KINDS else "right"


def _spine_column(project: Project, side: str) -> str:
    cols = project.columns_for_side(side)
    if not cols:
        return ""
    return cols[-1].id if side == "left" else cols[0].id


def _auto_group(project: Project, side: str) -> str:
    gid = f"auto-{side}"
    project.ensure_group(gid, "Dante devices (unplaced)", side, note="Found in the Dante preset but not placed yet. Give them a group and column in project.json.", auto=True)
    return gid


_WIRELESS_WORDS = ("ulxd", "qlxd", "axt", "ad4", "ur4", "slxd", "ew-dx", "em 6000", "6000 em", "wireless", "receiver")


def _pick_group(project: Project, kind: str, side: str, text: str = "") -> str:
    """An existing group on ``side`` whose label fits the kind, else the auto group."""
    hints: Tuple[str, ...] = _GROUP_HINTS.get(kind, ())
    if any(w in text.lower() for w in _WIRELESS_WORDS):
        hints = ("wireless", "rf") + hints
    for hint in hints:
        for g in project.groups_for_side(side):
            if g.auto:
                continue
            if hint in g.label.lower():
                return g.id
    return _auto_group(project, side)


def _device_side(dev: DanteDevice, kind: str, tx_used: set) -> str:
    """Left = feeds the network (sources, stage boxes, playback). Right = consumes it."""
    if kind in ("console", "pa", "iem"):
        return "right"
    receives = any(c.subscribed for c in dev.rx)
    transmits = dev.name in tx_used
    if kind in ("computer", "video", "stage_io", "other"):
        if receives and not transmits:
            return "right"  # recorder, monitor feed, output-only box
        return "left"
    return "left" if kind in _LEFT_KINDS else "right"


# ---------------------------------------------------------------- Dante


def merge_dante(project: Project, net: DanteNetwork, elsewhere: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Node]:
    """Attach Dante devices to nodes (creating cards when allowed). Returns device name → node.

    ``elsewhere`` (v2 docs) maps match keys to devices of the doc that are not drawn on this
    map (other rooms, shared inventory, hidden): those get a detached node so routes and details
    still resolve to the real device, but no card is added here.
    """
    mapping: Dict[str, Node] = {}
    tx_used = {s.tx_device for s in net.subscriptions()}
    for dev in net.devices.values():
        node = project.find_node_by_name(dev.name) or (project.find_node_by_name(dev.default_name) if dev.default_name else None)
        other = None
        if node is None and elsewhere:
            other = elsewhere.get(norm_name(dev.name)) or (elsewhere.get(norm_name(dev.default_name)) if dev.default_name else None)
        if other is not None:
            detached = _detached_nodes(project)
            node = detached.get(str(other.get("id")))
            if node is None:  # one detached node per device across imports, so details accumulate
                node = Node(id=str(other.get("id")), label=str(other.get("name") or dev.name), kind=str(other.get("kind") or "other"),
                            dante=True, dante_name=dev.name)
                detached[node.id] = node
            where = f"room {other.get('room')}" if other.get("room") else "shared inventory"
            msg = f"dante: '{dev.name}' belongs to {where}; not drawn here"
            if msg not in project.notes:
                project.notes.append(msg)
        elif node is None and project.options.auto_dante_nodes:
            kind = infer_kind(dev)
            side = _device_side(dev, kind, tx_used)
            node = Node(
                id=unique_id(project, dev.name),
                label=dev.name,
                sub=dev.model_text or "Dante device",
                kind=kind,
                brand=infer_brand(dev.manufacturer, dev.model),
                group=_pick_group(project, kind, side, f"{dev.manufacturer} {dev.model} {dev.name}"),
                column=_spine_column(project, side),
                dante=True,
                dante_name=dev.name,
                auto=True,
            )
            project.nodes.append(node)
            project.notes.append(f"dante: added card for unplaced device '{dev.name}' ({dev.model_text or 'unknown model'})")
        if node is None:
            project.notes.append(f"dante: device '{dev.name}' has no card (auto_dante_nodes is off)")
            continue
        node.dante = True
        for twin in project.nodes:  # cards that are the same device
            if twin.ref and project.canon_id(twin.id) == node.id:
                twin.dante = True
        if not node.dante_name:
            node.dante_name = dev.name
        if not node.brand and node.auto:
            node.brand = infer_brand(dev.manufacturer, dev.model)
        info = {
            "name": dev.name,
            "model": dev.model_text,
            "tx": len(dev.tx),
            "rx": len(dev.rx),
            "rx_subscribed": sum(1 for c in dev.rx if c.subscribed),
            "samplerate": dev.samplerate,
            "latency": dev.latency,
            "tx_labels": [c.label for c in dev.tx],
            "rx_labels": [c.label for c in dev.rx],
        }
        addrs = [a for a in (dev.primary_ip, dev.secondary_ip) if a]
        if addrs:
            info["addresses"] = addrs
        node.detail["dante"] = _merge_dante_detail(node.detail.get("dante"), info)
        mapping[dev.name] = node

    # flows between cards
    flows = net.flows()
    for (tx_name, rx_name), subs in flows.items():
        tx_node, rx_node = mapping.get(tx_name), mapping.get(rx_name)
        tx_label = tx_node.label if tx_node else tx_name
        rx_label = rx_node.label if rx_node else rx_name
        chans = [f"{s.tx_label}→{s.rx_label}" for s in subs]
        if tx_node is not None:
            tx_node.detail.setdefault("dante_flows", []).append({"dir": "out", "peer": rx_label, "peer_id": rx_node.id if rx_node else "", "count": len(subs), "channels": chans})
        if rx_node is not None:
            rx_node.detail.setdefault("dante_flows", []).append({"dir": "in", "peer": tx_label, "peer_id": tx_node.id if tx_node else "", "count": len(subs), "channels": chans})
        for s in subs:
            if rx_node is not None:
                project.patch_rows.append({"device": rx_node.id, "dir": "in", "port": f"Dante Rx {s.rx_id} · {s.rx_label}", "medium": "dante", "peer": tx_node.id if tx_node else "", "peer_name": tx_label, "peer_port": f"Dante Tx {s.tx_id} · {s.tx_label}" if s.tx_id else f"Dante Tx · {s.tx_label}", "signal": s.tx_label, "source": "dante"})
            if tx_node is not None:
                project.patch_rows.append({"device": tx_node.id, "dir": "out", "port": f"Dante Tx {s.tx_id} · {s.tx_label}" if s.tx_id else f"Dante Tx · {s.tx_label}", "medium": "dante", "peer": rx_node.id if rx_node else "", "peer_name": rx_label, "peer_port": f"Dante Rx {s.rx_id} · {s.rx_label}", "signal": s.tx_label, "source": "dante"})

    rows = []
    for s in sorted(net.subscriptions(), key=lambda s: (s.rx_device.lower(), s.rx_id)):
        rows.append({
            "rx_device": mapping[s.rx_device].label if s.rx_device in mapping else s.rx_device,
            "rx_channel": f"{s.rx_id} · {s.rx_label}",
            "tx_device": mapping[s.tx_device].label if s.tx_device in mapping else s.tx_device,
            "tx_channel": f"{s.tx_id} · {s.tx_label}" if s.tx_id else s.tx_label,
        })
    project.appendix.setdefault("dante", []).extend(rows)
    project.appendix.setdefault("dante_devices", []).extend(
        {"device": mapping[d.name].label if d.name in mapping else d.name, "dante_name": d.name, "model": d.model_text, "tx": len(d.tx), "rx": len(d.rx), "subscribed": sum(1 for c in d.rx if c.subscribed), "samplerate": d.samplerate, "latency": d.latency}
        for d in net.devices.values()
    )
    project.notes.extend(f"dante: {n}" for n in net.notes)
    return mapping


# -------------------------------------------------------------- console


def _pick_console_node(project: Project, node_id: str, data: ConsoleData) -> Node:
    if node_id:
        n = project.node(node_id)
        if n:
            return n
        project.notes.append(f"yamaha: import node '{node_id}' not found; attaching to the first console card")
    consoles = [n for n in project.nodes if n.kind == "console"]
    for n in consoles:
        if "foh" in n.label.lower() or "house" in (n.sub or "").lower():
            return n
    if consoles:
        return consoles[0]
    side = "right"
    node = Node(
        id=unique_id(project, data.model or "console"),
        label=f"{data.model or 'Console'}",
        sub="from CSV export",
        kind="console",
        brand="yamaha",
        group=_pick_group(project, "console", side),
        column=_spine_column(project, side),
        dante=True,
        auto=True,
    )
    project.nodes.append(node)
    project.notes.append("yamaha: no console card in the project; added one")
    return node


def merge_console(project: Project, data: ConsoleData, node_id: str, dante: Optional[DanteNetwork], dante_map: Dict[str, Node]) -> Node:
    node = _pick_console_node(project, node_id, data)
    named = data.named_inputs
    if data.model and not node.sub:
        node.sub = f"{data.model} · {len(named)} inputs named"
    if data.model and "yamaha" not in node.brand:
        node.brand = node.brand or "yamaha"

    # Resolve Dante patches to the transmitting card via the console's Dante device
    console_dev = None
    if dante is not None:
        console_dev = dante.find_device(node.dante_name) if node.dante_name else None
        if console_dev is None:
            for name, n in dante_map.items():
                if n is node:
                    console_dev = dante.find_device(name)
                    break
    rx_lookup: Dict[int, Tuple[str, str, Optional[Node]]] = {}
    tx_lookup: Dict[int, List[Tuple[str, str, Optional[Node]]]] = defaultdict(list)
    if console_dev is not None and dante is not None:
        for s in dante.subscriptions():
            if s.rx_device == console_dev.name:
                rx_lookup[s.rx_id] = (s.tx_device, s.tx_label, dante_map.get(s.tx_device))
            if s.tx_device == console_dev.name and s.tx_id is not None:
                tx_lookup[s.tx_id].append((s.rx_device, s.rx_label, dante_map.get(s.rx_device)))

    channels = []
    for ch in data.inputs:
        src_text, src_node = "", None
        if ch.patch and ch.patch.bus == "DANTE" and ch.patch.number in rx_lookup:
            dev_name, tx_label, src_node = rx_lookup[ch.patch.number]
            src_text = f"{src_node.label if src_node else dev_name} · {tx_label}"
        elif ch.patch and ch.patch.bus == "OMNI":
            src_text = f"{node.label} · Omni {ch.patch.number}"
            src_node = node
        row = {
            "channel": ch.label,
            "name": ch.name,
            "color": ch.color,
            "icon": ch.icon,
            "patch": ch.patch.text if ch.patch else "",
            "source": src_text,
            "source_id": src_node.id if src_node else "",
            "category": ch.category if ch.name else "",
            "insert1": ch.insert1.text if ch.insert1 else "",
            "insert2": ch.insert2.text if ch.insert2 else "",
            "direct_outs": ", ".join(p.text for p in ch.direct_outs),
        }
        channels.append(row)
        # rack returns (FX → ST IN) are internal to the console: not a patch-sheet row
        if ch.patch and ch.patch.bus != "NONE" and not ch.patch.is_rack and ch.name:
            project.patch_rows.append({
                "device": node.id, "dir": "in", "port": f"{ch.label} ← {describe_patch_source(ch.patch)}",
                "medium": "dante" if ch.patch.bus == "DANTE" else "analog", "peer": src_node.id if src_node and src_node is not node else "",
                "peer_name": src_text.split(" · ")[0] if src_text and src_node is not node else "", "peer_port": src_text.split(" · ", 1)[1] if " · " in src_text and src_node is not node else "",
                "signal": ch.name, "source": "console",
            })
    buses = [{
        "bus": b.label, "name": b.name, "color": b.color, "icon": b.icon,
        "outputs": ", ".join(p.text for p in b.outputs),
        "insert1": b.insert1.text if b.insert1 else "", "insert2": b.insert2.text if b.insert2 else "",
        "feeds": b.feeds_text(),
    } for b in data.buses if b.name or b.has_output or b.insert_returns]
    out_rows = []
    for op in data.output_patches:
        dest_text, dest_node = "", None
        if op.port.bus == "DANTE" and op.port.number in tx_lookup:
            parts = []
            for dev_name, rx_label, n in tx_lookup[op.port.number]:
                parts.append(f"{n.label if n else dev_name} · {rx_label}")
                dest_node = dest_node or n
            dest_text = "; ".join(parts)
        src_name = data.source_name(op.source)
        out_rows.append({"port": op.port.text, "source": op.raw_source or (op.source.text if op.source else ""), "name": src_name, "destination": dest_text})
        if op.source:
            project.patch_rows.append({
                "device": node.id, "dir": "out", "port": f"{op.port.text} ← {op.source.text}{(' (' + src_name + ')') if src_name else ''}",
                "medium": "dante" if op.port.bus == "DANTE" else "analog", "peer": dest_node.id if dest_node else "",
                "peer_name": dest_text.split(" · ")[0] if dest_text else "", "peer_port": dest_text.split(" · ", 1)[1] if " · " in dest_text else "",
                "signal": src_name or op.source.text, "source": "console",
            })
    racks = data.rack_table()
    dcas = [{"dca": d.label, "name": d.name, "color": d.color, "icon": d.icon} for d in data.dcas]

    node.detail["console"] = {
        "model": data.model,
        "firmware": data.firmware,
        "inputs_total": len(data.inputs),
        "inputs_named": len(named),
        "patch_by_bus": data.patch_counts(),
        "channels": channels,
        "buses": buses,
        "outputs": out_rows,
        "racks": racks,
        "dcas": dcas,
        "warnings": list(data.warnings),
        "categories": dict(Counter(c["category"] for c in channels if c["category"])),
    }
    project.appendix.setdefault("console", []).extend([dict(c, console=node.label) for c in channels if c["name"]])
    project.appendix.setdefault("console_outputs", []).extend([dict(o, console=node.label) for o in out_rows])
    project.appendix.setdefault("console_buses", []).extend([dict(b, console=node.label) for b in buses])
    if racks:
        project.appendix.setdefault("console_racks", []).extend([dict(r, console=node.label) for r in racks])
    if dcas:
        project.appendix.setdefault("console_dcas", []).extend([dict(d, console=node.label) for d in dcas])
    if data.warnings:
        project.appendix.setdefault("console_warnings", []).extend([{"console": node.label, "warning": w} for w in data.warnings])
    project.notes.extend(f"yamaha: {n}" for n in data.notes)
    project.notes.extend(f"yamaha: warning: {w}" for w in data.warnings)
    node.detail.setdefault("_console_data", data)  # for auto sources (not serialised)
    return node


# -------------------------------------------------------------- sources


def build_auto_sources(project: Project, console_node: Node, data: ConsoleData) -> None:
    """One source card per instrument category, linked to the stage boxes it is patched into."""
    channels = console_node.detail.get("console", {}).get("channels", [])
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for row in channels:
        if not row["name"] or not row["category"] or row["category"] in ("Effects returns", "Monitors"):
            continue
        by_cat[row["category"]].append(row)
    if not by_cat:
        project.notes.append("auto_sources: no named console inputs to build source cards from")
        return
    left_cols = project.columns_for_side("left")
    src_col = left_cols[0].id if left_cols else ""
    order = ["Drums", "Bass", "Guitars", "Keys", "Strings & horns", "Vocals", "Wireless mics", "Playback", "Ambience & talkback", "Other inputs"]
    for cat in sorted(by_cat, key=lambda c: order.index(c) if c in order else 99):
        rows = by_cat[cat]
        targets: Dict[str, List[dict]] = defaultdict(list)
        for r in rows:
            targets[r["source_id"] or ""].append(r)
        # group: the group of the most used stage box on the left, else first left group
        group_id = ""
        for tid, _ in sorted(targets.items(), key=lambda kv: -len(kv[1])):
            tn = project.node(tid) if tid else None
            if tn and _side_of(project, tn) == "left" and tn.group:
                group_id = tn.group
                break
        if not group_id:
            lg = project.groups_for_side("left")
            group_id = lg[0].id if lg else _auto_group(project, "left")
        parts = []
        for tid, trs in sorted(targets.items(), key=lambda kv: -len(kv[1])):
            tn = project.node(tid) if tid else None
            parts.append(f"{len(trs)} → {tn.label if tn else 'unpatched'}")
        node = Node(
            id=unique_id(project, f"src-{cat}"),
            label=cat,
            count=len(rows),
            sub=" · ".join(parts),
            kind="source",
            group=group_id,
            column=src_col,
            auto=True,
        )
        node.detail["channels"] = [{"channel": r["channel"], "name": r["name"], "patch": r["patch"], "source": r["source"]} for r in rows]
        project.nodes.append(node)
        for tid, trs in targets.items():
            if not tid:
                continue
            tn = project.node(tid)
            if tn is None:
                continue
            medium = "rf" if cat == "Wireless mics" else "analog"
            ch_nums = [int(r["channel"].split()[-1]) for r in trs if r["channel"].startswith("CH ")]
            project.links.append(Link(
                source=node.id, target=tid, medium=medium, count=len(trs),
                signal=", ".join(r["name"] for r in trs)[:120],
                to_port=f"{tn.label} in {compress_ranges(int(r['source'].split(' · ')[-1]) for r in trs if r['source'] and r['source'].split(' · ')[-1].strip().isdigit())}" if any(r["source"] for r in trs) else "",
                from_port=f"CH {compress_ranges(ch_nums)}" if ch_nums else "",
                auto=True,
            ))


# ----------------------------------------------------------------- Waves


def _pick_waves_node(project: Project, node_id: str) -> Node:
    if node_id:
        n = project.node(node_id)
        if n:
            return n
        project.notes.append(f"waves: import node '{node_id}' not found; attaching to the first FOH computer card")
    computers = [n for n in project.nodes if n.kind == "computer"]
    for n in computers:
        text = f"{n.label} {n.sub}".lower()
        if any(w in text for w in ("waves", "superrack", "multirack", "foh", "plugin")):
            return n
    if computers:
        return computers[0]
    side = "left"
    node = Node(id=unique_id(project, "waves-host"), label="Waves host", sub="SuperRack · DVS", kind="computer", brand="waves",
                group=_pick_group(project, "computer", side), column=_spine_column(project, side), dante=True, auto=True)
    project.nodes.append(node)
    project.notes.append("waves: no computer card in the project; added 'Waves host'")
    return node


def merge_waves(project: Project, sess: WavesSession, node_id: str) -> Node:
    node = _pick_waves_node(project, node_id)
    if not node.sub:
        node.sub = f"{sess.app or 'Waves'} · {len(sess.racks)} racks"
    if not node.brand:
        node.brand = "waves"
    node.detail["waves"] = {
        "app": sess.app,
        "session": sess.session_name,
        "racks": [{"index": r.index, "name": r.name, "input": r.input, "output": r.output, "plugins": list(r.plugins), "chain": r.chain(), "notes": r.notes} for r in sess.racks],
        "io_devices": list(sess.io_devices),
        "plugins": sess.plugin_names(),
    }
    project.appendix.setdefault("waves", []).extend({"host": node.label, "rack": r.name, "input": r.input, "output": r.output, "chain": r.chain(), "notes": r.notes} for r in sess.racks)
    for r in sess.racks:
        if r.input:
            project.patch_rows.append({"device": node.id, "dir": "in", "port": f"{r.input} → rack {r.name}", "medium": "dante", "peer": "", "peer_name": "", "peer_port": "", "signal": r.chain(), "source": "waves"})
        if r.output:
            project.patch_rows.append({"device": node.id, "dir": "out", "port": f"rack {r.name} → {r.output}", "medium": "dante", "peer": "", "peer_name": "", "peer_port": "", "signal": r.chain(), "source": "waves"})
    project.notes.extend(f"waves: {n}" for n in sess.notes)
    return node


# ---------------------------------------------------------------- driver


def resolve_import_path(spec_path: str, project_dir: Path) -> Path:
    p = Path(spec_path).expanduser()
    return p if p.is_absolute() else (project_dir / p)


def apply_imports(project: Project, project_dir: Path) -> None:
    """Parse every ``imports`` entry and merge it into the project (in place)."""
    _run_imports(project, project_dir)


def _run_imports(project: Project, project_dir: Path) -> Dict[str, object]:
    """``apply_imports`` body; also returns what the overlay lifter needs."""
    parsed = []
    for spec in project.imports:
        if spec.kind not in ("", "auto", "yamaha", "dante", "waves"):
            continue  # registry importers contribute to the v2 overlay instead
        path = resolve_import_path(spec.path, project_dir)
        if not path.exists():
            project.notes.append(f"import skipped: {spec.path} not found")
            continue
        try:
            result = parse_any(path, spec.kind)
        except SystemExit as exc:
            project.notes.append(f"import skipped: {spec.path}: {exc}")
            continue
        except ValueError as exc:
            project.notes.append(f"import skipped: {spec.path}: {exc}")
            continue
        if not isinstance(result, (DanteNetwork, ConsoleData, WavesSession)):
            continue
        parsed.append((spec, result))

    dante_map: Dict[str, Node] = {}
    dante_net: Optional[DanteNetwork] = None
    elsewhere = _elsewhere_index(project, project_dir) if any(isinstance(r, DanteNetwork) for _, r in parsed) else {}
    for spec, result in parsed:
        if isinstance(result, DanteNetwork):
            dante_map.update(merge_dante(project, result, elsewhere=elsewhere))
            dante_net = result if dante_net is None else _merge_nets(dante_net, result)
    console_nodes: List[Tuple[Node, ConsoleData]] = []
    for spec, result in parsed:
        if isinstance(result, ConsoleData):
            node = merge_console(project, result, spec.node, dante_net, dante_map)
            console_nodes.append((node, result))
    for spec, result in parsed:
        if isinstance(result, WavesSession):
            merge_waves(project, result, spec.node)
    if project.options.auto_sources:
        for node, data in console_nodes:
            build_auto_sources(project, node, data)
    for n in project.nodes:
        n.detail.pop("_console_data", None)
    return {"dante": dante_net, "dante_map": dante_map, "consoles": console_nodes}


_CHANNEL_KEYS = ("tx", "rx", "rx_subscribed", "tx_labels", "rx_labels")


def _merge_dante_detail(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a later Dante source into existing detail: a channel-less source (Device Info paste,
    routing CSV) never blanks channel counts / labels; other fields fill in when missing."""
    if not old:
        return new
    out = dict(old)
    for k, v in new.items():
        if k in _CHANNEL_KEYS:
            if v:  # non-zero count / non-empty list from a richer source wins
                out[k] = v
        elif k == "addresses":
            out[k] = list(dict.fromkeys(list(old.get(k) or []) + list(v)))
        elif v not in ("", None, [], {}) and not out.get(k):
            out[k] = v
    return out


def _detached_nodes(project: Project) -> Dict[str, Node]:
    nodes = getattr(project, "_fathom_detached", None)
    if nodes is None:
        nodes = {}
        try:
            project._fathom_detached = nodes  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover
            pass
    return nodes


def _merge_nets(a: DanteNetwork, b: DanteNetwork) -> DanteNetwork:
    from .parsers.dante import _merge_addresses

    for name, dev in b.devices.items():
        tgt = a.device(name)
        tgt.manufacturer = tgt.manufacturer or dev.manufacturer
        tgt.model = tgt.model or dev.model
        tgt.default_name = tgt.default_name or dev.default_name
        tgt.samplerate = tgt.samplerate or dev.samplerate
        tgt.latency = tgt.latency or dev.latency
        if dev.tx and not tgt.tx:
            tgt.tx = dev.tx
        if dev.rx and not tgt.rx:
            tgt.rx = dev.rx
        _merge_addresses(tgt, dev)
    a.notes.extend(b.notes)
    return a


def _attach_doc(project: Project, doc: Dict[str, Any]) -> None:
    if getattr(project, "doc", None) is None:
        try:
            project._fathom_doc = doc  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover - slotted Project
            pass


def _doc_of(project: Project, project_dir: Path) -> Optional[Dict[str, Any]]:
    """The v2 doc behind a flow project: attached by the adapter, else project.json if schema 2."""
    doc = getattr(project, "doc", None) or getattr(project, "_fathom_doc", None)
    if isinstance(doc, dict):
        return doc
    try:
        from .project import find_project_file, load_dict

        pf = find_project_file(Path(project_dir))
        if pf is None:
            return None
        d = load_dict(pf)
        return d if isinstance(d, dict) and d.get("fathom") == 2 else None
    except Exception:
        return None


def _elsewhere_index(project: Project, project_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Match keys → doc devices that exist in the v2 doc but are not cards on this map."""
    doc = _doc_of(project, project_dir)
    if not doc:
        return {}
    here = {n.id for n in project.nodes if not n.auto}
    here |= {project.canon_id(n.id) for n in project.nodes if n.ref}
    out: Dict[str, Dict[str, Any]] = {}
    for d in doc.get("devices") or []:
        if not isinstance(d, dict) or d.get("auto") or not d.get("id") or d["id"] in here:
            continue
        for k in [d.get("dante_name", ""), d.get("name", ""), d["id"]] + list(d.get("aliases") or []):
            if k:
                out.setdefault(norm_name(str(k)), d)
    return out


# ======================================================== v2 doc helpers
#
# W1's ``fathom.schema`` is the authority for v2 docs. These helpers use it
# when it imports and fall back to small local versions otherwise, so the
# engine keeps working while the backend core is being built.

Doc = Dict[str, Any]

LEGACY_KINDS = ("yamaha", "dante", "waves")


def _schema():
    try:
        from . import schema  # type: ignore

        return schema
    except Exception:
        return None


def doc_version(d: Dict[str, Any]) -> int:
    sc = _schema()
    if sc is not None and hasattr(sc, "doc_version"):
        return int(sc.doc_version(d))
    if d.get("fathom") == 2:
        return 2
    if d.get("fathom") == 1 or "signalflow" in d or any(k in d for k in ("nodes", "links", "groups", "columns")):
        return 1
    return 0 if not d else 1


def load_any(d: Dict[str, Any]) -> Doc:
    """v0/v1 → migrated v2 doc (needs W1's schema), v2 → as is."""
    sc = _schema()
    if sc is not None and hasattr(sc, "load_any"):
        return sc.load_any(d)
    if doc_version(d) == 2:
        return copy.deepcopy(d)
    raise RuntimeError("v1 → v2 migration needs fathom.schema (not available)")


def default_room(doc: Doc) -> str:
    rid = str((doc.get("settings") or {}).get("default_room") or "")
    rooms = [r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict)]
    if rid in rooms:
        return rid
    return str(rooms[0]) if rooms else "main"


def filter_state(doc: Doc, state: str = "all") -> Doc:
    """§4.4.6 state filter (W1 ``schema.filter_state`` when available)."""
    sc = _schema()
    if sc is not None and hasattr(sc, "filter_state"):
        return sc.filter_state(doc, state)
    state = state or "all"
    allowed = {
        "everything": {"installed", "planned", "spare", "retired"},
        "all": {"installed", "planned", "spare"},
        "planned": {"installed", "planned"},
        "as_built": {"installed"},
    }.get(state, {"installed", "planned", "spare"})
    out = dict(doc)
    devs = [d for d in doc.get("devices") or [] if (d.get("status") or "installed") in allowed]
    keep = {d.get("id") for d in devs}
    out["devices"] = devs
    out["cables"] = [
        c for c in doc.get("cables") or []
        if (c.get("status") or "installed") in allowed
        and (c.get("from") or {}).get("device") in keep and (c.get("to") or {}).get("device") in keep
    ]
    return out


def flow_project(doc: Doc, room_id: Optional[str] = None, state: str = "all") -> Project:
    """Flow adapter (W1 ``schema.flow_project``; minimal local fallback otherwise)."""
    sc = _schema()
    if sc is not None and hasattr(sc, "flow_project"):
        project = sc.flow_project(doc, room_id, state=state)
        _attach_doc(project, doc)
        return project
    from .model import project_from_dict

    room_id = room_id or default_room(doc)
    d = filter_state(doc, state)
    room = next((r for r in d.get("rooms") or [] if r.get("id") == room_id), {}) or {}
    flow = room.get("flow") or {}
    meta = dict(d.get("meta") or {})
    for k in ("title", "intro", "footnote", "system"):
        if flow.get(k):
            meta[k] = flow[k]
    if room_id != default_room(doc) and not flow.get("system"):
        meta["system"] = room.get("name", room_id)
    nodes = []
    in_room = set()
    for dev in d.get("devices") or []:
        if dev.get("room") != room_id or dev.get("auto") or (dev.get("flow") or {}).get("show") is False:
            continue
        f = dev.get("flow") or {}
        n = {"id": dev["id"], "label": dev.get("name", dev["id"]), "kind": dev.get("kind", "other")}
        for k in ("sub", "lines", "brand", "count", "suffix", "icon", "note", "aliases", "dante", "dante_name"):
            if dev.get(k) not in (None, "", []):
                n[k] = dev[k]
        for k in ("group", "column", "order"):
            if f.get(k) not in (None, ""):
                n[k] = f[k]
        nodes.append(n)
        in_room.add(dev["id"])
    for card in flow.get("extra_cards") or []:
        n = {k: v for k, v in card.items() if k not in ("device", "seq")}
        n["ref"] = card.get("device")
        n.setdefault("label", card.get("name", card.get("id")))
        nodes.append(n)
    links = []
    for c in d.get("cables") or []:
        a, b = (c.get("from") or {}).get("device"), (c.get("to") or {}).get("device")
        if a in in_room and b in in_room and not c.get("bundle"):
            links.append({"from": a, "to": b, "medium": c.get("medium", "analog"), "label": c.get("label", ""), "signal": c.get("signal", "")})
    v1 = {
        "fathom": 1, "meta": meta,
        "spine": flow.get("spine") or {"label": "Dante network", "show": True},
        "columns": flow.get("columns") or [], "groups": flow.get("groups") or [],
        "options": flow.get("options") or {}, "nodes": nodes, "links": links,
        "media": d.get("media") or {},
        "imports": [
            {"kind": i.get("kind", ""), "path": i.get("path", ""), "node": i.get("device", ""), "label": i.get("label", "")}
            for i in d.get("imports") or [] if (i.get("room") or default_room(doc)) == room_id
        ],
    }
    if not v1["columns"]:
        v1.pop("columns")
    project = project_from_dict(v1)
    _attach_doc(project, doc)
    return project


# ================================================================ overlay


def _norm(s: str) -> str:
    return norm_name(s or "")


def imports_hash(doc: Doc, project_dir: Path) -> str:
    """sha1 of (path, size, mtime_ns) of every import file (§4.11 cache key)."""
    h = hashlib.sha1()
    for imp in doc.get("imports") or []:
        p = resolve_import_path(str(imp.get("path", "")), project_dir)
        files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        for f in files:
            try:
                st = f.stat()
                h.update(f"{f}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
            except OSError:
                h.update(f"{f}|missing\n".encode("utf-8"))
    return h.hexdigest()


def _jsonable(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def _first_port(dev: Optional[Dict[str, Any]], medium: str) -> str:
    for p in (dev or {}).get("ports") or []:
        if p.get("medium") == medium:
            return str(p.get("id", ""))
    return ""


def _empty_overlay(doc: Doc, ihash: str) -> Dict[str, Any]:
    return {
        "revision": doc.get("revision", 0), "imports_hash": ihash,
        "devices": [], "detail": {}, "routes": [], "port_labels": {}, "interfaces": {},
        "dmx": {}, "patch_rows": [], "appendix": {}, "notes": [],
    }


def merge_contribution(ov: Dict[str, Any], c: Dict[str, Any], room: str = "") -> None:
    """Fold one importer contribution into the overlay (in place)."""
    have = {d["id"] for d in ov["devices"]}
    for dev in c.get("devices") or []:
        if dev.get("id") in have:
            continue
        dev = dict(dev)
        dev.setdefault("room", room)
        dev["auto"] = True
        ov["devices"].append(dev)
        have.add(dev["id"])
    for dev, det in (c.get("detail") or {}).items():
        ov["detail"].setdefault(dev, {}).update(_jsonable(det))
    ov["routes"].extend(c.get("routes") or [])
    for dev, labels in (c.get("port_labels") or {}).items():
        ov["port_labels"].setdefault(dev, {}).update(labels)
    for dev, ifs in (c.get("interfaces") or {}).items():
        cur = ov["interfaces"].setdefault(dev, [])
        ids = {i.get("id") for i in cur}
        cur.extend(i for i in ifs if i.get("id") not in ids)
    for dev, row in (c.get("dmx") or {}).items():
        ov["dmx"].setdefault(dev, row)
    ov["patch_rows"].extend(c.get("patch_rows") or [])
    for k, rows in (c.get("appendix") or {}).items():
        ov["appendix"].setdefault(k, []).extend(_jsonable(rows))
    ov["notes"].extend(c.get("notes") or [])


def _lift_legacy(doc: Doc, room: str, project: Project, info: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a merged v1 flow project back into an overlay contribution (§4.11)."""
    devices = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    by_key: Dict[str, str] = {}
    for d in devices.values():
        for k in [d.get("name", ""), d.get("dante_name", "")] + list(d.get("aliases") or []):
            if k:
                by_key.setdefault(_norm(k), d["id"])
    # auto card id -> device id (an existing doc device, maybe in another room, or a new overlay device)
    canon: Dict[str, str] = {}
    out_devices: List[Dict[str, Any]] = []
    for n in project.nodes:
        if n.ref:
            canon[n.id] = project.canon_id(n.id)
            continue
        if not n.auto:
            canon[n.id] = n.id
            continue
        hit = by_key.get(_norm(n.dante_name)) or by_key.get(_norm(n.label))
        if hit:
            canon[n.id] = hit
            continue
        did, i = n.id, 2
        while did in devices:
            did = f"{n.id}-{i}"
            i += 1
        canon[n.id] = did
        dd = n.detail.get("dante") or {}
        src = "dante" if (n.dante_name or dd) else ("waves" if n.kind == "computer" and n.brand == "waves" else "yamaha")
        dev: Dict[str, Any] = {"id": did, "name": n.label, "kind": n.kind, "room": room, "auto": True, "source": src, "ports": []}
        for k in ("sub", "brand", "count"):
            v = getattr(n, k)
            if v:
                dev[k] = v
        if n.dante:
            dev["dante"] = True
            dev["dante_name"] = n.dante_name or n.label
            ch = max(int(dd.get("tx") or 0), int(dd.get("rx") or 0), 1)
            dev["ports"] = [{"id": "dante", "name": "Dante", "dir": "io", "medium": "dante", "channels": ch}]
        out_devices.append(dev)
    for node in (info.get("dante_map") or {}).values():  # type: ignore[union-attr]
        if node not in project.nodes:  # device placed in another room: keep its id
            canon.setdefault(node.id, node.id)
    port_of = {d["id"]: d for d in out_devices}
    port_of.update({k: v for k, v in devices.items()})

    def cid(node_id: str) -> str:
        return canon.get(node_id, project.canon_id(node_id))

    detail: Dict[str, Dict[str, Any]] = {}
    for n in project.nodes:
        if n.detail:
            detail.setdefault(cid(n.id), {}).update(_jsonable(n.detail))
    for n in (info.get("dante_map") or {}).values():  # type: ignore[union-attr]
        if n not in project.nodes and n.detail:
            detail.setdefault(n.id, {}).update(_jsonable(n.detail))
    routes: List[Dict[str, Any]] = []
    net: Optional[DanteNetwork] = info.get("dante")  # type: ignore[assignment]
    dmap: Dict[str, Node] = info.get("dante_map") or {}  # type: ignore[assignment]
    interfaces: Dict[str, List[Dict[str, Any]]] = {}
    if net is not None:
        for s in net.subscriptions():
            tx, rx = dmap.get(s.tx_device), dmap.get(s.rx_device)
            if tx is None or rx is None:
                continue
            a, b = cid(tx.id), cid(rx.id)
            fr: Dict[str, Any] = {"device": a, "channel": f"{s.tx_id} · {s.tx_label}" if s.tx_id else s.tx_label}
            to: Dict[str, Any] = {"device": b, "channel": f"{s.rx_id} · {s.rx_label}"}
            pa, pb = _first_port(port_of.get(a), "dante"), _first_port(port_of.get(b), "dante")
            if pa:
                fr["port"] = pa
            if pb:
                to["port"] = pb
            routes.append({"kind": "dante", "from": fr, "to": to, "label": s.tx_label, "medium": "dante"})
        for name, dev in net.devices.items():
            node = dmap.get(name)
            if node is None:
                continue
            ifs = []
            for role, ip, mac in (("primary", dev.primary_ip, dev.primary_mac), ("secondary", dev.secondary_ip, dev.secondary_mac)):
                if ip:
                    row = {"id": f"dante-{role}", "role": role, "ip": ip, "protocol": "dante", "source": "dante"}
                    if mac:
                        row["mac"] = mac
                    ifs.append(row)
            if ifs:
                interfaces[cid(node.id)] = ifs
    for ln in project.links:
        if not ln.auto:
            continue
        routes.append({
            "kind": "console", "from": {"device": cid(ln.source), "channel": ln.from_port or ""},
            "to": {"device": cid(ln.target), "channel": ln.to_port or ""},
            "label": ln.signal or ln.label, "medium": ln.medium, "count": ln.count,
        })
    port_labels: Dict[str, Dict[str, str]] = {}
    for node, data in info.get("consoles") or []:  # type: ignore[union-attr]
        dev = devices.get(cid(node.id))
        if not dev:
            continue
        omni = [p for p in dev.get("ports") or [] if p.get("dir") in ("in", "io") and "omni" in _norm(p.get("group", "") + p.get("name", ""))]
        for ch in data.inputs:
            if not (ch.name and ch.patch and ch.patch.bus == "OMNI" and ch.patch.number):
                continue
            n = ch.patch.number
            port = next((p for p in omni if (p.get("index") == n) or str(p.get("id", "")).endswith(f"-{n}")), None)
            if port:
                port_labels.setdefault(dev["id"], {})[port["id"]] = ch.name
    patch_rows = []
    for r in project.patch_rows:
        r2 = dict(r)
        for k in ("device", "peer"):
            if r2.get(k):
                r2[k] = cid(r2[k])
        r2["room"] = room
        patch_rows.append(r2)
    return {
        "devices": out_devices, "detail": detail, "routes": routes, "port_labels": port_labels,
        "interfaces": interfaces, "patch_rows": patch_rows, "appendix": _jsonable(project.appendix),
        "notes": list(project.notes),
    }


def build_overlay(doc: Doc, project_dir: Path) -> Dict[str, Any]:
    """Computed import overlay (§4.11). Never mutates ``doc``."""
    from . import plugins

    project_dir = Path(project_dir)
    ov = _empty_overlay(doc, imports_hash(doc, project_dir))
    droom = default_room(doc)
    imports = [i for i in doc.get("imports") or [] if isinstance(i, dict)]
    legacy_rooms: List[str] = []
    for imp in imports:
        if imp.get("kind") in LEGACY_KINDS:
            r = imp.get("room") or droom
            if r not in legacy_rooms:
                legacy_rooms.append(r)
    for room in legacy_rooms:
        try:
            project = flow_project(doc, room)
            info = _run_imports(project, project_dir)
            merge_contribution(ov, _lift_legacy(doc, room, project, info), room)
        except Exception as exc:  # one bad room must not kill the overlay
            ov["notes"].append(f"imports for room '{room}' failed: {type(exc).__name__}: {exc}")
    for imp in imports:
        kind = str(imp.get("kind") or "")
        if kind in LEGACY_KINDS:
            continue
        importer = plugins.get_importer(kind)
        if importer is None:
            ov["notes"].append(f"import skipped: no importer for kind '{kind}'")
            continue
        if importer.contribute is None:
            continue  # one-shot importers never feed the overlay
        path = resolve_import_path(str(imp.get("path", "")), project_dir)
        if not path.exists():
            ov["notes"].append(f"import skipped: {imp.get('path')} not found")
            continue
        room = imp.get("room") or droom
        try:
            result = importer.parse(path, **(imp.get("options") or {}))
            c = importer.contribute(result, doc, {"import": imp, "room": room, "device": imp.get("device", "")})
            merge_contribution(ov, c or {}, room)
        except Exception as exc:
            ov["notes"].append(f"import {imp.get('id', imp.get('path'))} ({kind}) failed: {type(exc).__name__}: {exc}")
    return ov


def promote_ops(doc: Doc, overlay: Dict[str, Any], device_ids: List[str]) -> List[Dict[str, Any]]:
    """``put`` ops that persist overlay (auto) devices as real devices."""
    existing = {d.get("id") for d in doc.get("devices") or []}
    wanted = list(dict.fromkeys(device_ids))
    ops: List[Dict[str, Any]] = []
    for dev in overlay.get("devices") or []:
        did = dev.get("id")
        if did not in wanted or did in existing:
            continue
        value = {k: copy.deepcopy(v) for k, v in dev.items() if k not in ("auto", "source")}
        value.setdefault("ports", [])
        dmx = (overlay.get("dmx") or {}).get(did)
        if dmx and "dmx" not in value:
            value["dmx"] = {k: v for k, v in dmx.items() if k != "source"}
        labels = (overlay.get("port_labels") or {}).get(did) or {}
        for p in value["ports"]:
            p.pop("auto", None)
            if p.get("id") in labels and not p.get("label"):
                p["label"] = labels[p["id"]]
        ifs = (overlay.get("interfaces") or {}).get(did)
        if ifs and "interfaces" not in value:
            value["interfaces"] = [{k: v for k, v in i.items() if k != "source"} for i in ifs]
        ops.append({"op": "put", "coll": "devices", "id": did, "value": value})
    return ops
