"""Core package exports with lazy loading."""

from importlib import import_module

_EXPORTS = {
    "setup_logging": ("langgraph_maestro.core.logging", "setup_logging"),
    "get_logger": ("langgraph_maestro.core.logging", "get_logger"),
    "StallDetector": ("langgraph_maestro.core.stall", "StallDetector"),
    "web_search": ("langgraph_maestro.core.web", "web_search"),
    "web_scrape": ("langgraph_maestro.core.web", "web_scrape"),
    "search_and_extract": ("langgraph_maestro.core.web", "search_and_extract"),
    "is_search_available": ("langgraph_maestro.core.web", "is_search_available"),
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
