"""Per-project discovery settings.

Non-secret settings (controller URL, site, user, listen window, which probes
are enabled …) live in ``project.json`` under ``settings.discovery`` so they
travel with the project and show up in history like any other setting.

Secrets (UniFi API key / password) never enter the document or its history:
they are kept in ``<project>/discovery-secrets.json`` (mode 0600). The API
only ever reports ``<field>_set: true`` for them, and every value is also
redacted from log lines and snapshots by :func:`redact`.

Environment variables (``FATHOM_UNIFI_URL`` …, declared per field by the
probe) fill in anything the project leaves empty, so a Docker deployment can
be configured without touching the UI.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .probes import all_probes

Doc = Dict[str, Any]

DEFAULT_WINDOW = 60
MIN_WINDOW = 10
MAX_WINDOW = 300
SECRETS_FILE = "discovery-secrets.json"
REDACTED = "••••••••"


def _fields(probe_id: str) -> List[Dict[str, Any]]:
    for m in all_probes():
        if m.INFO.id == probe_id:
            return list(m.INFO.fields)
    return []


def secret_keys(probe_id: str) -> List[str]:
    return [str(f["key"]) for f in _fields(probe_id) if f.get("secret")]


def defaults() -> Dict[str, Any]:
    out: Dict[str, Any] = {"window": DEFAULT_WINDOW, "room": "", "probes": {}}
    for m in all_probes():
        p: Dict[str, Any] = {"enabled": True}
        for f in m.INFO.fields:
            if f.get("secret"):
                continue
            p[str(f["key"])] = f.get("default", "" if f.get("type") != "check" else False)
        out["probes"][m.INFO.id] = p
    return out


# ------------------------------------------------------------------ secrets file


def secrets_path(pdir: Path) -> Path:
    return Path(pdir) / SECRETS_FILE


def read_secrets(pdir: Path) -> Dict[str, Dict[str, str]]:
    p = secrets_path(pdir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: {kk: str(vv) for kk, vv in v.items()} for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def write_secrets(pdir: Path, data: Dict[str, Dict[str, str]]) -> None:
    p = secrets_path(pdir)
    clean = {k: {kk: vv for kk, vv in v.items() if vv} for k, v in data.items()}
    clean = {k: v for k, v in clean.items() if v}
    if not clean:
        if p.exists():
            p.unlink()
        return
    tmp = p.with_name("." + p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2)
    try:
        os.chmod(str(tmp), 0o600)
    except OSError:
        pass
    os.replace(str(tmp), str(p))


# ------------------------------------------------------------------ views


def stored(doc: Doc) -> Dict[str, Any]:
    """Settings as kept in the document (merged over defaults, no secrets, no env)."""
    out = defaults()
    raw = (doc.get("settings") or {}).get("discovery") if isinstance(doc.get("settings"), dict) else None
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("window"), (int, float)):
        out["window"] = _clamp_window(raw["window"])
    if isinstance(raw.get("room"), str):
        out["room"] = raw["room"]
    probes = raw.get("probes") if isinstance(raw.get("probes"), dict) else {}
    for pid, p in probes.items():
        if pid in out["probes"] and isinstance(p, dict):
            for k, v in p.items():
                if k in secret_keys(pid):
                    continue  # never trust a secret that leaked into the document
                out["probes"][pid][k] = v
    return out


def _clamp_window(v: Any) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW
    return max(MIN_WINDOW, min(MAX_WINDOW, n))


def public(doc: Doc, pdir: Optional[Path]) -> Dict[str, Any]:
    """What the API returns: stored settings plus ``<secret>_set`` flags and ``env`` hints; never a secret value."""
    out = stored(doc)
    sec = read_secrets(pdir) if pdir is not None else {}
    for m in all_probes():
        pid = m.INFO.id
        p = out["probes"][pid]
        for f in m.INFO.fields:
            key = str(f["key"])
            env = f.get("env")
            if f.get("secret"):
                p.pop(key, None)
                p[key + "_set"] = bool((sec.get(pid) or {}).get(key)) or bool(env and os.environ.get(env))
                p[key + "_from_env"] = bool(env and os.environ.get(env)) and not (sec.get(pid) or {}).get(key)
            elif env and not p.get(key) and os.environ.get(env):
                p[key + "_env"] = os.environ.get(env) if f.get("type") != "check" else _truthy(os.environ.get(env))
    return out


def effective(doc: Doc, pdir: Optional[Path]) -> Dict[str, Any]:
    """Settings for actually running: stored values, secrets from the side file, env fallbacks."""
    out = stored(doc)
    sec = read_secrets(pdir) if pdir is not None else {}
    for m in all_probes():
        pid = m.INFO.id
        p = out["probes"][pid]
        for f in m.INFO.fields:
            key = str(f["key"])
            env = f.get("env")
            if f.get("secret"):
                val = (sec.get(pid) or {}).get(key) or (os.environ.get(env, "") if env else "")
                if val:
                    p[key] = val
            elif env and (p.get(key) in ("", None, False)) and os.environ.get(env):
                p[key] = _truthy(os.environ[env]) if f.get("type") == "check" else os.environ[env]
    return out


def _truthy(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def apply_update(doc: Doc, pdir: Path, body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a PUT body; writes secrets to the side file and returns the ``settings.discovery`` value to store."""
    if not isinstance(body, dict):
        raise ValueError("settings must be an object")
    cur = stored(doc)
    out: Dict[str, Any] = {"window": cur["window"], "room": cur["room"], "probes": copy.deepcopy(cur["probes"])}
    if "window" in body:
        out["window"] = _clamp_window(body["window"])
    if "room" in body:
        if not isinstance(body["room"], str):
            raise ValueError("room must be a string")
        out["room"] = body["room"]
    probes = body.get("probes")
    if probes is not None and not isinstance(probes, dict):
        raise ValueError("probes must be an object")
    secrets = read_secrets(pdir)
    changed_secrets = False
    for pid, p in (probes or {}).items():
        if pid not in out["probes"]:
            raise ValueError(f"unknown probe {pid!r}")
        if not isinstance(p, dict):
            raise ValueError(f"probes.{pid} must be an object")
        fields = {str(f["key"]): f for f in _fields(pid)}
        for k, v in p.items():
            if k == "enabled":
                out["probes"][pid]["enabled"] = bool(v)
                continue
            f = fields.get(k)
            if f is None:
                if k.endswith("_set") or k.endswith("_env") or k.endswith("_from_env"):
                    continue  # echoes of a GET response
                raise ValueError(f"unknown setting {pid}.{k}")
            if f.get("secret"):
                if v is None:
                    continue  # unchanged
                if not isinstance(v, str):
                    raise ValueError(f"{pid}.{k} must be a string")
                secrets.setdefault(pid, {})
                if v == "":
                    secrets[pid].pop(k, None)
                else:
                    secrets[pid][k] = v
                changed_secrets = True
                continue
            if f.get("type") == "check":
                out["probes"][pid][k] = bool(v)
            elif v is None:
                out["probes"][pid][k] = ""
            elif isinstance(v, (str, int, float)):
                out["probes"][pid][k] = str(v) if not isinstance(v, str) else v.strip()
            elif isinstance(v, list):
                out["probes"][pid][k] = ",".join(str(x) for x in v)
            else:
                raise ValueError(f"{pid}.{k} has an unsupported value")
    if changed_secrets:
        write_secrets(pdir, secrets)
    return out


def redact(text: str, pdir: Optional[Path], doc: Optional[Doc] = None) -> str:
    """Replace any configured secret value in ``text`` (log lines, error messages)."""
    if not text:
        return text
    values: List[str] = []
    if pdir is not None:
        for p in read_secrets(pdir).values():
            values.extend(v for v in p.values() if v)
    for m in all_probes():
        for f in m.INFO.fields:
            if f.get("secret") and f.get("env") and os.environ.get(f["env"]):
                values.append(os.environ[f["env"]])
    for v in sorted(set(values), key=len, reverse=True):
        if len(v) >= 4:
            text = text.replace(v, REDACTED)
    return text


__all__ = [
    "DEFAULT_WINDOW", "MAX_WINDOW", "MIN_WINDOW", "REDACTED", "SECRETS_FILE", "apply_update", "defaults", "effective", "public",
    "read_secrets", "redact", "secret_keys", "secrets_path", "stored", "write_secrets",
]
