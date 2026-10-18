"""Shared LLM interface. Providers return JSON objects and nothing else."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def available(self) -> bool:
        """True when credentials and a model name are configured."""

    @abstractmethod
    def complete_json(self, *, system: str, user: str) -> dict:
        """Return one JSON object. Raise if the provider cannot do so."""
