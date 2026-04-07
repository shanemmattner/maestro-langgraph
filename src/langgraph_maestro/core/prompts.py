"""Prompt versioning via Langfuse REST API with local fallback."""

import json
import logging
import os
import urllib.request
from pathlib import Path

from langgraph_maestro.core.tracing import _langfuse_auth_header, _langfuse_host, is_langfuse_available

logger = logging.getLogger(__name__)


class FallbackPrompt:
    """Offline prompt when Langfuse is unreachable."""

    def __init__(self, text: str, name: str = "", label: str = "local"):
        self.text = text
        self.name = name
        self.label = label

    def __str__(self):
        return self.text


def get_prompt(name: str, fallback_text: str, label: str = "production") -> str:
    """Fetch a prompt from Langfuse. Falls back to local text if unreachable.

    Args:
        name: Prompt name in Langfuse.
        fallback_text: Local fallback text.
        label: Langfuse prompt label (default: "production").

    Returns:
        Prompt text string.
    """
    if not is_langfuse_available():
        return fallback_text

    try:
        host = _langfuse_host()
        url = f"{host}/api/public/v2/prompts/{name}?label={label}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": _langfuse_auth_header(),
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            prompt_text = data.get("prompt", "")
            if prompt_text:
                logger.debug("prompt_fetched", extra={"name": name, "label": label})
                return prompt_text
    except Exception as e:
        logger.debug("prompt_fetch_failed", extra={"name": name, "error": str(e)})

    return fallback_text
