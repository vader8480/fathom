"""Topology: turn neighbour edges into switch-port connections, cable
proposals, overlay interfaces and VLAN / network findings.

Connection confidence:

    0.90  LLDP / CDP neighbour (switch's own LLDP table, or a frame we heard)
    0.85  controller says the client is on this port (UniFi ``sw_mac`` / ``sw_port``, or a device uplink)
    0.95  both of the above agree
    0.60  the port's MAC table holds exactly this one address
    0.30  several hosts share the port with no LLDP switch behind it → the port is flagged
          ``unmanaged`` (an unmanaged switch, hub or AP hangs off it) and no cable is proposed

A port whose LLDP / uplink neighbour is itself a switch, AP or gateway is an
``uplink``: the switch-to-switch link is reported, the client MACs learned
behind it are listed as *via* that uplink and never become cables.

Canonical switch port label is ``Port N``. Proposed cables default to
``medium: network`` (``dante`` when both ends are Dante devices) and
``type: cat6``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..model import slug
from ..network import normalize_mac
from .correlate import Entity, level_for, loose
from .probes import Neighbour, NetworkObs, ProbeResult

Doc = Dict[str, Any]

INFRA_HINTS = frozenset({"switch", "ap", "gateway", "bridge", "controller"})
METHOD_WEIGHT = {"lldp": 0.90, "cdp": 0.90, "unifi_lldp": 0.90, "unifi_uplink": 0.85, "unifi_client": 0.85}
_PORT_NUM = re.compile(r"(\d+)\s*$")
_ROLE_FOR_INDEX = ("primary", "secondary", "control", "management", "media")


def port_index(label: str) -> Optional[int]:
    m = _PORT_NUM.search(str(label or ""))
    return int(m.group(1)) if m else None


def canonical_port(label: str) -> str:
    n = port_index(label)
    return f"Port {n}" if n is not None else str(label or "").strip()


@dataclass
class Connection:
    id: str
    switch: Dict[str, Any]  # {entity, device, label, mac}
    port: str  # canonical "Port N"
    port_index: Optional[int]
    peer: Dict[str, Any]  # {entity, device, label, mac, port, kind}
    methods: List[str] = field(default_factory=list)
    confidence: float = 0.0
    level: str = "low"
    flag: str = ""  # "" | uplink | unmanaged | via | host
    medium: str = "network"
    vlan: Optional[int] = None
    peers_on_port: int = 1
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    cable: Optional[Dict[str, Any]] = None  # proposed cable (from/to/medium/type/note) when worth creating
    status: str = "new"  # new | exists (a cable with these ends is already in the document)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ helpers over entities / doc


def _entity_maps(entities: Iterable[Entity]) -> Tuple[Dict[str, Entity], Dict[str, Entity], Dict[str, Entity]]:
    by_id: Dict[str, Entity] = {}
    by_mac: Dict[str, Entity] = {}
    by_name: Dict[str, Entity] = {}
    for e in entities:
        by_id[e.id] = e
        for m in e.macs:
            by_mac.setdefault(m, e)
        for n in (e.name, e.hostname, e.dante_name):
            if n:
                by_name.setdefault(loose(n), e)
    return by_id, by_mac, by_name


def _is_infra(e: Optional[Entity], caps: Iterable[str] = ()) -> bool:
    if e is not None and (e.kind_hint in INFRA_HINTS or e.kind == "switch"):
        return True
    low = " ".join(caps).lower()
    return "bridge" in low or "switch" in low or "router" in low or "wlan_ap" in low


def _doc_devices(doc: Optional[Doc]) -> Dict[str, Dict[str, Any]]:
    return {str(d["id"]): d for d in (doc or {}).get("devices") or [] if isinstance(d, dict) and d.get("id")}


def doc_port_for(dev: Optional[Dict[str, Any]], label: str = "", index: Optional[int] = None, medium_pref: Iterable[str] = ("network", "dante")) -> str:
    """Best port id on a document device for a discovered label / index."""
    if not dev:
        return ""
    ports = [p for p in dev.get("ports") or [] if isinstance(p, dict)]
    key = loose(label)
    if key:
        for p in ports:
            if key in (loose(str(p.get("id", ""))), loose(str(p.get("name", ""))), loose(str(p.get("label", "")))):
                return str(p["id"])
    if index is not None:
        net = [p for p in ports if p.get("medium") in ("network", "dante", "avb", "aes67", "qlan")]
        for p in net:
            if p.get("index") == index:
                return str(p["id"])
        for p in net:
            if port_index(str(p.get("id", ""))) == index or port_index(str(p.get("name", ""))) == index:
                return str(p["id"])
    if key or index is not None:
        return ""  # we knew which port it should be and the device has no such port: do not guess
    for med in medium_pref:
        for p in ports:
            if p.get("medium") == med:
                return str(p["id"])
    return ""


# ------------------------------------------------------------------ proposed devices


def propose_device(e: Entity, room: str, taken: Iterable[str], seen: str = "") -> Dict[str, Any]:
    """A document-shaped device for a new entity (also used as the overlay auto device)."""
    base = slug(e.name or e.dante_name or e.hostname or e.model or (e.macs[0].replace(":", "") if e.macs else e.id))
    did, i = base, 2
    taken_set = set(taken)
    while did in taken_set:
        did = f"{base}-{i}"
        i += 1
    dante = e.kind_hint == "dante" or bool(e.dante_name)
    dev: Dict[str, Any] = {"id": did, "name": e.name or e.dante_name or e.hostname or did, "kind": e.kind, "room": room, "ports": []}
    if e.manufacturer:
        dev["manufacturer"] = e.manufacturer
    if e.model:
        dev["model"] = e.model
    if dante:
        dev["dante"] = True
        dev["dante_name"] = e.dante_name or dev["name"]
    inv: Dict[str, Any] = {}
    if e.serial:
        inv["serial"] = e.serial
    if e.firmware:
        inv["firmware"] = e.firmware
    if inv:
        dev["inventory"] = inv
    if e.ports:  # a switch: one port per physical port
        for p in e.ports:
            idx = p.get("idx")
            if idx is None:
                continue
            port = {"id": f"p{idx}", "name": str(p.get("name") or f"Port {idx}"), "dir": "io", "medium": "network", "index": int(idx),
                    "connector": "SFP" if p.get("sfp") else "RJ45", "group": "Ports"}
            if p.get("poe"):
                port["note"] = "PoE"
            dev["ports"].append(port)
    else:
        for i, itf in enumerate(entity_interfaces(e)):
            dev["ports"].append({"id": "net-" + itf["role"] if i < 2 else f"net-{i + 1}", "name": ("Dante " if dante else "Network ") + itf["role"].capitalize(),
                                 "dir": "io", "medium": "dante" if dante else "network", "connector": "RJ45", "index": i + 1})
        if not dev["ports"]:
            dev["ports"].append({"id": "net-1", "name": "Dante" if dante else "Network", "dir": "io", "medium": "dante" if dante else "network", "connector": "RJ45", "index": 1})
    dev["interfaces"] = entity_interfaces(e)
    srcs = ", ".join(e.sources)
    dev["note"] = f"Discovered by {srcs}" + (f" on {seen[:10]}" if seen else "")
    dev["tags"] = ["discovered"]
    return dev


def entity_interfaces(e: Entity) -> List[Dict[str, Any]]:
    """Interface rows (schema §interfaces) for an entity: one per MAC / IP pair, Dante primary first."""
    rows: List[Dict[str, Any]] = []
    pairs: List[Dict[str, Any]] = []  # {mac, ip, role, vlan}
    for o in e.observations:
        mac, ip = normalize_mac(str(o.get("mac") or "")) or "", str(o.get("ip") or "")
        role = (o.get("evidence") or {}).get("role") if isinstance(o.get("evidence"), dict) else None
        if not mac and not ip:
            continue
        hit = next((p for p in pairs if (mac and p["mac"] == mac) or (ip and p["ip"] == ip)), None)
        if hit is None:
            pairs.append({"mac": mac, "ip": ip, "role": role, "vlan": o.get("vlan")})
        else:
            hit["mac"] = hit["mac"] or mac
            hit["ip"] = hit["ip"] or ip
            hit["role"] = hit["role"] or role
            hit["vlan"] = hit["vlan"] if hit["vlan"] is not None else o.get("vlan")
    for mac in e.macs:
        if not any(p["mac"] == mac for p in pairs):
            pairs.append({"mac": mac, "ip": "", "role": None, "vlan": None})
    for ip in e.ips:
        if not any(p["ip"] == ip for p in pairs):
            pairs.append({"mac": "", "ip": ip, "role": None, "vlan": None})
    order = {"primary": 0, "secondary": 1}
    pairs.sort(key=lambda p: (order.get(str(p["role"] or ""), 2), p["ip"] or "~", p["mac"]))
    for i, p in enumerate(pairs):
        mac, ip = p["mac"], p["ip"]
        r = str(p["role"] or (_ROLE_FOR_INDEX[i] if i < len(_ROLE_FOR_INDEX) else "media"))
        row: Dict[str, Any] = {"id": f"disc-{r}" if i < 2 else f"disc-{i + 1}", "role": r, "source": "discovery"}
        if ip:
            row["ip"] = ip
        if mac:
            row["mac"] = mac
        if e.hostname:
            row["hostname"] = e.hostname
        vlan = p["vlan"] if p["vlan"] is not None else (e.vlan if len(pairs) == 1 else None)
        if vlan is not None:
            row["vlan"] = int(vlan)
        if e.kind_hint == "dante" or e.dante_name:
            row["protocol"] = "dante"
        up = next((u for u in e.uplinks if u.get("mac") == mac and u.get("port") and u.get("port") != "wifi"), None)
        if up:
            row["_switch_mac"] = up["switch_mac"]  # resolved to a device id by build_connections
            row["_switch_port"] = canonical_port(up["port"])
        if e.seen:
            row["last_seen"] = e.seen
        rows.append(row)
    return rows


# ------------------------------------------------------------------ connections


def build_connections(entities: List[Entity], results: Iterable[ProbeResult], doc: Optional[Doc], device_ids: Dict[str, str]) -> List[Connection]:
    """Switch-port connections. ``device_ids`` maps entity id -> document / proposed device id."""
    by_id, by_mac, by_name = _entity_maps(entities)
    devices = _doc_devices(doc)
    neighbours: List[Neighbour] = []
    for r in results:
        neighbours.extend(r.neighbours)

    def resolve(mac: str, name: str = "") -> Optional[Entity]:
        m = normalize_mac(mac) or ""
        if m and m in by_mac:
            return by_mac[m]
        if name and loose(name) in by_name:
            return by_name[loose(name)]
        return None

    # (switch entity id, canonical port) -> {peer key: {"entity", "mac", "name", "port", "methods", "evidence", "caps", "vlan", "ip"}}
    buckets: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    host_links: List[Neighbour] = []
    for n in neighbours:
        if n.method in ("lldp", "cdp"):  # we heard the announcer: it is the far end of this host's own cable
            host_links.append(n)
            continue
        sw = resolve(n.local_mac, n.local_name)
        if sw is None:
            continue
        port = canonical_port(n.local_port)
        if not port:
            continue
        peer = resolve(n.remote_mac, n.remote_name)
        rmac = normalize_mac(n.remote_mac) or ""
        key = peer.id if peer else ("mac:" + rmac if rmac else "name:" + loose(n.remote_name))
        if key in ("mac:", "name:"):
            continue
        slot = buckets.setdefault((sw.id, port), {}).setdefault(key, {
            "entity": peer, "mac": rmac or (peer.macs[0] if peer and peer.macs else ""), "name": n.remote_name or (peer.label if peer else ""),
            "port": "", "methods": [], "evidence": [], "caps": [], "vlan": None, "ip": "",
        })
        if n.method not in slot["methods"]:
            slot["methods"].append(n.method)
        slot["port"] = slot["port"] or n.remote_port
        slot["ip"] = slot["ip"] or n.remote_ip
        slot["vlan"] = slot["vlan"] if slot["vlan"] is not None else n.vlan
        for c in n.remote_capabilities:
            if c not in slot["caps"]:
                slot["caps"].append(c)
        slot["evidence"].append(dict(n.evidence, source=n.source, method=n.method))

    out: List[Connection] = []
    existing = _existing_cables(doc)
    for (sw_id, port), peers in sorted(buckets.items(), key=lambda kv: (by_id[kv[0][0]].label.lower(), port_index(kv[0][1]) or 0, kv[0][1])):
        sw = by_id[sw_id]
        sw_dev_id = device_ids.get(sw.id, "")
        infra_peers = [p for p in peers.values() if _is_infra(p["entity"], p["caps"]) and any(m in METHOD_WEIGHT for m in p["methods"])]
        uplink = bool(infra_peers)
        distinct = len(peers)
        for key, p in peers.items():
            peer: Optional[Entity] = p["entity"]
            strong = [m for m in p["methods"] if m in METHOD_WEIGHT]
            flag = ""
            if uplink:
                if p in infra_peers:
                    flag = "uplink"
                    conf = max(METHOD_WEIGHT[m] for m in strong)
                    if len({"lldp" if m in ("unifi_lldp", "lldp", "cdp") else m for m in strong}) >= 2:
                        conf = 0.95
                else:
                    flag = "via"
                    conf = 0.30 if not strong else max(METHOD_WEIGHT[m] for m in strong) - 0.3
            elif strong:
                conf = max(METHOD_WEIGHT[m] for m in strong)
                if len({"lldp" if m in ("unifi_lldp", "lldp", "cdp") else m for m in strong}) >= 2:
                    conf = 0.95
                if distinct > 1:
                    conf -= 0.2
                    flag = "unmanaged"
            elif distinct == 1:
                conf = 0.60
            else:
                conf = 0.30
                flag = "unmanaged"
            conf = round(max(0.0, min(1.0, conf)), 2)
            peer_dev_id = device_ids.get(peer.id, "") if peer else ""
            peer_doc = devices.get(peer_dev_id)
            sw_doc = devices.get(sw_dev_id)
            medium = "dante" if (peer is not None and (peer.kind_hint == "dante" or peer.dante_name)) else "network"
            conn = Connection(
                id="conn-" + slug(f"{sw.id}-{port}-{key}")[:100], switch={"entity": sw.id, "device": sw_dev_id, "label": sw.label, "mac": sw.macs[0] if sw.macs else ""},
                port=port, port_index=port_index(port),
                peer={"entity": peer.id if peer else "", "device": peer_dev_id, "label": (peer.label if peer else "") or p["name"] or p["mac"] or key,
                      "mac": p["mac"], "ip": p["ip"] or (peer.ips[0] if peer and peer.ips else ""), "port": p["port"], "kind": peer.kind if peer else ""},
                methods=list(p["methods"]), confidence=conf, level=level_for(conf), flag=flag, medium=medium, vlan=p["vlan"], peers_on_port=distinct, evidence=p["evidence"],
            )
            if flag in ("", "uplink") and conf >= 0.5 and sw_dev_id and peer_dev_id and sw_dev_id != peer_dev_id:
                from_port = doc_port_for(sw_doc, index=conn.port_index) if sw_doc else (f"p{conn.port_index}" if conn.port_index is not None else "")
                to_port = doc_port_for(peer_doc, label=p["port"], index=port_index(p["port"]) if flag == "uplink" else None) if peer_doc else _proposed_peer_port(peer, p["mac"])
                cable: Dict[str, Any] = {"from": {"device": sw_dev_id}, "to": {"device": peer_dev_id}, "medium": medium, "type": "cat6",
                                         "note": "Discovered: %s on %s %s (%s, %.0f%%)" % (conn.peer["label"], sw.label, port, "/".join(p["methods"]), conf * 100)}
                if from_port:
                    cable["from"]["port"] = from_port
                if to_port:
                    cable["to"]["port"] = to_port
                conn.cable = cable
                ends = frozenset([(sw_dev_id, from_port), (peer_dev_id, to_port)])
                loose_ends = frozenset([sw_dev_id, peer_dev_id])
                if ends in existing or (loose_ends in existing and not from_port):
                    conn.status = "exists"
                elif any(frozenset([(sw_dev_id, from_port), (peer_dev_id, port_id)]) in existing for port_id in _doc_port_ids(peer_doc)):
                    conn.status = "exists"
            out.append(conn)

    for n in host_links:  # the far end of the Fathom host's own cable
        far = resolve(n.remote_mac, n.remote_name)
        conf = 0.90
        out.append(Connection(
            id="conn-host-" + slug(f"{n.remote_mac or n.remote_name}-{n.remote_port}")[:90],
            switch={"entity": far.id if far else "", "device": device_ids.get(far.id, "") if far else "", "label": (far.label if far else "") or n.remote_name or n.remote_mac, "mac": normalize_mac(n.remote_mac) or ""},
            port=canonical_port(n.remote_port) or n.remote_port, port_index=port_index(n.remote_port),
            peer={"entity": "", "device": "", "label": "this host (Fathom)", "mac": "", "ip": "", "port": n.local_port, "kind": "computer"},
            methods=[n.method], confidence=conf, level=level_for(conf), flag="host", medium="network", vlan=n.vlan, peers_on_port=1,
            evidence=[dict(n.evidence, source=n.source, method=n.method, description=n.remote_description)],
        ))
    return out


def _proposed_peer_port(peer: Optional[Entity], mac: str) -> str:
    if peer is None:
        return ""
    if peer.ports:
        return ""
    rows = entity_interfaces(peer)
    for i, r in enumerate(rows):
        if r.get("mac") == mac:
            return "net-" + r["role"] if i < 2 else f"net-{i + 1}"
    return "net-" + rows[0]["role"] if rows else "net-1"


def _doc_port_ids(dev: Optional[Dict[str, Any]]) -> List[str]:
    return [str(p.get("id")) for p in (dev or {}).get("ports") or [] if isinstance(p, dict) and p.get("id")]


def _existing_cables(doc: Optional[Doc]) -> set:
    out: set = set()
    for c in (doc or {}).get("cables") or []:
        if not isinstance(c, dict):
            continue
        a, b = c.get("from") or {}, c.get("to") or {}
        if not (isinstance(a, dict) and isinstance(b, dict)):
            continue
        out.add(frozenset([(str(a.get("device", "")), str(a.get("port", ""))), (str(b.get("device", "")), str(b.get("port", "")))]))
        out.add(frozenset([str(a.get("device", "")), str(b.get("device", ""))]))
    return out


# ------------------------------------------------------------------ networks


def build_networks(results: Iterable[ProbeResult], entities: Iterable[Entity], doc: Optional[Doc]) -> List[Dict[str, Any]]:
    """VLAN / subnet findings merged across probes and matched to document networks by VLAN or subnet."""
    merged: Dict[str, Dict[str, Any]] = {}
    for r in results:
        for n in r.networks:
            key = f"vlan:{n.vlan}" if n.vlan is not None else (f"subnet:{n.subnet}" if n.subnet else f"name:{loose(n.name)}")
            cur = merged.setdefault(key, {"id": "net-" + slug(key.replace(":", "-")), "name": n.name, "vlan": n.vlan, "subnet": n.subnet, "gateway": n.gateway,
                                          "purpose": n.purpose, "dhcp_range": n.dhcp_range, "sources": [], "hosts": 0, "evidence": [], "match": None, "status": "new"})
            for k in ("name", "subnet", "gateway", "purpose", "dhcp_range"):
                cur[k] = cur[k] or getattr(n, k)
            if n.source not in cur["sources"]:
                cur["sources"].append(n.source)
            cur["evidence"].append(dict(n.evidence, source=n.source))
    # VLANs we only saw on clients / LLDP frames
    for e in entities:
        if e.vlan is None:
            continue
        key = f"vlan:{e.vlan}"
        cur = merged.setdefault(key, {"id": "net-vlan-%d" % e.vlan, "name": e.network or f"VLAN {e.vlan}", "vlan": e.vlan, "subnet": "", "gateway": "", "purpose": "",
                                      "dhcp_range": "", "sources": [], "hosts": 0, "evidence": [], "match": None, "status": "new"})
        cur["hosts"] += 1
        for s in e.sources:
            if s not in cur["sources"]:
                cur["sources"].append(s)
    doc_nets = [n for n in (doc or {}).get("networks") or [] if isinstance(n, dict)]
    for cur in merged.values():
        hit = None
        for dn in doc_nets:
            if cur["vlan"] is not None and dn.get("vlan") == cur["vlan"]:
                hit = (dn, "VLAN %d" % cur["vlan"])
                break
            if cur["subnet"] and str(dn.get("subnet") or "") == cur["subnet"]:
                hit = (dn, "subnet " + cur["subnet"])
                break
        if hit is not None:
            dn, why = hit
            diffs = [k for k in ("subnet", "gateway") if cur.get(k) and dn.get(k) and str(dn.get(k)) != str(cur.get(k))]
            cur["match"] = {"network": dn.get("id"), "name": dn.get("name"), "reason": why, "differs": diffs}
            cur["status"] = "match"
    out = list(merged.values())
    out.sort(key=lambda n: (n["vlan"] if n["vlan"] is not None else 9999, n["name"]))
    return out


def connection_rows(conns: Iterable[Connection], doc: Optional[Doc], proposed: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cable-schedule-shaped rows (tag, from_room, from_device, from_port, to_room, to_device, to_port, medium, type …)."""
    devices = _doc_devices(doc)

    def room_of(did: str) -> str:
        d = devices.get(did) or proposed.get(did) or {}
        return str(d.get("room") or "")

    def port_label(did: str, pid: str, fallback: str) -> str:
        d = devices.get(did) or proposed.get(did) or {}
        for p in d.get("ports") or []:
            if isinstance(p, dict) and p.get("id") == pid:
                return str(p.get("label") or p.get("name") or pid)
        return fallback

    rows = []
    for c in conns:
        cab = c.cable or {}
        fr, to = cab.get("from") or {}, cab.get("to") or {}
        rows.append({
            "id": c.id, "tag": "", "from_room": room_of(c.switch.get("device", "")), "from_device": c.switch.get("label", ""),
            "from_port": port_label(fr.get("device", ""), fr.get("port", ""), c.port), "to_room": room_of(c.peer.get("device", "")), "to_device": c.peer.get("label", ""),
            "to_port": port_label(to.get("device", ""), to.get("port", ""), c.peer.get("port", "")), "medium": c.medium, "type": cab.get("type", "cat6") if cab else "",
            "length": "", "length_unit": "", "color": "", "channels": "", "signal": "/".join(c.methods), "status": c.status, "bundle": "",
            "note": c.flag or "", "confidence": c.confidence, "level": c.level, "flag": c.flag, "proposed": bool(c.cable), "vlan": c.vlan,
        })
    return rows


__all__ = [
    "Connection", "INFRA_HINTS", "METHOD_WEIGHT", "build_connections", "build_networks", "canonical_port", "connection_rows",
    "doc_port_for", "entity_interfaces", "port_index", "propose_device",
]
