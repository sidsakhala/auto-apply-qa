"""Google Vertex AI via Application Default Credentials.

No API keys or service-account files are read from the repository.
Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION, then authenticate with
``gcloud auth application-default login`` or a workload identity the runtime already has.
"""

from __future__ import annotations

import os

from src.llm.base import LLMProvider
from src.llm.json_utils import parse_json_object


class VertexAIProvider(LLMProvider):
    name = "vertex_ai"

    def __init__(
        self,
        model: str | None = None,
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        explicit = os.getenv("MODEL_NAME", "").strip()
        self.model = (
            model
            or explicit
            or os.getenv("VERTEX_AI_MODEL", "").strip()
            or "gemini-2.0-flash-001"
        )
        self.project = (project if project is not None else os.getenv("GOOGLE_CLOUD_PROJECT", "")).strip()
        self.location = (
            location if location is not None else os.getenv("GOOGLE_CLOUD_LOCATION", "")
        ).strip() or "us-central1"

    @property
    def available(self) -> bool:
        return bool(self.project and self.model)

    def complete_json(self, *, system: str, user: str) -> dict:
        if not self.available:
            raise RuntimeError("Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT.")
        import vertexai
        from vertexai.generative_models import GenerationConfig, GenerativeModel

        vertexai.init(project=self.project, location=self.location)
        model = GenerativeModel(self.model, system_instruction=system)
        response = model.generate_content(
            user,
            generation_config=GenerationConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        return parse_json_object(response.text or "")
