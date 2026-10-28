"""OpenAI: Chat Completions (default) or the Responses API (``api: "responses"``)."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import http
from ..base import LLMError, Message, Reply, ToolCall, ToolSpec, arguments_string, as_message, as_tool, norm_finish, parse_arguments
from .openai_compat import ChatCompletions

# Reasoning models reject ``temperature`` (and only accept ``max_completion_tokens``).
_NO_TEMPERATURE_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def responses_tools(tools: Sequence[ToolSpec]) -> List[Dict[str, Any]]:
    return [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]


def responses_tool_choice(choice: Any, tools: Sequence[ToolSpec]) -> Any:
    if not tools:
        return None
    if choice in (None, "", "auto"):
        return "auto"
    if choice in ("none", "required"):
        return choice
    if isinstance(choice, dict):
        return choice
    return {"type": "function", "name": str(choice)}


def responses_input(messages: Sequence[Message]) -> Dict[str, Any]:
    """``{"instructions": merged system text, "input": [...items...]}``."""
    system: List[str] = []
    items: List[Dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system.append(m.content)
        elif m.role == "tool":
            items.append({"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content or ""})
        elif m.role == "assistant":
            if m.content:
                items.append({"role": "assistant", "content": m.content})
            for tc in m.tool_calls:
                items.append({"type": "function_call", "call_id": tc.id, "name": tc.name, "arguments": arguments_string(tc)})
        else:
            items.append({"role": m.role, "content": m.content or ""})
    out: Dict[str, Any] = {"input": items}
    if system:
        out["instructions"] = "\n\n".join(system)
    return out


def responses_usage(usage: Any) -> Dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    out = {}
    if isinstance(usage.get("input_tokens"), int):
        out["input"] = usage["input_tokens"]
    if isinstance(usage.get("output_tokens"), int):
        out["output"] = usage["output_tokens"]
    return out


def parse_responses_reply(data: Dict[str, Any]) -> Reply:
    output = data.get("output")
    if not isinstance(output, list):
        raise LLMError("LLM endpoint returned an unexpected response", code="bad_response")
    text_parts: List[str] = []
    calls: List[ToolCall] = []
    for i, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
        elif kind == "function_call":
            raw = item.get("arguments")
            calls.append(ToolCall(id=str(item.get("call_id") or item.get("id") or "call_%d" % i), name=str(item.get("name") or ""),
                                  arguments=parse_arguments(raw), raw=raw if isinstance(raw, str) else json.dumps(raw) if raw is not None else ""))
    if calls:
        finish = "tool_calls"
    elif data.get("status") == "incomplete":
        reason = str((data.get("incomplete_details") or {}).get("reason") or "")
        finish = "length" if reason == "max_output_tokens" else "other"
    elif data.get("status") in (None, "completed"):
        finish = "stop"
    else:
        finish = "other"
    return Reply(text="".join(text_parts), tool_calls=calls, finish=norm_finish(finish), usage=responses_usage(data.get("usage")), raw=data)


def assemble_responses_stream(events: Any, on_delta: Optional[Callable[[str], None]]) -> Reply:
    """Fold Responses API SSE events: text deltas to ``on_delta``, the final ``response.completed`` object is parsed as a whole."""
    text_parts: List[str] = []
    calls: Dict[int, Dict[str, str]] = {}
    final: Optional[Dict[str, Any]] = None
    for event, data in events:
        if data.strip() == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or event or "")
        if kind == "response.output_text.delta" and isinstance(ev.get("delta"), str):
            text_parts.append(ev["delta"])
            if on_delta is not None:
                on_delta(ev["delta"])
        elif kind == "response.output_item.added":
            item = ev.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "function_call":
                slot = calls.setdefault(int(ev.get("output_index") or 0), {"id": "", "name": "", "arguments": ""})
                slot["id"] = str(item.get("call_id") or item.get("id") or "")
                slot["name"] = str(item.get("name") or "")
        elif kind == "response.function_call_arguments.delta" and isinstance(ev.get("delta"), str):
            slot = calls.setdefault(int(ev.get("output_index") or 0), {"id": "", "name": "", "arguments": ""})
            slot["arguments"] += ev["delta"]
        elif kind == "response.function_call_arguments.done" and isinstance(ev.get("arguments"), str):
            slot = calls.setdefault(int(ev.get("output_index") or 0), {"id": "", "name": "", "arguments": ""})
            slot["arguments"] = ev["arguments"]
        elif kind in ("response.completed", "response.incomplete") and isinstance(ev.get("response"), dict):
            final = ev["response"]
        elif kind == "response.failed":
            err = (ev.get("response") or {}).get("error") or {}
            raise LLMError("OpenAI response failed: %s" % str(err.get("message") or "unknown")[:200], code="upstream")
    if final is not None:
        reply = parse_responses_reply(final)
        if not reply.text and text_parts:
            reply.text = "".join(text_parts)
        reply.raw = dict(final, streamed=True)
        return reply
    tool_calls = [ToolCall(id=s["id"] or "call_%d" % i, name=s["name"], arguments=parse_arguments(s["arguments"]), raw=s["arguments"])
                  for i, s in sorted(calls.items())]
    return Reply(text="".join(text_parts), tool_calls=tool_calls, finish="tool_calls" if tool_calls else "stop", usage={},
                 raw={"output": [], "streamed": True})


class OpenAIProvider(ChatCompletions):
    id = "openai"
    label = "OpenAI"
    default_base_url = "https://api.openai.com/v1"
    needs_key = True
    lists_models = True
    apis = ("chat", "responses")
    max_tokens_field = "max_completion_tokens"

    def build_body(self, messages: Sequence[Message], tools: Sequence[ToolSpec], model: str, temperature: float, max_tokens: int,
                   tool_choice: Any, stream: bool) -> Dict[str, Any]:
        if model.lower().startswith(_NO_TEMPERATURE_PREFIXES):
            temperature = None  # type: ignore[assignment]
        return super().build_body(messages, tools, model, temperature, max_tokens, tool_choice, stream)

    def chat(self, messages: Sequence[Any], tools: Sequence[Any] = (), *, model: str = "", temperature: float = 0.2, max_tokens: int = 700,
             tool_choice: Any = "auto", timeout: Optional[float] = None, stream: bool = False,
             on_delta: Optional[Callable[[str], None]] = None) -> Reply:
        if self.api != "responses":
            return super().chat(messages, tools, model=model, temperature=temperature, max_tokens=max_tokens, tool_choice=tool_choice,
                                timeout=timeout, stream=stream, on_delta=on_delta)
        use_model = (model or self.model or "").strip()
        if not use_model:
            raise LLMError("no model set", code="not_configured")
        msgs = [as_message(m) for m in messages]
        specs = [as_tool(t) for t in tools or ()]
        body: Dict[str, Any] = {"model": use_model, "max_output_tokens": int(max_tokens), "stream": bool(stream)}
        body.update(responses_input(msgs))
        if temperature is not None and not use_model.lower().startswith(_NO_TEMPERATURE_PREFIXES):
            body["temperature"] = temperature
        if specs:
            body["tools"] = responses_tools(specs)
            choice = responses_tool_choice(tool_choice, specs)
            if choice is not None:
                body["tool_choice"] = choice
        tmo = timeout if timeout is not None else self.timeout
        if stream:
            return assemble_responses_stream(http.post_stream(self.url("responses"), body, self.headers(), tmo), on_delta)
        status, data = http.post_json(self.url("responses"), body, self.headers(), tmo)
        self.check_status(status, data)
        return parse_responses_reply(data)


__all__ = ["OpenAIProvider", "assemble_responses_stream", "parse_responses_reply", "responses_input", "responses_tool_choice", "responses_tools"]
