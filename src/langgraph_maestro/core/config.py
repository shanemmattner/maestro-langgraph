"""YAML config loader for langgraph-maestro."""

from pathlib import Path
from typing import Any

import yaml


_config_cache: dict[str, Any] | None = None
_config_path: Path | None = None


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and cache a YAML config file.

    Args:
        path: Explicit path to the YAML config file.

    Returns:
        The loaded configuration as a dictionary.

    Raises:
        FileNotFoundError: If the path doesn't exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    global _config_cache, _config_path

    path = Path(path)

    if not path.is_absolute() and not path.exists():
        # Resolve relative paths (e.g. "workflows/default/config.yaml")
        # against the package root directory.
        _pkg_root = Path(__file__).resolve().parent.parent  # langgraph_maestro/
        candidate = _pkg_root / path
        if candidate.exists():
            path = candidate

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    if config is None:
        config = {}

    _config_cache = config
    _config_path = path

    return config


def get_models_for_phase(phase: str, config: dict[str, Any]) -> list[str]:
    """Get the model fallback chain for a given phase.

    Args:
        phase: The phase name to look up.
        config: The configuration dictionary (loaded via load_config).

    Returns:
        A list of model names for the phase (the fallback chain).

    Raises:
        ValueError: If the phase is not found or the list is empty.
    """
    if "phases" not in config:
        raise ValueError("Config is missing 'phases' key")

    phases = config["phases"]

    if not isinstance(phases, dict):
        raise ValueError("Config 'phases' must be a dictionary")

    if phase not in phases:
        raise ValueError(f"Phase '{phase}' not found in config. Available phases: {list(phases.keys())}")

    models = phases[phase]

    if not isinstance(models, list):
        raise ValueError(f"Phase '{phase}' must have a list of models, got {type(models).__name__}")

    if not models:
        raise ValueError(f"Phase '{phase}' has an empty model list")

    return models


def clear_cache() -> None:
    """Clear the cached configuration.

    This is primarily useful for testing.
    """
    global _config_cache, _config_path
    _config_cache = None
    _config_path = None


def get_stall_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract stall detection settings from config."""
    timeouts = config.get("timeouts", {})
    stall = timeouts.get("stall", {})
    return {
        "timeout_seconds": timeouts.get("default", 300),
        "no_progress_threshold": stall.get("no_progress_threshold", 3),
        "loop_detection_window": stall.get("loop_detection_window", 5),
    }


def get_skills_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract skill injection settings from config."""
    return config.get("skills", {})


def get_pe_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract prompt engineering middleware settings from config."""
    defaults = {
        "enabled": False,
        "model": "MiniMax-M2.5-highspeed",
        "phases": [],
        "timeout": 120,
        "fallback_to_raw": True,
    }
    pe = config.get("prompt_engineering", {})
    return {**defaults, **pe}


def get_pe_enabled(phase: str, config: dict[str, Any]) -> bool:
    """Check if prompt engineering is enabled for a given phase.

    Checks phase-level override first, then falls back to global enabled flag.

    Args:
        phase: The phase name to check.
        config: The configuration dictionary.

    Returns:
        True if prompt engineering is enabled for the phase, False otherwise.
        Returns False by default if neither phase-level nor global key exists
        (PE is opt-in).
    """
    pe_config = config.get("prompt_engineering", {})

    # Check phase-level override first
    phases = pe_config.get("phases", {})
    if isinstance(phases, list):
        # Legacy format: phases is a whitelist list
        return bool(pe_config.get("enabled", False)) and phase in phases
    if isinstance(phases, dict) and phase in phases:
        phase_config = phases[phase]
        if isinstance(phase_config, dict) and "enabled" in phase_config:
            return bool(phase_config["enabled"])

    # Fall back to global enabled flag
    if "enabled" in pe_config:
        return bool(pe_config["enabled"])

    # Default to False — PE is opt-in
    return False


def get_timeout_for_model(model: str, config: dict[str, Any]) -> int:
    """Get per-model timeout from config, with fallback to default."""
    timeouts = config.get("timeouts", {})
    models = timeouts.get("models", {})
    default = timeouts.get("default", 300)

    model_lower = model.lower()
    if "minimax" in model_lower:
        return models.get("minimax", default)
    if "claude" in model_lower:
        return models.get("claude", default)
    if model.startswith("mlx-community/") or model.startswith("local"):
        return models.get("local", default)
    return default


def workflow_config_path(caller_file: str) -> str:
    """Resolve config.yaml relative to the calling workflow module's directory.

    Usage in workflow files::

        from langgraph_maestro.core.config import workflow_config_path
        _DEFAULT_CONFIG = workflow_config_path(__file__)

    Args:
        caller_file: Pass ``__file__`` from the calling module.

    Returns:
        Absolute path string to config.yaml next to the caller.
    """
    return str(Path(caller_file).parent / "config.yaml")
