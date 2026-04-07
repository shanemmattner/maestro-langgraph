"""Core package exports with lazy loading."""

from importlib import import_module

_EXPORTS = {
    "setup_logging": ("langgraph_maestro.core.logging", "setup_logging"),
    "get_logger": ("langgraph_maestro.core.logging", "get_logger"),
    "StallDetector": ("langgraph_maestro.core.stall", "StallDetector"),
    "inject_skills": ("langgraph_maestro.core.skills", "inject_skills"),
    "load_skill": ("langgraph_maestro.core.skills", "load_skill"),
    "get_model_overlay": ("langgraph_maestro.core.skills", "get_model_overlay"),
    "improve_prompt": ("langgraph_maestro.core.pe", "improve_prompt"),
    "pe_node_factory": ("langgraph_maestro.core.pe", "pe_node_factory"),
    "load_config": ("langgraph_maestro.core.config", "load_config"),
    "get_models_for_phase": ("langgraph_maestro.core.config", "get_models_for_phase"),
    "clear_cache": ("langgraph_maestro.core.config", "clear_cache"),
    "get_stall_config": ("langgraph_maestro.core.config", "get_stall_config"),
    "get_skills_config": ("langgraph_maestro.core.config", "get_skills_config"),
    "get_pe_config": ("langgraph_maestro.core.config", "get_pe_config"),
    "get_timeout_for_model": ("langgraph_maestro.core.config", "get_timeout_for_model"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'langgraph_maestro.core' has no attribute {name!r}")

    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
