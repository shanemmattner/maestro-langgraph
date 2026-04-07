"""Tests for core/tracing.py — OTel setup, Langfuse detection, trace ID management."""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestSetupTracing:
    """Test setup_tracing() backend selection."""

    def test_langfuse_backend_configures_otel(self):
        """TRACING_BACKEND=langfuse → OTel provider configured, LangSmith suppressed."""
        mock_provider = MagicMock()
        mock_trace = MagicMock()
        mock_trace.get_tracer_provider.return_value = mock_provider

        with patch.dict(os.environ, {
            "TRACING_BACKEND": "langfuse",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "http://localhost:3100",
        }):
            with patch.dict("sys.modules", {
                "opentelemetry": mock_trace,
                "opentelemetry.trace": mock_trace,
                "opentelemetry.sdk.trace": MagicMock(),
                "opentelemetry.sdk.trace.export": MagicMock(),
                "opentelemetry.exporter.otlp.proto.http.trace_exporter": MagicMock(),
            }):
                from langgraph_maestro.core.tracing import setup_tracing
                setup_tracing()

            # LangSmith should be suppressed
            assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"

    def test_no_langfuse_keys_disables_tracing_gracefully(self):
        """No LANGFUSE_* keys → tracing disabled, no crash."""
        env = {
            "TRACING_BACKEND": "langfuse",
        }
        # Remove any existing keys
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}
        clean_env.update(env)

        with patch.dict(os.environ, clean_env, clear=True):
            from langgraph_maestro.core.tracing import setup_tracing
            # Should not raise
            setup_tracing()


class TestFlushTraces:
    """Test flush_traces() calls provider.force_flush()."""

    def test_flush_calls_force_flush(self):
        """flush_traces() calls provider.force_flush()."""
        mock_provider = MagicMock()
        mock_provider.force_flush = MagicMock()

        with patch("opentelemetry.trace.get_tracer_provider", return_value=mock_provider):
            from langgraph_maestro.core.tracing import flush_traces
            flush_traces()

        mock_provider.force_flush.assert_called_once()

    def test_flush_no_crash_with_noop_provider(self):
        """flush_traces() doesn't crash when provider has no force_flush."""
        mock_provider = MagicMock(spec=[])  # no force_flush attr

        with patch("opentelemetry.trace.get_tracer_provider", return_value=mock_provider):
            from langgraph_maestro.core.tracing import flush_traces
            flush_traces()  # Should not raise


class TestGetRunUrl:
    """Test get_run_url() returns correct URL format."""

    def test_returns_trace_url_with_id(self):
        """get_run_url() returns {base_url}/traces/{trace_id} format."""
        with patch.dict(os.environ, {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "http://localhost:3100",
        }):
            from langgraph_maestro.core.tracing import set_current_trace_id, get_run_url
            set_current_trace_id("abc-123")
            url = get_run_url()
            assert url == "http://localhost:3100/traces/abc-123"

    def test_returns_base_traces_url_without_id(self):
        """get_run_url() returns {base_url}/traces when no trace ID set."""
        import langgraph_maestro.core.tracing as tracing_mod
        tracing_mod._current_trace_id = None

        with patch.dict(os.environ, {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "http://localhost:3100",
        }):
            url = tracing_mod.get_run_url()
            assert url == "http://localhost:3100/traces"

    def test_returns_none_without_langfuse_keys(self):
        """get_run_url() returns None when Langfuse not configured."""
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}

        with patch.dict(os.environ, clean_env, clear=True):
            from langgraph_maestro.core.tracing import get_run_url
            url = get_run_url()
            assert url is None


class TestIsLangfuseAvailable:
    """Test is_langfuse_available() detection."""

    def test_returns_true_with_both_keys(self):
        with patch.dict(os.environ, {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        }):
            from langgraph_maestro.core.tracing import is_langfuse_available
            assert is_langfuse_available() is True

    def test_returns_false_without_keys(self):
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}

        with patch.dict(os.environ, clean_env, clear=True):
            from langgraph_maestro.core.tracing import is_langfuse_available
            assert is_langfuse_available() is False

    def test_returns_false_with_only_public_key(self):
        clean_env = {k: v for k, v in os.environ.items()
                     if k != "LANGFUSE_SECRET_KEY"}
        clean_env["LANGFUSE_PUBLIC_KEY"] = "pk-test"

        with patch.dict(os.environ, clean_env, clear=True):
            from langgraph_maestro.core.tracing import is_langfuse_available
            assert is_langfuse_available() is False


class TestSetCurrentTraceId:
    """Test set_current_trace_id() stores ID for get_run_url()."""

    def test_stores_trace_id(self):
        import langgraph_maestro.core.tracing as tracing_mod
        tracing_mod.set_current_trace_id("test-trace-456")
        assert tracing_mod._current_trace_id == "test-trace-456"

    def test_overwrites_previous_id(self):
        import langgraph_maestro.core.tracing as tracing_mod
        tracing_mod.set_current_trace_id("first")
        tracing_mod.set_current_trace_id("second")
        assert tracing_mod._current_trace_id == "second"


class TestComputeCost:
    """Test _compute_cost() per-model pricing."""

    def test_known_model_returns_cost(self):
        from langgraph_maestro.core.llm import _compute_cost
        cost = _compute_cost("claude-sonnet-4-6-20250501", 1000, 500)
        # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105)

    def test_minimax_zero_cost(self):
        from langgraph_maestro.core.llm import _compute_cost
        cost = _compute_cost("MiniMax-M2.5-highspeed", 10000, 5000)
        assert cost == 0.0

    def test_unknown_model_returns_none(self):
        from langgraph_maestro.core.llm import _compute_cost
        cost = _compute_cost("some-unknown-model", 100, 100)
        assert cost is None

    def test_strips_provider_prefix(self):
        from langgraph_maestro.core.llm import _compute_cost
        cost = _compute_cost("minimax:MiniMax-M2.5-highspeed", 100, 100)
        assert cost == 0.0
