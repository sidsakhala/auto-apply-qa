"""Select an LLM provider from ``LLM_PROVIDER``. Missing credentials fall back to None."""

from __future__ import annotations

import os

from src.llm.base import LLMProvider
from src.utils.logger import get_logger

logger = get_logger("llm")


def get_provider() -> LLMProvider | None:
    name = os.getenv("LLM_PROVIDER", "vertex_ai").strip().lower()
    provider: LLMProvider
    if name in {"openai", "gpt"}:
        from src.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
    elif name in {"anthropic", "claude"}:
        from src.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
    elif name in {"vertex", "vertex_ai", "gemini", "google"}:
        from src.llm.vertex_ai_provider import VertexAIProvider

        provider = VertexAIProvider()
    elif name in {"none", "off", "heuristic"}:
        logger.info("LLM provider disabled; using deterministic analysis")
        return None
    else:
        logger.warning("Unknown LLM_PROVIDER '%s'; using deterministic analysis", name)
        return None

    if not provider.available:
        logger.info(
            "%s is selected but not configured. JD analysis will use the deterministic extractor.",
            provider.name,
        )
        return None
    return provider
