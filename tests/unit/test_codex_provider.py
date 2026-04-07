"""Tests for the codex provider in core/llm.py."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from langgraph_maestro.core.llm import _call_default_codex, get_provider


class TestGetProviderCodexRouting:
    """get_provider() routes codex/gpt models correctly."""

    def test_gpt_54_routes_to_codex(self):
        name, fn = get_provider("gpt-5.3-codex")
        assert name == "codex"

    def test_explicit_codex_prefix_routes_to_codex(self):
        name, fn = get_provider("codex:gpt-5.3-codex")
        assert name == "codex"

    def test_gpt_54_high_routes_to_codex(self):
        name, fn = get_provider("gpt-5.3-codex-high")
        assert name == "codex"

    def test_openai_prefix_routes_to_codex(self):
        name, fn = get_provider("openai/gpt-5.3-codex")
        assert name == "codex"

    def test_codex_bare_routes_to_codex(self):
        name, fn = get_provider("codex")
        assert name == "codex"

    def test_claude_does_not_route_to_codex(self):
        name, fn = get_provider("claude-sonnet-4-6")
        assert name == "claude_code"


class TestCallDefaultCodexReasoningParsing:
    """_call_default_codex() parses reasoning levels from model string."""

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_default_reasoning_is_medium(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("test", "gpt-5.3-codex", "", None, 60)
        assert result["model"] == "gpt-5.3-codex"
        assert result["reasoning"] == "medium"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_high_reasoning_parsed(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("test", "gpt-5.3-codex-high", "", None, 60)
        assert result["model"] == "gpt-5.3-codex"
        assert result["reasoning"] == "high"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_xhigh_reasoning_parsed(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("test", "gpt-5.3-codex-xhigh", "", None, 60)
        assert result["model"] == "gpt-5.3-codex"
        assert result["reasoning"] == "xhigh"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_codex_prefix_stripped(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("test", "codex:gpt-5.3-codex-high", "", None, 60)
        assert result["model"] == "gpt-5.3-codex"
        assert result["reasoning"] == "high"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_openai_prefix_stripped(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("test", "openai/gpt-5.3-codex", "", None, 60)
        assert result["model"] == "gpt-5.3-codex"
        assert result["reasoning"] == "medium"


class TestCallDefaultCodexSubprocessCommand:
    """_call_default_codex() builds the correct subprocess command."""

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_basic_command_structure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        _call_default_codex("do something", "gpt-5.3-codex", "sys prompt", None, 120)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--json" in cmd
        assert "--full-auto" in cmd
        assert "-m" in cmd
        assert cmd[cmd.index("-m") + 1] == "gpt-5.3-codex"
        # Reasoning config flag
        assert "-c" in cmd
        assert 'model_reasoning_effort="medium"' in cmd[cmd.index("-c") + 1]
        # Prompt is last arg, includes system prompt
        assert cmd[-1] == "sys prompt\n\ndo something"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_cwd_passed_as_flag(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        _call_default_codex("task", "gpt-5.3-codex", "", "/some/path", 120)

        cmd = mock_run.call_args[0][0]
        assert "-C" in cmd
        assert cmd[cmd.index("-C") + 1] == "/some/path"

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_no_cwd_flag_when_none(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        _call_default_codex("task", "gpt-5.3-codex", "", None, 120)

        cmd = mock_run.call_args[0][0]
        assert "-C" not in cmd

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_timeout_passed_to_subprocess(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        _call_default_codex("task", "gpt-5.3-codex", "", None, 999)

        kwargs = mock_run.call_args[1]
        assert kwargs["timeout"] == 999

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_capture_output_and_text_mode(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        _call_default_codex("task", "gpt-5.3-codex", "", None, 60)

        kwargs = mock_run.call_args[1]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_stderr_appended_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="partial", stderr="error details", returncode=1
        )
        result = _call_default_codex("task", "gpt-5.3-codex", "", None, 60)
        assert "STDERR:" in result["content"]
        assert "error details" in result["content"]

    @patch("langgraph_maestro.core.llm.subprocess.run")
    def test_returns_latency(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0
        )
        result = _call_default_codex("task", "gpt-5.3-codex", "", None, 60)
        assert "latency" in result
        assert isinstance(result["latency"], float)


class TestCallDefaultCodexErrors:
    """_call_default_codex() error handling."""

    @patch("langgraph_maestro.core.llm.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=60))
    def test_timeout_raises_runtime_error(self, mock_run):
        with pytest.raises(RuntimeError, match="timed out"):
            _call_default_codex("task", "gpt-5.3-codex", "", None, 60)

    @patch("langgraph_maestro.core.llm.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_cli_raises_runtime_error(self, mock_run):
        with pytest.raises(RuntimeError, match="not found"):
            _call_default_codex("task", "gpt-5.3-codex", "", None, 60)
