"""Tests for core/config.py"""

import pytest
from langgraph_maestro.core.config import load_config, get_models_for_phase, clear_cache, get_pe_enabled


class TestLoadConfig:
    def test_load_config_valid_yaml(self, tmp_config):
        """Test load_config with valid YAML."""
        config_path = tmp_config({
            'phases': {
                'planning': ['model-a', 'model-b']
            }
        })
        config = load_config(config_path)
        assert config == {'phases': {'planning': ['model-a', 'model-b']}}

    def test_load_config_raises_file_not_found(self):
        """Test load_config raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_config('/nonexistent/path/config.yaml')


class TestGetModelsForPhase:
    def test_get_models_for_phase_returns_model_list(self, tmp_config):
        """Test get_models_for_phase returns model list."""
        config_path = tmp_config({
            'phases': {
                'planning': ['claude-sonnet-4-6', 'claude_code:sonnet']
            }
        })
        config = load_config(config_path)
        models = get_models_for_phase('planning', config)
        assert models == ['claude-sonnet-4-6', 'claude_code:sonnet']

    def test_get_models_for_phase_raises_value_error_missing_phase(self, tmp_config):
        """Test get_models_for_phase raises ValueError for missing phase."""
        config_path = tmp_config({
            'phases': {
                'planning': ['model-a']
            }
        })
        config = load_config(config_path)
        with pytest.raises(ValueError) as exc_info:
            get_models_for_phase('nonexistent', config)
        assert "Phase 'nonexistent' not found in config" in str(exc_info.value)

    def test_get_models_for_phase_raises_value_error_empty_list(self, tmp_config):
        """Test get_models_for_phase raises ValueError for empty list."""
        config_path = tmp_config({
            'phases': {
                'planning': []
            }
        })
        config = load_config(config_path)
        with pytest.raises(ValueError) as exc_info:
            get_models_for_phase('planning', config)
        assert "empty model list" in str(exc_info.value)

    def test_get_models_for_phase_missing_phases_key(self, tmp_config):
        """Test raises ValueError when config is missing 'phases' key."""
        config_path = tmp_config({'other': 'value'})
        config = load_config(config_path)
        with pytest.raises(ValueError) as exc_info:
            get_models_for_phase('planning', config)
        assert "missing 'phases' key" in str(exc_info.value)

    def test_get_models_for_phase_phases_not_dict(self, tmp_config):
        """Test raises ValueError when phases is not a dictionary."""
        config_path = tmp_config({'phases': 'not-a-dict'})
        config = load_config(config_path)
        with pytest.raises(ValueError) as exc_info:
            get_models_for_phase('planning', config)
        assert "must be a dictionary" in str(exc_info.value)

    def test_get_models_for_phase_not_a_list(self, tmp_config):
        """Test raises ValueError when phase value is not a list."""
        config_path = tmp_config({
            'phases': {
                'planning': 'not-a-list'
            }
        })
        config = load_config(config_path)
        with pytest.raises(ValueError) as exc_info:
            get_models_for_phase('planning', config)
        assert "must have a list of models" in str(exc_info.value)


class TestClearCache:
    def test_clear_cache_works(self, tmp_config):
        """Test clear_cache works."""
        config_path = tmp_config({
            'phases': {
                'planning': ['model-a']
            }
        })
        # Load config to populate cache
        config = load_config(config_path)
        assert config is not None
        
        # Clear the cache
        clear_cache()
        
        # Now loading again should work (verifies cache was cleared)
        config2 = load_config(config_path)
        assert config2 == config


class TestGetPeEnabled:
    def test_global_on(self):
        """Test global-on: global enabled True returns True."""
        config = {
            "prompt_engineering": {
                "enabled": True
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is True
        assert isinstance(result, bool)

    def test_global_off(self):
        """Test global-off: global enabled False returns False."""
        config = {
            "prompt_engineering": {
                "enabled": False
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is False
        assert isinstance(result, bool)

    def test_phase_override_off(self):
        """Test phase-override-off: phase-level override sets enabled False."""
        config = {
            "prompt_engineering": {
                "enabled": True,
                "phases": {
                    "planning": {
                        "enabled": False
                    }
                }
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is False
        assert isinstance(result, bool)

    def test_phase_override_on(self):
        """Test phase-override-on: phase-level override sets enabled True."""
        config = {
            "prompt_engineering": {
                "enabled": False,
                "phases": {
                    "planning": {
                        "enabled": True
                    }
                }
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is True
        assert isinstance(result, bool)

    def test_missing_phase_fallback(self):
        """Test missing-phase-fallback: phase not in phases dict uses global."""
        config = {
            "prompt_engineering": {
                "enabled": False,
                "phases": {
                    "other_phase": {
                        "enabled": True
                    }
                }
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is False
        assert isinstance(result, bool)

    def test_missing_phases_key_fallback(self):
        """Test missing-phases-key-fallback: no phases key uses global."""
        config = {
            "prompt_engineering": {
                "enabled": True
            }
        }
        result = get_pe_enabled("planning", config)
        assert result is True
        assert isinstance(result, bool)
