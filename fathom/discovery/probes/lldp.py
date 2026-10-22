"""LLDP / CDP frame sniff for the run window (passive, listen only).

Opens a raw packet socket (Linux ``AF_PACKET``) and keeps the LLDP
(``01:80:c2:00:00:0e`` / EtherType 0x88CC) and CDP (``01:00:0c:cc:cc:cc`` via
SNAP) frames it hears. Switches send these every 30 s on each port, so the
run window should be at least 60 s. Bridges do not forward LLDP, so on a
normal access port this yields the switch the Fathom host is plugged into
(chassis, system name, management IP, model, and the port) plus any device on
a shared segment (hub, mirrored port). Needs ``CAP_NET_RAW``; without it the
probe reports *skipped* with a note instead of failing the run. Nothing is
ever transmitted.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

from ...network import normalize_mac
from . import PASSIVE, Neighbour, Observation, ProbeInfo, ProbeResult, fixture_delay, fixture_payload

INFO = ProbeInfo(
    id="lldp", label="LLDP / CDP sniff", mode=PASSIVE, maturity="experimental",
    help="Listens for LLDP and CDP announcements for the run window: switch chassis, system name, management IP, model and the port this host is on; AV devices that announce themselves on a shared segment.",
    sends="Nothing. Raw-socket listen only (needs CAP_NET_RAW: AmbientCapabilities in the systemd unit, or setcap on the venv's python; on ESXi the port group needs Promiscuous Mode = Accept).",
    needs=["net_raw", "linux"],
    fields=[
        {"key": "interface", "label": "Interface", "placeholder": "all (eth0, enp3s0 …)", "env": "FATHOM_DISCOVERY_INTERFACE"},
    ],
)

LLDP_DST = "01:80:c2:00:00:0e"
LLDP_DST_ALT = ("01:80:c2:00:00:03", "01:80:c2:00:00:00")
CDP_DST = "01:00:0c:cc:cc:cc"
ETH_P_ALL = 0x0003
ETH_P_LLDP = 0x88CC
LLDP_CAPS = [(1, "other"), (2, "repeater"), (4, "bridge"), (8, "wlan_ap"), (16, "router"), (32, "telephone"), (64, "docsis"), (128, "station")]
CDP_CAPS = [(0x01, "router"), (0x02, "bridge"), (0x04, "bridge"), (0x08, "switch"), (0x10, "host"), (0x20, "igmp"), (0x40, "repeater")]
MED_INVENTORY = {5: "hardware_rev", 6: "firmware", 7: "software", 8: "serial", 9: "manufacturer", 10: "model", 11: "asset_id"}


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def capability() -> Tuple[bool, str]:
    """Can this process open a packet socket? (No packet is sent.)"""
    if not hasattr(socket, "AF_PACKET"):
        return False, "raw packet sockets are only available on Linux"
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))  # type: ignore[attr-defined]
    except PermissionError:
        return False, "no CAP_NET_RAW: add AmbientCapabilities=CAP_NET_RAW to the systemd unit, or `setcap cap_net_raw,cap_net_bind_service+eip` on the venv's python (run `fathom discovery doctor`)"
    except OSError as exc:
        return False, f"cannot open a packet socket: {exc}"
    s.close()
    return True, "packet socket available"


def collect(settings: Dict[str, Any], job: Any = None, window: float = 60.0) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        if job is not None:
            job.wait(fixture_delay(window))
        return fx
    out: Dict[str, Any] = {"window": window, "interface": str((settings or {}).get("interface") or ""), "frames": [], "notes": [],
                           "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ok, why = capability()
    if not ok:
        out["status"] = "skipped"
        out["notes"].append(why)
        return out
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))  # type: ignore[attr-defined]
    try:
        if out["interface"]:
            s.bind((out["interface"], 0))
        s.settimeout(0.5)
        started = time.time()
        deadline = started + max(5.0, float(window))
        seen: Dict[Tuple[str, str], int] = {}
        while time.time() < deadline:
            if job is not None and job.cancelled:
                break
            try:
                frame, addr = s.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                out["notes"].append(f"receive error: {exc}")
                break
            if len(frame) < 14:
                continue
            dst = _mac(frame[0:6])
            if dst != LLDP_DST and dst != CDP_DST and dst not in LLDP_DST_ALT:
                continue
            key = (_mac(frame[6:12]), dst)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                out["frames"].append({"hex": frame.hex(), "t": round(time.time() - started, 1), "iface": addr[0] if isinstance(addr, tuple) and addr else ""})
            if job is not None:
                job.set_progress(stage=f"lldp: {len(out['frames'])} announcers heard, {int(deadline - time.time())} s left")
        out["counts"] = {f"{k[0]}>{k[1]}": v for k, v in seen.items()}
    finally:
        s.close()
    return out


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return {"ok": True, "message": f"fixture replay: {len(fx.get('frames') or [])} frames", "fixture": True}
    ok, why = capability()
    iface = str((settings or {}).get("interface") or "")
    try:
        from .. import doctor

        itfs = [i for i in doctor.interfaces() if i["kind"] in ("physical", "vlan") and i.get("up")]
    except Exception:
        itfs = []
    desc = ", ".join(i["name"] + (f" (VLAN {i['vlan']})" if i.get("vlan") is not None else "") for i in itfs) or "no interface found"
    hint = "" if len(itfs) > 1 else "; one interface only: mDNS sees just its VLAN, add a NIC or 8021q sub-interface per audio VLAN"
    msg = f"{why}; will listen on {iface or 'all interfaces'} for the run window. Interfaces: {desc}{hint}. `fathom discovery doctor` checks for foreign LLDP frames." if ok else f"{why}. Interfaces: {desc}."
    return {"ok": ok, "message": msg, "capability": ok, "interfaces": itfs}


# ------------------------------------------------------------------ parse


def _lldp_tlvs(payload: bytes) -> List[Tuple[int, bytes]]:
    out: List[Tuple[int, bytes]] = []
    i = 0
    while i + 2 <= len(payload):
        hdr = struct.unpack("!H", payload[i:i + 2])[0]
        t, ln = hdr >> 9, hdr & 0x1FF
        i += 2
        val = payload[i:i + ln]
        i += ln
        out.append((t, val))
        if t == 0:
            break
    return out


def _text(b: bytes) -> str:
    return b.decode("utf-8", "replace").strip("\x00 \r\n")


def parse_lldp(frame: bytes) -> Dict[str, Any]:
    """Decode one LLDP frame (Ethernet header included) into a flat dict."""
    src = _mac(frame[6:12])
    body = frame[14:]
    if struct.unpack("!H", frame[12:14])[0] == 0x8100 and len(frame) >= 18:  # VLAN tagged
        body = frame[18:]
    info: Dict[str, Any] = {"src": src, "kind": "lldp", "chassis_id": "", "chassis_mac": "", "port_id": "", "port_description": "", "system_name": "",
                            "system_description": "", "capabilities": [], "enabled_capabilities": [], "mgmt_ip": "", "ttl": None, "vlan": None, "inventory": {}}
    for t, v in _lldp_tlvs(body):
        if t == 1 and v:
            sub = v[0]
            if sub == 4 and len(v) >= 7:
                info["chassis_mac"] = _mac(v[1:7])
                info["chassis_id"] = info["chassis_mac"]
            elif sub == 5 and len(v) >= 6 and v[1] == 1:
                info["chassis_id"] = ".".join(str(x) for x in v[2:6])
            else:
                info["chassis_id"] = _text(v[1:])
        elif t == 2 and v:
            sub = v[0]
            if sub == 3 and len(v) >= 7:
                info["port_id"] = _mac(v[1:7])
            else:
                info["port_id"] = _text(v[1:])
        elif t == 3 and len(v) >= 2:
            info["ttl"] = struct.unpack("!H", v[:2])[0]
        elif t == 4:
            info["port_description"] = _text(v)
        elif t == 5:
            info["system_name"] = _text(v)
        elif t == 6:
            info["system_description"] = _text(v)
        elif t == 7 and len(v) >= 4:
            caps, en = struct.unpack("!HH", v[:4])
            info["capabilities"] = [n for bit, n in LLDP_CAPS if caps & bit]
            info["enabled_capabilities"] = [n for bit, n in LLDP_CAPS if en & bit]
        elif t == 8 and len(v) >= 2:
            alen = v[0]
            if alen >= 5 and v[1] == 1 and len(v) >= 1 + alen:
                info["mgmt_ip"] = ".".join(str(x) for x in v[2:6])
            elif alen >= 17 and v[1] == 2 and len(v) >= 1 + alen:
                import ipaddress

                try:
                    info.setdefault("mgmt_ip6", str(ipaddress.IPv6Address(bytes(v[2:18]))))
                except ValueError:
                    pass
        elif t == 127 and len(v) >= 4:
            oui, sub = v[:3], v[3]
            data = v[4:]
            if oui == b"\x00\x80\xc2" and sub == 1 and len(data) >= 2:
                info["vlan"] = struct.unpack("!H", data[:2])[0]
            elif oui == b"\x00\x12\xbb" and sub in MED_INVENTORY:
                info["inventory"][MED_INVENTORY[sub]] = _text(data)
            elif oui == b"\x00\x12\xbb" and sub == 1 and len(data) >= 3:
                info["med_device_type"] = data[2]
    return info


def parse_cdp(frame: bytes) -> Optional[Dict[str, Any]]:
    src = _mac(frame[6:12])
    i = 14
    if len(frame) >= 22 and frame[14:17] == b"\xaa\xaa\x03":
        i = 22  # LLC (3) + SNAP OUI (3) + PID (2)
    if len(frame) < i + 4:
        return None
    info: Dict[str, Any] = {"src": src, "kind": "cdp", "device_id": "", "port_id": "", "platform": "", "software": "", "addresses": [], "capabilities": [], "vlan": None, "ttl": frame[i + 1]}
    i += 4
    while i + 4 <= len(frame):
        t, ln = struct.unpack("!HH", frame[i:i + 4])
        if ln < 4:
            break
        v = frame[i + 4:i + ln]
        i += ln
        if t == 0x0001:
            info["device_id"] = _text(v)
        elif t == 0x0003:
            info["port_id"] = _text(v)
        elif t == 0x0005:
            info["software"] = _text(v).splitlines()[0] if _text(v) else ""
        elif t == 0x0006:
            info["platform"] = _text(v)
        elif t == 0x000A and len(v) >= 2:
            info["vlan"] = struct.unpack("!H", v[:2])[0]
        elif t == 0x0004 and len(v) >= 4:
            caps = struct.unpack("!I", v[:4])[0]
            info["capabilities"] = sorted({n for bit, n in CDP_CAPS if caps & bit})
        elif t in (0x0002, 0x0016) and len(v) >= 4:
            n = struct.unpack("!I", v[:4])[0]
            j = 4
            for _ in range(n):
                if j + 2 > len(v):
                    break
                ptype, plen = v[j], v[j + 1]
                proto = v[j + 2:j + 2 + plen]
                j += 2 + plen
                if j + 2 > len(v):
                    break
                alen = struct.unpack("!H", v[j:j + 2])[0]
                addr = v[j + 2:j + 2 + alen]
                j += 2 + alen
                if ptype == 1 and proto == b"\xcc" and alen == 4:
                    info["addresses"].append(".".join(str(x) for x in addr))
    return info


def _kind_from_caps(caps: List[str], descr: str = "") -> str:
    low = " ".join(caps).lower()
    d = (descr or "").lower()
    if "wlan_ap" in low:
        return "ap"
    if "switch" in low or "bridge" in low:
        return "switch"
    if "router" in low:
        return "gateway"
    if "telephone" in low:
        return "other"
    if "dante" in d or "brooklyn" in d or "ultimo" in d:
        return "dante"
    return "client" if ("station" in low or "host" in low) else "network"


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("lldp: payload is not an object")
        return res
    if raw.get("status") == "skipped":
        res.status = "skipped"
    for n in raw.get("notes") or []:
        res.notes.append(f"lldp: {n}")
    seen = str(raw.get("fetched") or "")
    n_lldp = n_cdp = 0
    for f in raw.get("frames") or []:
        if not isinstance(f, dict) or not f.get("hex"):
            continue
        try:
            frame = bytes.fromhex(str(f["hex"]).replace(" ", "").replace(":", ""))
        except ValueError:
            continue
        if len(frame) < 14:
            continue
        dst = _mac(frame[0:6])
        etype = struct.unpack("!H", frame[12:14])[0]
        if etype == 0x8100 and len(frame) >= 18:
            etype = struct.unpack("!H", frame[16:18])[0]
        if etype == ETH_P_LLDP or dst == LLDP_DST:
            info = parse_lldp(frame)
            n_lldp += 1
            mac = info["chassis_mac"] or (info["port_id"] if normalize_mac(info["port_id"]) else "") or info["src"]
            name = info["system_name"]
            inv = info.get("inventory") or {}
            kind = _kind_from_caps(info["enabled_capabilities"] or info["capabilities"], info["system_description"])
            res.observations.append(Observation(
                source="lldp", mac=mac, ip=info["mgmt_ip"], name=name, hostname=name, kind_hint=kind, seen=seen,
                manufacturer=inv.get("manufacturer", ""), model=inv.get("model", "") or _model_from_descr(info["system_description"]),
                serial=inv.get("serial", ""), firmware=inv.get("firmware", "") or inv.get("software", ""), vlan=info["vlan"],
                extra_macs=[info["src"]] if info["src"] != mac else [],
                evidence={"chassis_id": info["chassis_id"], "port_id": info["port_id"], "port_description": info["port_description"],
                          "system_description": info["system_description"], "capabilities": info["capabilities"], "ttl": info["ttl"], "heard_at": f.get("t"), "iface": f.get("iface")},
            ))
            res.neighbours.append(Neighbour(
                source="lldp", method="lldp", local_mac="", local_name="this host", local_port=str(f.get("iface") or raw.get("interface") or ""),
                remote_mac=mac, remote_name=name, remote_port=info["port_description"] or info["port_id"], remote_ip=info["mgmt_ip"],
                remote_description=info["system_description"], remote_capabilities=info["enabled_capabilities"] or info["capabilities"], vlan=info["vlan"],
                evidence={"port_id": info["port_id"], "ttl": info["ttl"]},
            ))
        elif dst == CDP_DST:
            info = parse_cdp(frame)
            if info is None:
                continue
            n_cdp += 1
            kind = _kind_from_caps(info["capabilities"], info["platform"])
            res.observations.append(Observation(
                source="lldp", mac=info["src"], ip=info["addresses"][0] if info["addresses"] else "", name=info["device_id"], hostname=info["device_id"].split(".")[0],
                kind_hint=kind, manufacturer="Cisco" if "cisco" in info["platform"].lower() else "", model=info["platform"].replace("cisco ", "").replace("Cisco ", ""),
                firmware=info["software"], vlan=info["vlan"], seen=seen,
                evidence={"port_id": info["port_id"], "platform": info["platform"], "capabilities": info["capabilities"], "ttl": info["ttl"], "heard_at": f.get("t"), "iface": f.get("iface"), "protocol": "cdp"},
            ))
            res.neighbours.append(Neighbour(
                source="lldp", method="cdp", local_mac="", local_name="this host", local_port=str(f.get("iface") or raw.get("interface") or ""),
                remote_mac=info["src"], remote_name=info["device_id"], remote_port=info["port_id"], remote_ip=info["addresses"][0] if info["addresses"] else "",
                remote_description=info["platform"], remote_capabilities=info["capabilities"], vlan=info["vlan"], evidence={"ttl": info["ttl"]},
            ))
    res.stats = {"frames": len(raw.get("frames") or []), "lldp": n_lldp, "cdp": n_cdp, "interface": raw.get("interface") or "all"}
    if res.status == "ok" and not raw.get("frames"):
        res.notes.append("lldp: no LLDP / CDP frames heard in the window (switch LLDP off, or the window was shorter than the announce interval of 30 s)")
    return res


def _model_from_descr(descr: str) -> str:
    d = (descr or "").strip()
    if not d:
        return ""
    head = d.split(",")[0].split(" running ")[0].split(" Version")[0].strip()
    return head[:60]


__all__ = ["CDP_DST", "INFO", "LLDP_DST", "capability", "collect", "parse", "parse_cdp", "parse_lldp", "test"]
