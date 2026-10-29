"""xAI Grok: OpenAI Chat Completions schema at ``https://api.x.ai/v1``."""

from __future__ import annotations

from .openai_compat import ChatCompletions


class XAIProvider(ChatCompletions):
    id = "xai"
    label = "xAI Grok"
    default_base_url = "https://api.x.ai/v1"
    needs_key = True
    lists_models = True
    max_tokens_field = "max_tokens"


__all__ = ["XAIProvider"]
