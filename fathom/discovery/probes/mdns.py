"""mDNS / DNS-SD listen: Dante devices, AV services and generic services
advertised on the local link during the run window (passive).

Browsing is the standard multicast query every Dante Controller, printer
dialog and AirPlay picker sends; nothing is addressed to a device directly.
Needs the ``zeroconf`` package (``pip install 'fathom-audio[discovery]'``);
the probe degrades to a note when it is missing. Recorded payloads replay
through :func:`parse`, so the fixtures in ``tests/fixtures/discovery`` and
``FATHOM_DISCOVERY_FIXTURES`` need no network.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ...network import normalize_mac
from . import PASSIVE, Observation, ProbeInfo, ProbeResult, fixture_delay, fixture_payload

INFO = ProbeInfo(
    id="mdns", label="mDNS / Dante listen", mode=PASSIVE, maturity="experimental",
    help="Listens for Dante (_netaudio-*), AV (Blackmagic, Sennheiser SSC, NDI, AirPlay …) and generic (_http, _ssh, printers) service announcements for the run window. Dante name, IP, often manufacturer and model.",
    sends="Standard multicast DNS-SD queries to 224.0.0.251:5353 (what Dante Controller does). Nothing unicast to any device.",
    needs=["zeroconf"],
    fields=[
        {"key": "extra_services", "label": "Extra service types", "placeholder": "_myvendor._tcp.local., …", "help": "Comma-separated DNS-SD types to browse in addition to the built-in list."},
        {"key": "discover_types", "label": "Also enumerate advertised service types", "type": "check", "default": True},
        {"key": "interface_ip", "label": "Listen on interface (IP)", "placeholder": "all interfaces", "env": "FATHOM_DISCOVERY_INTERFACE_IP"},
    ],
)

DANTE_TYPES = ("_netaudio-arc._udp.local.", "_netaudio-chan._udp.local.", "_netaudio-cmc._udp.local.", "_netaudio-dbc._udp.local.")
# service type -> (manufacturer hint, kind hint)
AV_TYPES: Dict[str, Tuple[str, str]] = {
    "_blackmagic._tcp.local.": ("Blackmagic Design", "video"),
    "_videohub._tcp.local.": ("Blackmagic Design", "video_router"),
    "_ssc._udp.local.": ("Sennheiser", "wireless_rx"),
    "_ndi._tcp.local.": ("", "video_source"),
    "_airplay._tcp.local.": ("", "display"),
    "_raop._tcp.local.": ("", "speaker"),
    "_googlecast._tcp.local.": ("Google", "display"),
    "_sonos._tcp.local.": ("Sonos", "speaker"),
    "_qlab._tcp.local.": ("Figure 53", "computer"),
    "_osc._udp.local.": ("", "control"),
    "_shure._tcp.local.": ("Shure", "wireless_rx"),
}
GENERIC_TYPES: Dict[str, str] = {
    "_http._tcp.local.": "", "_https._tcp.local.": "", "_ssh._tcp.local.": "computer", "_sftp-ssh._tcp.local.": "computer",
    "_workstation._tcp.local.": "computer", "_smb._tcp.local.": "computer", "_afpovertcp._tcp.local.": "computer",
    "_device-info._tcp.local.": "computer", "_companion-link._tcp.local.": "computer", "_rdlink._tcp.local.": "computer",
    "_printer._tcp.local.": "other", "_ipp._tcp.local.": "other", "_ipps._tcp.local.": "other", "_pdl-datastream._tcp.local.": "other",
    "_rtsp._tcp.local.": "camera", "_hap._tcp.local.": "other", "_homekit._tcp.local.": "other",
}
BLACKMAGIC_CLASSES = {"atemswitcher": "video_switcher", "videohub": "video_router", "hyperdeck": "recorder", "webpresenter": "encoder", "teranex": "converter", "smartview": "display"}
_NAME_RE = re.compile(r"^(?P<inst>.+?)\.(?P<type>_[^.]+\._(?:tcp|udp)\.local\.?)$")


def default_types(settings: Optional[Dict[str, Any]] = None) -> List[str]:
    out = list(DANTE_TYPES) + list(AV_TYPES) + list(GENERIC_TYPES)
    for t in str((settings or {}).get("extra_services") or "").replace(";", ",").split(","):
        t = t.strip()
        if not t:
            continue
        if not t.endswith("."):
            t += "."
        if not t.endswith(".local."):
            t = t.rstrip(".") + ".local."
        if t not in out:
            out.append(t)
    return out


def _decode(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return "" if v is None else str(v)


def available() -> Tuple[bool, str]:
    try:
        import zeroconf  # type: ignore

        return True, getattr(zeroconf, "__version__", "")
    except Exception:
        return False, ""


def collect(settings: Dict[str, Any], job: Any = None, window: float = 60.0) -> Dict[str, Any]:
    """Browse for ``window`` seconds and return the records heard (or replay a fixture)."""
    fx = fixture_payload(INFO.id)
    if fx is not None:
        if job is not None:
            job.wait(fixture_delay(window))
        return fx
    ok, version = available()
    if not ok:
        raise RuntimeError("the zeroconf package is not installed: pip install 'fathom-audio[discovery]'")
    from zeroconf import IPVersion, ServiceBrowser, Zeroconf, ZeroconfServiceTypes  # type: ignore

    s = settings or {}
    iface = str(s.get("interface_ip") or "").strip()
    zc = Zeroconf(ip_version=IPVersion.V4Only, interfaces=[iface] if iface else None) if iface else Zeroconf(ip_version=IPVersion.V4Only)
    records: Dict[Tuple[str, str], Dict[str, Any]] = {}
    pending: List[Tuple[str, str]] = []
    lock = threading.Lock()
    started = time.time()
    deadline = started + max(5.0, float(window))
    types = default_types(s)

    class _Listener:
        def add_service(self, zc_: Any, type_: str, name: str) -> None:
            with lock:
                pending.append((type_, name))

        def update_service(self, zc_: Any, type_: str, name: str) -> None:
            with lock:
                pending.append((type_, name))

        def remove_service(self, zc_: Any, type_: str, name: str) -> None:
            pass

    try:
        if s.get("discover_types", True) and (deadline - time.time()) > 8:
            try:
                found = ZeroconfServiceTypes.find(zc=zc, timeout=min(4.0, (deadline - time.time()) / 4))
                for t in found or ():
                    if t not in types:
                        types.append(t)
                if job is not None:
                    job.log(f"mdns: {len(found or ())} service types advertised on the link")
            except Exception as exc:  # enumeration is optional
                if job is not None:
                    job.log(f"mdns: type enumeration failed: {exc}", "warn")
        browser = ServiceBrowser(zc, types, listener=_Listener())
        while time.time() < deadline:
            if job is not None and job.cancelled:
                break
            with lock:
                todo, pending[:] = list(pending), []
            for type_, name in todo:
                try:
                    info = zc.get_service_info(type_, name, timeout=1500)
                except Exception:
                    info = None
                if info is None:
                    continue
                try:
                    addrs = list(info.parsed_scoped_addresses()) if hasattr(info, "parsed_scoped_addresses") else list(info.parsed_addresses())
                except Exception:
                    addrs = []
                props = {}
                for k, v in (info.properties or {}).items():
                    props[_decode(k)] = _decode(v)
                records[(type_, name)] = {"type": type_, "name": name, "server": _decode(getattr(info, "server", "")), "addresses": addrs,
                                         "port": getattr(info, "port", None), "properties": props, "heard": round(time.time() - started, 1)}
            if job is not None:
                job.set_progress(stage=f"mdns: {len(records)} services heard, {int(deadline - time.time())} s left")
                if job.wait(0.5):
                    break
            else:
                time.sleep(0.5)
        try:
            browser.cancel()
        except Exception:
            pass
    finally:
        try:
            zc.close()
        except Exception:
            pass
    return {"window": window, "types": types, "zeroconf": version, "records": list(records.values()),
            "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return {"ok": True, "message": f"fixture replay: {len(fx.get('records') or [])} service records", "fixture": True}
    ok, version = available()
    if not ok:
        return {"ok": False, "message": "zeroconf is not installed on the server: pip install 'fathom-audio[discovery]' into the server's venv and restart fathom.service.", "install": True}
    n = len(default_types(settings))
    iface = str((settings or {}).get("interface_ip") or "").strip()
    return {"ok": True, "message": f"zeroconf {version} ready; will browse {n} service types on {iface or 'all interfaces'} for the run window."}


# ------------------------------------------------------------------ parse


def _split(name: str) -> Tuple[str, str]:
    m = _NAME_RE.match(name or "")
    if not m:
        return name or "", ""
    inst = m.group("inst").replace("\\032", " ").replace("\\.", ".")
    t = m.group("type")
    return inst, t if t.endswith(".") else t + "."


def _dante(groups: Dict[str, List[Dict[str, Any]]], res: ProbeResult, seen: str) -> None:
    for inst, recs in groups.items():
        ips: List[str] = []
        mac = ""
        mf = model = ""
        services: List[str] = []
        txt: Dict[str, str] = {}
        for r in recs:
            t = str(r.get("type") or "")
            if t not in services:
                services.append(t)
            for a in r.get("addresses") or []:
                a = str(a).split("%")[0]
                if a and ":" not in a and a not in ips:
                    ips.append(a)
            props = r.get("properties") or {}
            for k, v in props.items():
                txt.setdefault(f"{t.split('.')[0]}:{k}", str(v))
            if t.startswith("_netaudio-cmc"):
                mf = mf or str(props.get("mf") or props.get("manufacturer") or "")
                model = model or str(props.get("model") or "")
                raw_id = str(props.get("id") or "")
                if normalize_mac(raw_id):
                    mac = mac or raw_id
            if t.startswith("_netaudio-arc"):
                info = str(props.get("router_info") or "")
                if info and not model:
                    model = info.replace("_", " ").strip('"')
        hostname = ""
        for r in recs:
            srv = str(r.get("server") or "").rstrip(".")
            if srv:
                hostname = srv[:-6] if srv.lower().endswith(".local") else srv
                break
        base = dict(source="mdns", dante_name=inst, name=inst, hostname=hostname, manufacturer=mf, model=model, kind_hint="dante", services=services, seen=seen)
        if not ips:
            res.observations.append(Observation(mac=mac, evidence={"txt": txt, "role": "primary"}, **base))
            continue
        for i, ip in enumerate(ips[:2]):
            role = "primary" if i == 0 else "secondary"
            res.observations.append(Observation(ip=ip, mac=mac if i == 0 else "", evidence={"txt": txt, "role": role, "ips": ips}, **base))
        if len(ips) > 2:
            res.notes.append(f"mdns: {inst} advertises {len(ips)} addresses; only two kept")


def _generic(groups: Dict[str, List[Dict[str, Any]]], res: ProbeResult, seen: str) -> None:
    for key, recs in groups.items():
        services: List[str] = []
        ips: List[str] = []
        names: List[str] = []
        mf = model = serial = ""
        kind = ""
        txt: Dict[str, str] = {}
        hostname = key[:-6] if key.lower().endswith(".local") else key
        for r in recs:
            t = str(r.get("type") or "")
            inst, _ = _split(str(r.get("name") or ""))
            if t not in services:
                services.append(t)
            if inst and inst not in names:
                names.append(inst)
            for a in r.get("addresses") or []:
                a = str(a).split("%")[0]
                if a and ":" not in a and a not in ips:
                    ips.append(a)
            props = {str(k): str(v) for k, v in (r.get("properties") or {}).items()}
            for k, v in props.items():
                txt.setdefault(f"{t.split('.')[0]}:{k}", v)
            hint_mf, hint_kind = AV_TYPES.get(t, ("", GENERIC_TYPES.get(t, "")))
            mf = mf or hint_mf or props.get("manufacturer") or props.get("vendor") or props.get("mf") or props.get("usb_MFG") or ""
            model = model or props.get("model") or props.get("md") or props.get("am") or props.get("ty") or props.get("usb_MDL") or props.get("product") or ""
            serial = serial or props.get("serial") or props.get("sn") or props.get("serialNumber") or ""
            if t == "_blackmagic._tcp.local.":
                cls = str(props.get("class") or "").lower()
                kind = kind or BLACKMAGIC_CLASSES.get(cls, "video")
                model = model or props.get("name") or ""
            kind = kind or hint_kind
        if not kind:
            kind = "computer" if any(s in services for s in ("_ssh._tcp.local.", "_workstation._tcp.local.", "_smb._tcp.local.")) else "other"
        res.observations.append(Observation(
            source="mdns", ip=ips[0] if ips else "", hostname=hostname, name=names[0] if names else hostname, manufacturer=mf, model=model, serial=serial,
            kind_hint=kind, services=services, seen=seen, evidence={"txt": txt, "ips": ips, "instances": names},
        ))


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("mdns: payload is not an object")
        return res
    seen = str(raw.get("fetched") or "")
    dante: Dict[str, List[Dict[str, Any]]] = {}
    other: Dict[str, List[Dict[str, Any]]] = {}
    n = 0
    for r in raw.get("records") or []:
        if not isinstance(r, dict):
            continue
        n += 1
        t = str(r.get("type") or "")
        inst, t2 = _split(str(r.get("name") or ""))
        t = t or t2
        r = dict(r, type=t)
        if t in DANTE_TYPES or t.startswith("_netaudio-"):
            dante.setdefault(inst, []).append(r)
        else:
            server = str(r.get("server") or "").rstrip(".") or inst
            other.setdefault(server, []).append(r)
    _dante(dante, res, seen)
    _generic(other, res, seen)
    res.stats = {"records": n, "dante_devices": len(dante), "hosts": len(other), "types": len(raw.get("types") or [])}
    if raw.get("window") is not None:
        res.stats["window"] = raw.get("window")
    return res


__all__ = ["AV_TYPES", "DANTE_TYPES", "GENERIC_TYPES", "INFO", "available", "collect", "default_types", "parse", "test"]
