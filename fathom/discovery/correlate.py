"""Identity resolution for discovery observations.

Every probe reports *sightings* (:class:`~fathom.discovery.probes.Observation`).
This module folds them into **entities** (one per physical host), scores how
sure we are that the entity is real and well described, and matches each
entity against the devices already in the project document so the UI can
offer "merge into existing" instead of creating a duplicate.

Resolution keys (union-find over observations):

- MAC address (including a switch's extra chassis MACs),
- IPv4 address — only within one run, so a DHCP lease that moved between
  runs can never glue two hosts together,
- hostname / Dante device name (loose key: letters and digits only, ``.local``
  stripped) — Dante primary and secondary interfaces share the name, so the
  two sightings become one device with two interfaces,
- serial number.

Entity confidence (0–1):

    0.50  a MAC address is known (0.25 without one)
   +0.20  seen by two or more sources
   +0.15  has a name (hostname, Dante name or controller alias)
   +0.10  manufacturer or model known
   +0.05  serial number known

``high`` ≥ 0.80, ``medium`` ≥ 0.50, else ``low``.

Match-to-existing score against a document device:

   +0.60  MAC equals an interface MAC          +0.60  serial equals inventory serial
   +0.30  IP equals an interface IP            +0.35  name / hostname / Dante name / alias equal (loose key)
   +0.10  model equal (only counts with another hit)
   ×0.20  both sides know a serial and they differ (a differing model is only noted: documents go stale on models)

``match`` ≥ 0.60, ``possible`` ≥ 0.35; the best-scoring device wins.

The *signals* come from :mod:`fathom.dedupe` (:func:`~fathom.dedupe.score_pair`
on the entity rendered as a device): the same key normalisation, exact-name /
alias / Dante-name / hostname detection and disagreement penalties the
device-merge UI uses, so a discovered host and a duplicate device are judged
by one rule book. Only the *weights* differ: a discovered sighting is weaker
evidence than two hand-entered devices (an IP alone is a lease, not an
identity), and dedupe's fuzzy name-similarity signals are left out here so a
``Lectern mic`` is never offered as a match for a ``Choir mic``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..model import norm_name
from ..network import normalize_mac
from .probes import Observation, ProbeResult

Doc = Dict[str, Any]

#: kind hints the probes emit -> Fathom device kinds (vocab A.1)
KIND_FOR_HINT: Dict[str, str] = {
    "switch": "switch", "ap": "network", "gateway": "network", "bridge": "network", "controller": "network", "nvr": "recorder",
    "network": "network", "dante": "stage_io", "client": "other", "wireless_client": "computer", "computer": "computer",
    "console": "console", "video_switcher": "video_switcher", "video_router": "video_router", "camera": "camera",
    "display": "display", "speaker": "speaker", "recorder": "recorder", "control": "control", "wireless_rx": "wireless_rx",
    "video": "video", "processor": "processor", "amp": "amp", "lighting_console": "lighting_console", "dmx_node": "dmx_node",
    "other": "other", "encoder": "encoder", "video_source": "video_source", "projector": "projector", "intercom": "intercom",
}

GENERIC_HOSTNAMES = frozenset({"localhost", "unknown", "android", "iphone", "ipad", "macbook", "pc", "laptop", "device", "host"})

LEVELS = (("high", 0.80), ("medium", 0.50), ("low", 0.0))

_CONSOLE_RE = re.compile(r"\b(cl[135]|ql[15]|tf[135]|tf-?rack|dm[37]|rivage|pm[0-9]|m32|x32|wing|sq-?[567]|dlive|avantis|s6l|digico)\b", re.I)
_STAGE_IO_RE = re.compile(r"\b(rio|tio|ri8|ro8|rsio|dl16|dl32|dx168|dx32|sd-?rack|d-?rack|dante.?(io|ip|box))\b", re.I)
_WIRELESS_RE = re.compile(r"\b(ulxd|axt|ad4|qlxd|slxd|ur4|ew-?dx|em\s?6000|d2|psm|p10t)\b", re.I)
_AMP_RE = re.compile(r"\b(amp|pld|cxd|dpa|d80|d40|d20|xti|ipd|ipa|ipx|30d|10d)\b", re.I)


def level_for(score: float) -> str:
    for name, minimum in LEVELS:
        if score >= minimum:
            return name
    return "low"


def loose(text: str) -> str:
    """Loose match key: strip a trailing ``.local``, keep letters and digits."""
    t = (text or "").strip().rstrip(".")
    if t.lower().endswith(".local"):
        t = t[: -len(".local")]
    return norm_name(t)


def _good_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_unspecified or a.is_multicast or a.is_loopback)


def _good_host(host: str) -> bool:
    key = loose(host)
    return len(key) >= 3 and key not in GENERIC_HOSTNAMES


# ------------------------------------------------------------------ union-find


class _Union:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _keys(o: Observation) -> List[str]:
    keys: List[str] = []
    for m in [o.mac] + list(o.extra_macs):
        if m:
            keys.append("mac:" + m)
    if o.ip and _good_ip(o.ip):
        keys.append("ip:" + o.ip)
    if o.hostname and _good_host(o.hostname):
        keys.append("host:" + loose(o.hostname))
    if o.dante_name and _good_host(o.dante_name):
        keys.append("host:" + loose(o.dante_name))
    if o.serial and len(o.serial.strip()) >= 4:
        keys.append("serial:" + o.serial.strip().lower())
    return keys


# ------------------------------------------------------------------ entities


@dataclass
class Entity:
    id: str
    macs: List[str] = field(default_factory=list)
    ips: List[str] = field(default_factory=list)
    hostname: str = ""
    name: str = ""
    dante_name: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    vlan: Optional[int] = None
    network: str = ""
    kind: str = "other"
    kind_hint: str = ""
    sources: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    #: per-MAC uplinks reported by a controller: [{mac, switch_mac, port, source}]
    uplinks: List[Dict[str, Any]] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)  # switches only
    observations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    level: str = "low"
    reasons: List[str] = field(default_factory=list)
    match: Optional[Dict[str, Any]] = None
    status: str = "new"  # new | match | possible | unresolved
    seen: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def label(self) -> str:
        return self.name or self.dante_name or self.hostname or (self.ips[0] if self.ips else "") or (self.macs[0] if self.macs else self.id)


def _pick(cur: str, new: str) -> str:
    return cur if cur else (new or "")


def _entity_id(obs: Sequence[Observation]) -> str:
    macs = sorted({m for o in obs for m in [o.mac] + list(o.extra_macs) if m})
    if macs:
        return "disc-" + macs[0].replace(":", "")
    for attr in ("dante_name", "hostname", "serial", "ip"):
        vals = sorted({loose(getattr(o, attr)) or getattr(o, attr) for o in obs if getattr(o, attr)})
        if vals:
            return "disc-" + hashlib.sha1(("%s=%s" % (attr, vals[0])).encode("utf-8")).hexdigest()[:10]
    return "disc-" + hashlib.sha1(repr(sorted(o.to_dict().items() for o in obs)[:1]).encode("utf-8")).hexdigest()[:10]


def infer_kind(hint: str, manufacturer: str = "", model: str = "", name: str = "", services: Iterable[str] = ()) -> str:
    """Fathom device kind for a probe hint plus whatever we know about the box."""
    text = " ".join([manufacturer or "", model or "", name or ""])
    if hint in ("dante", "client", "wireless_client", "", "other", "network") or hint not in KIND_FOR_HINT:
        if _CONSOLE_RE.search(text):
            return "console"
        if _STAGE_IO_RE.search(text):
            return "stage_io"
        if _WIRELESS_RE.search(text):
            return "wireless_rx"
        if _AMP_RE.search(text) and hint == "dante":
            return "amp"
        low = text.lower()
        if hint == "dante":
            if "shure" in low:
                return "wireless_rx"
            if "q-sys" in low or "qsys" in low or "tesira" in low or "symetrix" in low or "biamp" in low or "dsp" in low:
                return "processor"
            if "computer" in low or "dvs" in low or "virtual" in low or "via" in low:
                return "computer"
            return "stage_io"
        if hint == "client":
            svcs = " ".join(services).lower()
            if "_ssh." in svcs or "_workstation." in svcs or "_smb." in svcs or "_rdp." in svcs:
                return "computer"
            if "apple" in low or "dell" in low or "lenovo" in low or "hp inc" in low or "microsoft" in low or "intel" in low:
                return "computer"
            if "blackmagic" in low:
                return "video"
            if "crestron" in low or "extron" in low or "amx" in low or "qsc" in low:
                return "control"
            return "other"
    return KIND_FOR_HINT.get(hint, "other")


def build_entities(results: Iterable[ProbeResult]) -> List[Entity]:
    """Group observations from all probes into one entity per host."""
    obs: List[Observation] = []
    for r in results:
        obs.extend(r.observations)
    if not obs:
        return []
    uf = _Union(len(obs))
    first: Dict[str, int] = {}
    for i, o in enumerate(obs):
        for k in _keys(o):
            j = first.setdefault(k, i)
            if j != i:
                uf.union(i, j)
    groups: Dict[int, List[Observation]] = {}
    for i, o in enumerate(obs):
        groups.setdefault(uf.find(i), []).append(o)

    entities: List[Entity] = []
    seen_ids: Dict[str, int] = {}
    for members in groups.values():
        # controller + LLDP sightings first: they carry the most structure
        members.sort(key=lambda o: ({"unifi": 0, "lldp": 1, "mdns": 2, "arp": 3}.get(o.source, 9)))
        eid = _entity_id(members)
        if eid in seen_ids:  # defensive: never two entities with one id
            seen_ids[eid] += 1
            eid = f"{eid}-{seen_ids[eid]}"
        else:
            seen_ids[eid] = 1
        e = Entity(id=eid)
        for o in members:
            for m in [o.mac] + list(o.extra_macs):
                if m and m not in e.macs:
                    e.macs.append(m)
            if o.ip and _good_ip(o.ip) and o.ip not in e.ips:
                e.ips.append(o.ip)
            e.hostname = _pick(e.hostname, o.hostname)
            e.dante_name = _pick(e.dante_name, o.dante_name)
            e.name = _pick(e.name, o.name)
            e.manufacturer = _pick(e.manufacturer, o.manufacturer)
            e.model = _pick(e.model, o.model)
            e.serial = _pick(e.serial, o.serial)
            e.firmware = _pick(e.firmware, o.firmware)
            e.network = _pick(e.network, o.network)
            e.seen = e.seen or o.seen
            if e.vlan is None and o.vlan is not None:
                e.vlan = o.vlan
            if o.source not in e.sources:
                e.sources.append(o.source)
            for s in o.services:
                if s not in e.services:
                    e.services.append(s)
            if o.uplink_mac:
                up = {"mac": o.mac, "switch_mac": o.uplink_mac, "port": o.uplink_port, "source": o.source}
                if up not in e.uplinks:
                    e.uplinks.append(up)
            if o.ports and not e.ports:
                e.ports = list(o.ports)
            # the most specific hint wins: switch/ap/gateway > dante > named kinds > client
            rank = {"switch": 0, "ap": 1, "gateway": 1, "dante": 2}
            if not e.kind_hint or rank.get(o.kind_hint, 3 if o.kind_hint not in ("", "client", "wireless_client", "other", "network") else 5) < rank.get(e.kind_hint, 5):
                e.kind_hint = o.kind_hint or e.kind_hint
            e.observations.append({
                "source": o.source, "mac": o.mac, "ip": o.ip, "hostname": o.hostname, "name": o.name, "dante_name": o.dante_name,
                "manufacturer": o.manufacturer, "model": o.model, "serial": o.serial, "vlan": o.vlan,
                "kind_hint": o.kind_hint, "uplink": (o.uplink_mac + (" " + o.uplink_port if o.uplink_port else "")) if o.uplink_mac else "",
                "evidence": o.evidence,
            })
        if not e.name:
            e.name = e.dante_name or e.hostname
        e.kind = infer_kind(e.kind_hint, e.manufacturer, e.model, e.name or e.hostname, e.services)
        score_entity(e)
        entities.append(e)
    entities.sort(key=lambda x: (-x.confidence, x.label.lower()))
    return entities


def score_entity(e: Entity) -> None:
    score, reasons = 0.0, []
    if e.macs:
        score += 0.50
        reasons.append("MAC address known")
    else:
        score += 0.25
    if len(e.sources) >= 2:
        score += 0.20
        reasons.append("seen by %d sources (%s)" % (len(e.sources), ", ".join(e.sources)))
    if e.hostname or e.dante_name or e.name:
        score += 0.15
        reasons.append("named")
    if e.manufacturer or e.model:
        score += 0.10
        reasons.append("manufacturer / model known")
    if e.serial:
        score += 0.05
        reasons.append("serial known")
    e.confidence = round(min(1.0, score), 2)
    e.level = level_for(e.confidence)
    e.reasons = reasons
    if not e.macs and not (e.hostname or e.dante_name or e.name):
        e.status = "unresolved"


# ------------------------------------------------------------------ matching against the document


class DocIndex:
    """Lookup tables over the project's devices for match scoring."""

    def __init__(self, doc: Doc) -> None:
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.by_mac: Dict[str, str] = {}
        self.by_ip: Dict[str, str] = {}
        self.by_serial: Dict[str, str] = {}
        self.by_name: Dict[str, List[str]] = {}
        self.by_model: Dict[str, List[str]] = {}
        for d in doc.get("devices") or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            did = str(d["id"])
            self.devices[did] = d
            for itf in d.get("interfaces") or []:
                if not isinstance(itf, dict):
                    continue
                m = normalize_mac(str(itf.get("mac") or ""))
                if m:
                    self.by_mac.setdefault(m, did)
                ip = str(itf.get("ip") or "").strip()
                if ip and _good_ip(ip):
                    self.by_ip.setdefault(ip, did)
                if itf.get("hostname") and _good_host(str(itf["hostname"])):
                    self._name(loose(str(itf["hostname"])), did)
            inv = d.get("inventory") or {}
            if isinstance(inv, dict) and inv.get("serial") and len(str(inv["serial"]).strip()) >= 4:
                self.by_serial.setdefault(str(inv["serial"]).strip().lower(), did)
            for n in [d.get("name"), d.get("dante_name"), did] + list(d.get("aliases") or []):
                if n and _good_host(str(n)):
                    self._name(loose(str(n)), did)
            if d.get("model"):
                self.by_model.setdefault(loose(str(d["model"])), []).append(did)

    def _name(self, key: str, did: str) -> None:
        lst = self.by_name.setdefault(key, [])
        if did not in lst:
            lst.append(did)

    def candidates(self, e: Entity) -> List[str]:
        """Document devices worth scoring: anything sharing a MAC, serial, IP, name key or model with the entity."""
        out: List[str] = []

        def add(did: Optional[str]) -> None:
            if did and did not in out:
                out.append(did)

        for m in e.macs:
            add(self.by_mac.get(m))
        if e.serial:
            add(self.by_serial.get(e.serial.strip().lower()))
        for ip in e.ips:
            add(self.by_ip.get(ip))
        for val in (e.dante_name, e.hostname, e.name):
            if val and _good_host(val):
                for did in self.by_name.get(loose(val), []):
                    add(did)
        if e.model:
            for did in self.by_model.get(loose(e.model), []):
                add(did)
        return out

    def score(self, e: Entity) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
        """Discovery weights applied to the signals :func:`fathom.dedupe.score_pair` finds between the entity and each candidate."""
        from .. import dedupe

        scores: Dict[str, float] = {}
        why: Dict[str, List[str]] = {}
        edev = entity_as_device(e)
        ke = dedupe._keys(edev)
        for did in self.candidates(e):
            dev = self.devices[did]
            _, reasons = dedupe.score_pair(edev, dev)
            signals = {r["signal"] for r in reasons}
            kd = dedupe._keys(dev)
            pts, reason_list = 0.0, []
            for m in e.macs:
                if m in (ke["mac"] & kd["mac"]):
                    pts += 0.60
                    reason_list.append(f"MAC {m}")
            if "serial" in signals:
                pts += 0.60
                reason_list.append(f"serial {e.serial}")
            for ip in e.ips:
                if ip in (ke["ip"] & kd["ip"]):
                    pts += 0.30
                    reason_list.append(f"IP {ip}")
            named = _name_signal(e, signals, ke, kd)
            if named:
                pts += 0.35
                reason_list.append(named)
            if "model" in signals and pts > 0:
                pts += 0.10
                reason_list.append(f"model {e.model}")
            if pts <= 0:
                continue  # model alone (or a fuzzy name) never matches
            if "serial_differs" in signals:
                pts *= 0.20
                reason_list.append("but the serial numbers differ")
            if "model_differs" in signals:  # the document is often out of date on exactly this; say so, do not punish it
                reason_list.append(f"model differs ({e.model} vs {dev.get('model')})")
            scores[did] = round(pts, 2)
            why[did] = reason_list
        return scores, why


def entity_as_device(e: Entity) -> Dict[str, Any]:
    """The entity in document-device shape, so :mod:`fathom.dedupe` can compare it with real devices."""
    itfs: List[Dict[str, Any]] = []
    for mac in e.macs:
        itfs.append({"mac": mac, "hostname": e.hostname})
    for ip in e.ips:
        itfs.append({"ip": ip, "hostname": e.hostname})
    if not itfs and e.hostname:
        itfs.append({"hostname": e.hostname})
    aliases = [x for x in (e.hostname, e.dante_name) if x and _good_host(x) and loose(x) != loose(e.name)]
    dev: Dict[str, Any] = {"id": e.id, "name": e.name or e.hostname or e.dante_name, "kind": e.kind, "manufacturer": e.manufacturer, "model": e.model,
                           "dante_name": e.dante_name, "aliases": aliases, "interfaces": itfs}
    if e.serial and len(e.serial.strip()) >= 4:
        dev["inventory"] = {"serial": e.serial}
    return dev


def _name_signal(e: Entity, signals: set, ke: Dict[str, set], kd: Dict[str, set]) -> str:
    """One reason string for an exact name-family hit (Dante name, hostname, alias, name), or ``""``."""
    doc_names = kd["name"] | kd["aliases"] | kd["dante_name"]
    if "dante_name" in signals and e.dante_name and _good_host(e.dante_name):
        return f"Dante name {e.dante_name}"
    if "hostname" in signals or (e.hostname and _good_host(e.hostname) and loose(e.hostname) in doc_names):
        return f"hostname {e.hostname}"
    if ("alias" in signals or "name" in signals) and e.name and _good_host(e.name) and loose(e.name) in doc_names:
        return f"name {e.name}"
    if "alias" in signals and e.dante_name and _good_host(e.dante_name) and loose(e.dante_name) in doc_names:
        return f"Dante name {e.dante_name}"
    return ""


def match_entities(entities: List[Entity], doc: Doc) -> None:
    """Attach ``match`` / ``status`` to every entity (in place)."""
    idx = DocIndex(doc)
    for e in entities:
        if e.status == "unresolved":
            e.match = None
            continue
        scores, why = idx.score(e)
        if not scores:
            e.match, e.status = None, "new"
            continue
        best = max(scores.items(), key=lambda kv: (kv[1], kv[0]))
        did, score = best
        dev = idx.devices[did]
        score = round(min(1.0, score), 2)
        status = "match" if score >= 0.60 else ("possible" if score >= 0.35 else "new")
        e.match = {
            "device": did, "name": dev.get("name", did), "kind": dev.get("kind", ""), "room": dev.get("room", ""),
            "score": score, "level": level_for(score), "reasons": why.get(did, []),
            "others": [{"device": d, "name": idx.devices[d].get("name", d), "score": round(min(1.0, s), 2)} for d, s in sorted(scores.items(), key=lambda kv: -kv[1]) if d != did][:3],
        } if status != "new" else None
        e.status = status


def correlate(results: Iterable[ProbeResult], doc: Optional[Doc] = None) -> List[Entity]:
    """Entities for a run, matched against ``doc`` when given."""
    entities = build_entities(list(results))
    if doc is not None:
        match_entities(entities, doc)
    return entities


__all__ = ["DocIndex", "Entity", "KIND_FOR_HINT", "build_entities", "correlate", "entity_as_device", "infer_kind", "level_for", "loose", "match_entities", "score_entity"]
