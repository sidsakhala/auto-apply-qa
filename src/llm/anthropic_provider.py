"""Anthropic messages API. The prompt requires a JSON object."""

from __future__ import annotations

import os

from src.llm.base import LLMProvider
from src.llm.json_utils import parse_json_object


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        explicit = os.getenv("MODEL_NAME", "").strip()
        self.model = model or explicit or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5"
        self.api_key = (api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete_json(self, *, system: str, user: str) -> dict:
        if not self.available:
            raise RuntimeError("Anthropic is not configured. Set ANTHROPIC_API_KEY.")
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.1,
            system=system,
            messages=[{"role": "user", "content": user + "\n\nReturn one JSON object and no other text."}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "text", ""))
        return parse_json_object(text)
