"""``fathom discovery doctor``: can this host see the AV network?

Reports, without touching any device:

- whether the process holds ``CAP_NET_RAW`` (LLDP / CDP listener) and
  ``CAP_NET_BIND_SERVICE`` (port 80 / 443 without root), and whether a packet
  socket actually opens,
- the network interfaces with their MAC, addresses, 802.1Q VLAN id (for
  ``eth0.30``-style sub-interfaces), link state and promiscuous flag,
- optionally, a 35 s listen: how many LLDP / CDP announcers were heard and
  whether any came from another host (a *foreign* frame proves that the
  hypervisor port group forwards frames not addressed to this VM, i.e.
  Promiscuous Mode is Accept on ESXi).

Everything here is Linux-specific and degrades to "unknown" elsewhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CAP_NET_BIND_SERVICE = 10
CAP_NET_RAW = 13
DEFAULT_LISTEN = 35
_SYS_NET = Path("/sys/class/net")
_VLAN_CONFIG = Path("/proc/net/vlan/config")
IFF_UP = 0x1
IFF_PROMISC = 0x100


# ------------------------------------------------------------------ capabilities


def _cap_sets() -> Dict[str, int]:
    out: Dict[str, int] = {}
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("Cap") and ":" in line:
                k, v = line.split(":", 1)
                try:
                    out[k.strip()] = int(v.strip(), 16)
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def capabilities() -> Dict[str, Any]:
    """Effective capabilities of this process plus a real packet-socket attempt."""
    from .probes import lldp

    caps = _cap_sets()
    eff = caps.get("CapEff", 0)
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    sock_ok, sock_msg = lldp.capability()
    return {
        "user": os.environ.get("USER") or os.environ.get("LOGNAME") or (str(os.geteuid()) if hasattr(os, "geteuid") else ""),
        "root": bool(root),
        "cap_net_raw": bool(eff >> CAP_NET_RAW & 1) or bool(root),
        "cap_net_bind_service": bool(eff >> CAP_NET_BIND_SERVICE & 1) or bool(root),
        "ambient": {"cap_net_raw": bool(caps.get("CapAmb", 0) >> CAP_NET_RAW & 1), "cap_net_bind_service": bool(caps.get("CapAmb", 0) >> CAP_NET_BIND_SERVICE & 1)},
        "packet_socket": sock_ok, "packet_socket_message": sock_msg,
        "python": sys.executable,
        "known": bool(caps),
    }


# ------------------------------------------------------------------ interfaces


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _vlan_map() -> Dict[str, Dict[str, Any]]:
    """``{sub-interface: {"vlan": id, "parent": name}}`` from /proc/net/vlan/config (8021q module)."""
    out: Dict[str, Dict[str, Any]] = {}
    for line in _read(_VLAN_CONFIG).splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) == 3 and parts[1].isdigit():
            out[parts[0]] = {"vlan": int(parts[1]), "parent": parts[2]}
    return out


def _addresses() -> Dict[str, List[str]]:
    """Interface -> IPv4 addresses with prefix, via ``ip -j addr`` when present."""
    ip = shutil.which("ip")
    out: Dict[str, List[str]] = {}
    if not ip:
        return _addresses_ioctl()
    try:
        res = subprocess.run([ip, "-j", "-4", "addr", "show"], capture_output=True, text=True, timeout=5, check=False)
        if res.returncode == 0 and res.stdout.strip().startswith("["):
            for itf in json.loads(res.stdout):
                name = str(itf.get("ifname") or "")
                for a in itf.get("addr_info") or []:
                    if a.get("family") == "inet" and a.get("local"):
                        out.setdefault(name, []).append(f"{a['local']}/{a.get('prefixlen', '')}".rstrip("/"))
            return out
        res = subprocess.run([ip, "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5, check=False)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "inet":
                out.setdefault(parts[1].split("@")[0], []).append(parts[3])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return out


def _addresses_ioctl() -> Dict[str, List[str]]:
    """SIOCGIFADDR / SIOCGIFNETMASK per interface (no iproute2 on the box)."""
    out: Dict[str, List[str]] = {}
    try:
        import fcntl
        import socket
        import struct
    except ImportError:
        return out
    if not _SYS_NET.is_dir():
        return out
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for p in _SYS_NET.iterdir():
            name = p.name.encode()[:15]
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name))[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x891B, struct.pack("256s", name))[20:24])
            except OSError:
                continue
            prefix = sum(bin(int(x)).count("1") for x in mask.split("."))
            out.setdefault(p.name, []).append(f"{addr}/{prefix}")
    finally:
        s.close()
    return out


def interfaces() -> List[Dict[str, Any]]:
    """Network interfaces of this host (loopback and docker bridges last)."""
    if not _SYS_NET.is_dir():
        return []
    vlans = _vlan_map()
    addrs = _addresses()
    rows: List[Dict[str, Any]] = []
    for p in sorted(_SYS_NET.iterdir()):
        name = p.name
        try:
            flags = int(_read(p / "flags") or "0", 16)
        except ValueError:
            flags = 0
        vlan = vlans.get(name, {})
        vid: Optional[int] = vlan.get("vlan")
        parent = vlan.get("parent", "")
        if vid is None and "." in name and name.rsplit(".", 1)[1].isdigit():  # 8021q without /proc entry
            parent, vid = name.rsplit(".", 1)[0], int(name.rsplit(".", 1)[1])
        kind = "loopback" if name == "lo" else "bridge" if (p / "bridge").is_dir() else "vlan" if vid is not None else "virtual" if (p / "device").exists() is False and name != "lo" else "physical"
        rows.append({
            "name": name, "kind": kind, "mac": _read(p / "address"), "state": _read(p / "operstate") or "unknown", "up": bool(flags & IFF_UP),
            "promisc": bool(flags & IFF_PROMISC), "mtu": _read(p / "mtu"), "vlan": vid, "parent": parent, "addresses": addrs.get(name, []),
            "carrier": _read(p / "carrier") == "1",
        })
    order = {"physical": 0, "vlan": 1, "virtual": 2, "bridge": 3, "loopback": 4}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["name"]))
    return rows


def local_macs() -> List[str]:
    return sorted({r["mac"] for r in interfaces() if r.get("mac") and r["mac"] != "00:00:00:00:00:00"})


# ------------------------------------------------------------------ listen


def listen(seconds: float = DEFAULT_LISTEN, interface: str = "", progress: Any = None) -> Dict[str, Any]:
    """Listen for LLDP / CDP for ``seconds`` and classify the announcers (sends nothing)."""
    from .probes import lldp

    t0 = time.time()
    raw = lldp.collect({"interface": interface}, None, window=float(seconds)) if progress is None else lldp.collect({"interface": interface}, progress, window=float(seconds))
    mine = set(local_macs())
    res = lldp.parse(raw)
    announcers = []
    for n in res.neighbours:
        own = n.remote_mac in mine
        announcers.append({"mac": n.remote_mac, "name": n.remote_name, "port": n.remote_port, "ip": n.remote_ip, "vlan": n.vlan, "method": n.method,
                           "interface": n.local_port, "foreign": not own, "description": n.remote_description})
    frames = raw.get("frames") or []
    return {
        "seconds": round(time.time() - t0, 1), "requested": seconds, "status": raw.get("status", "ok"), "notes": list(raw.get("notes") or []),
        "frames": len(frames), "announcers": announcers, "foreign": sum(1 for a in announcers if a["foreign"]),
        "fixture": bool(raw.get("fixture")) or "fetched" not in raw and bool(frames),
    }


# ------------------------------------------------------------------ report


def report(seconds: float = DEFAULT_LISTEN, interface: str = "", do_listen: bool = True, progress: Any = None) -> Dict[str, Any]:
    caps = capabilities()
    itfs = interfaces()
    out: Dict[str, Any] = {"capabilities": caps, "interfaces": itfs, "listen": None, "advice": []}
    phys = [i for i in itfs if i["kind"] in ("physical", "vlan")]
    vlan_ids = sorted({i["vlan"] for i in itfs if i.get("vlan") is not None})
    if not caps["cap_net_raw"] and not caps["packet_socket"]:
        out["advice"].append("No CAP_NET_RAW: the LLDP / CDP listener cannot open a packet socket. Give the service "
                             "AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE (deploy/fathom.service) or run "
                             f"`sudo setcap cap_net_raw,cap_net_bind_service+eip {os.path.realpath(sys.executable)}`.")
    if len(phys) <= 1 and not vlan_ids:
        out["advice"].append("One interface and no VLAN sub-interfaces: mDNS / Dante discovery only covers the VLAN this interface is on. "
                             "Add a NIC per audio VLAN (per-VLAN port groups) or tag sub-interfaces (VLAN 4095 / VGT port group + 8021q).")
    from .probes import fixture_dir

    if do_listen and (caps["packet_socket"] or caps["cap_net_raw"] or fixture_dir() is not None):
        out["listen"] = listen(seconds, interface, progress)
        lst = out["listen"]
        if lst["status"] == "skipped":
            out["advice"].append("Listener skipped: " + "; ".join(lst["notes"]))
        elif lst["foreign"] == 0:
            out["advice"].append(f"No LLDP / CDP frame from another host in {seconds:.0f} s. On ESXi set Promiscuous Mode = Accept on the VM's port group "
                                 "(vSwitch or distributed port group security policy); Forged Transmits and MAC Changes can stay Reject. "
                                 "Also check that the upstream switch port has LLDP (or CDP) transmit enabled — most announce every 30 s.")
    elif do_listen:
        out["listen"] = {"status": "skipped", "notes": ["no packet socket"], "frames": 0, "foreign": 0, "announcers": []}
    return out


def format_report(rep: Dict[str, Any]) -> str:
    c = rep["capabilities"]
    lines = ["fathom discovery doctor"]
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    lines.append(f"  user: {c['user']}{' (root)' if c['root'] else ''}  python: {c['python']}")
    lines.append(f"  CAP_NET_RAW: {yn(c['cap_net_raw'])}   CAP_NET_BIND_SERVICE: {yn(c['cap_net_bind_service'])}   packet socket: {yn(c['packet_socket'])} ({c['packet_socket_message']})")
    lines.append("  interfaces:")
    for i in rep["interfaces"]:
        if i["kind"] == "loopback":
            continue
        bits = [i["name"], i["kind"], i["mac"] or "-", i["state"]]
        if i.get("vlan") is not None:
            bits.append(f"vlan {i['vlan']} on {i['parent']}")
        if i["addresses"]:
            bits.append(", ".join(i["addresses"]))
        if i["promisc"]:
            bits.append("PROMISC")
        lines.append("    " + "  ".join(bits))
    lst = rep.get("listen")
    if lst:
        lines.append(f"  LLDP / CDP listen ({lst.get('seconds', 0)} s): {lst['frames']} frames, {len(lst['announcers'])} announcers, {lst['foreign']} from other hosts")
        for a in lst["announcers"]:
            lines.append(f"    {a['method']:4} {a['mac']}  {a['name'] or '-'}  port {a['port'] or '-'}  {a['ip'] or ''}  on {a['interface'] or '?'}{'' if a['foreign'] else '  (this host)'}")
        for n in lst.get("notes") or []:
            lines.append("    note: " + n)
    for adv in rep["advice"]:
        lines.append("  ! " + adv)
    if not rep["advice"]:
        lines.append("  ok: this host can listen for LLDP / CDP and sees other hosts' frames")
    return "\n".join(lines)


__all__ = ["CAP_NET_BIND_SERVICE", "CAP_NET_RAW", "DEFAULT_LISTEN", "capabilities", "format_report", "interfaces", "listen", "local_macs", "report"]
