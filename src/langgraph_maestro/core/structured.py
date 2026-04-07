"""Structured LLM output using Pydantic schema validation + auto-retry.

call_llm_structured() calls call_llm_with_fallback() and validates the
JSON response against a Pydantic model.  On validation failure it
re-injects the validation error into a follow-up prompt and retries up
to *max_retries* times — matching the Instructor auto-retry pattern
described in issue #1.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def call_llm_structured(
    prompt: str,
    models: List[str],
    response_model: Type[T],
    *,
    phase: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    system_prompt: str = "You are a helpful assistant. Return valid JSON only.",
    cwd: Optional[str] = None,
    max_retries: int = 2,
) -> T:
    """Call an LLM and validate the response against *response_model*.

    On a ``ValidationError`` the error message is injected back into the
    prompt and the call is retried up to *max_retries* additional times.

    Returns a validated Pydantic model instance.

    Raises:
        RuntimeError: if all retries are exhausted without a valid response.
    """
    current_prompt = prompt
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 2):  # 1 initial + max_retries
        result = call_llm_with_fallback(
            prompt=current_prompt,
            models=models,
            phase=phase,
            config=config,
            cwd=cwd,
            system_prompt=system_prompt,
        )

        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            last_error = ValueError(f"Could not extract JSON from LLM response (attempt {attempt})")
            logger.warning(
                "structured_parse_failed",
                extra={"attempt": attempt, "content_len": len(content)},
            )
            current_prompt = (
                f"{prompt}\n\n"
                f"[Previous attempt {attempt} failed — response was not valid JSON. "
                f"Return ONLY a JSON object matching the required schema.]"
            )
            continue

        try:
            instance = response_model.model_validate(parsed)
            logger.info(
                "structured_ok",
                extra={"model": response_model.__name__, "attempt": attempt},
            )
            return instance
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "structured_validation_failed",
                extra={"attempt": attempt, "errors": exc.error_count()},
            )
            current_prompt = (
                f"{prompt}\n\n"
                f"[Previous attempt {attempt} produced invalid JSON. "
                f"Validation errors: {exc}. "
                f"Fix these errors and return ONLY a corrected JSON object.]"
            )

    raise RuntimeError(
        f"call_llm_structured exhausted {max_retries + 1} attempts for "
        f"{response_model.__name__}. Last error: {last_error}"
    )
