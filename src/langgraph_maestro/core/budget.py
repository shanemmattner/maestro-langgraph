"""Budget management module for langgraph-maestro.

Provides per-run and daily token budget guards to prevent excessive token usage.
"""

import logging
import threading
from datetime import date, datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Exception raised when token budget is exceeded."""

    def __init__(self, limit: int, current: int, budget_type: str = "per_run"):
        self.limit = limit
        self.current = current
        self.budget_type = budget_type
        super().__init__(
            f"Budget exceeded: {budget_type} limit of {limit} tokens reached "
            f"(current: {current})"
        )


class BudgetGuard:
    """Tracks token usage across pipeline runs and enforces budget limits.

    Supports both per-run limits and daily limits. Thread-safe for concurrent usage.
    """

    def __init__(
        self,
        per_run_limit: int = 500000,
        daily_limit: int = 5000000,
        abort_on_exceed: bool = True,
        warning_threshold: float = 0.8
    ):
        """Initialize BudgetGuard with specified limits.

        Args:
            per_run_limit: Maximum tokens allowed per pipeline run
            daily_limit: Maximum tokens allowed per calendar day
            abort_on_exceed: Whether to raise BudgetExceeded or just warn
            warning_threshold: Percentage at which to log warnings (0.0-1.0)
        """
        self.per_run_limit = per_run_limit
        self.daily_limit = daily_limit
        self.abort_on_exceed = abort_on_exceed
        self.warning_threshold = warning_threshold

        # Per-run tracking (reset on new guard instance)
        self._per_run_usage: int = 0

        # Daily tracking (keyed by date string)
        self._daily_usage: Dict[str, int] = {}
        self._lock = threading.Lock()

        logger.info(
            f"BudgetGuard initialized: per_run={per_run_limit}, "
            f"daily={daily_limit}, abort_on_exceed={abort_on_exceed}"
        )

    def check_budget(self, tokens_used: int) -> None:
        """Check if adding tokens would exceed budget limits.

        Args:
            tokens_used: Number of tokens to add to current usage

        Raises:
            BudgetExceeded: If either per-run or daily limit is exceeded
        """
        if tokens_used < 0:
            raise ValueError(f"tokens_used must be non-negative, got {tokens_used}")

        with self._lock:
            today = date.today().isoformat()
            current_per_run = self._per_run_usage
            current_daily = self._daily_usage.get(today, 0)

            new_per_run = current_per_run + tokens_used
            new_daily = current_daily + tokens_used

            # Check per-run limit
            if new_per_run > self.per_run_limit:
                logger.error(
                    f"Per-run budget exceeded: {new_per_run}/{self.per_run_limit}"
                )
                if self.abort_on_exceed:
                    raise BudgetExceeded(self.per_run_limit, new_per_run, "per_run")

            # Check daily limit
            if new_daily > self.daily_limit:
                logger.error(
                    f"Daily budget exceeded: {new_daily}/{self.daily_limit}"
                )
                if self.abort_on_exceed:
                    raise BudgetExceeded(self.daily_limit, new_daily, "daily")

            # Check warning thresholds
            self._check_warnings(current_per_run, new_per_run, self.per_run_limit, "per_run")
            self._check_warnings(current_daily, new_daily, self.daily_limit, "daily")

            # Update usage
            self._per_run_usage = new_per_run
            self._daily_usage[today] = new_daily

            # Clean up old daily usage entries
            keys_to_remove = [k for k in self._daily_usage if k != today]
            for k in keys_to_remove:
                del self._daily_usage[k]

            logger.debug(
                f"Budget updated: per_run={new_per_run}, daily={new_daily}"
            )

    def _check_warnings(
        self,
        current: int,
        new_value: int,
        limit: int,
        budget_type: str
    ) -> None:
        """Log warning if usage crosses threshold."""
        threshold = int(limit * self.warning_threshold)

        # Warn if crossed 80% threshold
        if current < threshold and new_value >= threshold:
            logger.warning(
                f"{budget_type.capitalize()} budget at {self.warning_threshold*100:.0f}%: "
                f"{new_value}/{limit} tokens"
            )

    def get_usage(self) -> Dict[str, int]:
        """Get current usage statistics.

        Returns:
            Dict with per_run_usage, daily_usage, per_run_limit, daily_limit
        """
        with self._lock:
            today = date.today().isoformat()
            return {
                "per_run_usage": self._per_run_usage,
                "daily_usage": self._daily_usage.get(today, 0),
                "per_run_limit": self.per_run_limit,
                "daily_limit": self.daily_limit
            }

    def reset_per_run(self) -> None:
        """Reset per-run usage counter."""
        with self._lock:
            self._per_run_usage = 0
            logger.info("Per-run budget reset")

    def reset_daily(self) -> None:
        """Reset daily usage for today."""
        with self._lock:
            today = date.today().isoformat()
            if today in self._daily_usage:
                del self._daily_usage[today]
            logger.info("Daily budget reset")


def get_budget_config(config: dict) -> dict:
    """Extract budget settings from workflow configuration.

    Args:
        config: Full workflow configuration dict

    Returns:
        Dict with budget settings (per_run_tokens, daily_tokens, abort_on_exceed)
    """
    budget_config = config.get("budget", {})

    return {
        "per_run_tokens": budget_config.get("per_run_tokens", 500000),
        "daily_tokens": budget_config.get("daily_tokens", 5000000),
        "abort_on_exceed": budget_config.get("abort_on_exceed", True)
    }
