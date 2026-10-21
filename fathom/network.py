"""IP / network schedule and checks (FR-NET).

Manual interfaces (``device.interfaces``) plus overlay interfaces from imports
(Dante preset addresses, Dante Device Info paste); manual wins on the same
device + role. Problems follow the §4.7 shape.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]
Problem = Dict[str, Any]

IP_COLUMNS: List[Tuple[str, str]] = [
    ("room", "Room"), ("device", "Device"), ("interface", "Interface"), ("role", "Role"), ("ip", "IP"), ("prefix", "Prefix"),
    ("gateway", "Gateway"), ("vlan", "VLAN"), ("network", "Network"), ("mac", "MAC"), ("hostname", "Hostname"),
    ("switch", "Switch"), ("switch_port", "Switch port"), ("protocol", "Protocol"), ("dhcp", "DHCP"), ("source", "Source"), ("note", "Note"),
]

_HEX12 = re.compile(r"^[0-9a-f]{12}$")


def normalize_mac(text: str) -> Optional[str]:
    """``AABB.CCDD.EEFF`` / ``aa-bb-…`` / ``aa:bb:…`` / bare hex → ``aa:bb:cc:dd:ee:ff``; else None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.match(r"^[0-9a-f]{1,2}([:-])[0-9a-f]{1,2}(\1[0-9a-f]{1,2}){4}$", t):
        parts = re.split(r"[:-]", t)
        h = "".join(p.zfill(2) for p in parts)
    elif re.match(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$", t):
        h = t.replace(".", "")
    else:
        h = t
    if not _HEX12.match(h):
        return None
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


def _ip(text: Any) -> Optional[ipaddress.IPv4Address]:
    try:
        a = ipaddress.ip_address(str(text).strip())
        return a if isinstance(a, ipaddress.IPv4Address) else None  # type: ignore[return-value]
    except ValueError:
        return None


def _ip_any(text: Any) -> Optional[Any]:
    try:
        return ipaddress.ip_address(str(text).strip())
    except ValueError:
        return None


def _net(text: Any) -> Optional[Any]:
    try:
        return ipaddress.ip_network(str(text).strip(), strict=False)
    except ValueError:
        return None


def _prob(level: str, code: str, ref: str, path: str, message: str) -> Problem:
    return {"level": level, "code": code, "ref": ref, "path": path, "message": message}


def network_problems(doc: Doc) -> List[Problem]:
    """bad_ip, bad_subnet, bad_mac, ip_duplicate, ip_outside_subnet, vlan_mismatch (all warnings)."""
    out: List[Problem] = []
    nets: Dict[str, Dict[str, Any]] = {}
    for n in doc.get("networks") or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", ""))
        nets[nid] = n
        if n.get("subnet") and _net(n["subnet"]) is None:
            out.append(_prob("warning", "bad_subnet", f"networks/{nid}", f"networks/{nid}/subnet", f"{n.get('name', nid)}: '{n['subnet']}' is not a valid subnet (CIDR)"))
        if n.get("gateway") and _ip_any(n["gateway"]) is None:
            out.append(_prob("warning", "bad_ip", f"networks/{nid}", f"networks/{nid}/gateway", f"{n.get('name', nid)}: gateway '{n['gateway']}' is not a valid IP"))
    seen: Dict[Tuple[str, str], str] = {}
    for d in doc.get("devices") or []:
        if not isinstance(d, dict):
            continue
        did = str(d.get("id", ""))
        for i, iface in enumerate(d.get("interfaces") or []):
            if not isinstance(iface, dict):
                continue
            ref, base = f"devices/{did}", f"devices/{did}/interfaces/{i}"
            label = f"{d.get('name', did)} · {iface.get('id', i)}"
            ip = None
            if iface.get("ip"):
                ip = _ip_any(iface["ip"])
                if ip is None:
                    out.append(_prob("warning", "bad_ip", ref, base + "/ip", f"{label}: '{iface['ip']}' is not a valid IP"))
            if iface.get("gateway") and _ip_any(iface["gateway"]) is None:
                out.append(_prob("warning", "bad_ip", ref, base + "/gateway", f"{label}: gateway '{iface['gateway']}' is not a valid IP"))
            if iface.get("mac") and normalize_mac(str(iface["mac"])) is None:
                out.append(_prob("warning", "bad_mac", ref, base + "/mac", f"{label}: '{iface['mac']}' is not a MAC address"))
            net = nets.get(str(iface.get("network") or ""))
            if ip is not None:
                key = (str(iface.get("network") or ""), str(ip))
                if key in seen:
                    out.append(_prob("warning", "ip_duplicate", ref, base + "/ip", f"{label}: {ip} is also used by {seen[key]}"))
                else:
                    seen[key] = label
                if net and net.get("subnet"):
                    sn = _net(net["subnet"])
                    if sn is not None and ip.version == sn.version and ip not in sn:
                        out.append(_prob("warning", "ip_outside_subnet", ref, base + "/ip", f"{label}: {ip} is outside {net.get('name', '')} {sn}"))
            if net and iface.get("vlan") not in (None, "") and net.get("vlan") not in (None, "") and str(iface["vlan"]) != str(net["vlan"]):
                out.append(_prob("warning", "vlan_mismatch", ref, base + "/vlan", f"{label}: VLAN {iface['vlan']} but {net.get('name', '')} is VLAN {net['vlan']}"))
    return out


def ip_schedule(doc: Doc, overlay: Optional[Dict[str, Any]] = None, room: str = "*") -> Dict[str, Any]:
    devices = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
    for d in (overlay or {}).get("devices") or []:
        devices.setdefault(d.get("id"), d)
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    nets = {n.get("id"): n for n in doc.get("networks") or [] if isinstance(n, dict)}
    rows: List[Dict[str, Any]] = []
    have: set = set()

    def port_name(dev_id: str, pid: str) -> str:
        for p in (devices.get(dev_id) or {}).get("ports") or []:
            if p.get("id") == pid:
                return str(p.get("name") or pid)
        return pid

    def add(dev: Dict[str, Any], iface: Dict[str, Any], source: str) -> None:
        did = dev.get("id")
        droom = dev.get("room", "")
        if room not in ("*", None) and droom != room:
            return
        role = iface.get("role") or "primary"
        if (did, role) in have and source != "manual":
            return
        have.add((did, role))
        net = nets.get(iface.get("network") or "") or {}
        prefix = iface.get("prefix")
        if prefix in (None, "") and net.get("subnet") and _net(net["subnet"]) is not None:
            prefix = _net(net["subnet"]).prefixlen
        sw = iface.get("switch") or ""
        mac = iface.get("mac") or ""
        rows.append({
            "room": (rooms.get(droom) or {}).get("name", droom), "room_id": droom,
            "device": dev.get("name", did), "device_id": did, "interface": iface.get("id", ""), "role": role,
            "ip": iface.get("ip", ""), "prefix": "" if prefix is None else prefix,
            "gateway": iface.get("gateway") or net.get("gateway", ""),
            "vlan": iface.get("vlan") if iface.get("vlan") not in (None, "") else net.get("vlan", ""),
            "network": net.get("name", iface.get("network", "")), "network_id": iface.get("network", ""),
            "mac": (normalize_mac(mac) or mac) if mac else "", "hostname": iface.get("hostname", ""),
            "switch": (devices.get(sw) or {}).get("name", sw), "switch_id": sw,
            "switch_port": port_name(sw, iface.get("switch_port", "")) if sw in devices else iface.get("switch_port", ""),
            "switch_port_id": iface.get("switch_port", ""),
            "protocol": iface.get("protocol") or net.get("protocol", ""),
            "dhcp": "yes" if iface.get("dhcp") else "", "source": source, "note": iface.get("note", ""),
        })

    for dev in doc.get("devices") or []:
        if isinstance(dev, dict):
            for iface in dev.get("interfaces") or []:
                if isinstance(iface, dict):
                    add(dev, iface, "manual")
    for did, ifs in sorted(((overlay or {}).get("interfaces") or {}).items()):
        dev = devices.get(did)
        if dev is None:
            continue
        for iface in ifs:
            add(dev, iface, str(iface.get("source") or "import"))

    def key(r: Dict[str, Any]) -> Tuple[Any, ...]:
        ip = _ip(r["ip"])
        return (0 if ip is not None else 1, int(ip) if ip is not None else 0, str(r["device"]).lower(), str(r["interface"]))

    rows.sort(key=key)
    return {"kind": "ip", "columns": [{"key": k, "label": lab} for k, lab in IP_COLUMNS], "rows": rows, "problems": network_problems(doc)}


__all__ = ["normalize_mac", "ip_schedule", "network_problems", "IP_COLUMNS"]
