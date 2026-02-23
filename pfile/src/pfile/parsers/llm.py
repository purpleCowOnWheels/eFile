"""Shared LLM client and utilities for structured document extraction."""

from __future__ import annotations

import json
import os
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from pfile.security import redact_pii

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Return a shared OpenAI client, initialised lazily from OPENAI_API_KEY."""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running pFile: export OPENAI_API_KEY=sk-..."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def extract_structured(
    text: str,
    prompt: str,
    model_class: type[T],
    model: str = "gpt-4o",
    temperature: float = 0.0,
) -> tuple[T, dict[str, float]]:
    """
    Send extracted PDF text to the LLM and parse the response into a Pydantic model.

    PII (SSNs, EINs, account numbers) is redacted before the text is sent.

    Returns (parsed_model, confidence_scores) where confidence_scores maps
    field names to 0.0–1.0. The LLM is asked to include a `_confidence` dict
    alongside the data.
    """
    client = get_client()
    safe_text = redact_pii(text)

    schema = model_class.model_json_schema()
    system = (
        "You are a precise tax document parser. "
        "Extract the requested fields from the provided tax document text. "
        "Return ONLY valid JSON matching the schema provided. "
        "For any field you cannot find or are uncertain about, use null. "
        "Include a '_confidence' object mapping each field name to a float 0.0-1.0 "
        "indicating your confidence in the extracted value (1.0 = certain, 0.0 = not found). "
        "Note: some identifying numbers have been redacted (shown as XXX-XX-XXXX etc.) "
        "for privacy; return null for those fields."
    )

    user = (
        f"{prompt}\n\n"
        f"JSON Schema to match:\n{json.dumps(schema, indent=2)}\n\n"
        f"Document text:\n{safe_text}"
    )

    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    raw = json.loads(response.choices[0].message.content)
    confidence: dict[str, float] = raw.pop("_confidence", {})

    parsed = model_class.model_validate(raw)
    return parsed, confidence
