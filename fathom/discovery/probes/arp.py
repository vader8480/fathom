"""Host ARP / neighbour table with OUI vendor lookup and reverse DNS (passive).

Reads what the Fathom host's kernel already knows (``/proc/net/arp``,
``ip neigh``, or ``arp -an`` on macOS / BSD). No sweep, no ping: an entry is
only there because the host talked to that address recently (the UniFi pull
and mDNS listen populate it as a side effect). Vendors come from the bundled
OUI table; reverse DNS asks the host's resolver, not the device.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...network import normalize_mac
from .. import oui
from . import PASSIVE, Observation, ProbeInfo, ProbeResult, fixture_payload

INFO = ProbeInfo(
    id="arp", label="ARP table + OUI vendors", mode=PASSIVE, maturity="tested",
    help="Reads the host's ARP / neighbour table and names each MAC's vendor from the bundled OUI list; adds reverse-DNS hostnames where the resolver already knows them. No sweep.",
    sends="Nothing to devices. Optional reverse-DNS lookups go to the host's DNS resolver.",
    needs=[],
    fields=[
        {"key": "reverse_dns", "label": "Reverse DNS lookups", "type": "check", "default": True},
    ],
)

_PROC = Path("/proc/net/arp")
_IP_NEIGH_RE = re.compile(r"^(?P<ip>[0-9a-fA-F.:]+)\s+(?:dev\s+(?P<dev>\S+)\s+)?(?:lladdr\s+(?P<mac>[0-9a-fA-F:]{17})\s+)?.*?(?P<state>REACHABLE|STALE|DELAY|PROBE|FAILED|INCOMPLETE|PERMANENT|NOARP)?\s*$")
_ARP_AN_RE = re.compile(r"^(?P<host>\S+)\s+\((?P<ip>[0-9.]+)\)\s+at\s+(?P<mac>[0-9a-fA-F:.-]+|\(incomplete\))(?:\s+on\s+(?P<dev>\S+))?")
_WIN_RE = re.compile(r"^\s*(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mac>[0-9a-fA-F-]{17})\s+(?P<type>\w+)")
RDNS_BUDGET = 8.0


def read_table() -> Tuple[str, str]:
    """``(format, text)`` of the host's neighbour table."""
    if _PROC.is_file():
        try:
            return "proc", _PROC.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    ip = shutil.which("ip")
    if ip:
        try:
            out = subprocess.run([ip, "-4", "neigh", "show"], capture_output=True, text=True, timeout=5, check=False)
            if out.returncode == 0:
                return "ip-neigh", out.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    arp = shutil.which("arp")
    if arp:
        try:
            out = subprocess.run([arp, "-an"] if os.name != "nt" else [arp, "-a"], capture_output=True, text=True, timeout=5, check=False)
            if out.returncode == 0:
                return "arp-an" if os.name != "nt" else "windows", out.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return "none", ""


def parse_table(fmt: str, text: str) -> List[Dict[str, Any]]:
    """Normalised entries ``{ip, mac, dev, state}`` (complete entries only)."""
    rows: List[Dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        ip = mac = dev = state = ""
        if fmt == "proc":
            if line.lower().startswith("ip address"):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            ip, flags, mac, dev = parts[0], parts[2], parts[3], parts[5]
            state = "complete" if flags not in ("0x0",) else "incomplete"
        elif fmt == "ip-neigh":
            m = _IP_NEIGH_RE.match(line)
            if not m:
                continue
            ip, mac, dev, state = m.group("ip"), m.group("mac") or "", m.group("dev") or "", (m.group("state") or "").lower()
        elif fmt == "arp-an":
            m = _ARP_AN_RE.match(line)
            if not m:
                continue
            ip, mac, dev, state = m.group("ip"), m.group("mac"), m.group("dev") or "", "complete"
            if mac == "(incomplete)":
                state = "incomplete"
        elif fmt == "windows":
            m = _WIN_RE.match(line)
            if not m:
                continue
            ip, mac, state = m.group("ip"), m.group("mac"), m.group("type").lower()
        else:
            continue
        nmac = normalize_mac(mac) or ""
        if not nmac or nmac == "00:00:00:00:00:00" or state in ("incomplete", "failed"):
            continue
        if oui.is_multicast(nmac) or ip.startswith(("224.", "239.", "255.")) or ip == "0.0.0.0":
            continue
        rows.append({"ip": ip, "mac": nmac, "dev": dev, "state": state})
    return rows


def _rdns(ips: List[str], budget: float = RDNS_BUDGET) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not ips:
        return out

    def one(ip: str) -> Tuple[str, str]:
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror, OSError, UnicodeError):
            return ip, ""

    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fathom-rdns")
    futs = [pool.submit(one, ip) for ip in ips]
    done, _ = wait(futs, timeout=budget)
    for f in done:
        ip, name = f.result()
        if name:
            out[ip] = name
    pool.shutdown(wait=False)
    return out


def collect(settings: Dict[str, Any], job: Any = None) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return fx
    fmt, text = read_table()
    out: Dict[str, Any] = {"format": fmt, "text": text, "rdns": {}, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if fmt == "none":
        out["notes"] = ["no ARP table source found (/proc/net/arp, ip neigh, arp -an)"]
        return out
    if (settings or {}).get("reverse_dns", True):
        rows = parse_table(fmt, text)
        if job is not None:
            job.set_progress(stage=f"arp: {len(rows)} entries, resolving names")
        out["rdns"] = _rdns([r["ip"] for r in rows])
    return out


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return {"ok": True, "message": "fixture replay", "fixture": True}
    fmt, text = read_table()
    if fmt == "none":
        return {"ok": False, "message": "No ARP table source on this host (/proc/net/arp, ip neigh, arp -an)."}
    rows = parse_table(fmt, text)
    return {"ok": True, "message": f"{len(rows)} neighbour entries readable via {fmt}; {len(oui.table())} OUI prefixes loaded."}


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("arp: payload is not an object")
        return res
    for n in raw.get("notes") or []:
        res.notes.append(f"arp: {n}")
    fmt = str(raw.get("format") or "proc")
    if fmt == "none":
        res.status = "skipped"
        return res
    rows = parse_table(fmt, str(raw.get("text") or ""))
    rdns = raw.get("rdns") if isinstance(raw.get("rdns"), dict) else {}
    seen = str(raw.get("fetched") or "")
    vendors = 0
    for r in rows:
        full = oui.vendor(r["mac"])
        if full:
            vendors += 1
        host = str(rdns.get(r["ip"]) or "")
        res.observations.append(Observation(
            source="arp", mac=r["mac"], ip=r["ip"], hostname=host.split(".")[0] if host.endswith((".local", ".lan", ".home", ".arpa")) else host,
            manufacturer=oui.short_vendor(full) if full else "", seen=seen,
            evidence={"iface": r["dev"], "state": r["state"], "vendor": full, "fqdn": host, "locally_administered": oui.is_locally_administered(r["mac"])},
        ))
    res.stats = {"entries": len(rows), "with_vendor": vendors, "with_hostname": len([o for o in res.observations if o.hostname]), "format": fmt}
    return res


__all__ = ["INFO", "collect", "parse", "parse_table", "read_table", "test"]
