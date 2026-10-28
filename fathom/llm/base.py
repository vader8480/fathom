"""Provider-neutral types for the LLM adapter layer (SPEC §6.9.6a).

Every provider speaks these dataclasses; the wire formats (OpenAI Chat
Completions, OpenAI Responses, Anthropic Messages) live in
``fathom/llm/providers``. Nothing here touches the network.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

FINISH_VALUES = ("stop", "tool_calls", "length", "other")


class LLMError(Exception):
    """Any failure talking to a provider (HTTP error, timeout, bad JSON, unsupported call).

    ``status`` is the upstream HTTP status when there was one (else 0). The
    message is safe to show and log: it never carries headers or the key and
    upstream bodies are truncated.
    """

    def __init__(self, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = int(status or 0)
        self.code = code or ("http_%d" % self.status if self.status else "error")


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    raw: str = ""  # the provider's argument string, kept for round-tripping


@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)  # assistant only
    tool_call_id: str = ""  # tool only: the call being answered
    name: str = ""  # tool name for role=tool


@dataclass
class Reply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish: str = "stop"  # stop | tool_calls | length | other
    usage: Dict[str, int] = field(default_factory=dict)  # {"input": n, "output": n} when known
    raw: Dict[str, Any] = field(default_factory=dict)  # provider response; never logged by callers


def parse_arguments(raw: Any) -> Dict[str, Any]:
    """Tool-call arguments as a dict: JSON strings are parsed, invalid JSON becomes ``{"_raw": str}``."""
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = raw if isinstance(raw, str) else json.dumps(raw)
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {"_raw": text}
    return data if isinstance(data, dict) else {"_raw": text}


def arguments_string(call: ToolCall) -> str:
    """The argument string to send back to a provider (the raw text when we have it)."""
    if call.raw:
        return call.raw
    args = call.arguments or {}
    if set(args) == {"_raw"} and isinstance(args["_raw"], str):
        return args["_raw"]
    return json.dumps(args, ensure_ascii=False)


def as_message(item: Any) -> Message:
    """Accept a ``Message`` or a plain ``{"role", "content"}`` dict (the legacy ``llm.chat`` shape)."""
    if isinstance(item, Message):
        return item
    if isinstance(item, dict):
        calls = []
        for tc in item.get("tool_calls") or []:
            if isinstance(tc, ToolCall):
                calls.append(tc)
            elif isinstance(tc, dict):
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                raw = fn.get("arguments")
                calls.append(ToolCall(id=str(tc.get("id") or ""), name=str(fn.get("name") or ""), arguments=parse_arguments(raw),
                                      raw=raw if isinstance(raw, str) else ""))
        return Message(role=str(item.get("role") or "user"), content=str(item.get("content") if item.get("content") is not None else ""),
                       tool_calls=calls, tool_call_id=str(item.get("tool_call_id") or ""), name=str(item.get("name") or ""))
    raise LLMError("messages must be Message objects or {role, content} dicts", code="bad_request")


def as_tool(item: Any) -> ToolSpec:
    if isinstance(item, ToolSpec):
        return item
    if isinstance(item, dict):
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        return ToolSpec(name=str(fn.get("name") or ""), description=str(fn.get("description") or ""),
                        parameters=fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {"type": "object", "properties": {}})
    raise LLMError("tools must be ToolSpec objects or dicts", code="bad_request")


class Provider:
    """Base class. Subclasses set the class attributes and implement ``chat``/``list_models``."""

    id = ""
    label = ""
    default_base_url = ""
    needs_key = True
    lists_models = True
    presets: Dict[str, str] = {}
    apis: Sequence[str] = ("chat",)

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(config or {})
        self.base_url = str(cfg.get("base_url") or self.default_base_url or "").strip().rstrip("/")
        self.api_key = str(cfg.get("api_key") or "")
        self.model = str(cfg.get("model") or "").strip()
        self.api = str(cfg.get("api") or self.apis[0]).strip() or self.apis[0]
        self.timeout = cfg.get("timeout")
        self.config = cfg

    # -- helpers for subclasses

    def url(self, path: str) -> str:
        if not self.base_url:
            raise LLMError("%s needs a base URL" % (self.label or self.id), code="bad_url")
        return self.base_url + "/" + path.lstrip("/")

    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def check_status(self, status: int, data: Any) -> None:
        """Turn a non-2xx upstream status into ``LLMError`` (message built from the body, truncated)."""
        if 200 <= int(status) < 300:
            return
        detail = ""
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("type") or "")
            elif isinstance(err, str):
                detail = err
            elif isinstance(data.get("_text"), str):
                detail = data["_text"]
            elif data.get("message"):
                detail = str(data.get("message"))
        detail = redact(detail[:500], [self.api_key])
        msg = "%s returned HTTP %d" % (self.label or self.id, int(status))
        if detail:
            msg += ": " + detail
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(int(status), "upstream")
        raise LLMError(msg, status=int(status), code=code)

    # -- contract

    def chat(self, messages: Sequence[Any], tools: Sequence[Any] = (), *, model: str = "", temperature: float = 0.2, max_tokens: int = 700,
             tool_choice: Any = "auto", timeout: Optional[float] = None, stream: bool = False,
             on_delta: Optional[Callable[[str], None]] = None) -> Reply:
        raise NotImplementedError

    def list_models(self) -> List[str]:
        raise LLMError("%s does not list models" % (self.label or self.id), code="not_supported")

    def test_connection(self, model: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        """``{"ok", "model", "latency_ms", "detail"}``: a 1-token chat ("Say OK"); never raises."""
        use_model = (model or self.model or "").strip()
        t0 = time.monotonic()
        try:
            if use_model:
                reply = self.chat([Message("user", "Say OK")], model=use_model, max_tokens=5, temperature=0.0, timeout=timeout)
                detail = (reply.text or "").strip() or ("finish=%s" % reply.finish)
            elif self.lists_models:
                models = self.list_models()
                detail = "reachable, %d model(s) available; pick one" % len(models)
            else:
                return {"ok": False, "model": "", "latency_ms": 0, "detail": "no model set"}
        except LLMError as exc:
            return {"ok": False, "model": use_model, "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(exc)}
        return {"ok": True, "model": use_model, "latency_ms": int((time.monotonic() - t0) * 1000), "detail": detail[:200]}


def redact(text: str, secrets: Sequence[str]) -> str:
    out = text or ""
    for s in secrets:
        if s and len(s) >= 4 and s in out:
            out = out.replace(s, "••••")
    return out


def norm_finish(value: str) -> str:
    return value if value in FINISH_VALUES else "other"


__all__ = ["FINISH_VALUES", "LLMError", "Message", "Provider", "Reply", "ToolCall", "ToolSpec", "arguments_string", "as_message", "as_tool",
           "norm_finish", "parse_arguments", "redact"]
