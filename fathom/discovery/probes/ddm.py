"""Dante Domain Manager: read-only GraphQL query for the enrolled devices and
their subscriptions (active, opt-in — only the DDM server is contacted).

DDM exposes a GraphQL API (``https://<ddm>/graphql``, API key from
*Settings › API* sent as a bearer token). One query lists the domains, the
devices enrolled in each (name, manufacturer / product, interfaces with MAC
and address) and every receive channel with the transmitter it is
subscribed to. This is the only documented programmatic route to Dante
subscriptions: Dante Controller has no public API, so on sites without DDM
the preset-XML import remains the way to get full Dante routing into Fathom
(the Discovery view says so).

The query is read-only (GraphQL ``query``, never a ``mutation``), is sent
to the configured DDM URL only, and nothing is sent to the Dante devices
themselves. Maturity is *experimental*: the field set follows the public
DDM API v1 schema and is parsed tolerantly (missing fields are skipped), but
it has only been exercised against the recorded fixture, not a live DDM.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from ...network import normalize_mac
from . import ACTIVE, Observation, ProbeInfo, ProbeResult, fixture_payload

INFO = ProbeInfo(
    id="ddm", label="Dante Domain Manager (GraphQL)", mode=ACTIVE, maturity="experimental", default_enabled=False, targets="url",
    help="Asks the Dante Domain Manager for the devices enrolled in each domain (name, manufacturer, model, interfaces) and their current subscriptions. "
         "Without a DDM, Dante routing still comes from the Dante Controller preset-XML import.",
    sends="One HTTPS POST to <DDM URL>/graphql with a read-only GraphQL query (domains → devices → interfaces, rx/tx channels, subscriptions), "
          "authenticated with the API key as a bearer token. Nothing is sent to Dante devices and no mutation is ever issued.",
    needs=[],
    fields=[
        {"key": "url", "label": "DDM URL", "placeholder": "https://ddm.campus.local", "env": "FATHOM_DDM_URL", "help": "The Dante Domain Manager web address (the /graphql path is added)."},
        {"key": "api_key", "label": "API key", "secret": True, "env": "FATHOM_DDM_API_KEY", "help": "Settings › API in DDM; a read-only key is enough."},
        {"key": "verify_tls", "label": "Verify TLS certificate", "type": "check", "default": False, "env": "FATHOM_DDM_VERIFY_TLS"},
    ],
)

TIMEOUT = 15.0
MAX_BYTES = 8 * 1024 * 1024

# One read-only query. Field names follow the public DDM API v1 schema; unknown fields are tolerated by the parser.
QUERY = """
query FathomDiscovery {
  domains {
    id
    name
    devices {
      id
      name
      enrolmentState
      identity { manufacturer product productVersion danteVersion }
      interfaces { macAddress address netmask subnet }
      status { connectivity subscriptions clocking }
      rxChannels { index name subscribedDevice subscribedChannel status }
      txChannels { index name }
    }
  }
}
""".strip()


class DdmError(Exception):
    pass


def _settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    s = settings or {}
    url = str(s.get("url") or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    return {"url": url, "api_key": str(s.get("api_key") or ""), "verify_tls": bool(s.get("verify_tls")), "timeout": float(s.get("timeout") or TIMEOUT)}


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or ""


def _post_graphql(url: str, api_key: str, verify_tls: bool, timeout: float, query: str) -> Dict[str, Any]:
    """POST ``query`` to ``<url>/graphql``; returns the decoded JSON body or raises :class:`DdmError`."""
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    opener = request.build_opener(request.HTTPSHandler(context=ctx))
    body = json.dumps({"query": query, "operationName": "FathomDiscovery"}).encode("utf-8")
    req = request.Request(url + "/graphql", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES)
            status = resp.status
    except error.HTTPError as exc:
        raw, status = exc.read(MAX_BYTES), exc.code
    except (error.URLError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as exc:
        raise DdmError(f"cannot reach {url}: {getattr(exc, 'reason', exc)}")
    if status in (401, 403):
        raise DdmError(f"DDM rejected the API key ({status})")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except ValueError:
        raise DdmError(f"DDM answered HTTP {status} with something that is not JSON (is this the DDM URL?)")
    if status != 200:
        raise DdmError(f"DDM answered HTTP {status}: {str(payload)[:200]}")
    if not isinstance(payload, dict):
        raise DdmError("unexpected GraphQL response")
    if payload.get("errors") and not payload.get("data"):
        msgs = "; ".join(str(e.get("message") or e) for e in payload["errors"] if isinstance(e, dict))
        raise DdmError(f"GraphQL error: {msgs or payload['errors']}")
    return payload


def collect(settings: Dict[str, Any], job: Any = None) -> Dict[str, Any]:
    """Run the query against the configured DDM (or replay the fixture). Raises :class:`DdmError`."""
    fx = fixture_payload(INFO.id)
    if fx is not None:
        return fx
    s = _settings(settings)
    if not s["url"]:
        raise DdmError("no DDM URL configured")
    if not s["api_key"]:
        raise DdmError("no DDM API key configured")
    if job is not None:
        job.log(f"ddm: querying {s['url']}/graphql (read-only; Dante devices are not contacted)")
    payload = _post_graphql(s["url"], s["api_key"], s["verify_tls"], s["timeout"], QUERY)
    out: Dict[str, Any] = {"url": s["url"], "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data": payload.get("data") or {}}
    if payload.get("errors"):
        out["errors"] = [str(e.get("message") or e) for e in payload["errors"] if isinstance(e, dict)]
    return out


def test(settings: Dict[str, Any]) -> Dict[str, Any]:
    fx = fixture_payload(INFO.id)
    if fx is not None:
        res = parse(fx)
        return {"ok": True, "message": f"fixture replay: {len(res.observations)} devices, {res.stats.get('subscriptions', 0)} subscriptions", "fixture": True}
    s = _settings(settings)
    if not s["url"]:
        return {"ok": False, "message": "Set the DDM URL first."}
    if not s["api_key"]:
        return {"ok": False, "message": "Set the DDM API key first."}
    try:
        payload = _post_graphql(s["url"], s["api_key"], s["verify_tls"], s["timeout"], "query FathomDiscovery { domains { id name } }")
    except DdmError as exc:
        return {"ok": False, "message": str(exc)}
    domains = [d for d in ((payload.get("data") or {}).get("domains") or []) if isinstance(d, dict)]
    names = ", ".join(str(d.get("name") or d.get("id") or "?") for d in domains[:6])
    return {"ok": True, "message": f"{len(domains)} domain{'s' if len(domains) != 1 else ''}" + (f": {names}" if names else ""), "domains": len(domains)}


# ------------------------------------------------------------------ parse


def _devices(raw: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """``(domain name, device)`` pairs from a payload, whatever of ``data.domains`` / ``domains`` / ``devices`` it carries."""
    data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
    out: List[Tuple[str, Dict[str, Any]]] = []
    if not isinstance(data, dict):
        return out
    for dom in data.get("domains") or []:
        if not isinstance(dom, dict):
            continue
        dname = str(dom.get("name") or dom.get("id") or "")
        for dev in dom.get("devices") or []:
            if isinstance(dev, dict):
                out.append((dname, dev))
    for dev in data.get("devices") or []:
        if isinstance(dev, dict):
            out.append(("", dev))
    return out


def parse(raw: Any, settings: Optional[Dict[str, Any]] = None) -> ProbeResult:
    res = ProbeResult(probe=INFO.id)
    if not isinstance(raw, dict):
        res.status = "error"
        res.notes.append("ddm: payload is not an object")
        return res
    seen = str(raw.get("fetched") or "")
    subs_total = 0
    domains: Dict[str, int] = {}
    for dname, dev in _devices(raw):
        ident = dev.get("identity") if isinstance(dev.get("identity"), dict) else {}
        ifaces = [i for i in dev.get("interfaces") or [] if isinstance(i, dict)]
        macs = [m for m in (normalize_mac(str(i.get("macAddress") or "")) or "" for i in ifaces) if m]
        ips = [str(i.get("address") or "").strip() for i in ifaces if i.get("address")]
        name = str(dev.get("name") or "").strip()
        if not macs and not name:
            continue
        subs = []
        for ch in dev.get("rxChannels") or []:
            if not isinstance(ch, dict) or not ch.get("subscribedDevice"):
                continue
            subs.append({"rx": str(ch.get("name") or ch.get("index") or ""), "tx_device": str(ch.get("subscribedDevice") or ""),
                         "tx_channel": str(ch.get("subscribedChannel") or ""), "status": str(ch.get("status") or "")})
        subs_total += len(subs)
        status = dev.get("status") if isinstance(dev.get("status"), dict) else {}
        res.observations.append(Observation(
            source=INFO.id, mac=macs[0] if macs else "", extra_macs=macs[1:], ip=ips[0] if ips else "", dante_name=name, name=name,
            manufacturer=str(ident.get("manufacturer") or ""), model=str(ident.get("product") or ""), firmware=str(ident.get("productVersion") or ""),
            kind_hint="dante", services=["dante"], seen=seen,
            evidence={"domain": dname, "ddm_id": dev.get("id"), "enrolment": dev.get("enrolmentState"), "dante_version": ident.get("danteVersion"),
                      "connectivity": status.get("connectivity"), "rx_channels": len(dev.get("rxChannels") or []), "tx_channels": len(dev.get("txChannels") or []),
                      "subscriptions": subs, "addresses": ips},
        ))
        domains[dname] = domains.get(dname, 0) + 1
    res.stats = {"devices": len(res.observations), "subscriptions": subs_total, "domains": len(domains)}
    if raw.get("errors"):
        res.notes.append("ddm: partial answer: " + "; ".join(str(e) for e in raw["errors"])[:300])
    if res.observations:
        res.notes.append(f"ddm: {len(res.observations)} enrolled Dante devices in {len(domains)} domain{'s' if len(domains) != 1 else ''}, {subs_total} subscriptions "
                         "(kept as evidence; full Dante routing still comes from the preset-XML import)")
    else:
        res.status = "error" if not _devices(raw) and not raw.get("data") else "ok"
        res.notes.append("ddm: no enrolled devices in the answer")
    return res


__all__ = ["DdmError", "INFO", "QUERY", "TIMEOUT", "collect", "parse", "test"]
