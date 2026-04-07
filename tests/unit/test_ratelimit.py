"""Unit tests for core/ratelimit.py"""

import unittest
import threading
import time
from unittest.mock import patch

from langgraph_maestro.core.ratelimit import (
    RateLimitError,
    detect_rate_limit,
    RateLimitTracker,
    get_rate_limit_config,
)


class TestDetectRateLimit(unittest.TestCase):
    """Tests for detect_rate_limit function."""
    
    def test_detect_rate_limit_json_error(self):
        """Test detection of rate limit in JSON error field."""
        response = '{"error":"rate_limit","message":"Too many requests"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_json_error_spaced(self):
        """Test detection of rate limit with space after colon."""
        response = '{"error": "rate_limit", "message": "Too many requests"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_code_field(self):
        """Test detection of rate limit in code field."""
        response = '{"code":"rate_limit","msg":"Rate limit exceeded"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_code_field_spaced(self):
        """Test detection of rate limit in code field with space."""
        response = '{"code": "rate_limit", "msg": "Rate limit exceeded"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_case_insensitive(self):
        """Test case-insensitive detection of rate limit."""
        response = '{"message": "RATE LIMIT exceeded"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_case_insensitive_mixed(self):
        """Test mixed case rate limit detection."""
        response = '{"error": "Rate Limit detected"}'
        self.assertTrue(detect_rate_limit(response))
    
    def test_detect_rate_limit_normal_response(self):
        """Test that normal responses return False."""
        response = '{"result": "success", "data": []}'
        self.assertFalse(detect_rate_limit(response))
    
    def test_detect_rate_limit_empty_response(self):
        """Test empty response returns False."""
        self.assertFalse(detect_rate_limit(""))
        self.assertFalse(detect_rate_limit(None))
    
    def test_detect_rate_limit_other_error(self):
        """Test that other errors don't trigger detection."""
        response = '{"error":"invalid_request","message":"Missing parameter"}'
        self.assertFalse(detect_rate_limit(response))


class TestRateLimitTracker(unittest.TestCase):
    """Tests for RateLimitTracker class."""
    
    def test_tracker_consecutive_count(self):
        """Test consecutive count increments correctly."""
        tracker = RateLimitTracker(max_consecutive=3)
        
        self.assertEqual(tracker.consecutive_count, 0)
        
        tracker.record_rate_limit()
        self.assertEqual(tracker.consecutive_count, 1)
        
        tracker.record_rate_limit()
        self.assertEqual(tracker.consecutive_count, 2)
    
    def test_tracker_reset_on_success(self):
        """Test counter resets on successful request."""
        tracker = RateLimitTracker(max_consecutive=3)
        
        tracker.record_rate_limit()
        tracker.record_rate_limit()
        self.assertEqual(tracker.consecutive_count, 2)
        
        tracker.record_success()
        self.assertEqual(tracker.consecutive_count, 0)
    
    def test_tracker_raises_after_max(self):
        """Test RateLimitError raised after max consecutive."""
        tracker = RateLimitTracker(max_consecutive=2)
        
        tracker.record_rate_limit()
        self.assertEqual(tracker.consecutive_count, 1)
        
        # Second one should raise - at this point count=2, so backoff = 2^2 * 5 = 20
        with self.assertRaises(RateLimitError) as context:
            tracker.record_rate_limit()
        
        # When error is raised, count is already 2, so backoff = 2^2 * 5 = 20
        self.assertEqual(context.exception.retry_after_seconds, 20.0)
    
    def test_tracker_backoff_exponential(self):
        """Test exponential backoff calculation."""
        tracker = RateLimitTracker(max_consecutive=5)
        tracker.set_delays(base_delay=5, max_delay=120)
        
        tracker.record_rate_limit()
        tracker.record_rate_limit()
        tracker.record_rate_limit()
        
        # 2^3 * 5 = 40
        self.assertEqual(tracker.get_backoff_seconds(), 40)
    
    def test_tracker_backoff_capped(self):
        """Test backoff is capped at max_delay."""
        tracker = RateLimitTracker(max_consecutive=10)
        tracker.set_delays(base_delay=5, max_delay=60)
        
        # Push count high enough to exceed max_delay
        for _ in range(6):
            tracker.record_rate_limit()
        
        # 2^6 * 5 = 320, but capped at 60
        self.assertEqual(tracker.get_backoff_seconds(), 60)
    
    def test_tracker_default_values(self):
        """Test default initialization values."""
        tracker = RateLimitTracker()
        
        self.assertEqual(tracker._max_consecutive, 3)
        self.assertEqual(tracker._base_delay, 5.0)
        self.assertEqual(tracker._max_delay, 120.0)


class TestGetRateLimitConfig(unittest.TestCase):
    """Tests for get_rate_limit_config function."""
    
    def test_config_defaults(self):
        """Test default configuration when no config provided."""
        config = get_rate_limit_config({})
        
        self.assertEqual(config["max_consecutive"], 3)
        self.assertEqual(config["base_delay"], 5)
        self.assertEqual(config["max_delay"], 120)
    
    def test_config_custom_values(self):
        """Test custom configuration values."""
        config = get_rate_limit_config({
            "ratelimit": {
                "max_consecutive": 5,
                "base_delay": 10,
                "max_delay": 60
            }
        })
        
        self.assertEqual(config["max_consecutive"], 5)
        self.assertEqual(config["base_delay"], 10)
        self.assertEqual(config["max_delay"], 60)
    
    def test_config_partial_override(self):
        """Test partial configuration override."""
        config = get_rate_limit_config({
            "ratelimit": {
                "max_consecutive": 2
            }
        })
        
        self.assertEqual(config["max_consecutive"], 2)
        self.assertEqual(config["base_delay"], 5)  # default
        self.assertEqual(config["max_delay"], 120)  # default
    
    def test_config_none_input(self):
        """Test None input returns defaults."""
        config = get_rate_limit_config(None)
        
        self.assertEqual(config["max_consecutive"], 3)


class TestThreadSafety(unittest.TestCase):
    """Tests for thread safety of RateLimitTracker."""
    
    def test_thread_safety_concurrent_record(self):
        """Test concurrent record_rate_limit calls are thread-safe."""
        tracker = RateLimitTracker(max_consecutive=300)  # Higher than 4*50=200
        errors = []
        
        def record_limits():
            try:
                for _ in range(50):
                    tracker.record_rate_limit()
            except Exception as e:
                errors.append(e)
        
        threads = []
        for _ in range(4):
            t = threading.Thread(target=record_limits)
            threads.append(t)
        
        # Start all threads simultaneously
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Should not have any unexpected errors
        self.assertEqual(len(errors), 0)
        
        # Count should be 200 (4 threads * 50 calls)
        self.assertEqual(tracker.consecutive_count, 200)
    
    def test_thread_safety_mixed_operations(self):
        """Test mixed success/failure recording is thread-safe."""
        tracker = RateLimitTracker(max_consecutive=1000)
        
        def worker():
            for _ in range(20):
                tracker.record_rate_limit()
                tracker.record_success()
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Should end at 0 due to success calls
        self.assertEqual(tracker.consecutive_count, 0)


class TestRateLimitError(unittest.TestCase):
    """Tests for RateLimitError exception."""
    
    def test_error_with_retry_after(self):
        """Test error includes retry_after_seconds."""
        error = RateLimitError("Rate limit exceeded", retry_after_seconds=30.0)
        
        self.assertEqual(str(error), "Rate limit exceeded")
        self.assertEqual(error.retry_after_seconds, 30.0)
    
    def test_error_without_retry_after(self):
        """Test error works without retry_after_seconds."""
        error = RateLimitError("Rate limit exceeded")
        
        self.assertEqual(str(error), "Rate limit exceeded")
        self.assertIsNone(error.retry_after_seconds)


if __name__ == "__main__":
    unittest.main()
