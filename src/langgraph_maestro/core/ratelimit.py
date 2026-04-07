"""Rate limit detection and handling for langgraph-maestro.

This module provides utilities for detecting rate limit responses from APIs
and handling them gracefully with exponential backoff.
"""

import logging
import re
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Exception raised when a rate limit is detected.

    Attributes:
        retry_after_seconds: Suggested wait time before retrying.
    """

    def __init__(self, message: str = "Rate limit exceeded", retry_after_seconds: Optional[float] = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def detect_rate_limit(response_text: str) -> bool:
    """Detect if the response indicates a rate limit error.

    Checks for common rate limit indicators in API responses:
    - JSON error field with "rate_limit" value
    - JSON code field with "rate_limit" value
    - Case-insensitive "rate limit" in error messages

    Args:
        response_text: The response text to check.

    Returns:
        True if rate limit detected, False otherwise.
    """
    if not response_text:
        return False

    # Check for '"error":"rate_limit"' or '"error": "rate_limit"'
    if re.search(r'"error"\s*:\s*"rate_limit"', response_text, re.IGNORECASE):
        logger.debug("Rate limit detected in error field")
        return True

    # Check for '"code":"rate_limit"' or '"code": "rate_limit"'
    if re.search(r'"code"\s*:\s*"rate_limit"', response_text, re.IGNORECASE):
        logger.debug("Rate limit detected in code field")
        return True

    # Case-insensitive check for "rate limit" in the response
    if re.search(r"rate\s+limit", response_text, re.IGNORECASE):
        logger.debug("Rate limit detected in message text")
        return True

    return False


class RateLimitTracker:
    """Thread-safe tracker for consecutive rate limit occurrences.

    Tracks consecutive rate limit errors and provides exponential backoff
    timing for retry logic.
    """

    def __init__(self, max_consecutive: int = 3):
        """Initialize the rate limit tracker.

        Args:
            max_consecutive: Maximum consecutive rate limits before abort.
        """
        self._max_consecutive = max_consecutive
        self._consecutive_count = 0
        self._lock = threading.Lock()
        self._base_delay = 5.0
        self._max_delay = 120.0

    @property
    def consecutive_count(self) -> int:
        """Get the current consecutive rate limit count."""
        with self._lock:
            return self._consecutive_count

    def record_rate_limit(self) -> None:
        """Record a rate limit occurrence.

        Increments the consecutive counter. Raises RateLimitError if
        max_consecutive is exceeded.

        Raises:
            RateLimitError: When max consecutive rate limits exceeded.
        """
        with self._lock:
            self._consecutive_count += 1
            count = self._consecutive_count

        logger.warning(f"Rate limit detected, consecutive count: {count}/{self._max_consecutive}")

        if count >= self._max_consecutive:
            backoff = self.get_backoff_seconds()
            raise RateLimitError(
                f"Max consecutive rate limits ({self._max_consecutive}) exceeded",
                retry_after_seconds=backoff
            )

    def record_success(self) -> None:
        """Record a successful request.

        Resets the consecutive counter to zero.
        """
        with self._lock:
            if self._consecutive_count > 0:
                logger.info("Rate limit reset - request successful")
            self._consecutive_count = 0

    def get_backoff_seconds(self) -> float:
        """Calculate exponential backoff delay.

        Uses formula: min(2^consecutive * base_delay, max_delay)

        Returns:
            Delay in seconds before retry.
        """
        with self._lock:
            count = self._consecutive_count

        # Exponential backoff: 2^count * base_delay
        delay = (2 ** count) * self._base_delay

        # Cap at max_delay
        return min(delay, self._max_delay)

    def set_delays(self, base_delay: float, max_delay: float) -> None:
        """Configure backoff delay parameters.

        Args:
            base_delay: Base delay in seconds (default 5).
            max_delay: Maximum delay in seconds (default 120).
        """
        with self._lock:
            self._base_delay = base_delay
            self._max_delay = max_delay


def get_rate_limit_config(config: dict) -> dict:
    """Extract rate limit configuration from config dict.

    Expected config structure:
        ratelimit:
            max_consecutive: 3
            base_delay: 5
            max_delay: 120

    Args:
        config: Application configuration dictionary.

    Returns:
        Dictionary with rate limit settings.
    """
    defaults = {
        "max_consecutive": 3,
        "base_delay": 5,
        "max_delay": 120
    }

    if not config:
        return defaults

    ratelimit_config = config.get("ratelimit", {})

    return {
        "max_consecutive": ratelimit_config.get("max_consecutive", defaults["max_consecutive"]),
        "base_delay": ratelimit_config.get("base_delay", defaults["base_delay"]),
        "max_delay": ratelimit_config.get("max_delay", defaults["max_delay"])
    }
