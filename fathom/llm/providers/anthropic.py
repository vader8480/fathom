"""Anthropic Messages API (``POST /v1/messages``, ``anthropic-version: 2023-06-01``)."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import http
from ..base import LLMError, Message, Provider, Reply, ToolCall, ToolSpec, as_message, as_tool, norm_finish, parse_arguments

ANTHROPIC_VERSION = "2023-06-01"
STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


def tools_payload(tools: Sequence[ToolSpec]) -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]


def tool_choice_payload(choice: Any, tools: Sequence[ToolSpec]) -> Any:
    if not tools:
        return None
    if choice in (None, "", "auto"):
        return {"type": "auto"}
    if choice == "none":
        return {"type": "none"}
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict):
        return choice
    return {"type": "tool", "name": str(choice)}


def split_messages(messages: Sequence[Message]) -> Dict[str, Any]:
    """``{"system": merged text, "messages": [...]}`` in Anthropic shape.

    Tool results become ``tool_result`` blocks in a *user* turn; consecutive
    tool messages (and a user text that follows them) collapse into one turn.
    """
    system: List[str] = []
    out: List[Dict[str, Any]] = []

    def blocks_of(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
        c = turn["content"]
        if isinstance(c, str):
            turn["content"] = [{"type": "text", "text": c}] if c else []
        return turn["content"]

    for m in messages:
        if m.role == "system":
            if m.content:
                system.append(m.content)
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or ""}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and \
                    all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if m.role == "assistant":
            if m.tool_calls:
                blocks: List[Dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    if set(args) == {"_raw"}:
                        args = {}
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": args})
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "assistant", "content": m.content or ""})
            continue
        # user text: merge into a preceding tool-result turn so roles keep alternating
        if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
            blocks_of(out[-1]).append({"type": "text", "text": m.content or ""})
        else:
            out.append({"role": "user", "content": m.content or ""})
    return {"system": "\n\n".join(system), "messages": out}


def usage_of(usage: Any) -> Dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    out = {}
    if isinstance(usage.get("input_tokens"), int):
        out["input"] = usage["input_tokens"]
    if isinstance(usage.get("output_tokens"), int):
        out["output"] = usage["output_tokens"]
    return out


def parse_reply(data: Dict[str, Any]) -> Reply:
    content = data.get("content")
    if not isinstance(content, list):
        raise LLMError("LLM endpoint returned an unexpected response", code="bad_response")
    text_parts: List[str] = []
    calls: List[ToolCall] = []
    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block.get("type") == "tool_use":
            inp = block.get("input")
            calls.append(ToolCall(id=str(block.get("id") or "toolu_%d" % i), name=str(block.get("name") or ""), arguments=parse_arguments(inp),
                                  raw=json.dumps(inp, ensure_ascii=False) if isinstance(inp, dict) else str(inp or "")))
    stop = str(data.get("stop_reason") or "")
    finish = STOP_REASONS.get(stop, "other" if stop else "stop")
    if calls and finish == "stop":
        finish = "tool_calls"
    return Reply(text="".join(text_parts), tool_calls=calls, finish=norm_finish(finish), usage=usage_of(data.get("usage")), raw=data)


def assemble_stream(events: Any, on_delta: Optional[Callable[[str], None]]) -> Reply:
    """Fold Messages-API SSE events (``message_start`` … ``message_stop``) into one ``Reply``."""
    blocks: Dict[int, Dict[str, Any]] = {}
    usage: Dict[str, int] = {}
    stop_reason = ""
    meta: Dict[str, Any] = {}
    for event, data in events:
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or event or "")
        idx = int(ev.get("index") or 0)
        if kind == "message_start":
            msg = ev.get("message") or {}
            meta = {k: msg.get(k) for k in ("id", "model", "role") if msg.get(k)}
            usage.update(usage_of(msg.get("usage")))
        elif kind == "content_block_start":
            cb = ev.get("content_block") or {}
            if cb.get("type") == "tool_use":
                blocks[idx] = {"type": "tool_use", "id": str(cb.get("id") or ""), "name": str(cb.get("name") or ""), "json": "",
                               "input": cb.get("input") if isinstance(cb.get("input"), dict) and cb.get("input") else None}
            else:
                blocks[idx] = {"type": "text", "text": str(cb.get("text") or "")}
        elif kind == "content_block_delta":
            delta = ev.get("delta") or {}
            slot = blocks.setdefault(idx, {"type": "text", "text": ""})
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                slot.setdefault("text", "")
                slot["text"] += delta["text"]
                if on_delta is not None:
                    on_delta(delta["text"])
            elif delta.get("type") == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                slot.setdefault("json", "")
                slot["json"] += delta["partial_json"]
        elif kind == "message_delta":
            d = ev.get("delta") or {}
            if d.get("stop_reason"):
                stop_reason = str(d["stop_reason"])
            usage.update(usage_of(ev.get("usage")))
        elif kind == "error":
            err = ev.get("error") or {}
            raise LLMError("Anthropic stream error: %s" % str(err.get("message") or err.get("type") or "unknown")[:200], code="upstream")
    content: List[Dict[str, Any]] = []
    for _i, slot in sorted(blocks.items()):
        if slot["type"] == "tool_use":
            inp = slot.get("input")
            if inp is None:
                inp = parse_arguments(slot.get("json") or "")
            content.append({"type": "tool_use", "id": slot["id"], "name": slot["name"], "input": inp})
        else:
            content.append({"type": "text", "text": slot.get("text", "")})
    raw = dict(meta, type="message", content=content, stop_reason=stop_reason or None, usage={"input_tokens": usage.get("input", 0),
                                                                                                "output_tokens": usage.get("output", 0)}, streamed=True)
    reply = parse_reply(raw)
    reply.usage = usage
    return reply


class AnthropicProvider(Provider):
    id = "anthropic"
    label = "Anthropic Claude"
    default_base_url = "https://api.anthropic.com/v1"
    needs_key = True
    lists_models = True

    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json", "anthropic-version": ANTHROPIC_VERSION}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    def chat(self, messages: Sequence[Any], tools: Sequence[Any] = (), *, model: str = "", temperature: float = 0.2, max_tokens: int = 700,
             tool_choice: Any = "auto", timeout: Optional[float] = None, stream: bool = False,
             on_delta: Optional[Callable[[str], None]] = None) -> Reply:
        use_model = (model or self.model or "").strip()
        if not use_model:
            raise LLMError("no model set", code="not_configured")
        msgs = [as_message(m) for m in messages]
        specs = [as_tool(t) for t in tools or ()]
        parts = split_messages(msgs)
        body: Dict[str, Any] = {"model": use_model, "max_tokens": int(max_tokens), "messages": parts["messages"], "stream": bool(stream)}
        if parts["system"]:
            body["system"] = parts["system"]
        if temperature is not None:
            body["temperature"] = temperature
        if specs:
            body["tools"] = tools_payload(specs)
            choice = tool_choice_payload(tool_choice, specs)
            if choice is not None:
                body["tool_choice"] = choice
        tmo = timeout if timeout is not None else self.timeout
        if stream:
            return assemble_stream(http.post_stream(self.url("messages"), body, self.headers(), tmo), on_delta)
        status, data = http.post_json(self.url("messages"), body, self.headers(), tmo)
        self.check_status(status, data)
        return parse_reply(data)

    def list_models(self) -> List[str]:
        status, data = http.get_json(self.url("models?limit=1000"), self.headers(), self.timeout)
        self.check_status(status, data)
        items = data.get("data") if isinstance(data.get("data"), list) else []
        return sorted({str(it["id"]) for it in items if isinstance(it, dict) and it.get("id")})


__all__ = ["ANTHROPIC_VERSION", "AnthropicProvider", "assemble_stream", "parse_reply", "split_messages", "tool_choice_payload", "tools_payload"]
