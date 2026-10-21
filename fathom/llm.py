"""Optional LLM bridge (SPEC §6.9.6, FR-AST-07): OpenAI-compatible chat completions via ``urllib``.

Configured only by environment: ``FATHOM_LLM_URL``, ``FATHOM_LLM_MODEL``,
``FATHOM_LLM_API_KEY`` (optional), ``FATHOM_LLM_TIMEOUT`` (seconds, default 20),
``FATHOM_LLM_MAX_CONTEXT`` (chars, default 24000). The API key is never logged
or returned.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(Exception):
    """Any failure talking to the LLM endpoint (HTTP error, timeout, bad JSON)."""


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_env("FATHOM_LLM_URL") and _env("FATHOM_LLM_MODEL"))


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


def _host(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    return p.hostname + (f":{p.port}" if p.port else "") if p.hostname else ""


def info() -> Dict[str, Any]:
    """``{"configured", "model", "host"}`` — never the key."""
    url = _env("FATHOM_LLM_URL")
    return {"configured": configured(), "model": _env("FATHOM_LLM_MODEL") or None, "host": _host(url) or None}


def _endpoint(url: str) -> str:
    u = url.rstrip("/")
    return u if u.endswith("/chat/completions") else u + "/chat/completions"


def chat(messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 700, timeout: Optional[float] = None) -> str:
    """POST ``<url>/chat/completions`` and return ``choices[0].message.content``."""
    if not configured():
        raise LLMError("LLM not configured (set FATHOM_LLM_URL and FATHOM_LLM_MODEL)")
    url = _endpoint(_env("FATHOM_LLM_URL"))
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise LLMError("FATHOM_LLM_URL must be an http(s) URL")
    body = json.dumps({"model": _env("FATHOM_LLM_MODEL"), "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": False}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = _env("FATHOM_LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout if timeout is not None else timeout_default()) as resp:
            raw = resp.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        raise LLMError(f"LLM endpoint returned HTTP {e.code}") from None
    except (socket.timeout, TimeoutError):
        raise LLMError("LLM request timed out") from None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise LLMError("LLM request timed out") from None
        raise LLMError(f"LLM endpoint unreachable ({type(reason).__name__})") from None
    except OSError as e:
        raise LLMError(f"LLM request failed ({type(e).__name__})") from None
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        raise LLMError("LLM endpoint returned an unexpected response") from None
    if not isinstance(content, str):
        raise LLMError("LLM endpoint returned an unexpected response")
    return content


__all__ = ["LLMError", "configured", "info", "chat", "max_context", "timeout_default"]
