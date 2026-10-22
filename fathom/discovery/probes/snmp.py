"""SNMP read-only walk of managed switches (active, opt-in).

Only the switches the user lists are contacted, one at a time, with small
GETBULK batches (10 OIDs), a pause between requests, a per-request timeout
and few retries. Nothing is ever SET. What is read:

- ``SNMPv2-MIB`` system group — name, description, location, uptime;
- ``IF-MIB`` — port names, aliases, MACs, speed, link state;
- ``BRIDGE-MIB`` / ``Q-BRIDGE-MIB`` — which MAC addresses are learned on
  which port (and in which VLAN), the switch's bridge address, VLAN names;
- ``LLDP-MIB`` — the switch's own LLDP neighbour table: what hangs off each
  port by chassis id, port id, system name and management address;
- ``ENTITY-MIB`` — chassis manufacturer, model, serial and software revision.

The raw payload saved for a run is a flat ``{oid: value}`` map per host, so a
walk recorded from a real switch replays as a fixture unchanged. Byte strings
that are not printable text (MAC addresses, chassis ids) are stored as
``0x…`` hex. The walk uses ``puresnmp`` (``fathom-audio[discovery]``); SNMPv3
with privacy additionally needs ``puresnmp[crypto]``.
"""

from __future__ import annotations

import ipaddress
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...network import normalize_mac
from .. import oui
from . import ACTIVE, Neighbour, NetworkObs, Observation, ProbeInfo, ProbeResult, fixture_payload, host_list, split_host_port
from .lldp import LLDP_CAPS, _model_from_descr

DEFAULT_PORT = 161
TIMEOUT = 5.0  # seconds per request
RETRIES = 2
PAUSE = 0.02  # seconds between requests to one switch
BULK = 10  # OIDs per GETBULK
MAX_ROWS = 6000  # per table group and host
HOST_BUDGET = 120.0  # seconds per switch before the rest of the walk is skipped
AUTH_METHODS = ("sha1", "md5")
PRIV_METHODS = ("none", "aes", "des")

INFO = ProbeInfo(
    id="snmp", label="SNMP (managed switches)", mode=ACTIVE, maturity="tested", default_enabled=False, targets="hosts",
    help="Reads each listed switch's port table, learned MAC addresses per port and VLAN, its LLDP neighbour table and chassis inventory over SNMP v2c or v3. "
         "This is the most direct source of which device is on which switch port.",
    sends="Read-only SNMP GET / GETBULK (UDP 161) to the listed switches only: system, IF-MIB, BRIDGE / Q-BRIDGE MAC table, LLDP-MIB, ENTITY-MIB. "
          "One switch at a time, 10 OIDs per request, 20 ms between requests, 5 s timeout, 2 retries. Never a SET.",
    needs=["puresnmp"],
    fields=[
        {"key": "hosts", "label": "Switches", "type": "list", "placeholder": "10.99.0.3\n10.99.0.4:1161", "env": "FATHOM_SNMP_HOSTS",
         "help": "Management addresses, one per line (host or host:port). Nothing outside this list is queried."},
        {"key": "version", "label": "Version", "type": "select", "options": ["v2c", "v3"], "default": "v2c", "env": "FATHOM_SNMP_VERSION"},
        {"key": "community", "label": "Community", "secret": True, "env": "FATHOM_SNMP_COMMUNITY", "help": "v2c read-only community."},
        {"key": "username", "label": "v3 user", "env": "FATHOM_SNMP_USER", "help": "SNMPv3 security name (read-only view)."},
        {"key": "auth_protocol", "label": "v3 auth", "type": "select", "options": list(AUTH_METHODS), "default": "sha1", "env": "FATHOM_SNMP_AUTH_PROTOCOL"},
        {"key": "auth_key", "label": "v3 auth key", "secret": True, "env": "FATHOM_SNMP_AUTH_KEY"},
        {"key": "priv_protocol", "label": "v3 privacy", "type": "select", "options": list(PRIV_METHODS), "default": "none", "env": "FATHOM_SNMP_PRIV_PROTOCOL",
         "help": "AES / DES need the puresnmp[crypto] extra on the server."},
        {"key": "priv_key", "label": "v3 privacy key", "secret": True, "env": "FATHOM_SNMP_PRIV_KEY"},
    ],
)

# OIDs (numeric; no MIB files needed) ------------------------------------------------------------
SYS = "1.3.6.1.2.1.1"
SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_CONTACT, SYS_NAME, SYS_LOCATION = (SYS + f".{i}.0" for i in (1, 2, 3, 4, 5, 6))
IF_DESCR, IF_TYPE, IF_PHYS, IF_OPER = "1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.3", "1.3.6.1.2.1.2.2.1.6", "1.3.6.1.2.1.2.2.1.8"
IF_NAME, IF_HIGH_SPEED, IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.1", "1.3.6.1.2.1.31.1.1.1.15", "1.3.6.1.2.1.31.1.1.1.18"
BRIDGE_ADDR, BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.1.0", "1.3.6.1.2.1.17.1.4.1.2"
D1D_FDB_PORT, D1D_FDB_STATUS = "1.3.6.1.2.1.17.4.3.1.2", "1.3.6.1.2.1.17.4.3.1.3"
D1Q_FDB_PORT, D1Q_FDB_STATUS = "1.3.6.1.2.1.17.7.1.2.2.1.2", "1.3.6.1.2.1.17.7.1.2.2.1.3"
D1Q_VLAN_FDB_ID, D1Q_VLAN_NAME, D1Q_PVID = "1.3.6.1.2.1.17.7.1.4.2.1.3", "1.3.6.1.2.1.17.7.1.4.3.1.1", "1.3.6.1.2.1.17.7.1.4.5.1.1"
LLDP_LOC = "1.0.8802.1.1.2.1.3"
LLDP_LOC_CHASSIS_SUBTYPE, LLDP_LOC_CHASSIS, LLDP_LOC_SYSNAME, LLDP_LOC_SYSDESC = (LLDP_LOC + f".{i}.0" for i in (1, 2, 3, 4))
LLDP_LOC_PORT_SUBTYPE, LLDP_LOC_PORT_ID, LLDP_LOC_PORT_DESC = LLDP_LOC + ".7.1.2", LLDP_LOC + ".7.1.3", LLDP_LOC + ".7.1.4"
LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_REM_MAN_ADDR = "1.0.8802.1.1.2.1.4.2.1.3"  # lldpRemManAddrIfSubtype: the address is in the index
ENT = "1.3.6.1.2.1.47.1.1.1.1"
ENT_DESCR, ENT_CLASS, ENT_NAME, ENT_SW, ENT_SERIAL, ENT_MFG, ENT_MODEL = (ENT + f".{i}" for i in (2, 5, 7, 10, 11, 12, 13))

#: walk groups: (label, [roots], row cap). Order matters: identity first so a slow switch still yields something.
GROUPS: List[Tuple[str, List[str], int]] = [
    ("system", [SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_CONTACT, SYS_NAME, SYS_LOCATION], 6),
    ("interfaces", [IF_DESCR, IF_TYPE, IF_PHYS, IF_OPER, IF_NAME, IF_HIGH_SPEED, IF_ALIAS], MAX_ROWS),
    ("bridge", [BRIDGE_ADDR, BASE_PORT_IFINDEX], MAX_ROWS),
    ("lldp", [LLDP_LOC_CHASSIS_SUBTYPE, LLDP_LOC_CHASSIS, LLDP_LOC_SYSNAME, LLDP_LOC_SYSDESC, LLDP_LOC_PORT_SUBTYPE, LLDP_LOC_PORT_ID, LLDP_LOC_PORT_DESC, LLDP_REM, LLDP_REM_MAN_ADDR], MAX_ROWS),
    ("fdb", [D1Q_FDB_PORT, D1Q_FDB_STATUS], MAX_ROWS),
    ("fdb-bridge", [D1D_FDB_PORT, D1D_FDB_STATUS], MAX_ROWS),
    ("vlans", [D1Q_VLAN_FDB_ID, D1Q_VLAN_NAME, D1Q_PVID], MAX_ROWS),
    ("entity", [ENT_DESCR, ENT_CLASS, ENT_NAME, ENT_SW, ENT_SERIAL, ENT_MFG, ENT_MODEL], 512),
]
_SCALARS = {SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_CONTACT, SYS_NAME, SYS_LOCATION, BRIDGE_ADDR,
            LLDP_LOC_CHASSIS_SUBTYPE, LLDP_LOC_CHASSIS, LLDP_LOC_SYSNAME, LLDP_LOC_SYSDESC}
ETHERNET_IF_TYPES = {6, 7, 62, 69, 117}  # ethernetCsmacd, iso88023, fastEther, fastEtherFX, gigabitEthernet
FDB_LEARNED = 3
_PORT_NUM = re.compile(r"(\d+)\s*$")


class SnmpError(Exception):
    pass


# ------------------------------------------------------------------ availability / settings


def available() -> Tuple[bool, str]:
    try:
        import puresnmp  # noqa: F401
    except ImportError:
        return False, ""
    return True, str(getattr(puresnmp, "__version__", "") or "")


def _settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    s = settings or {}
    return {
        "hosts": host_list(s.get("hosts")), "version": "v3" if str(s.get("version") or "").lower() == "v3" else "v2c",
        "community": str(s.get("community") or ""), "username": str(s.get("username") or ""),
        "auth_protocol": str(s.get("auth_protocol") or "sha1").lower(), "auth_key": str(s.get("auth_key") or ""),
        "priv_protocol": str(s.get("priv_protocol") or "none").lower(), "priv_key": str(s.get("priv_key") or ""),
    }


def _credentials(s: Dict[str, Any]) -> Any:
    from puresnmp.credentials import V2C, V3, Auth, Priv

    if s["version"] == "v3":
        if not s["username"]:
            raise SnmpError("SNMPv3 needs a user name")
        auth = Auth(s["auth_key"].encode("utf-8"), s["auth_protocol"]) if s["auth_key"] else None
        priv = Priv(s["priv_key"].encode("utf-8"), s["priv_protocol"]) if s["priv_key"] and s["priv_protocol"] != "none" else None
        return V3(s["username"], auth=auth, priv=priv)
    if not s["community"]:
        raise SnmpError("no SNMP community configured")
    return V2C(s["community"])


#: columns whose OCTET STRING values are opaque (MACs, chassis / port ids, capability BITS): always stored as hex
_BINARY_PREFIXES = (IF_PHYS + ".", BRIDGE_ADDR, LLDP_LOC_CHASSIS, LLDP_REM + ".5.", LLDP_REM + ".7.", LLDP_REM + ".11.", LLDP_REM + ".12.")


def _encode(v: Any, oid: str = "") -> Any:
    """JSON-safe value for the raw dump; opaque bytes (MACs, chassis ids) as ``0x…``."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, (bytes, bytearray)):
        b = bytes(v)
        if oid.startswith(_BINARY_PREFIXES) or len(b) == 6 or any(c < 9 or (13 < c < 32) or c == 127 for c in b):
            return "0x" + b.hex()
        try:
            return b.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return "0x" + b.hex()
    if isinstance(v, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(v)
    if hasattr(v, "total_seconds"):
        return int(v.total_seconds() * 100)
    return str(v)


class _Pacer:
    """Sender wrapper: a pause before every PDU (rate limit), timeout / retries pinned, cancel honoured, requests counted."""

    def __init__(self, job: Any, pause: float = PAUSE) -> None:
        self.job, self.pause, self.requests = job, pause, 0

    async def __call__(self, endpoint: Any, packet: bytes, timeout: float = TIMEOUT, loop: Any = None, retries: int = RETRIES) -> bytes:
        import asyncio

        from puresnmp.transport import send_udp

        if self.job is not None:
            self.job.check()
        if self.requests:
            await asyncio.sleep(self.pause)
        self.requests += 1
        return await send_udp(endpoint, packet, timeout=max(1, int(round(timeout))), loop=loop, retries=max(1, int(retries)))


async def _walk_async(host: str, port: int, creds: Any, job: Any, pacer: _Pacer, groups: Iterable[Tuple[str, List[str], int]], budget: float) -> Dict[str, Any]:
    from puresnmp import Client, PyWrapper
    from puresnmp.exc import SnmpError as PureError
    from puresnmp.exc import Timeout

    client = Client(host, creds, port=port, sender=pacer)  # type: ignore[arg-type]
    client.configure(timeout=int(TIMEOUT), retries=RETRIES)
    py = PyWrapper(client)
    oids: Dict[str, Any] = {}
    notes: List[str] = []
    t0 = time.time()
    for label, roots, cap in groups:
        if time.time() - t0 > budget:
            notes.append(f"time budget of {budget:.0f} s used up before {label}")
            break
        rows = 0
        try:
            for r in (r for r in roots if r in _SCALARS):
                try:
                    v = await py.get(r)
                except Timeout:
                    raise
                except PureError:
                    continue  # the switch does not implement this object
                if v is not None and type(v).__name__ not in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                    oids[r] = _encode(v, r)
            tables = [r for r in roots if r not in _SCALARS]
            if tables:
                async for vb in py.bulkwalk(tables, bulk_size=BULK):
                    oids[str(vb.oid)] = _encode(vb.value, str(vb.oid))
                    rows += 1
                    if rows >= cap:
                        notes.append(f"{label}: stopped after {cap} rows")
                        break
        except Timeout:
            if label == "system":
                raise SnmpError(f"{host}: no SNMP answer in {TIMEOUT:.0f} s × {RETRIES} (community / v3 user, ACL, UDP {port}?)")
            notes.append(f"{label}: timed out after {rows} rows")
        except PureError as exc:
            if label == "system":
                raise SnmpError(f"{host}: {type(exc).__name__}: {exc}")
            notes.append(f"{label}: {type(exc).__name__}: {exc}")
        if job is not None:
            job.check()
    return {"oids": oids, "notes": notes, "requests": pacer.requests, "elapsed": round(time.time() - t0, 2)}


def walk_host(host: str, port: int, s: Dict[str, Any], job: Any = None, groups: Optional[Iterable[Tuple[str, List[str], int]]] = None, budget: float = HOST_BUDGET) -> Dict[str, Any]:
    """Blocking walk of one switch (runs its own asyncio loop in the calling thread)."""
    import asyncio

    ok, _ = available()
    if not ok:
        raise SnmpError("puresnmp is not installed: pip install 'fathom-audio[discovery]'")
    creds = _credentials(s)
    try:
        return asyncio.run(_walk_async(host, port, creds, job, _Pacer(job), groups or GROUPS, budget))
    except SnmpError:
        raise
    except OSError as exc:
        raise SnmpError(f"{host}: {exc}")


def collect(settings: Dict[str, Any], job: Any = None) -> Dict[str, Any]:
    """Walk every configured switch in turn (or replay a fixture)."""
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return fx
    s = _settings(settings)
    if not s["hosts"]:
        raise SnmpError("no switches listed")
    out: Dict[str, Any] = {"version": s["version"], "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hosts": {}}
    for item in s["hosts"]:
        host, port = split_host_port(item, DEFAULT_PORT)
        entry: Dict[str, Any] = {"host": host, "port": port, "status": "ok", "error": "", "oids": {}, "notes": [], "requests": 0, "elapsed": 0.0}
        out["hosts"][item] = entry
        if job is not None:
            job.log(f"snmp: walking {host} (udp {port}, {s['version']}, read-only)")
        try:
            entry.update(walk_host(host, port, s, job))
        except SnmpError as exc:
            entry["status"], entry["error"] = "error", str(exc)
            if job is not None:
                job.log(f"snmp: {exc}", "warn")
            continue
        if job is not None:
            job.log(f"snmp: {host}: {len(entry['oids'])} values in {entry['requests']} requests, {entry['elapsed']} s")
    return out


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        hosts = fx.get("hosts") or {}
        return {"ok": True, "message": f"fixture replay: {len(hosts)} switches", "fixture": True}
    ok, _ = available()
    if not ok:
        return {"ok": False, "message": "puresnmp is not installed on the server: pip install 'fathom-audio[discovery]'"}
    s = _settings(settings)
    if not s["hosts"]:
        return {"ok": False, "message": "List at least one switch first."}
    try:
        _credentials(s)
    except SnmpError as exc:
        return {"ok": False, "message": str(exc)}
    parts, good = [], 0
    for item in s["hosts"][:8]:
        host, port = split_host_port(item, DEFAULT_PORT)
        try:
            r = walk_host(host, port, s, None, groups=[("system", [SYS_DESCR, SYS_NAME], 2)], budget=15.0)
        except SnmpError as exc:
            parts.append(f"{host}: {str(exc).split(': ', 1)[-1]}")
            continue
        good += 1
        parts.append(f"{host}: {r['oids'].get(SYS_NAME) or '?'} ({_model_from_descr(str(r['oids'].get(SYS_DESCR) or '')) or 'no sysDescr'}) in {r['elapsed']} s")
    return {"ok": good > 0, "message": "; ".join(parts) + (" — one GET per switch, nothing else was read" if good else ""), "reachable": good}


# ------------------------------------------------------------------ parse


def _sub(oids: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    p = prefix + "."
    return {k[len(p):]: v for k, v in oids.items() if k.startswith(p)}


def _mac_of(v: Any) -> str:
    if isinstance(v, str) and v.startswith("0x") and len(v) == 14:
        return normalize_mac(":".join(v[2 + i:4 + i] for i in range(0, 12, 2))) or ""
    return normalize_mac(str(v or "")) or ""


def _index_mac(parts: List[str]) -> str:
    try:
        return ":".join(f"{int(x):02x}" for x in parts[-6:]) if len(parts) >= 6 and all(0 <= int(x) < 256 for x in parts[-6:]) else ""
    except ValueError:
        return ""


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith("0x"):
        try:
            return bytes.fromhex(v[2:]).decode("utf-8", "replace").strip("\x00 ")
        except ValueError:
            return v
    return str(v).strip()


def _chassis(subtype: Any, value: Any) -> Tuple[str, str]:
    """LLDP chassis / port id by subtype -> (mac, text). Chassis subtype 4 and port subtype 3 are MAC addresses."""
    try:
        st = int(subtype)
    except (TypeError, ValueError):
        st = 0
    if st in (3, 4):
        return _mac_of(value), ""
    if st == 5 and isinstance(value, str) and value.startswith("0x") and len(value) == 12 and value[2:4] == "01":  # networkAddress, IPv4
        return "", ".".join(str(int(value[i:i + 2], 16)) for i in range(4, 12, 2))
    text = _text(value)
    mac = normalize_mac(text) or ""
    return (mac, "") if mac else ("", text)


def _caps(v: Any) -> List[str]:
    if not isinstance(v, str) or not v.startswith("0x") or len(v) < 4:
        return []
    bits = int(v[2:4], 16)
    rev = int(f"{bits:08b}"[::-1], 2)  # LLDP-MIB BITS: bit 0 is the MSB of the first octet
    return [n for bit, n in LLDP_CAPS if rev & bit]


def parse_host(key: str, entry: Dict[str, Any], seen: str, res: ProbeResult) -> None:
    oids = entry.get("oids") or {}
    host = str(entry.get("host") or key)
    tag = f"snmp {host}"
    if entry.get("status") != "ok" or not oids:
        res.notes.append(f"{tag}: {entry.get('error') or 'no data'}")
        return
    for n in entry.get("notes") or []:
        res.notes.append(f"{tag}: {n}")
    sys_name, sys_descr = _text(oids.get(SYS_NAME)), _text(oids.get(SYS_DESCR))
    bridge_mac = _mac_of(oids.get(BRIDGE_ADDR))
    loc_mac, _ = _chassis(oids.get(LLDP_LOC_CHASSIS_SUBTYPE), oids.get(LLDP_LOC_CHASSIS))
    # interfaces -----------------------------------------------------------------------------
    if_name, if_descr, if_type, if_phys, if_oper = _sub(oids, IF_NAME), _sub(oids, IF_DESCR), _sub(oids, IF_TYPE), _sub(oids, IF_PHYS), _sub(oids, IF_OPER)
    if_speed, if_alias = _sub(oids, IF_HIGH_SPEED), _sub(oids, IF_ALIAS)
    ports: List[Dict[str, Any]] = []
    port_macs: List[str] = []
    label_for_ifindex: Dict[str, str] = {}
    for idx in sorted(set(if_name) | set(if_descr), key=lambda x: int(x) if x.isdigit() else 0):
        try:
            itype = int(if_type.get(idx, 6))
        except (TypeError, ValueError):
            itype = 6
        label = _text(if_name.get(idx)) or _text(if_descr.get(idx))
        label_for_ifindex[idx] = label
        if itype not in ETHERNET_IF_TYPES or not label:
            continue
        mac = _mac_of(if_phys.get(idx))
        if mac and mac not in port_macs:
            port_macs.append(mac)
        m = _PORT_NUM.search(label)
        n = int(m.group(1)) if m else None
        ports.append({"idx": n if n is not None else int(idx), "ifindex": int(idx) if idx.isdigit() else None, "name": label, "alias": _text(if_alias.get(idx)),
                      "up": str(if_oper.get(idx)) == "1", "speed": if_speed.get(idx), "poe": False, "mac": mac})
    sw_mac = bridge_mac or loc_mac or (port_macs[0] if port_macs else "")
    # bridge port -> label -------------------------------------------------------------------
    bridge_port_label: Dict[str, str] = {}
    for bp, ifi in _sub(oids, BASE_PORT_IFINDEX).items():
        bridge_port_label[bp] = label_for_ifindex.get(str(ifi), "") or f"Port {bp}"
    # entity -----------------------------------------------------------------------------------
    ent_class = _sub(oids, ENT_CLASS)
    chassis_idx = next((i for i, c in sorted(ent_class.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0) if str(c) == "3"), None)
    mfg = _text(_sub(oids, ENT_MFG).get(chassis_idx)) if chassis_idx else ""
    model = _text(_sub(oids, ENT_MODEL).get(chassis_idx)) if chassis_idx else ""
    serial = _text(_sub(oids, ENT_SERIAL).get(chassis_idx)) if chassis_idx else ""
    sw_rev = _text(_sub(oids, ENT_SW).get(chassis_idx)) if chassis_idx else ""
    if not model:
        model = _model_from_descr(sys_descr)
    if not mfg:
        low = sys_descr.lower()
        for needle, name in (("cisco", "Cisco"), ("netgear", "NETGEAR"), ("juniper", "Juniper"), ("aruba", "Aruba"), ("hp ", "HPE"), ("procurve", "HPE"), ("extreme", "Extreme"),
                             ("ubiquiti", "Ubiquiti"), ("unifi", "Ubiquiti"), ("mikrotik", "MikroTik"), ("luminex", "Luminex"), ("dell", "Dell"), ("brocade", "Brocade")):
            if needle in low:
                mfg = name
                break
        if not mfg and "proav" in low:
            mfg = "NETGEAR"
        if not mfg and sw_mac:
            mfg = oui.short_vendor(oui.vendor(sw_mac))
    ip = host if _is_ip(host) else ""
    sw = Observation(
        source="snmp", mac=sw_mac, ip=ip, hostname=sys_name, name=sys_name, manufacturer=mfg, model=model, serial=serial, firmware=sw_rev,
        kind_hint="switch", ports=ports, extra_macs=[m for m in port_macs if m != sw_mac], services=["snmp"], seen=seen,
        evidence={"sysDescr": sys_descr[:200], "sysObjectID": _text(oids.get(SYS_OBJECT_ID)), "sysLocation": _text(oids.get(SYS_LOCATION)), "sysContact": _text(oids.get(SYS_CONTACT)),
                  "uptime_ticks": oids.get(SYS_UPTIME), "ports": len(ports), "bridge_address": bridge_mac, "requests": entry.get("requests"), "elapsed": entry.get("elapsed")},
    )
    res.observations.append(sw)
    own = set(sw.extra_macs) | ({sw_mac} if sw_mac else set())
    sw_name = sys_name or host
    # LLDP neighbours --------------------------------------------------------------------------
    loc_port_id, loc_port_desc, loc_port_sub = _sub(oids, LLDP_LOC_PORT_ID), _sub(oids, LLDP_LOC_PORT_DESC), _sub(oids, LLDP_LOC_PORT_SUBTYPE)
    rem = _sub(oids, LLDP_REM)
    rem_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for suffix, v in rem.items():
        parts = suffix.split(".")
        if len(parts) != 4:
            continue
        col, _tm, lport, ridx = parts
        rem_rows.setdefault((lport, ridx), {})[col] = v
    man_addr: Dict[Tuple[str, str], str] = {}
    for suffix in _sub(oids, LLDP_REM_MAN_ADDR):
        parts = suffix.split(".")
        if len(parts) >= 9 and parts[3] == "1" and parts[4] == "4":  # ipv4, length 4
            man_addr.setdefault((parts[1], parts[2]), ".".join(parts[5:9]))
    uplink_ports: set = set()
    n_lldp = 0
    for (lport, ridx), cols in sorted(rem_rows.items(), key=lambda kv: (int(kv[0][0]) if kv[0][0].isdigit() else 0, kv[0][1])):
        rmac, rtext = _chassis(cols.get("4"), cols.get("5"))
        pmac, ptext = _chassis(cols.get("6"), cols.get("7"))
        local = _text(loc_port_id.get(lport)) if str(loc_port_sub.get(lport)) != "3" else ""
        local = local or bridge_port_label.get(lport) or label_for_ifindex.get(lport) or _text(loc_port_desc.get(lport)) or f"Port {lport}"
        caps = _caps(cols.get("12")) or _caps(cols.get("11"))
        rname = _text(cols.get("9"))
        rdesc = _text(cols.get("10"))
        if not rmac and pmac:
            rmac = pmac
        if not rmac and not rname:
            continue
        n_lldp += 1
        if any(c in ("bridge", "router", "wlan_ap", "repeater") for c in caps):
            uplink_ports.add(lport)
        res.neighbours.append(Neighbour(
            source="snmp", method="snmp_lldp", local_mac=sw_mac, local_name=sw_name, local_port=local, remote_mac=rmac, remote_name=rname,
            remote_port=ptext or _text(cols.get("8")) or pmac, remote_ip=man_addr.get((lport, ridx), rtext if rtext.count(".") == 3 else ""),
            remote_description=rdesc, remote_capabilities=caps,
            evidence={"switch": sw_name, "local_port": local, "chassis_id": rmac or rtext, "port_id": ptext or pmac, "port_description": _text(cols.get("8"))},
        ))
    # learned MAC table --------------------------------------------------------------------------
    fdb_port, fdb_status = _sub(oids, D1Q_FDB_PORT), _sub(oids, D1Q_FDB_STATUS)
    vlan_for_fdb: Dict[str, int] = {}
    for suffix, fid in _sub(oids, D1Q_VLAN_FDB_ID).items():
        vid = suffix.split(".")[-1]
        if vid.isdigit():
            try:
                vlan_for_fdb[str(int(fid))] = int(vid)
            except (TypeError, ValueError):
                pass
    qbridge = True
    if not fdb_port:
        qbridge = False
        fdb_port, fdb_status = _sub(oids, D1D_FDB_PORT), _sub(oids, D1D_FDB_STATUS)
        if fdb_port:
            res.notes.append(f"{tag}: Q-BRIDGE MAC table empty, BRIDGE-MIB used (per-VLAN contexts are not walked)")
    learned: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for suffix, bp in fdb_port.items():
        parts = suffix.split(".")
        mac = _index_mac(parts)
        if not mac or str(bp) in ("0", ""):
            continue
        status = str(fdb_status.get(suffix, FDB_LEARNED))
        if status not in (str(FDB_LEARNED), "5"):  # learned | mgmt
            continue
        if mac in own or oui.is_multicast(mac):
            continue
        vlan: Optional[int] = None
        if qbridge and len(parts) == 7:
            fid = parts[0]
            vlan = vlan_for_fdb.get(fid, int(fid) if fid.isdigit() and 0 < int(fid) < 4095 else None)
        cur = learned.setdefault((mac, str(bp)), {"mac": mac, "bridge_port": str(bp), "vlans": []})
        if vlan is not None and vlan not in cur["vlans"]:
            cur["vlans"].append(vlan)
    per_port: Dict[str, int] = {}
    for row in learned.values():
        per_port[row["bridge_port"]] = per_port.get(row["bridge_port"], 0) + 1
    n_obs = 0
    for row in sorted(learned.values(), key=lambda r: (int(r["bridge_port"]) if r["bridge_port"].isdigit() else 0, r["mac"])):
        bp, mac = row["bridge_port"], row["mac"]
        label = bridge_port_label.get(bp) or f"Port {bp}"
        vlan = row["vlans"][0] if row["vlans"] else None
        res.neighbours.append(Neighbour(
            source="snmp", method="mac_table", local_mac=sw_mac, local_name=sw_name, local_port=label, remote_mac=mac, vlan=vlan,
            evidence={"switch": sw_name, "port": label, "vlans": row["vlans"], "macs_on_port": per_port[bp]},
        ))
        if bp in uplink_ports:
            continue  # behind another switch: the edge is kept, the sighting belongs to that switch's own table
        vendor = oui.vendor(mac)
        n_obs += 1
        res.observations.append(Observation(
            source="snmp", mac=mac, vlan=vlan, kind_hint="client", manufacturer=oui.short_vendor(vendor) if vendor else "", uplink_mac=sw_mac, uplink_port=label, seen=seen,
            evidence={"via": "mac_table", "switch": sw_name, "port": label, "vendor": vendor, "vlans": row["vlans"]},
        ))
    # VLAN names -----------------------------------------------------------------------------------
    n_vlans = 0
    for vid, name in _sub(oids, D1Q_VLAN_NAME).items():
        if not vid.isdigit():
            continue
        vname = _text(name)
        if int(vid) == 1 and vname.lower() in ("", "default", "default vlan"):
            continue
        n_vlans += 1
        res.networks.append(NetworkObs(source="snmp", name=vname or f"VLAN {vid}", vlan=int(vid), evidence={"switch": sw_name}))
    res.stats.setdefault("switches", 0)
    res.stats["switches"] += 1
    res.stats["ports"] = res.stats.get("ports", 0) + len(ports)
    res.stats["lldp"] = res.stats.get("lldp", 0) + n_lldp
    res.stats["macs"] = res.stats.get("macs", 0) + len(learned)
    res.stats["vlans"] = res.stats.get("vlans", 0) + n_vlans
    res.notes.append(f"{tag}: {sw_name}: {len(ports)} ports, {n_lldp} LLDP neighbours, {len(learned)} learned MACs ({n_obs} hosts on edge ports), {n_vlans} VLANs")


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("snmp: payload is not an object")
        return res
    seen = str(raw.get("fetched") or "")
    hosts = raw.get("hosts") or {}
    if not isinstance(hosts, dict) or not hosts:
        res.status = "skipped"
        res.notes.append("snmp: no switches walked")
        return res
    for key, entry in hosts.items():
        if isinstance(entry, dict):
            parse_host(str(key), entry, seen, res)
    res.stats["hosts"] = len(hosts)
    res.stats["failed"] = sum(1 for e in hosts.values() if isinstance(e, dict) and e.get("status") != "ok")
    if res.stats["failed"] == len(hosts):
        res.status = "error"
    return res


__all__ = ["GROUPS", "INFO", "SnmpError", "available", "collect", "parse", "parse_host", "test", "walk_host"]
