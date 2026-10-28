from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.analysis.schema_validator import (
    SchemaValidationError,
    validate_ai_reasoning_payload,
)
from app.config import load_config


@dataclass(frozen=True)
class AiReasoningResult:
    """AI explanation of a deterministic optimization analysis."""

    recommendation: str
    confidence: float | None
    reason: str
    concerns: tuple[str, ...]
    missing_evidence: tuple[str, ...]


_ALLOWED_RECOMMENDATIONS = {
    "KEEP_CURRENT",
    "DOWNSIZE_CANDIDATE",
    "UPSCALE_CANDIDATE",
    "STOP_INSTANCE",
    "INVESTIGATE",
    "INSUFFICIENT_DATA",
}
_MAX_VALIDATION_ATTEMPTS = 3


class AiReasoning:
    """Generate constrained reasoning from deterministic AWS evidence."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_config(cls) -> AiReasoning:
        """Create the AI reasoning service from application configuration."""
        config = load_config()
        if not config.openai.api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        return cls(
            client=OpenAI(api_key=config.openai.api_key),
            model=config.openai.model,
        )

    def reason(self, evidence: dict[str, Any]) -> AiReasoningResult:
        """
        Return validated AI reasoning.

        Only invalid model output is retried. API/network exceptions are allowed
        to propagate to the caller rather than being mistaken for schema errors.
        """
        system_prompt = """
You are an AWS FinOps reasoning assistant. Use only the supplied evidence.
Never invent AWS metrics, prices, configuration history, or facts.
Never assume missing evidence exists. If evidence is insufficient, use
INSUFFICIENT_DATA. Do not override deterministic Python safety decisions.
Be conservative. Explain your reasoning clearly. Return ONLY a JSON object
with exactly these fields:
{
  "recommendation": "KEEP_CURRENT | DOWNSIZE_CANDIDATE | UPSCALE_CANDIDATE | STOP_INSTANCE | INVESTIGATE | INSUFFICIENT_DATA",
  "confidence": 0.0,
  "reason": "non-empty string",
  "concerns": ["string"],
  "missing_evidence": ["string"]
}
Use null for confidence when it cannot be justified. Do not add extra fields.
"""
        validation_feedback = ""
        last_error: SchemaValidationError | None = None

        for attempt in range(1, _MAX_VALIDATION_ATTEMPTS + 1):
            request_payload = {
                "evidence": evidence,
                "validation_feedback": validation_feedback or None,
                "attempt": attempt,
                "maximum_attempts": _MAX_VALIDATION_ATTEMPTS,
            }
            response = self._client.responses.create(
                model=self._model,
                instructions=system_prompt,
                input=json.dumps(request_payload, default=str),
            )
            content = response.output_text.strip()

            try:
                if not content:
                    raise SchemaValidationError("AI response is empty.")
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise SchemaValidationError(
                        f"AI response is not valid JSON: {exc.msg}."
                    ) from exc

                data = validate_ai_reasoning_payload(data)
                recommendation = data["recommendation"]
                confidence = data["confidence"]
                if confidence is not None:
                    confidence = float(confidence)
                if recommendation == "INSUFFICIENT_DATA":
                    confidence = None

                return AiReasoningResult(
                    recommendation=recommendation,
                    confidence=confidence,
                    reason=data["reason"],
                    concerns=tuple(data["concerns"]),
                    missing_evidence=tuple(data["missing_evidence"]),
                )
            except SchemaValidationError as exc:
                last_error = exc
                validation_feedback = (
                    f"Your previous response failed schema validation: {exc} "
                    "Return a corrected JSON object with exactly the required "
                    "fields and types. Do not invent evidence."
                )

        raise SchemaValidationError(
            f"AI response failed schema validation after "
            f"{_MAX_VALIDATION_ATTEMPTS} attempts: {last_error}"
        )
