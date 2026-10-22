"""Run-to-run diff: what changed on the network between two discovery runs.

Both sides are *findings* (see :func:`fathom.discovery.compute_findings`),
recomputed against the same live document so a device promoted in between
does not show up as a change. Devices are paired across runs by MAC, then
serial, then Dante name / hostname, then IP (only when neither side has a
MAC); links are keyed by the paired switch, its canonical port and the
paired peer. Nothing here runs on its own: a diff is computed when a run a
person started finishes (and persisted next to it), or on request for any
pair of completed runs.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .correlate import GENERIC_HOSTNAMES, loose
from .topology import canonical_port

Findings = Dict[str, Any]

#: entity fields whose change is reported (label, before, after)
CHANGE_FIELDS: Tuple[Tuple[str, str], ...] = (("ips", "IP"), ("vlan", "VLAN"), ("hostname", "hostname"), ("dante_name", "Dante name"))
# ``name`` is whichever source's label won and changes whenever a better source joins; hostname and Dante name are the identities
#: connection flags that count as a link between two boxes (``via`` rows are derived, not links)
LINK_FLAGS = ("", "uplink", "unmanaged", "host")


def _name_key(value: str) -> str:
    k = loose(value)
    return k if k and len(k) >= 3 and k not in GENERIC_HOSTNAMES else ""


def _locations(e: Dict[str, Any], f: Findings, labels: Dict[str, str]) -> List[Dict[str, Any]]:
    """Where the entity hangs, best evidence first: its direct connections (by confidence), then every reported uplink.

    A controller can only say "behind port 24 of the core" while SNMP on the edge switch says "port 1 of
    sw-stage"; both are true at once, so a move is only reported when neither side's best location appears
    anywhere in the other side's list.
    """
    out: List[Dict[str, Any]] = []
    direct = [c for c in f.get("connections") or [] if (c.get("peer") or {}).get("entity") == e.get("id") and c.get("flag") in ("", "uplink")]
    direct.sort(key=lambda c: -float(c.get("confidence") or 0))
    for c in direct:
        sw = c.get("switch") or {}
        out.append({"switch": sw.get("label") or "", "switch_mac": sw.get("mac") or "", "port": canonical_port(c.get("port") or ""), "port_label": c.get("port") or "",
                    "confidence": c.get("confidence"), "evidence": "link"})
    for up in e.get("uplinks") or []:
        if up.get("port") and up.get("port") != "wifi" and up.get("switch_mac"):
            out.append({"switch": labels.get(up["switch_mac"], up["switch_mac"]), "switch_mac": up["switch_mac"], "port": canonical_port(up["port"]), "port_label": up["port"],
                        "confidence": None, "evidence": "uplink"})
    return out


def _location(e: Dict[str, Any], f: Findings, labels: Dict[str, str]) -> Optional[Dict[str, Any]]:
    locs = _locations(e, f, labels)
    return locs[0] if locs else None


def _loc_key(loc: Dict[str, Any]) -> Tuple[str, str]:
    return (loc.get("switch_mac") or loc.get("switch") or "", loc.get("port") or "")


def _moved(cur_locs: List[Dict[str, Any]], prev_locs: List[Dict[str, Any]]) -> bool:
    if not cur_locs or not prev_locs:
        return False
    cur_keys = {_loc_key(l) for l in cur_locs}
    prev_keys = {_loc_key(l) for l in prev_locs}
    return _loc_key(cur_locs[0]) not in prev_keys and _loc_key(prev_locs[0]) not in cur_keys


def _host_key(value: Any) -> str:
    """First DNS label, loosely: ``bc-switch`` and ``bc-switch.campus.local`` are the same host."""
    return loose(str(value or "").split(".")[0])


def _summary(e: Dict[str, Any], f: Findings, labels: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": e.get("id"), "label": e.get("label") or e.get("name") or e.get("id"), "kind": e.get("kind") or "", "manufacturer": e.get("manufacturer") or "",
        "model": e.get("model") or "", "macs": list(e.get("macs") or []), "ips": list(e.get("ips") or []), "hostname": e.get("hostname") or "", "dante_name": e.get("dante_name") or "",
        "vlan": e.get("vlan"), "sources": list(e.get("sources") or []), "status": e.get("status") or "", "device_id": e.get("device_id") or "", "confidence": e.get("confidence"),
        "level": e.get("level") or "", "location": _location(e, f, labels),
    }


def _labels(f: Findings) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for e in f.get("entities") or []:
        for m in e.get("macs") or []:
            out.setdefault(m, e.get("label") or e.get("id") or m)
    return out


def pair_entities(cur: Iterable[Dict[str, Any]], prev: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """Current entity id -> previous entity id for the same box (MAC, serial, name, then IP for MAC-less hosts)."""
    prev = list(prev)
    by_mac: Dict[str, str] = {}
    by_serial: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    by_ip: Dict[str, str] = {}
    for p in prev:
        pid = str(p.get("id"))
        for m in p.get("macs") or []:
            by_mac.setdefault(m, pid)
        if p.get("serial") and len(str(p["serial"])) >= 4:
            by_serial.setdefault(str(p["serial"]).lower(), pid)
        for n in (p.get("dante_name"), p.get("hostname"), p.get("name")):
            k = _name_key(str(n or ""))
            if k:
                by_name.setdefault(k, pid)
        if not p.get("macs"):
            for ip in p.get("ips") or []:
                by_ip.setdefault(ip, pid)
    taken: set = set()
    pairs: Dict[str, str] = {}
    for strength in ("mac", "serial", "name", "ip"):
        for e in cur:
            eid = str(e.get("id"))
            if eid in pairs:
                continue
            hit = ""
            if strength == "mac":
                # a MAC is identity: several current entities may share one previous one (a box seen as two hosts this time)
                hit = next((by_mac[m] for m in e.get("macs") or [] if m in by_mac), "")
                if hit:
                    pairs[eid] = hit
                    taken.add(hit)
                continue
            elif strength == "serial" and e.get("serial") and len(str(e["serial"])) >= 4:
                hit = by_serial.get(str(e["serial"]).lower(), "")
            elif strength == "name":
                hit = next((by_name[k] for k in (_name_key(str(e.get(n) or "")) for n in ("dante_name", "hostname", "name")) if k and k in by_name), "")
            elif strength == "ip" and not e.get("macs"):
                hit = next((by_ip[ip] for ip in e.get("ips") or [] if ip in by_ip), "")
            if hit and hit not in taken:
                pairs[eid] = hit
                taken.add(hit)
    return pairs


def absorbed_entities(cur: Iterable[Dict[str, Any]], prev: Iterable[Dict[str, Any]], pairs: Dict[str, str]) -> Dict[str, str]:
    """Previous entity id -> current entity id for previous hosts that were folded into a paired current entity by MAC.

    Two previous hosts (primary and secondary Dante interface, say) that one current entity now carries both MACs of
    are the same box, not a missing device.
    """
    matched = set(pairs.values())
    cur_by_mac: Dict[str, str] = {}
    for e in cur:
        for m in e.get("macs") or []:
            cur_by_mac.setdefault(m, str(e.get("id")))
    out: Dict[str, str] = {}
    for p in prev:
        pid = str(p.get("id"))
        if pid in matched:
            continue
        hit = next((cur_by_mac[m] for m in p.get("macs") or [] if m in cur_by_mac), "")
        if hit and hit in pairs:
            out[pid] = hit
    return out


def _link_key(c: Dict[str, Any], ident: Dict[str, str]) -> Tuple[str, str, str]:
    sw, peer = c.get("switch") or {}, c.get("peer") or {}
    return (ident.get(str(sw.get("entity") or ""), "sw:" + str(sw.get("mac") or sw.get("label") or "")), canonical_port(c.get("port") or ""),
            ident.get(str(peer.get("entity") or ""), "peer:" + str(peer.get("mac") or peer.get("label") or "")))


def _link_summary(c: Dict[str, Any]) -> Dict[str, Any]:
    sw, peer = c.get("switch") or {}, c.get("peer") or {}
    return {"id": c.get("id"), "switch": sw.get("label") or "", "switch_mac": sw.get("mac") or "", "port": c.get("port") or "", "peer": peer.get("label") or "",
            "peer_mac": peer.get("mac") or "", "peer_port": peer.get("port") or "", "methods": list(c.get("methods") or []), "confidence": c.get("confidence"),
            "level": c.get("level") or "", "flag": c.get("flag") or "", "status": c.get("status") or "", "medium": c.get("medium") or "network", "vlan": c.get("vlan")}


def compute_diff(cur: Findings, prev: Findings, cur_id: str = "", prev_id: str = "") -> Dict[str, Any]:
    """Differences from ``prev`` to ``cur``: new / missing devices, moved ports, changed addresses, new / lost links."""
    from ..history import utc_now

    cur_ents = [e for e in cur.get("entities") or [] if e.get("status") != "ignored"]
    prev_ents = [e for e in prev.get("entities") or [] if e.get("status") != "ignored"]
    pairs = pair_entities(cur_ents, prev_ents)
    absorbed = absorbed_entities(cur_ents, prev_ents, pairs)
    absorbing: Dict[str, List[str]] = {}
    for pid, eid in absorbed.items():
        absorbing.setdefault(eid, []).append(pid)
    split_prev = {pid for pid in set(pairs.values()) if sum(1 for v in pairs.values() if v == pid) > 1}
    cur_labels, prev_labels = _labels(cur), _labels(prev)
    prev_by_id = {str(p.get("id")): p for p in prev_ents}
    out: Dict[str, Any] = {"run": cur_id, "against": prev_id, "computed": utc_now(), "new_devices": [], "missing_devices": [], "moved": [], "changed": [], "new_links": [], "lost_links": []}
    unchanged = 0
    for e in cur_ents:
        eid = str(e.get("id"))
        pid = pairs.get(eid)
        if not pid:
            out["new_devices"].append(_summary(e, cur, cur_labels))
            continue
        p = prev_by_id[pid]
        s_cur = _summary(e, cur, cur_labels)
        touched = False
        cur_locs, prev_locs = _locations(e, cur, cur_labels), _locations(p, prev, prev_labels)
        for other in absorbing.get(eid, []):
            prev_locs.extend(_locations(prev_by_id[other], prev, prev_labels))
        if _moved(cur_locs, prev_locs):
            out["moved"].append({"id": e.get("id"), "label": s_cur["label"], "kind": s_cur["kind"], "macs": s_cur["macs"], "from": prev_locs[0], "to": cur_locs[0], "previous_id": pid})
            touched = True
        if pid in split_prev or eid in absorbing:
            fields: Tuple[Tuple[str, str], ...] = ()  # one box seen as a different number of hosts: addresses are not comparable one-to-one
        else:
            fields = CHANGE_FIELDS
        for key, label in fields:
            a, b = p.get(key), e.get(key)
            if key == "ips":
                a, b = sorted(a or []), sorted(b or [])
                if a == b or not a or not b:
                    continue  # a host seen without an address this time is not a change of address
            elif key == "hostname":
                if _host_key(a) == _host_key(b) or not a or not b:
                    continue
            elif key == "dante_name":
                if loose(str(a or "")) == loose(str(b or "")) or not a or not b:
                    continue
            elif a == b or a is None or b is None:
                continue
            out["changed"].append({"id": e.get("id"), "label": s_cur["label"], "field": key, "field_label": label, "before": a, "after": b, "previous_id": pid})
            touched = True
        if not touched:
            unchanged += 1
    matched_prev = set(pairs.values()) | set(absorbed)
    for p in prev_ents:
        if str(p.get("id")) not in matched_prev:
            out["missing_devices"].append(_summary(p, prev, prev_labels))
    # links: both sides are keyed by the *previous* identity of each box -----------------------
    ident_cur = {str(e.get("id")): pairs.get(str(e.get("id")), "cur:" + str(e.get("id"))) for e in cur_ents}
    ident_prev = {str(p.get("id")): pairs.get(absorbed.get(str(p.get("id")), ""), str(p.get("id"))) for p in prev_ents}
    cur_links = {_link_key(c, ident_cur): c for c in cur.get("connections") or [] if c.get("flag", "") in LINK_FLAGS and c.get("status") != "ignored"}
    prev_links = {_link_key(c, ident_prev): c for c in prev.get("connections") or [] if c.get("flag", "") in LINK_FLAGS and c.get("status") != "ignored"}
    # a peer that was "on port 24" (several MACs, unmanaged) and is now reached *via* an uplink on port 24 is the same
    # observation reclassified by better evidence, so via rows count as present when deciding what is new or lost
    cur_seen = cur_links.keys() | {_link_key(c, ident_cur) for c in cur.get("connections") or [] if c.get("flag") == "via"}
    prev_seen = prev_links.keys() | {_link_key(c, ident_prev) for c in prev.get("connections") or [] if c.get("flag") == "via"}
    for k, c in cur_links.items():
        if k not in prev_seen:
            out["new_links"].append(_link_summary(c))
    for k, c in prev_links.items():
        if k not in cur_seen:
            out["lost_links"].append(_link_summary(c))
    out["new_links"].sort(key=lambda l: (l["switch"], l["port"], l["peer"]))
    out["lost_links"].sort(key=lambda l: (l["switch"], l["port"], l["peer"]))
    out["counts"] = {
        "new_devices": len(out["new_devices"]), "missing_devices": len(out["missing_devices"]), "moved": len(out["moved"]), "changed": len(out["changed"]),
        "new_links": len(out["new_links"]), "lost_links": len(out["lost_links"]), "unchanged": unchanged, "paired": len(pairs),
        "entities": len(cur_ents), "previous_entities": len(prev_ents), "links": len(cur_links), "previous_links": len(prev_links),
    }
    out["counts"]["changes"] = sum(out["counts"][k] for k in ("new_devices", "missing_devices", "moved", "changed", "new_links", "lost_links"))
    return out


def empty_diff(cur_id: str = "", cur: Optional[Findings] = None) -> Dict[str, Any]:
    """The diff of a run that has nothing to be compared with (``against`` is None, every change count is 0)."""
    from ..history import utc_now

    ents = [e for e in (cur or {}).get("entities") or [] if e.get("status") != "ignored"]
    links = [c for c in (cur or {}).get("connections") or [] if c.get("flag", "") in LINK_FLAGS and c.get("status") != "ignored"]
    return {"run": cur_id, "against": None, "computed": utc_now(), "new_devices": [], "missing_devices": [], "moved": [], "changed": [], "new_links": [], "lost_links": [],
            "counts": {"new_devices": 0, "missing_devices": 0, "moved": 0, "changed": 0, "new_links": 0, "lost_links": 0, "unchanged": 0, "paired": 0, "entities": len(ents),
                       "previous_entities": 0, "links": len(links), "previous_links": 0, "changes": 0}}


__all__ = ["CHANGE_FIELDS", "LINK_FLAGS", "absorbed_entities", "compute_diff", "empty_diff", "pair_entities"]
