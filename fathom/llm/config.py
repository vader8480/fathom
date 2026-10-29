"""Server-level LLM configuration (SPEC §6.9.6a).

Non-secret settings live in ``<FATHOM_DATA>/llm.json``; the key in
``llm-secrets.json`` (see :mod:`fathom.llm.secrets`). Environment variables
win field by field so a systemd unit or Docker env can pin any value:

``FATHOM_LLM_PROVIDER`` (``openai`` | ``anthropic`` | ``xai`` | ``openai_compat``;
defaults to ``openai_compat`` when only ``FATHOM_LLM_URL`` is set, so the
original env-only setup keeps working), ``FATHOM_LLM_URL`` (base URL),
``FATHOM_LLM_MODEL``, ``FATHOM_LLM_API_KEY``, ``FATHOM_LLM_API`` (``chat`` |
``responses``, OpenAI only), ``FATHOM_LLM_TIMEOUT`` (seconds, default 20),
``FATHOM_LLM_MAX_CONTEXT`` (chars, default 24000).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

from . import secrets as _secrets

SETTINGS_FILE = "llm.json"
APIS = ("chat", "responses")
DEFAULTS: Dict[str, Any] = {"provider": "", "base_url": "", "model": "", "api": "chat", "temperature": 0.2, "max_tokens": 700,
                            "web_lookup": False, "daily_cap": 200}
ENV_FIELDS = {"provider": "FATHOM_LLM_PROVIDER", "base_url": "FATHOM_LLM_URL", "model": "FATHOM_LLM_MODEL", "api_key": "FATHOM_LLM_API_KEY",
              "api": "FATHOM_LLM_API"}
LEGACY_PROVIDER = "openai_compat"
_LOCK = threading.RLock()


class ConfigError(ValueError):
    def __init__(self, message: str, code: str = "bad_request") -> None:
        super().__init__(message)
        self.code = code


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def settings_path() -> Path:
    from ..project import data_root

    return data_root() / SETTINGS_FILE


def read_file() -> Dict[str, Any]:
    p = settings_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_file(data: Dict[str, Any]) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(str(tmp), str(p))


def timeout_default() -> float:
    try:
        return max(1.0, float(_env("FATHOM_LLM_TIMEOUT") or 20))
    except ValueError:
        return 20.0


def max_context() -> int:
    try:
        return max(1000, int(_env("FATHOM_LLM_MAX_CONTEXT") or 24000))
    except ValueError:
        return 24000


def provider_ids() -> Dict[str, Any]:
    from .providers import PROVIDERS

    return PROVIDERS


# ------------------------------------------------------------------ merge


def effective() -> Dict[str, Any]:
    """Defaults ← file ← env, field by field; includes ``api_key`` and a ``source`` map. Never return it to a client."""
    out: Dict[str, Any] = dict(DEFAULTS)
    source: Dict[str, str] = {k: "default" for k in DEFAULTS}
    source["api_key"] = "default"
    stored = read_file()
    for k in DEFAULTS:
        if k in stored and stored[k] is not None:
            out[k] = stored[k]
            source[k] = "file"
    key = _secrets.api_key()
    if key:
        source["api_key"] = "file"
    for k, env_name in ENV_FIELDS.items():
        v = _env(env_name)
        if v:
            if k == "api_key":
                key = v
            else:
                out[k] = v
            source[k] = "env"
    out["api_key"] = key
    if not out.get("provider") and out.get("base_url"):
        out["provider"] = LEGACY_PROVIDER
        source["provider"] = "default"
    out["provider"] = str(out.get("provider") or "")
    out["base_url"] = str(out.get("base_url") or "").strip().rstrip("/")
    out["model"] = str(out.get("model") or "").strip()
    out["api"] = str(out.get("api") or "chat") if str(out.get("api") or "chat") in APIS else "chat"
    out["temperature"] = _as_float(out.get("temperature"), DEFAULTS["temperature"])
    out["max_tokens"] = _as_int(out.get("max_tokens"), DEFAULTS["max_tokens"])
    out["web_lookup"] = bool(out.get("web_lookup"))
    out["daily_cap"] = _as_int(out.get("daily_cap"), DEFAULTS["daily_cap"])
    out["timeout"] = timeout_default()
    out["max_context"] = max_context()
    out["updated"] = str(stored.get("updated") or "")
    out["updated_by"] = str(stored.get("updated_by") or "")
    out["source"] = source
    return out


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


def resolved_base_url(cfg: Optional[Dict[str, Any]] = None) -> str:
    cfg = cfg if cfg is not None else effective()
    if cfg.get("base_url"):
        return str(cfg["base_url"])
    cls = provider_ids().get(str(cfg.get("provider") or ""))
    return str(getattr(cls, "default_base_url", "") or "") if cls else ""


def configured(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Provider resolvable, model set, key set when the provider needs one, base URL set when it has no default."""
    cfg = cfg if cfg is not None else effective()
    cls = provider_ids().get(str(cfg.get("provider") or ""))
    if cls is None or not cfg.get("model"):
        return False
    if getattr(cls, "needs_key", False) and not cfg.get("api_key"):
        return False
    return bool(resolved_base_url(cfg))


def public(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the admin UI may see: everything except the key (``api_key_set`` instead) plus provenance."""
    cfg = cfg if cfg is not None else effective()
    out = {k: cfg.get(k) for k in ("provider", "base_url", "model", "api", "temperature", "max_tokens", "web_lookup", "daily_cap",
                                   "timeout", "max_context", "updated", "updated_by")}
    out["api_key_set"] = bool(cfg.get("api_key"))
    out["source"] = dict(cfg.get("source") or {})
    out["effective_base_url"] = resolved_base_url(cfg)
    out["configured"] = configured(cfg)
    return out


# ------------------------------------------------------------------ save


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        raise ConfigError("base_url must be an http(s) URL", "bad_url") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("base_url must be an http(s) URL", "bad_url")
    return url.rstrip("/")


def validate(update: Dict[str, Any]) -> Dict[str, Any]:
    """Normalised subset of ``update`` limited to the stored fields; raises ``ConfigError`` (code ``bad_enum`` / ``bad_url`` / ``bad_request``)."""
    if not isinstance(update, dict):
        raise ConfigError("expected a JSON object")
    out: Dict[str, Any] = {}
    if "provider" in update:
        pid = str(update.get("provider") or "").strip()
        if pid and pid not in provider_ids():
            raise ConfigError("provider must be one of " + ", ".join(provider_ids()), "bad_enum")
        out["provider"] = pid
    if "base_url" in update:
        out["base_url"] = _check_url(str(update.get("base_url") or ""))
    if "model" in update:
        out["model"] = str(update.get("model") or "").strip()[:200]
    if "api" in update:
        api = str(update.get("api") or "chat").strip() or "chat"
        if api not in APIS:
            raise ConfigError("api must be one of " + ", ".join(APIS), "bad_enum")
        out["api"] = api
    if "temperature" in update:
        try:
            t = float(update.get("temperature"))
        except (TypeError, ValueError):
            raise ConfigError("temperature must be a number") from None
        if not 0.0 <= t <= 2.0:
            raise ConfigError("temperature must be between 0 and 2")
        out["temperature"] = t
    if "max_tokens" in update:
        try:
            n = int(update.get("max_tokens"))
        except (TypeError, ValueError):
            raise ConfigError("max_tokens must be an integer") from None
        if not 1 <= n <= 128000:
            raise ConfigError("max_tokens must be between 1 and 128000")
        out["max_tokens"] = n
    if "web_lookup" in update:
        out["web_lookup"] = bool(update.get("web_lookup"))
    if "daily_cap" in update:
        try:
            n = int(update.get("daily_cap"))
        except (TypeError, ValueError):
            raise ConfigError("daily_cap must be an integer") from None
        if n < 0:
            raise ConfigError("daily_cap must be 0 or more")
        out["daily_cap"] = n
    return out


def save(update: Dict[str, Any], by: str = "") -> Dict[str, Any]:
    """Merge ``update`` into ``llm.json`` (atomic) and the key into the secrets file; returns ``public()``.

    ``api_key``: a non-empty string replaces the stored key, an empty string
    leaves it alone, ``clear_api_key: true`` removes it.
    """
    fields = validate(update)
    with _LOCK:
        stored = read_file()
        stored.update(fields)
        stored["updated"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stored["updated_by"] = str(by or "")
        write_file(stored)
        key = update.get("api_key")
        if isinstance(key, str) and key.strip():
            _secrets.set_api_key(key.strip())
        elif update.get("clear_api_key") is True:
            _secrets.set_api_key("")
    return public()


def probe_config(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Effective config overlaid with unsaved form values (``provider``, ``base_url``, ``model``, ``api``, ``api_key``, ``timeout``).

    An empty ``api_key`` means "use the stored one"; when the provider changes
    and no key is typed, a stored key for another provider is not reused.
    """
    cfg = effective()
    body = body if isinstance(body, dict) else {}
    fields = validate({k: body[k] for k in ("provider", "base_url", "model", "api") if k in body})
    if "provider" in fields and fields["provider"] and fields["provider"] != cfg.get("provider"):
        if "base_url" not in fields:
            cfg["base_url"] = ""  # the old provider's URL does not apply
        if not (isinstance(body.get("api_key"), str) and body["api_key"].strip()):
            cfg["api_key"] = ""
    cfg.update(fields)
    if not cfg.get("provider") and cfg.get("base_url"):
        cfg["provider"] = LEGACY_PROVIDER
    key = body.get("api_key")
    if isinstance(key, str) and key.strip():
        cfg["api_key"] = key.strip()
    if body.get("timeout") is not None:
        try:
            cfg["timeout"] = min(120.0, max(1.0, float(body["timeout"])))
        except (TypeError, ValueError):
            raise ConfigError("timeout must be a number of seconds") from None
    return cfg


__all__ = ["APIS", "ConfigError", "DEFAULTS", "ENV_FIELDS", "LEGACY_PROVIDER", "SETTINGS_FILE", "configured", "effective", "max_context",
           "probe_config", "public", "read_file", "resolved_base_url", "save", "settings_path", "timeout_default", "validate", "write_file"]
