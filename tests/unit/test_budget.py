"""Unit tests for core/budget module."""

import logging
import threading
import time
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from langgraph_maestro.core.budget import BudgetExceeded, BudgetGuard, get_budget_config


class TestBudgetGuard:
    """Tests for BudgetGuard class."""
    
    def test_initialization(self):
        """Test BudgetGuard initializes with correct defaults."""
        guard = BudgetGuard(
            per_run_limit=1000,
            daily_limit=5000,
            abort_on_exceed=True
        )
        
        assert guard.per_run_limit == 1000
        assert guard.daily_limit == 5000
        assert guard.abort_on_exceed is True
        assert guard._per_run_usage == 0
    
    def test_budget_tracking_increments(self):
        """Test budget tracking increments correctly."""
        guard = BudgetGuard(per_run_limit=1000, daily_limit=5000, abort_on_exceed=True)
        
        # Initial usage should be 0
        usage = guard.get_usage()
        assert usage["per_run_usage"] == 0
        assert usage["daily_usage"] == 0
        
        # Add tokens
        guard.check_budget(100)
        usage = guard.get_usage()
        assert usage["per_run_usage"] == 100
        assert usage["daily_usage"] == 100
        
        # Add more tokens
        guard.check_budget(200)
        usage = guard.get_usage()
        assert usage["per_run_usage"] == 300
        assert usage["daily_usage"] == 300
    
    def test_warning_at_80_percent(self, caplog):
        """Test warning is logged at 80% threshold."""
        caplog.set_level(logging.WARNING)
        
        guard = BudgetGuard(
            per_run_limit=1000,
            daily_limit=5000,
            abort_on_exceed=False
        )
        
        # Cross per-run 80% threshold (800 tokens)
        guard.check_budget(800)
        
        # Should log warning
        assert any(
            "Per_run budget at 80%" in record.message
            for record in caplog.records
        ), "Expected warning at 80% threshold"
    
    def test_warning_only_once(self, caplog):
        """Test warning is only logged once when crossing threshold."""
        caplog.set_level(logging.WARNING)
        
        guard = BudgetGuard(
            per_run_limit=1000,
            daily_limit=5000,
            abort_on_exceed=False
        )
        
        # Cross threshold
        guard.check_budget(800)
        # Add more without crossing new threshold
        guard.check_budget(50)
        
        warning_count = sum(
            1 for record in caplog.records
            if "Per_run budget at 80%" in record.message
        )
        
        # Should only warn once
        assert warning_count == 1
    
    def test_budget_exceeded_raises_exception(self):
        """Test BudgetExceeded is raised at limit."""
        guard = BudgetGuard(
            per_run_limit=100,
            daily_limit=1000,
            abort_on_exceed=True
        )
        
        with pytest.raises(BudgetExceeded) as exc_info:
            guard.check_budget(150)
        
        assert exc_info.value.limit == 100
        assert exc_info.value.current == 150
        assert exc_info.value.budget_type == "per_run"
    
    def test_daily_limit_exceeded(self):
        """Test daily limit is enforced."""
        guard = BudgetGuard(
            per_run_limit=100000,
            daily_limit=500,
            abort_on_exceed=True
        )
        
        with pytest.raises(BudgetExceeded) as exc_info:
            guard.check_budget(600)
        
        assert exc_info.value.budget_type == "daily"
        assert exc_info.value.limit == 500
    
    def test_no_abort_on_exceed(self, caplog):
        """Test budget continues tracking when abort_on_exceed is False."""
        caplog.set_level(logging.ERROR)
        
        guard = BudgetGuard(
            per_run_limit=100,
            daily_limit=1000,
            abort_on_exceed=False
        )
        
        # Should not raise
        guard.check_budget(150)
        
        # But should still track
        usage = guard.get_usage()
        assert usage["per_run_usage"] == 150
    
    def test_get_usage_returns_correct_dict(self):
        """Test get_usage returns correct statistics."""
        guard = BudgetGuard(
            per_run_limit=1000,
            daily_limit=5000,
            abort_on_exceed=True
        )
        
        guard.check_budget(250)
        
        usage = guard.get_usage()
        
        assert usage == {
            "per_run_usage": 250,
            "daily_usage": 250,
            "per_run_limit": 1000,
            "daily_limit": 5000
        }
    
    def test_daily_reset_on_new_day(self):
        """Test daily usage resets on new day."""
        guard = BudgetGuard(
            per_run_limit=100000,
            daily_limit=1000,
            abort_on_exceed=True
        )
        
        # Use some tokens today
        guard.check_budget(500)
        usage = guard.get_usage()
        assert usage["daily_usage"] == 500
        
        # Mock yesterday's date
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        guard._daily_usage[yesterday] = 800
        
        # Daily for today should still be 500
        assert guard.get_usage()["daily_usage"] == 500
        
        # Clear today's usage (simulating new day)
        guard._daily_usage = {yesterday: 800}
        
        # Now daily usage should be 0 for today
        today = date.today().isoformat()
        assert guard._daily_usage.get(today, 0) == 0
    
    def test_thread_safety_concurrent_increments(self):
        """Test thread safety with concurrent increments."""
        guard = BudgetGuard(
            per_run_limit=100000,
            daily_limit=100000,
            abort_on_exceed=False  # Use False to ensure all increments are tracked
        )
        
        num_threads = 10
        increments_per_thread = 100
        tokens_per_increment = 10
        
        def increment_budget():
            for _ in range(increments_per_thread):
                guard.check_budget(tokens_per_increment)
        
        threads = [threading.Thread(target=increment_budget) for _ in range(num_threads)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All increments should be tracked (with abort_on_exceed=False)
        usage = guard.get_usage()
        expected = num_threads * increments_per_thread * tokens_per_increment
        
        assert usage["per_run_usage"] == expected, (
            f"Expected {expected}, got {usage['per_run_usage']}"
        )
        assert usage["daily_usage"] == expected
    
    def test_reset_per_run(self):
        """Test per-run reset functionality."""
        guard = BudgetGuard(
            per_run_limit=1000,
            daily_limit=5000,
            abort_on_exceed=True
        )
        
        guard.check_budget(500)
        assert guard.get_usage()["per_run_usage"] == 500
        
        guard.reset_per_run()
        assert guard.get_usage()["per_run_usage"] == 0
    
    def test_reset_daily(self):
        """Test daily reset functionality."""
        guard = BudgetGuard(
            per_run_limit=100000,
            daily_limit=5000,
            abort_on_exceed=True
        )
        
        guard.check_budget(1000)
        assert guard.get_usage()["daily_usage"] == 1000
        
        guard.reset_daily()
        assert guard.get_usage()["daily_usage"] == 0


class TestGetBudgetConfig:
    """Tests for get_budget_config helper function."""
    
    def test_extracts_budget_settings(self):
        """Test budget config extraction from full config."""
        config = {
            "budget": {
                "per_run_tokens": 100000,
                "daily_tokens": 1000000,
                "abort_on_exceed": True
            },
            "other_settings": {"foo": "bar"}
        }
        
        result = get_budget_config(config)
        
        assert result == {
            "per_run_tokens": 100000,
            "daily_tokens": 1000000,
            "abort_on_exceed": True
        }
    
    def test_defaults_when_missing(self):
        """Test defaults applied when budget config missing."""
        config = {}
        
        result = get_budget_config(config)
        
        assert result == {
            "per_run_tokens": 500000,
            "daily_tokens": 5000000,
            "abort_on_exceed": True
        }
    
    def test_partial_config(self):
        """Test partial config with some defaults."""
        config = {
            "budget": {
                "per_run_tokens": 750000
            }
        }
        
        result = get_budget_config(config)
        
        assert result["per_run_tokens"] == 750000
        assert result["daily_tokens"] == 5000000  # default
        assert result["abort_on_exceed"] is True  # default


class TestBudgetExceeded:
    """Tests for BudgetExceeded exception."""
    
    def test_exception_message(self):
        """Test exception message format."""
        exc = BudgetExceeded(1000, 1500, "per_run")
        
        assert "1000" in str(exc)
        assert "1500" in str(exc)
        assert "per_run" in str(exc)
    
    def test_exception_attributes(self):
        """Test exception has correct attributes."""
        exc = BudgetExceeded(500, 750, "daily")
        
        assert exc.limit == 500
        assert exc.current == 750
        assert exc.budget_type == "daily"
