"""Tests for get_provider() from core/llm.py"""

import pytest
from langgraph_maestro.core.llm import get_provider, _providers


class TestGetProvider:
    def test_minimax_routes_to_minimax(self):
        """Test 'MiniMax-M2.5-highspeed' routes to minimax."""
        provider_name, provider_fn = get_provider('MiniMax-M2.5-highspeed')
        assert provider_name == 'minimax'
        assert provider_fn == _providers['minimax']

    def test_minimax_lowercase_routes_to_minimax(self):
        """Test 'minimax-model' routes to minimax (lowercase)."""
        provider_name, provider_fn = get_provider('minimax-model')
        assert provider_name == 'minimax'

    def test_local_mlx_community_routes_to_local(self):
        """Test 'mlx-community/model' routes to local."""
        provider_name, provider_fn = get_provider('mlx-community/Llama-3.2-3B-Instruct-4bit')
        assert provider_name == 'local'
        assert provider_fn == _providers['local']

    def test_local_prefix_routes_to_local(self):
        """Test 'local' routes to local."""
        provider_name, provider_fn = get_provider('local')
        assert provider_name == 'local'
        assert provider_fn == _providers['local']

    def test_local_model_name_routes_to_local(self):
        """Test 'local:model-name' routes to local."""
        provider_name, provider_fn = get_provider('local:some-model')
        assert provider_name == 'local'
        assert provider_fn == _providers['local']

    def test_claude_sonnet_routes_to_claude_code(self):
        """Test 'claude-sonnet-4-6' routes to claude_code."""
        provider_name, provider_fn = get_provider('claude-sonnet-4-6')
        assert provider_name == 'claude_code'
        assert provider_fn == _providers['claude_code']

    def test_claude_explicit_prefix_routes_to_claude_code(self):
        """Test 'claude_code:sonnet' routes to claude_code (explicit prefix)."""
        provider_name, provider_fn = get_provider('claude_code:sonnet')
        assert provider_name == 'claude_code'
        assert provider_fn == _providers['claude_code']

    def test_claude_opus_routes_to_claude_code(self):
        """Test 'claude-opus-4-5' routes to claude_code."""
        provider_name, provider_fn = get_provider('claude-opus-4-5')
        assert provider_name == 'claude_code'

    def test_default_routes_to_claude_code(self):
        """Test unknown model defaults to claude_code."""
        provider_name, provider_fn = get_provider('some-unknown-model')
        assert provider_name == 'claude_code'
        assert provider_fn == _providers['claude_code']

    def test_explicit_provider_prefix_takes_precedence(self):
        """Test explicit provider prefix takes precedence over auto-detection."""
        # Even though model contains 'minimax', explicit prefix should take precedence
        provider_name, provider_fn = get_provider('claude_code:minimax-model')
        assert provider_name == 'claude_code'
