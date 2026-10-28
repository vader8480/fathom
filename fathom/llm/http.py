"""Tiny HTTP client for the providers: ``urllib`` only, http(s) only, size caps, redacted errors.

Tests monkeypatch :func:`post_json`, :func:`get_json` and :func:`post_stream`
with recorders, so providers must call these module attributes (never bind them
at import time).
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .base import LLMError, redact

MAX_REQUEST = 4 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
MAX_SSE_LINE = 1024 * 1024
DETAIL_CHARS = 500
USER_AGENT = "fathom-llm/1"


def timeout_default() -> float:
    try:
        return max(1.0, float((os.environ.get("FATHOM_LLM_TIMEOUT") or "").strip() or 20))
    except ValueError:
        return 20.0


def check_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        raise LLMError("bad URL", code="bad_url") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMError("the LLM base URL must be an http(s) URL", code="bad_url")
    return url


def _secrets(headers: Dict[str, str]) -> List[str]:
    out = []
    for k, v in (headers or {}).items():
        if k.lower() in ("authorization", "x-api-key", "api-key"):
            out.append(v)
            if v.lower().startswith("bearer "):
                out.append(v[7:])
    return out


def _request(method: str, url: str, body: Optional[Dict[str, Any]], headers: Dict[str, str], timeout: Optional[float]) -> urllib.request.Request:
    check_url(url)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_REQUEST:
            raise LLMError("LLM request body larger than %d MB" % (MAX_REQUEST // (1024 * 1024)), code="too_large")
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    return urllib.request.Request(url, data=data, headers=h, method=method)


def _open(req: urllib.request.Request, timeout: Optional[float], secrets: List[str]) -> Any:
    try:
        return urllib.request.urlopen(req, timeout=timeout if timeout is not None else timeout_default())
    except urllib.error.HTTPError as exc:
        return exc  # an HTTPError is also a response: the caller reads its body and status
    except (socket.timeout, TimeoutError):
        raise LLMError("LLM request timed out", code="timeout") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise LLMError("LLM request timed out", code="timeout") from None
        raise LLMError("LLM endpoint unreachable (%s)" % redact(_short(reason), secrets), code="unreachable") from None
    except OSError as exc:
        raise LLMError("LLM request failed (%s)" % redact(_short(exc), secrets), code="unreachable") from None


def _short(exc: Any) -> str:
    name = type(exc).__name__
    text = str(exc)
    return name if not text or len(text) > 120 else "%s: %s" % (name, text)


def _read(resp: Any, secrets: List[str]) -> Tuple[int, Dict[str, Any]]:
    status = int(getattr(resp, "status", None) or getattr(resp, "code", 0) or 0)
    try:
        raw = resp.read(MAX_RESPONSE + 1)
    except (socket.timeout, TimeoutError):
        raise LLMError("LLM request timed out", code="timeout") from None
    except OSError as exc:
        raise LLMError("LLM response could not be read (%s)" % type(exc).__name__, code="unreachable") from None
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if len(raw) > MAX_RESPONSE:
        raise LLMError("LLM response larger than %d MB" % (MAX_RESPONSE // (1024 * 1024)), status=status, code="too_large")
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {"_text": redact(text[:DETAIL_CHARS], secrets)}
    if not isinstance(data, dict):
        data = {"_data": data}
    return status, data


def post_json(url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
    """``(status, parsed_body)``; non-JSON bodies come back as ``{"_text": first 500 chars}``.

    Transport failures (bad URL, DNS, refused, timeout, oversize) raise ``LLMError``;
    HTTP error statuses are returned so the provider can turn them into a
    redacted ``LLMError`` with the upstream message.
    """
    secrets = _secrets(headers)
    req = _request("POST", url, body, headers, timeout)
    return _read(_open(req, timeout, secrets), secrets)


def get_json(url: str, headers: Dict[str, str], timeout: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
    secrets = _secrets(headers)
    req = _request("GET", url, None, headers, timeout)
    return _read(_open(req, timeout, secrets), secrets)


def iter_sse(lines: Any) -> Iterator[Tuple[str, str]]:
    """Yield ``(event, data)`` per SSE event from an iterable of text lines (or one text blob).

    ``data:`` lines of one event are joined with newlines, ``event:`` names are
    kept (empty when absent), comments and other fields are ignored.
    """
    if isinstance(lines, bytes):
        lines = lines.decode("utf-8", "replace")
    if isinstance(lines, str):
        lines = lines.splitlines()
    event, data = "", []
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.rstrip("\r\n")
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    if data:
        yield event, "\n".join(data)


def post_stream(url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: Optional[float] = None) -> Iterator[Tuple[str, str]]:
    """POST and yield SSE ``(event, data)`` tuples; a non-2xx status raises ``LLMError`` with the (truncated) body."""
    secrets = _secrets(headers)
    h = dict(headers or {})
    h["Accept"] = "text/event-stream"
    req = _request("POST", url, body, h, timeout)
    resp = _open(req, timeout, secrets)
    status = int(getattr(resp, "status", None) or getattr(resp, "code", 0) or 0)
    if not 200 <= status < 300:
        _, data = _read(resp, secrets)
        err = data.get("error")
        detail = err.get("message") if isinstance(err, dict) else (err if isinstance(err, str) else data.get("_text") or "")
        msg = "LLM endpoint returned HTTP %d" % status + (": " + redact(str(detail)[:DETAIL_CHARS], secrets) if detail else "")
        raise LLMError(msg, status=status, code="upstream")

    def lines() -> Iterator[str]:
        total = 0
        try:
            while True:
                raw = resp.readline(MAX_SSE_LINE + 1)
                if not raw:
                    break
                total += len(raw)
                if len(raw) > MAX_SSE_LINE or total > MAX_RESPONSE:
                    raise LLMError("LLM stream too large", status=status, code="too_large")
                yield raw.decode("utf-8", "replace")
        except (socket.timeout, TimeoutError):
            raise LLMError("LLM stream timed out", code="timeout") from None
        except OSError as exc:
            raise LLMError("LLM stream failed (%s)" % type(exc).__name__, code="unreachable") from None
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return iter_sse(lines())


__all__ = ["DETAIL_CHARS", "MAX_REQUEST", "MAX_RESPONSE", "check_url", "get_json", "iter_sse", "post_json", "post_stream", "timeout_default"]
