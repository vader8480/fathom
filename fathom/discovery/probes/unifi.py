"""UniFi Network application: read-only pull of devices, port tables, LLDP
neighbours, clients and networks (passive — only the controller is contacted).

Works against a UniFi OS console (UDM / UDM-Pro / Cloud Key Gen2 / UNVR,
``https://<console>`` with the Network app under ``/proxy/network``) and the
classic software controller (``https://<host>:8443``). Authentication is an
API key (``X-API-KEY``, Network 9+ on UniFi OS) or a local user / password.
Everything is a GET on the controller; nothing talks to the switches, APs or
clients themselves. The stdlib HTTP client is used so this probe works
without the ``discovery`` extra.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import time
from http.cookiejar import CookieJar
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from ...network import normalize_mac
from . import PASSIVE, Neighbour, NetworkObs, Observation, ProbeInfo, ProbeResult, fixture_payload

INFO = ProbeInfo(
    id="unifi", label="UniFi Network controller", mode=PASSIVE, maturity="tested",
    help="Reads devices (switches, APs, gateways), per-port LLDP neighbours, wired clients with their switch port, and networks / VLANs from the UniFi Network API.",
    sends="HTTPS GET requests to the controller only (API key or login). Nothing is sent to switches, APs or clients.",
    needs=[],
    fields=[
        {"key": "url", "label": "Controller URL", "placeholder": "https://10.0.0.1 or https://unifi.local:8443", "env": "FATHOM_UNIFI_URL"},
        {"key": "site", "label": "Site", "placeholder": "default", "env": "FATHOM_UNIFI_SITE"},
        {"key": "api_key", "label": "API key", "secret": True, "env": "FATHOM_UNIFI_API_KEY", "help": "Settings › Control Plane › Integrations on the console. Preferred over a password."},
        {"key": "username", "label": "Username", "env": "FATHOM_UNIFI_USER", "help": "A local read-only admin (not a Ubiquiti cloud account)."},
        {"key": "password", "label": "Password", "secret": True, "env": "FATHOM_UNIFI_PASSWORD"},
        {"key": "verify_tls", "label": "Verify TLS certificate", "type": "check", "default": False, "env": "FATHOM_UNIFI_VERIFY_TLS"},
    ],
)

DEVICE_TYPES = {"usw": "switch", "uap": "ap", "ugw": "gateway", "udm": "gateway", "uxg": "gateway", "ubb": "bridge", "usg": "gateway", "uck": "controller", "unvr": "nvr"}
TIMEOUT = 12.0


class UnifiError(Exception):
    pass


class _Client:
    """Tiny cookie-aware HTTPS client for the two UniFi API flavours."""

    def __init__(self, url: str, site: str = "default", username: str = "", password: str = "", api_key: str = "", verify_tls: bool = False, timeout: float = TIMEOUT) -> None:
        self.base = (url or "").strip().rstrip("/")
        if self.base and "://" not in self.base:
            self.base = "https://" + self.base
        self.site = (site or "default").strip() or "default"
        self.username, self.password, self.api_key = username or "", password or "", api_key or ""
        self.timeout = timeout
        self.flavour = ""  # unifi-os | legacy
        self.csrf = ""
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()), request.HTTPSHandler(context=ctx))

    @property
    def host(self) -> str:
        from urllib.parse import urlsplit

        return urlsplit(self.base).hostname or ""

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-KEY", self.api_key)
        if self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                self.csrf = resp.headers.get("X-CSRF-Token") or self.csrf
                raw = resp.read()
                status = resp.status
        except error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except (error.URLError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise UnifiError(f"cannot reach {self.base}: {reason}")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except ValueError:
            payload = {"raw": raw[:200].decode("utf-8", "replace")}
        return status, payload

    def _api(self, path: str) -> str:
        prefix = "/proxy/network/api/s/" if self.flavour == "unifi-os" else "/api/s/"
        return f"{prefix}{self.site}/{path}"

    def login(self) -> str:
        if self.api_key:
            # Network 9+ accepts the key directly; probe both prefixes with a cheap call.
            for flavour in ("unifi-os", "legacy"):
                self.flavour = flavour
                st, payload = self._request("GET", self._api("self"))
                if st == 200:
                    return flavour
                if st in (401, 403):
                    raise UnifiError(f"the controller rejected the API key ({st})")
            raise UnifiError("API key auth needs a UniFi OS console running Network 9 or newer; use a username and password otherwise")
        if not self.username or not self.password:
            raise UnifiError("no credentials: set an API key or a username and password")
        creds = {"username": self.username, "password": self.password, "remember": False}
        st, payload = self._request("POST", "/api/auth/login", creds)
        if st == 200:
            self.flavour = "unifi-os"
            return self.flavour
        if st in (401, 403, 429):
            raise UnifiError(f"login failed on the UniFi OS console ({st}): {payload.get('message') or payload.get('msg') or 'check the username and password'}")
        st, payload = self._request("POST", "/api/login", creds)
        if st == 200:
            self.flavour = "legacy"
            return self.flavour
        meta = payload.get("meta") if isinstance(payload, dict) else None
        msg = (meta or {}).get("msg") if isinstance(meta, dict) else None
        raise UnifiError(f"login failed ({st}): {msg or 'check the URL, username and password'}")

    def get(self, path: str) -> List[Dict[str, Any]]:
        st, payload = self._request("GET", self._api(path))
        if st != 200:
            meta = payload.get("meta") if isinstance(payload, dict) else None
            msg = (meta or {}).get("msg") if isinstance(meta, dict) else payload
            raise UnifiError(f"{path}: HTTP {st} {msg}")
        data = payload.get("data") if isinstance(payload, dict) else payload
        return [d for d in (data or []) if isinstance(d, dict)]


def _settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    s = settings or {}
    return {
        "url": str(s.get("url") or ""), "site": str(s.get("site") or "default"), "username": str(s.get("username") or ""),
        "password": str(s.get("password") or ""), "api_key": str(s.get("api_key") or ""), "verify_tls": bool(s.get("verify_tls")),
        "timeout": float(s.get("timeout") or TIMEOUT),
    }


def collect(settings: Dict[str, Any], job: Any = None) -> Dict[str, Any]:
    """Pull the controller tables (or replay a fixture). Raises :class:`UnifiError`."""
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return fx
    s = _settings(settings)
    if not s["url"]:
        raise UnifiError("no controller URL configured")
    c = _Client(**s)
    flavour = c.login()
    if job is not None:
        job.log(f"unifi: logged in to {c.base} ({flavour}), site {c.site}")
    out: Dict[str, Any] = {"api": flavour, "site": c.site, "url": c.base, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out["devices"] = c.get("stat/device")
    if job is not None:
        job.check()
    out["clients"] = c.get("stat/sta")
    if job is not None:
        job.check()
    try:
        out["networks"] = c.get("rest/networkconf")
    except UnifiError as exc:
        out["networks"] = []
        out["notes"] = [f"networks not readable: {exc}"]
    return out


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return {"ok": True, "message": f"fixture replay: {len(fx.get('devices') or [])} devices, {len(fx.get('clients') or [])} clients", "fixture": True}
    s = _settings(settings)
    if not s["url"]:
        return {"ok": False, "message": "Set the controller URL first."}
    try:
        c = _Client(**s)
        flavour = c.login()
        devices = c.get("stat/device")
    except UnifiError as exc:
        return {"ok": False, "message": str(exc)}
    kinds: Dict[str, int] = {}
    for d in devices:
        k = DEVICE_TYPES.get(str(d.get("type") or ""), str(d.get("type") or "other"))
        kinds[k] = kinds.get(k, 0) + 1
    desc = ", ".join(f"{n} {k}{'es' if k == 'switch' and n != 1 else 's' if n != 1 else ''}" for k, n in sorted(kinds.items())) or "no devices"
    return {"ok": True, "message": f"{flavour} API, site '{c.site}': {desc}", "api": flavour, "devices": len(devices)}


# ------------------------------------------------------------------ parse


def _port_label(idx: Any, name: Any) -> str:
    try:
        n = int(idx)
    except (TypeError, ValueError):
        return str(name or "").strip()
    return f"Port {n}"


def _subnet(ip_subnet: str) -> Tuple[str, str]:
    """UniFi ``ip_subnet`` is the gateway address with the prefix (``10.6.9.1/24``)."""
    try:
        iface = ipaddress.ip_interface(str(ip_subnet))
    except ValueError:
        return "", ""
    return str(iface.network), str(iface.ip)


def _device_obs(d: Dict[str, Any], seen: str) -> Optional[Observation]:
    mac = normalize_mac(str(d.get("mac") or ""))
    if not mac:
        return None
    dtype = str(d.get("type") or "")
    ports = []
    for p in d.get("port_table") or []:
        if not isinstance(p, dict):
            continue
        idx = p.get("port_idx")
        if idx is None:
            continue
        ports.append({
            "idx": int(idx), "name": str(p.get("name") or _port_label(idx, "")), "up": bool(p.get("up")), "speed": p.get("speed"),
            "poe": bool(p.get("poe_enable")), "media": str(p.get("media") or ""), "sfp": bool(p.get("is_uplink")) or str(p.get("media") or "").upper() == "SFP",
        })
    obs = Observation(
        source="unifi", mac=mac, ip=str(d.get("ip") or ""), name=str(d.get("name") or d.get("hostname") or ""), hostname=str(d.get("hostname") or ""),
        manufacturer="Ubiquiti", model=str(d.get("model") or ""), serial=str(d.get("serial") or ""), firmware=str(d.get("version") or ""),
        kind_hint=DEVICE_TYPES.get(dtype, dtype or "network"), ports=ports, seen=seen,
        evidence={"type": dtype, "model": d.get("model"), "adopted": d.get("adopted"), "state": d.get("state"), "ports": len(ports), "uptime": d.get("uptime")},
    )
    if d.get("model_in_lts") or d.get("shortname"):
        obs.evidence["shortname"] = d.get("shortname") or d.get("model_in_lts")
    up = d.get("uplink") if isinstance(d.get("uplink"), dict) else {}
    if up.get("uplink_mac"):
        obs.uplink_mac = str(up.get("uplink_mac"))
        obs.uplink_port = _port_label(up.get("uplink_remote_port"), "")
    return obs


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("unifi: payload is not an object")
        return res
    seen = str(raw.get("fetched") or "")
    devices = [d for d in raw.get("devices") or [] if isinstance(d, dict)]
    clients = [c for c in raw.get("clients") or [] if isinstance(c, dict)]
    networks = [n for n in raw.get("networks") or [] if isinstance(n, dict)]
    names: Dict[str, str] = {}
    for d in devices:
        obs = _device_obs(d, seen)
        if obs is None:
            continue
        names[obs.mac] = obs.name or obs.model or obs.mac
        res.observations.append(obs)
    for d in devices:
        mac = normalize_mac(str(d.get("mac") or ""))
        if not mac:
            continue
        dname = names.get(mac, mac)
        for e in d.get("lldp_table") or []:
            if not isinstance(e, dict):
                continue
            chassis = str(e.get("chassis_id") or "")
            res.neighbours.append(Neighbour(
                source="unifi", method="unifi_lldp", local_mac=mac, local_name=dname,
                local_port=_port_label(e.get("local_port_idx"), e.get("local_port_name")),
                remote_mac=chassis if normalize_mac(chassis) else "", remote_name=str(e.get("chassis_name") or e.get("system_name") or ("" if normalize_mac(chassis) else chassis)),
                remote_port=str(e.get("port_id") or ""), evidence={"is_wired": e.get("is_wired"), "chassis_id": chassis},
            ))
        up = d.get("uplink") if isinstance(d.get("uplink"), dict) else {}
        if up.get("uplink_mac") and up.get("uplink_remote_port") is not None:
            umac = normalize_mac(str(up.get("uplink_mac"))) or ""
            if umac:
                res.neighbours.append(Neighbour(
                    source="unifi", method="unifi_uplink", local_mac=umac, local_name=names.get(umac, ""), local_port=_port_label(up.get("uplink_remote_port"), ""),
                    remote_mac=mac, remote_name=dname, remote_port=_port_label(up.get("port_idx"), "") if up.get("port_idx") is not None else "",
                    evidence={"type": up.get("type"), "speed": up.get("speed")},
                ))
        for p in d.get("port_table") or []:
            if not isinstance(p, dict) or not isinstance(p.get("mac_table"), list):
                continue
            for m in p["mac_table"]:
                if not isinstance(m, dict) or not normalize_mac(str(m.get("mac") or "")):
                    continue
                res.neighbours.append(Neighbour(
                    source="unifi", method="mac_table", local_mac=mac, local_name=dname, local_port=_port_label(p.get("port_idx"), p.get("name")),
                    remote_mac=str(m.get("mac")), remote_ip=str(m.get("ip") or ""), vlan=m.get("vlan") if isinstance(m.get("vlan"), int) else None,
                    evidence={"age": m.get("age"), "uptime": m.get("uptime")},
                ))
    wired = wireless = 0
    known_macs = {o.mac for o in res.observations} | {normalize_mac(str(c.get("mac") or "")) or "" for c in clients}
    for n in res.neighbours:  # addresses learned on a port but not in the client list (e.g. a Dante secondary interface): still a sighting
        if n.method != "mac_table" or not n.remote_mac or n.remote_mac in known_macs:
            continue
        known_macs.add(n.remote_mac)
        res.observations.append(Observation(
            source="unifi", mac=n.remote_mac, ip=n.remote_ip, vlan=n.vlan, kind_hint="client", uplink_mac=n.local_mac, uplink_port=n.local_port, seen=seen,
            evidence={"via": "mac_table", "switch": n.local_name, "port": n.local_port},
        ))
    for c in clients:
        mac = normalize_mac(str(c.get("mac") or ""))
        if not mac:
            continue
        is_wired = bool(c.get("is_wired"))
        vlan = c.get("vlan")
        obs = Observation(
            source="unifi", mac=mac, ip=str(c.get("ip") or c.get("fixed_ip") or ""), hostname=str(c.get("hostname") or ""), name=str(c.get("name") or ""),
            vlan=int(vlan) if isinstance(vlan, int) and vlan > 0 else None, network=str(c.get("network") or ""),
            kind_hint="client" if is_wired else "wireless_client", seen=seen,
            evidence={"oui": c.get("oui"), "is_wired": is_wired, "last_seen": c.get("last_seen"), "uptime": c.get("uptime"),
                      "dev_cat": c.get("dev_cat"), "os_name": c.get("os_name"), "essid": c.get("essid")},
        )
        if is_wired and c.get("sw_mac"):
            obs.uplink_mac = str(c.get("sw_mac"))
            obs.uplink_port = _port_label(c.get("sw_port"), "")
            wired += 1
            res.neighbours.append(Neighbour(
                source="unifi", method="unifi_client", local_mac=str(c.get("sw_mac")), local_name=names.get(normalize_mac(str(c.get("sw_mac"))) or "", ""),
                local_port=obs.uplink_port, remote_mac=mac, remote_name=obs.name or obs.hostname, remote_ip=obs.ip, vlan=obs.vlan,
                evidence={"sw_depth": c.get("sw_depth"), "last_seen": c.get("last_seen")},
            ))
        elif not is_wired and c.get("ap_mac"):
            obs.uplink_mac = str(c.get("ap_mac"))
            obs.uplink_port = "wifi"
            wireless += 1
        res.observations.append(obs)
    for n in networks:
        if n.get("enabled") is False:
            continue
        subnet, gateway = _subnet(str(n.get("ip_subnet") or ""))
        vlan = n.get("vlan")
        try:
            vlan_i: Optional[int] = int(vlan) if vlan not in (None, "") else None
        except (TypeError, ValueError):
            vlan_i = None
        if vlan_i is None and n.get("vlan_enabled") is False and subnet:
            vlan_i = 1 if n.get("purpose") == "corporate" else None
        dhcp = ""
        if n.get("dhcpd_enabled") and n.get("dhcpd_start") and n.get("dhcpd_stop"):
            dhcp = f"{n['dhcpd_start']}-{n['dhcpd_stop']}"
        res.networks.append(NetworkObs(
            source="unifi", name=str(n.get("name") or ""), vlan=vlan_i, subnet=subnet, gateway=gateway, purpose=str(n.get("purpose") or ""), dhcp_range=dhcp,
            evidence={"networkgroup": n.get("networkgroup"), "domain_name": n.get("domain_name"), "igmp_snooping": n.get("igmp_snooping")},
        ))
    res.stats = {"devices": len([o for o in res.observations if o.manufacturer == "Ubiquiti"]), "clients": len(clients), "wired_clients": wired,
                 "wireless_clients": wireless, "networks": len(res.networks), "lldp": len([n for n in res.neighbours if n.method == "unifi_lldp"]), "api": raw.get("api")}
    for note in raw.get("notes") or []:
        res.notes.append(f"unifi: {note}")
    return res


__all__ = ["INFO", "UnifiError", "collect", "parse", "test"]
