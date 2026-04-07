"""Stall detection for task execution.

Provides timestamp-based detection of:
- timeout: task exceeded max time
- no_progress: no completed tasks in a wave
- loop: repeated task patterns detected
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class StallDetector:
    """Tracks per-task timing and detects stall conditions.

    Uses synchronous timestamp-based detection - no threading/async.
    """

    def __init__(
        self,
        timeout_seconds: float = 300.0,
        no_progress_threshold: int = 3,
        loop_detection_window: int = 5,
    ):
        self.timeout_seconds = timeout_seconds
        self.no_progress_threshold = no_progress_threshold
        self.loop_detection_window = loop_detection_window

        self._task_start_times: dict[str, float] = {}
        self._wave_completion_counts: list[int] = []
        self._consecutive_empty_waves = 0
        self._recent_tasks: list[dict] = []
        self.stalls: list[dict] = []

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "StallDetector":
        """Create a StallDetector from a workflow config dict."""
        timeouts = config.get("timeouts", {})
        stall = timeouts.get("stall", {})
        return cls(
            timeout_seconds=timeouts.get("default", 300),
            no_progress_threshold=stall.get("no_progress_threshold", 3),
            loop_detection_window=stall.get("loop_detection_window", 5),
        )

    def start_task(self, task_id: str) -> None:
        """Mark task as started with current timestamp."""
        self._task_start_times[task_id] = time.time()

    def end_task(self, task_id: str, result: dict | None = None) -> None:
        """Mark task as completed and update tracking."""
        self._task_start_times.pop(task_id, None)
        if result:
            sig = self._make_signature(task_id, result)
            self._recent_tasks.append(sig)
            if len(self._recent_tasks) > self.loop_detection_window:
                self._recent_tasks.pop(0)

    def check_timeout(self, task_id: str) -> dict | None:
        """Check if a task has exceeded timeout. Returns stall dict or None."""
        start_time = self._task_start_times.get(task_id)
        if start_time is None:
            return None

        elapsed = time.time() - start_time
        if elapsed > self.timeout_seconds:
            stall = {
                "type": "timeout",
                "task_id": task_id,
                "elapsed_seconds": elapsed,
                "threshold": self.timeout_seconds,
            }
            self.stalls.append(stall)
            logger.warning(
                "stall_timeout",
                extra={"task_id": task_id, "elapsed": elapsed, "threshold": self.timeout_seconds},
            )
            return stall
        return None

    def record_wave_completion(self, completed_count: int) -> dict | None:
        """Record wave completion and check for no_progress."""
        self._wave_completion_counts.append(completed_count)

        if completed_count == 0:
            self._consecutive_empty_waves += 1
        else:
            self._consecutive_empty_waves = 0

        if self._consecutive_empty_waves >= self.no_progress_threshold:
            stall = {
                "type": "no_progress",
                "consecutive_empty_waves": self._consecutive_empty_waves,
                "threshold": self.no_progress_threshold,
                "wave_completions": list(self._wave_completion_counts[-5:]),
            }
            self.stalls.append(stall)
            logger.warning(
                "stall_no_progress",
                extra={
                    "consecutive_empty_waves": self._consecutive_empty_waves,
                    "threshold": self.no_progress_threshold,
                },
            )
            return stall
        return None

    def check_loop(self) -> dict | None:
        """Check for repetitive task patterns."""
        if len(self._recent_tasks) < self.loop_detection_window:
            return None

        window = self._recent_tasks[-self.loop_detection_window:]
        if len(set(str(t) for t in window)) == 1:
            stall = {
                "type": "loop",
                "repeated_signature": window[0],
                "window_size": len(window),
            }
            self.stalls.append(stall)
            logger.warning(
                "stall_loop",
                extra={"repeated_signature": str(window[0]), "window_size": len(window)},
            )
            return stall
        return None

    def get_stalls(self) -> list[dict]:
        """Return all detected stalls."""
        return list(self.stalls)

    def clear(self) -> None:
        """Reset detector state for new run."""
        self._task_start_times.clear()
        self._wave_completion_counts.clear()
        self._consecutive_empty_waves = 0
        self._recent_tasks.clear()
        self.stalls.clear()

    @staticmethod
    def _make_signature(task_id: str, result: dict) -> dict:
        """Create a signature for loop detection from task result."""
        return {
            "task_id": task_id,
            "status": result.get("status"),
            "changes": tuple(sorted(result.get("changes", []))),
        }
