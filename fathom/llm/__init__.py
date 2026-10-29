"""Optional LLM bridge (SPEC §6.9.6 / §6.9.6a, FR-AST-07): multi-provider adapter layer over stdlib ``urllib``.

Providers: ``openai`` (Chat Completions or Responses API), ``anthropic``
(Messages API), ``xai`` (Grok, OpenAI-compatible) and ``openai_compat`` (any
OpenAI-compatible server: Ollama, LM Studio, vLLM, llama.cpp …). Settings come
from ``<FATHOM_DATA>/llm.json`` + ``llm-secrets.json`` with ``FATHOM_LLM_*``
environment overrides (see :mod:`fathom.llm.config`). The API key is never
logged or returned.

Public names used by ``assistant.py`` and the server: ``configured()``,
``info()``, ``chat()`` (plain ``{role, content}`` dicts → text), ``chat_tools()``
(``Message``/``ToolSpec`` → ``Reply``), ``LLMError``, ``max_context()``,
``timeout_default()``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence
import urllib.parse

from . import config
from .base import LLMError, Message, Provider, Reply, ToolCall, ToolSpec, as_message
from .config import max_context, timeout_default


def configured() -> bool:
    return config.configured()


def _host(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    return p.hostname + (":%d" % p.port if p.port else "") if p.hostname else ""


def info() -> Dict[str, Any]:
    """``{"configured", "provider", "model", "host"}`` — never the key."""
    cfg = config.effective()
    return {"configured": config.configured(cfg), "provider": cfg.get("provider") or None, "model": cfg.get("model") or None,
            "host": _host(config.resolved_base_url(cfg)) or None}


def provider(cfg: Optional[Dict[str, Any]] = None) -> Provider:
    """The configured provider instance (``LLMError`` when not configured)."""
    from .providers import make

    cfg = cfg if cfg is not None else config.effective()
    if not config.configured(cfg):
        raise LLMError("LLM not configured (set a provider, model and key under Settings › Assistant or FATHOM_LLM_*)", code="not_configured")
    return make(cfg)


def chat_tools(messages: Sequence[Any], tools: Sequence[Any] = (), *, model: str = "", temperature: Optional[float] = None,
               max_tokens: Optional[int] = None, tool_choice: Any = "auto", timeout: Optional[float] = None, stream: bool = False,
               on_delta: Optional[Callable[[str], None]] = None) -> Reply:
    """Tool-calling chat with the configured provider; ``messages`` are ``Message`` objects (or ``{role, content}`` dicts)."""
    cfg = config.effective()
    p = provider(cfg)
    return p.chat([as_message(m) for m in messages], list(tools or ()), model=model or cfg["model"],
                  temperature=cfg["temperature"] if temperature is None else temperature,
                  max_tokens=cfg["max_tokens"] if max_tokens is None else max_tokens, tool_choice=tool_choice,
                  timeout=timeout if timeout is not None else cfg["timeout"], stream=stream, on_delta=on_delta)


def chat(messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 700, timeout: Optional[float] = None) -> str:
    """Legacy text chat (§6.9.6): plain ``{role, content}`` dicts in, the assistant's text out."""
    reply = chat_tools(messages, (), temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    if reply.text is None or (not reply.text and reply.finish == "other"):
        raise LLMError("LLM endpoint returned an unexpected response", code="bad_response")
    return reply.text


__all__ = ["LLMError", "Message", "Provider", "Reply", "ToolCall", "ToolSpec", "chat", "chat_tools", "config", "configured", "info",
           "max_context", "provider", "timeout_default"]
