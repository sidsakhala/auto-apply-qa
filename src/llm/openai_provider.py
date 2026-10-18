"""OpenAI chat completions with a JSON response."""

from __future__ import annotations

import os

from src.llm.base import LLMProvider
from src.llm.json_utils import parse_json_object


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.api_key = (api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete_json(self, *, system: str, user: str) -> dict:
        if not self.available:
            raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY.")
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        return parse_json_object(content)
