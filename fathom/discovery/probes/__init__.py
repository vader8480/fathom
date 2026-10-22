"""Discovery probes: one module per source, each returning a normalised
:class:`ProbeResult`.

Every probe module exposes

- ``INFO`` — a :class:`ProbeInfo` (id, label, ``mode`` passive | active,
  ``maturity`` experimental | tested | mature, help text, settings fields),
- ``collect(settings, job) -> raw`` — the only function that touches the
  network or the host; returns a JSON-serialisable payload that is saved as
  the run's snapshot,
- ``parse(raw, settings) -> ProbeResult`` — pure; turns a payload (live or a
  recorded fixture) into observations, neighbour edges and networks,
- ``test(settings) -> dict`` — a quick capability / reachability check used
  by the Test button; never starts a listen window.

Passive probes (Phase 1) read from a controller that already holds the data
(UniFi), or listen to what devices already broadcast (mDNS, LLDP / CDP, the
host's ARP table). None of them sends a packet to an audio device; the mDNS
browse is the same standard multicast query Dante Controller issues.

Active probes (Phase 2: SNMP, Yamaha SCP, Blackmagic Videohub, Q-SYS QRC;
Phase 3: the Dante Domain Manager GraphQL API) send read-only queries to the
hosts the user lists — and only to those. They
are off by default (``ProbeInfo.default_enabled``), declare what they put on
the wire (``sends``), run one host at a time with a pause between requests
and a timeout per request, and never issue a write / set command.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...network import normalize_mac

PASSIVE = "passive"
ACTIVE = "active"
MATURITIES = ("experimental", "tested", "mature")


@dataclass
class ProbeInfo:
    id: str
    label: str
    mode: str = PASSIVE
    maturity: str = "experimental"
    help: str = ""
    sends: str = ""  # what the probe puts on the wire, in one line
    needs: List[str] = field(default_factory=list)  # capabilities: zeroconf, net_raw, linux, puresnmp
    fields: List[Dict[str, Any]] = field(default_factory=list)  # settings fields shown in the UI (types: text, check, secret, list, select)
    default_enabled: bool = True  # active probes are opt-in
    targets: str = ""  # active probes: the settings key that lists the hosts they may contact

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Observation:
    """One sighting of a host by one probe."""

    source: str
    mac: str = ""
    ip: str = ""
    hostname: str = ""
    name: str = ""
    dante_name: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    vlan: Optional[int] = None
    network: str = ""
    kind_hint: str = ""  # switch | ap | gateway | dante | console | computer | ...
    services: List[str] = field(default_factory=list)
    uplink_mac: str = ""  # switch the source says this host hangs off
    uplink_port: str = ""
    ports: List[Dict[str, Any]] = field(default_factory=list)  # switches: [{idx, name, up, speed, poe}]
    extra_macs: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    seen: str = ""

    def __post_init__(self) -> None:
        self.mac = normalize_mac(self.mac) or ""
        self.uplink_mac = normalize_mac(self.uplink_mac) or ""
        self.extra_macs = [m for m in (normalize_mac(x) or "" for x in self.extra_macs) if m and m != self.mac]
        self.ip = (self.ip or "").strip()
        self.hostname = (self.hostname or "").strip().rstrip(".")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Neighbour:
    """A link edge reported by a source (LLDP neighbour, controller port table …)."""

    source: str
    method: str  # lldp | cdp | unifi_lldp | unifi_client | mac_table
    local_mac: str = ""  # the switch / chassis that reported it
    local_name: str = ""
    local_port: str = ""
    remote_mac: str = ""
    remote_name: str = ""
    remote_port: str = ""
    remote_ip: str = ""
    remote_description: str = ""
    remote_capabilities: List[str] = field(default_factory=list)
    vlan: Optional[int] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.local_mac = normalize_mac(self.local_mac) or ""
        self.remote_mac = normalize_mac(self.remote_mac) or ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkObs:
    source: str
    name: str = ""
    vlan: Optional[int] = None
    subnet: str = ""
    gateway: str = ""
    purpose: str = ""
    dhcp_range: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProbeResult:
    probe: str
    status: str = "ok"  # ok | skipped | error
    observations: List[Observation] = field(default_factory=list)
    neighbours: List[Neighbour] = field(default_factory=list)
    networks: List[NetworkObs] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        return {
            "probe": self.probe, "status": self.status, "hosts": len(self.observations), "links": len(self.neighbours),
            "networks": len(self.networks), "notes": list(self.notes), "stats": dict(self.stats),
        }


def fixture_dir() -> Optional[Path]:
    """``FATHOM_DISCOVERY_FIXTURES``: replay recorded payloads instead of touching the network (tests, demos)."""
    raw = os.environ.get("FATHOM_DISCOVERY_FIXTURES") or ""
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() else None


def fixture_payload(probe_id: str) -> Any:
    """The recorded payload for ``probe_id`` under the fixture dir, or None."""
    import json

    d = fixture_dir()
    if d is None:
        return None
    for name in (f"{probe_id}.json", f"{probe_id}.txt"):
        p = d / name
        if p.is_file():
            if p.suffix == ".json":
                return json.loads(p.read_text(encoding="utf-8"))
            return p.read_text(encoding="utf-8")
    return None


def fixture_delay(window: float) -> float:
    """How long a listen probe pretends to listen in replay mode (``FATHOM_DISCOVERY_FIXTURE_DELAY`` s, default 1)."""
    try:
        d = float(os.environ.get("FATHOM_DISCOVERY_FIXTURE_DELAY") or 1.0)
    except ValueError:
        d = 1.0
    return max(0.0, min(float(window), d))


def all_probes() -> List[Any]:
    """Probe modules / objects in UI order: passive first, then the opt-in active ones."""
    from . import arp, consoles, ddm, lldp, mdns, snmp, unifi

    return [unifi, mdns, lldp, arp, snmp, consoles.YAMAHA, consoles.VIDEOHUB, consoles.QSYS, ddm]


def host_list(value: Any) -> List[str]:
    """Normalise a ``list`` field (comma / newline / space separated text, or a JSON list) to unique host strings."""
    if isinstance(value, (list, tuple)):
        items = [str(x) for x in value]
    else:
        items = str(value or "").replace(";", ",").replace("\n", ",").replace(" ", ",").split(",")
    out: List[str] = []
    for it in items:
        it = it.strip()
        if it and it not in out:
            out.append(it)
    return out


def split_host_port(item: str, default_port: int) -> Any:
    """``"10.0.0.1:1611"`` -> ``("10.0.0.1", 1611)``; bare hosts get ``default_port``."""
    host, port = item.strip(), default_port
    if host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
        host, p = host.rsplit(":", 1)
        port = int(p)
    return host, port


def probe_by_id(probe_id: str) -> Optional[Any]:
    for m in all_probes():
        if m.INFO.id == probe_id:
            return m
    return None


__all__ = [
    "ACTIVE", "MATURITIES", "PASSIVE", "Neighbour", "NetworkObs", "Observation", "ProbeInfo", "ProbeResult",
    "all_probes", "fixture_delay", "fixture_dir", "fixture_payload", "host_list", "probe_by_id", "split_host_port",
]
