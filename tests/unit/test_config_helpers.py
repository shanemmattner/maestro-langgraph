"""Tests for new config helper functions: get_stall_config, get_skills_config, get_pe_config, get_timeout_for_model."""

import pytest
from langgraph_maestro.core.config import get_stall_config, get_skills_config, get_pe_config, get_timeout_for_model


class TestGetStallConfig:
    def test_full_config(self):
        config = {
            "timeouts": {
                "default": 600,
                "stall": {"no_progress_threshold": 5, "loop_detection_window": 10},
            }
        }
        result = get_stall_config(config)
        assert result == {
            "timeout_seconds": 600,
            "no_progress_threshold": 5,
            "loop_detection_window": 10,
        }

    def test_empty_config_uses_defaults(self):
        result = get_stall_config({})
        assert result["timeout_seconds"] == 300
        assert result["no_progress_threshold"] == 3
        assert result["loop_detection_window"] == 5

    def test_partial_config(self):
        config = {"timeouts": {"default": 120}}
        result = get_stall_config(config)
        assert result["timeout_seconds"] == 120
        assert result["no_progress_threshold"] == 3

    def test_stall_section_missing(self):
        config = {"timeouts": {"default": 200, "models": {}}}
        result = get_stall_config(config)
        assert result["timeout_seconds"] == 200
        assert result["no_progress_threshold"] == 3


class TestGetSkillsConfig:
    def test_returns_skills_dict(self):
        config = {"skills": {"model_overlays": {"minimax": "json only"}}}
        assert get_skills_config(config) == {"model_overlays": {"minimax": "json only"}}

    def test_missing_skills_returns_empty(self):
        assert get_skills_config({}) == {}

    def test_returns_reference_not_copy(self):
        """get_skills_config returns the dict directly, no deep copy."""
        skills = {"always": ["web-search"]}
        config = {"skills": skills}
        assert get_skills_config(config) is skills


class TestGetPeConfig:
    def test_defaults_when_missing(self):
        result = get_pe_config({})
        assert result["enabled"] is False
        assert result["model"] == "MiniMax-M2.5-highspeed"
        assert result["phases"] == []
        assert result["timeout"] == 120
        assert result["fallback_to_raw"] is True

    def test_config_overrides_defaults(self):
        config = {
            "prompt_engineering": {
                "enabled": True,
                "model": "custom-model",
                "phases": ["generate", "review"],
                "timeout": 60,
            }
        }
        result = get_pe_config(config)
        assert result["enabled"] is True
        assert result["model"] == "custom-model"
        assert result["phases"] == ["generate", "review"]
        assert result["timeout"] == 60
        assert result["fallback_to_raw"] is True  # default preserved

    def test_partial_override(self):
        config = {"prompt_engineering": {"enabled": True}}
        result = get_pe_config(config)
        assert result["enabled"] is True
        assert result["model"] == "MiniMax-M2.5-highspeed"  # default


class TestGetTimeoutForModel:
    def test_minimax_model(self):
        config = {"timeouts": {"default": 300, "models": {"minimax": 120}}}
        assert get_timeout_for_model("MiniMax-M2.5-highspeed", config) == 120

    def test_claude_model(self):
        config = {"timeouts": {"default": 300, "models": {"claude": 600}}}
        assert get_timeout_for_model("claude-sonnet-4-6-20250501", config) == 600

    def test_local_mlx_model(self):
        config = {"timeouts": {"default": 300, "models": {"local": 180}}}
        assert get_timeout_for_model("mlx-community/phi-3", config) == 180

    def test_local_prefix_model(self):
        config = {"timeouts": {"default": 300, "models": {"local": 180}}}
        assert get_timeout_for_model("local-llama", config) == 180

    def test_unknown_model_uses_default(self):
        config = {"timeouts": {"default": 300, "models": {"minimax": 120}}}
        assert get_timeout_for_model("some-unknown-model", config) == 300

    def test_no_models_section_uses_default(self):
        config = {"timeouts": {"default": 300}}
        assert get_timeout_for_model("MiniMax-M2.5", config) == 300

    def test_empty_config_uses_300(self):
        assert get_timeout_for_model("anything", {}) == 300

    def test_model_key_missing_falls_back_to_default(self):
        config = {"timeouts": {"default": 500, "models": {"local": 100}}}
        assert get_timeout_for_model("MiniMax-M2.5", config) == 500
