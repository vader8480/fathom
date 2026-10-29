"""OpenAI Chat Completions wire format, shared by ``openai``, ``xai`` and any local OpenAI-compatible server.

``OpenAICompatProvider`` is the generic provider (base URL required; Ollama, LM
Studio, vLLM, llama.cpp server …). ``ChatCompletions`` holds the request /
response normalisation so the other OpenAI-style providers reuse it.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import http
from ..base import LLMError, Message, Provider, Reply, ToolCall, ToolSpec, arguments_string, as_message, as_tool, norm_finish, parse_arguments

PRESETS = {"ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1", "vllm": "http://localhost:8000/v1",
           "llamacpp": "http://localhost:8080/v1"}


def tools_payload(tools: Sequence[ToolSpec]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]


def tool_choice_payload(choice: Any, tools: Sequence[ToolSpec]) -> Any:
    if not tools:
        return None
    if choice in (None, "", "auto"):
        return "auto"
    if choice in ("none", "required"):
        return choice
    if isinstance(choice, dict):
        return choice
    return {"type": "function", "function": {"name": str(choice)}}


def messages_payload(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
        elif m.role == "assistant" and m.tool_calls:
            item: Dict[str, Any] = {"role": "assistant", "content": m.content or None,
                                    "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": arguments_string(tc)}}
                                                   for tc in m.tool_calls]}
            out.append(item)
        else:
            out.append({"role": m.role, "content": m.content or ""})
    return out


def parse_tool_calls(items: Any) -> List[ToolCall]:
    calls: List[ToolCall] = []
    for i, tc in enumerate(items if isinstance(items, list) else []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        raw = fn.get("arguments")
        calls.append(ToolCall(id=str(tc.get("id") or "call_%d" % i), name=str(fn.get("name") or ""), arguments=parse_arguments(raw),
                              raw=raw if isinstance(raw, str) else json.dumps(raw) if raw is not None else ""))
    return calls


def parse_reply(data: Dict[str, Any]) -> Reply:
    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        raise LLMError("LLM endpoint returned an unexpected response", code="bad_response") from None
    content = message.get("content")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in content)
    text = content if isinstance(content, str) else ""
    calls = parse_tool_calls(message.get("tool_calls"))
    finish = str(choice.get("finish_reason") or "stop")
    if calls and finish == "stop":
        finish = "tool_calls"  # Ollama and friends report "stop" even when they return tool calls
    return Reply(text=text, tool_calls=calls, finish=norm_finish(finish), usage=usage_of(data.get("usage")), raw=data)


def usage_of(usage: Any) -> Dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    out = {}
    if isinstance(usage.get("prompt_tokens"), int):
        out["input"] = usage["prompt_tokens"]
    if isinstance(usage.get("completion_tokens"), int):
        out["output"] = usage["completion_tokens"]
    return out


def assemble_stream(events: Any, on_delta: Optional[Callable[[str], None]]) -> Reply:
    """Fold Chat Completions SSE chunks into one ``Reply`` (text deltas go to ``on_delta``)."""
    text_parts: List[str] = []
    calls: Dict[int, Dict[str, str]] = {}
    finish = ""
    usage: Dict[str, int] = {}
    last: Dict[str, Any] = {}
    for _event, data in events:
        if data.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        last = chunk
        if chunk.get("usage"):
            usage = usage_of(chunk.get("usage"))
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                text_parts.append(piece)
                if on_delta is not None:
                    on_delta(piece)
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = int(tc.get("index") or 0)
                slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") or {}
                if fn.get("name") and not slot["name"]:
                    slot["name"] = str(fn["name"])
                if isinstance(fn.get("arguments"), str):
                    slot["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                finish = str(choice["finish_reason"])
    tool_calls = [ToolCall(id=slot["id"] or "call_%d" % i, name=slot["name"], arguments=parse_arguments(slot["arguments"]), raw=slot["arguments"])
                  for i, slot in sorted(calls.items())]
    if tool_calls and finish in ("", "stop"):
        finish = "tool_calls"
    raw = {"choices": [{"message": {"role": "assistant", "content": "".join(text_parts),
                                    "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw}} for c in tool_calls]},
                        "finish_reason": finish or "stop"}], "streamed": True}
    for k in ("id", "model"):
        if last.get(k):
            raw[k] = last[k]
    return Reply(text="".join(text_parts), tool_calls=tool_calls, finish=norm_finish(finish or "stop"), usage=usage, raw=raw)


class ChatCompletions(Provider):
    """Mixin-style base: ``POST <base>/chat/completions`` and ``GET <base>/models``."""

    max_tokens_field = "max_tokens"
    tolerate_models_404 = False

    def chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):  # legacy FATHOM_LLM_URL pointing at the full endpoint
            return self.base_url
        return self.url("chat/completions")

    def build_body(self, messages: Sequence[Message], tools: Sequence[ToolSpec], model: str, temperature: float, max_tokens: int,
                   tool_choice: Any, stream: bool) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": model, "messages": messages_payload(messages), "stream": bool(stream)}
        if temperature is not None:
            body["temperature"] = temperature
        body[self.max_tokens_field] = int(max_tokens)
        if tools:
            body["tools"] = tools_payload(tools)
            choice = tool_choice_payload(tool_choice, tools)
            if choice is not None:
                body["tool_choice"] = choice
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def chat(self, messages: Sequence[Any], tools: Sequence[Any] = (), *, model: str = "", temperature: float = 0.2, max_tokens: int = 700,
             tool_choice: Any = "auto", timeout: Optional[float] = None, stream: bool = False,
             on_delta: Optional[Callable[[str], None]] = None) -> Reply:
        use_model = (model or self.model or "").strip()
        if not use_model:
            raise LLMError("no model set", code="not_configured")
        msgs = [as_message(m) for m in messages]
        specs = [as_tool(t) for t in tools or ()]
        body = self.build_body(msgs, specs, use_model, temperature, max_tokens, tool_choice, stream)
        tmo = timeout if timeout is not None else self.timeout
        if stream:
            events = http.post_stream(self.chat_url(), body, self.headers(), tmo)
            return assemble_stream(events, on_delta)
        status, data = http.post_json(self.chat_url(), body, self.headers(), tmo)
        self.check_status(status, data)
        return parse_reply(data)

    def list_models(self) -> List[str]:
        if not self.lists_models:
            return super().list_models()
        base = self.base_url[: -len("/chat/completions")] if self.base_url.endswith("/chat/completions") else self.base_url
        url = (base or self.default_base_url).rstrip("/") + "/models"
        status, data = http.get_json(url, self.headers(), self.timeout)
        if status == 404 and self.tolerate_models_404:
            return []
        self.check_status(status, data)
        items = data.get("data") if isinstance(data.get("data"), list) else data.get("models") if isinstance(data.get("models"), list) else []
        ids = []
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else it
            if isinstance(mid, str) and mid:
                ids.append(mid)
        return sorted(set(ids))


class OpenAICompatProvider(ChatCompletions):
    id = "openai_compat"
    label = "OpenAI-compatible server (Ollama, LM Studio, vLLM, llama.cpp …)"
    default_base_url = ""
    needs_key = False
    lists_models = True
    presets = PRESETS
    tolerate_models_404 = True


__all__ = ["PRESETS", "ChatCompletions", "OpenAICompatProvider", "assemble_stream", "messages_payload", "parse_reply", "parse_tool_calls",
           "tool_choice_payload", "tools_payload", "usage_of"]
