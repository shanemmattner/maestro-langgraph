"""Tests for extract_json() from core/llm.py"""

import pytest
from langgraph_maestro.core.llm import extract_json


class TestExtractJson:
    def test_direct_json_parse(self):
        """Test direct JSON parse."""
        text = '{"key": "value", "number": 42}'
        result = extract_json(text)
        assert result == {"key": "value", "number": 42}

    def test_markdown_fence_stripping(self):
        """Test markdown fence stripping."""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_markdown_fence_stripping_no_lang(self):
        """Test markdown fence stripping without language identifier."""
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_regex_extraction_from_surrounding_text(self):
        """Test regex extraction from surrounding text."""
        text = 'Here is the JSON: {"key": "value"} for you.'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_trailing_comma_removal(self):
        """Test trailing comma removal."""
        text = '{"key": "value",}'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_trailing_comma_removal_nested(self):
        """Test trailing comma removal in nested structures."""
        text = '{"items": ["a", "b",],}'
        result = extract_json(text)
        assert result == {"items": ["a", "b"]}

    def test_single_to_double_quote_conversion(self):
        """Test single to double quote conversion."""
        text = "{'key': 'value'}"
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_returns_none_for_non_json_text(self):
        """Test returns None for non-JSON text."""
        text = 'This is just plain text without any JSON.'
        result = extract_json(text)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Test returns None for empty string."""
        text = ''
        result = extract_json(text)
        assert result is None

    def test_complex_json(self):
        """Test complex nested JSON."""
        text = '{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}'
        result = extract_json(text)
        assert result == {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}

    def test_json_with_newlines(self):
        """Test JSON with newlines."""
        text = '{\n  "key": "value"\n}'
        result = extract_json(text)
        assert result == {"key": "value"}
