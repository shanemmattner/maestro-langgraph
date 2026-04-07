"""Maestro service lifecycle — ensures the observability stack is running.

Called from core/runner.py before every workflow. Fast no-op if stack is healthy.
"""

import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_INFRA_DIR = Path(__file__).parent.parent / "infrastructure"
_CACHE_DIR = Path.home() / ".cache" / "maestro"
_LAST_ACTIVE_FILE = _CACHE_DIR / "last_active"
_LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3100")
_START_TIMEOUT = 180  # seconds to wait for start.sh


def ensure_stack_running() -> None:
    """Ensure Langfuse stack is up. Starts it if not. No-op if keys not configured."""
    # Skip if tracing not configured
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        logger.debug("services: tracing not configured, skipping stack check")
        return

    # Touch last_active FIRST to prevent watchdog race
    _touch_last_active()

    if _is_langfuse_healthy():
        logger.debug("services: stack healthy")
        return

    logger.info("services: stack not healthy, starting...")
    _start_stack()


def touch_active() -> None:
    """Refresh the last_active timestamp. Call periodically in long-running workflows."""
    _touch_last_active()


def _touch_last_active() -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_ACTIVE_FILE.write_text(str(int(time.time())))
    except OSError as e:
        logger.warning("services: could not touch last_active: %s", e)


def _is_langfuse_healthy() -> bool:
    try:
        url = f"{_LANGFUSE_BASE_URL}/api/public/health"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_stack() -> None:
    start_sh = _INFRA_DIR / "start.sh"
    if not start_sh.exists():
        logger.warning("services: start.sh not found at %s — run 'infrastructure/setup.sh' or start Langfuse manually", start_sh)
        return

    try:
        result = subprocess.run(
            ["/bin/bash", str(start_sh)],
            timeout=_START_TIMEOUT,
            check=True,
            capture_output=False,  # stream output to terminal
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Stack failed to start within {_START_TIMEOUT}s")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"start.sh failed with exit code {e.returncode}")

    if not _is_langfuse_healthy():
        raise RuntimeError("Stack started but Langfuse health check still failing")

    logger.info("services: stack started successfully")
