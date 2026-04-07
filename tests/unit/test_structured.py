"""Unit tests for core/structured.py — call_llm_structured()."""

import json
import pytest
from pydantic import BaseModel, Field
from typing import List

from langgraph_maestro.core.structured import call_llm_structured


class SimpleOutput(BaseModel):
    items: List[str] = Field(..., min_length=1)
    count: int


class TestCallLlmStructured:
    def test_returns_validated_model_on_valid_json(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({"items": ["a", "b"], "count": 2}),
            "model": "mock",
            "latency": 0.1,
        })
        result = call_llm_structured(
            prompt="list items",
            models=["mock-model"],
            response_model=SimpleOutput,
        )
        assert isinstance(result, SimpleOutput)
        assert result.items == ["a", "b"]
        assert result.count == 2

    def test_retries_on_invalid_json(self, mock_llm):
        # First response is not JSON, second is valid
        mock_llm.append({"content": "not json", "model": "mock", "latency": 0.1})
        mock_llm.append({
            "content": json.dumps({"items": ["x"], "count": 1}),
            "model": "mock",
            "latency": 0.1,
        })
        result = call_llm_structured(
            prompt="list items",
            models=["mock-model"],
            response_model=SimpleOutput,
            max_retries=2,
        )
        assert result.items == ["x"]

    def test_retries_on_validation_error(self, mock_llm):
        # First response fails validation (empty items), second is valid
        mock_llm.append({
            "content": json.dumps({"items": [], "count": 0}),
            "model": "mock",
            "latency": 0.1,
        })
        mock_llm.append({
            "content": json.dumps({"items": ["y"], "count": 1}),
            "model": "mock",
            "latency": 0.1,
        })
        result = call_llm_structured(
            prompt="list items",
            models=["mock-model"],
            response_model=SimpleOutput,
            max_retries=2,
        )
        assert result.items == ["y"]

    def test_raises_after_exhausting_retries(self, mock_llm):
        # All responses are bad
        for _ in range(4):
            mock_llm.append({"content": "garbage", "model": "mock", "latency": 0.1})
        with pytest.raises(RuntimeError, match="exhausted"):
            call_llm_structured(
                prompt="list items",
                models=["mock-model"],
                response_model=SimpleOutput,
                max_retries=2,
            )

    def test_passes_phase_and_config(self, mock_llm):
        mock_llm.append({
            "content": json.dumps({"items": ["z"], "count": 1}),
            "model": "mock",
            "latency": 0.1,
        })
        result = call_llm_structured(
            prompt="list",
            models=["mock-model"],
            response_model=SimpleOutput,
            phase="decompose",
            config=None,
        )
        assert isinstance(result, SimpleOutput)
