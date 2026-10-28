"""Provider registry: ``PROVIDERS``, ``make(config)`` and the UI ``catalog()``."""

from __future__ import annotations

from typing import Any, Dict, List, Type

from ..base import LLMError, Provider
from .anthropic import AnthropicProvider
from .openai import OpenAIProvider
from .openai_compat import PRESETS, OpenAICompatProvider
from .xai import XAIProvider

PROVIDERS: Dict[str, Type[Provider]] = {
    OpenAIProvider.id: OpenAIProvider,
    AnthropicProvider.id: AnthropicProvider,
    XAIProvider.id: XAIProvider,
    OpenAICompatProvider.id: OpenAICompatProvider,
}


def make(config: Dict[str, Any]) -> Provider:
    """Instantiate the provider named by ``config["provider"]`` (``LLMError(code="bad_enum")`` when unknown)."""
    pid = str((config or {}).get("provider") or "").strip()
    cls = PROVIDERS.get(pid)
    if cls is None:
        raise LLMError("unknown LLM provider %r (one of %s)" % (pid, ", ".join(PROVIDERS)), code="bad_enum")
    return cls(config)


def catalog() -> List[Dict[str, Any]]:
    return [{"id": cls.id, "label": cls.label, "default_base_url": cls.default_base_url, "needs_key": bool(cls.needs_key),
             "lists_models": bool(cls.lists_models), "presets": dict(cls.presets), "apis": list(cls.apis)} for cls in PROVIDERS.values()]


__all__ = ["PRESETS", "PROVIDERS", "AnthropicProvider", "OpenAICompatProvider", "OpenAIProvider", "XAIProvider", "catalog", "make"]
