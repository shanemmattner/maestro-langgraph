"""Tests for core.stall.StallDetector."""

import time

import pytest
from langgraph_maestro.core.stall import StallDetector


class TestStallDetectorTimeout:
    def test_no_timeout_when_within_limit(self):
        sd = StallDetector(timeout_seconds=10)
        sd.start_task("t1")
        assert sd.check_timeout("t1") is None

    def test_timeout_detected(self):
        sd = StallDetector(timeout_seconds=0.01)
        sd.start_task("t1")
        time.sleep(0.02)
        result = sd.check_timeout("t1")
        assert result is not None
        assert result["type"] == "timeout"
        assert result["task_id"] == "t1"
        assert result["elapsed_seconds"] > 0.01

    def test_timeout_unknown_task_returns_none(self):
        sd = StallDetector()
        assert sd.check_timeout("unknown") is None

    def test_timeout_appended_to_stalls(self):
        sd = StallDetector(timeout_seconds=0.01)
        sd.start_task("t1")
        time.sleep(0.02)
        sd.check_timeout("t1")
        assert len(sd.get_stalls()) == 1
        assert sd.get_stalls()[0]["type"] == "timeout"


class TestStallDetectorNoProgress:
    def test_no_stall_with_progress(self):
        sd = StallDetector(no_progress_threshold=3)
        assert sd.record_wave_completion(5) is None
        assert sd.record_wave_completion(3) is None

    def test_stall_after_threshold_empty_waves(self):
        sd = StallDetector(no_progress_threshold=3)
        sd.record_wave_completion(0)
        sd.record_wave_completion(0)
        result = sd.record_wave_completion(0)
        assert result is not None
        assert result["type"] == "no_progress"
        assert result["consecutive_empty_waves"] == 3

    def test_progress_resets_counter(self):
        sd = StallDetector(no_progress_threshold=3)
        sd.record_wave_completion(0)
        sd.record_wave_completion(0)
        sd.record_wave_completion(1)  # resets
        sd.record_wave_completion(0)
        assert sd.record_wave_completion(0) is None  # only 2 consecutive


class TestStallDetectorLoop:
    def test_no_loop_with_few_tasks(self):
        sd = StallDetector(loop_detection_window=3)
        sd.end_task("t1", {"status": "done", "changes": ["a"]})
        assert sd.check_loop() is None

    def test_loop_detected_with_identical_tasks(self):
        sd = StallDetector(loop_detection_window=3)
        for _ in range(3):
            sd.end_task("t1", {"status": "done", "changes": ["a"]})
        result = sd.check_loop()
        assert result is not None
        assert result["type"] == "loop"

    def test_no_loop_with_different_tasks(self):
        sd = StallDetector(loop_detection_window=3)
        sd.end_task("t1", {"status": "done", "changes": ["a"]})
        sd.end_task("t2", {"status": "done", "changes": ["b"]})
        sd.end_task("t3", {"status": "done", "changes": ["c"]})
        assert sd.check_loop() is None


class TestStallDetectorFromConfig:
    def test_from_config_with_all_values(self):
        config = {
            "timeouts": {
                "default": 600,
                "stall": {
                    "no_progress_threshold": 5,
                    "loop_detection_window": 10,
                },
            }
        }
        sd = StallDetector.from_config(config)
        assert sd.timeout_seconds == 600
        assert sd.no_progress_threshold == 5
        assert sd.loop_detection_window == 10

    def test_from_config_with_defaults(self):
        sd = StallDetector.from_config({})
        assert sd.timeout_seconds == 300
        assert sd.no_progress_threshold == 3
        assert sd.loop_detection_window == 5

    def test_from_config_partial(self):
        config = {"timeouts": {"default": 120}}
        sd = StallDetector.from_config(config)
        assert sd.timeout_seconds == 120
        assert sd.no_progress_threshold == 3


class TestStallDetectorClear:
    def test_clear_resets_all_state(self):
        sd = StallDetector(timeout_seconds=0.01, no_progress_threshold=1)
        sd.start_task("t1")
        time.sleep(0.02)
        sd.check_timeout("t1")
        sd.record_wave_completion(0)
        sd.end_task("t1", {"status": "done", "changes": []})

        sd.clear()
        assert sd.get_stalls() == []
        assert sd._task_start_times == {}
        assert sd._wave_completion_counts == []
        assert sd._consecutive_empty_waves == 0
        assert sd._recent_tasks == []


class TestStallDetectorEdgeCases:
    def test_end_task_without_start(self):
        """end_task for unknown task should not crash."""
        sd = StallDetector()
        sd.end_task("unknown")  # no-op, shouldn't raise

    def test_end_task_without_result(self):
        """end_task without result should not record signature."""
        sd = StallDetector()
        sd.start_task("t1")
        sd.end_task("t1")
        assert sd._recent_tasks == []

    def test_end_task_with_result_records_signature(self):
        sd = StallDetector()
        sd.start_task("t1")
        sd.end_task("t1", {"status": "done", "changes": ["a", "b"]})
        assert len(sd._recent_tasks) == 1
        sig = sd._recent_tasks[0]
        assert sig["task_id"] == "t1"
        assert sig["status"] == "done"
        assert sig["changes"] == ("a", "b")

    def test_loop_window_slides(self):
        """Recent tasks list should not exceed loop_detection_window."""
        sd = StallDetector(loop_detection_window=3)
        for i in range(10):
            sd.end_task(f"t{i}", {"status": "done", "changes": [str(i)]})
        assert len(sd._recent_tasks) == 3

    def test_multiple_stalls_accumulate(self):
        sd = StallDetector(timeout_seconds=0.01, no_progress_threshold=1)
        sd.start_task("t1")
        time.sleep(0.02)
        sd.check_timeout("t1")
        sd.record_wave_completion(0)
        assert len(sd.get_stalls()) == 2
        assert sd.get_stalls()[0]["type"] == "timeout"
        assert sd.get_stalls()[1]["type"] == "no_progress"

    def test_no_progress_continues_accumulating(self):
        """After threshold hit, further empty waves keep appending stalls."""
        sd = StallDetector(no_progress_threshold=2)
        sd.record_wave_completion(0)
        sd.record_wave_completion(0)  # triggers
        sd.record_wave_completion(0)  # triggers again
        assert len(sd.get_stalls()) == 2

    def test_make_signature_missing_keys(self):
        """_make_signature handles missing keys gracefully."""
        sig = StallDetector._make_signature("t1", {})
        assert sig["task_id"] == "t1"
        assert sig["status"] is None
        assert sig["changes"] == ()

    def test_start_task_overwrites_previous(self):
        """Starting same task again should update the start time."""
        sd = StallDetector(timeout_seconds=10)
        sd.start_task("t1")
        old_time = sd._task_start_times["t1"]
        time.sleep(0.01)
        sd.start_task("t1")
        assert sd._task_start_times["t1"] > old_time
