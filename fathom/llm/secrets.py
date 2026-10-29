"""The LLM API key: ``<FATHOM_DATA>/llm-secrets.json`` (mode 0600, atomic write).

Same pattern as ``fathom/discovery/settings.py``: the key never enters
``llm.json``, API responses or logs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

SECRETS_FILE = "llm-secrets.json"


def secrets_path() -> Path:
    from ..project import data_root

    return data_root() / SECRETS_FILE


def read_secrets() -> Dict[str, str]:
    p = secrets_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v} if isinstance(data, dict) else {}


def write_secrets(data: Dict[str, str]) -> None:
    p = secrets_path()
    clean = {k: v for k, v in (data or {}).items() if isinstance(v, str) and v}
    if not clean:
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2)
    try:
        os.chmod(str(tmp), 0o600)
    except OSError:
        pass
    os.replace(str(tmp), str(p))


def api_key() -> str:
    return read_secrets().get("api_key", "")


def set_api_key(value: str) -> None:
    sec = read_secrets()
    if value:
        sec["api_key"] = value
    else:
        sec.pop("api_key", None)
    write_secrets(sec)


__all__ = ["SECRETS_FILE", "api_key", "read_secrets", "secrets_path", "set_api_key", "write_secrets"]
