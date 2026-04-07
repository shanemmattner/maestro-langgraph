"""Tests for core/mc.py — lean Claude runner."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langgraph_maestro.core.mc import (
    build_cmd,
    parse_usage,
    git_branch_context,
    run_mcp_server,
    MCP_TOOLS,
    SYSTEM_PROMPT,
    _is_local_model,
    _get_env,
    _mcp_bash,
    _mcp_read,
    _mcp_edit,
    _mcp_write,
)


class TestBuildCmd:
    def test_returns_cmd_and_prompt(self):
        cmd, prompt = build_cmd("Fix bug", model="claude-sonnet-4-6")
        assert isinstance(cmd, list)
        assert prompt == "Fix bug"

    def test_cmd_has_required_flags(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        assert "claude" in cmd[0]
        assert "-p" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"

    def test_tools_empty_string(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        idx = cmd.index("--tools")
        assert cmd[idx + 1] == ""

    def test_mcp_config_points_to_self(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        idx = cmd.index("--mcp-config")
        cfg = json.loads(cmd[idx + 1])
        assert "mcpServers" in cfg
        assert "m" in cfg["mcpServers"]
        args = cfg["mcpServers"]["m"]["args"]
        assert "--mcp-server" in args

    def test_system_prompt_default(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        idx = cmd.index("--system-prompt")
        assert SYSTEM_PROMPT in cmd[idx + 1]

    def test_agent_prompt_prepended(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6",
                           agent_prompt="You are a reviewer.")
        idx = cmd.index("--system-prompt")
        sp = cmd[idx + 1]
        assert sp.startswith("You are a reviewer.")
        assert SYSTEM_PROMPT in sp

    def test_max_budget_usd(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6", max_budget_usd=0.50)
        idx = cmd.index("--max-budget-usd")
        assert cmd[idx + 1] == "0.5"

    def test_no_budget_flag_when_none(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        assert "--max-budget-usd" not in cmd

    def test_stream_json_output(self):
        cmd, _ = build_cmd("task", model="claude-sonnet-4-6")
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "stream-json"


class TestParseUsage:
    def test_extracts_tokens_and_cost(self):
        final = {
            "usage": {
                "input_tokens": 1000,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 300,
                "output_tokens": 500,
            },
            "total_cost_usd": 0.0042,
        }
        u = parse_usage(final)
        assert u["input"] == 1000
        assert u["cache_new"] == 200
        assert u["cache_read"] == 300
        assert u["output"] == 500
        assert u["cost"] == 0.0042

    def test_empty_final(self):
        u = parse_usage({})
        assert u["input"] == 0
        assert u["output"] == 0
        assert u["cost"] == 0

    def test_partial_usage(self):
        u = parse_usage({"usage": {"input_tokens": 42}})
        assert u["input"] == 42
        assert u["output"] == 0


class TestIsLocalModel:
    def test_local_keyword(self):
        assert _is_local_model("local")

    def test_mlx_community_prefix(self):
        assert _is_local_model("mlx-community/Qwen3-32B")

    def test_claude_model_not_local(self):
        assert not _is_local_model("claude-sonnet-4-6")

    def test_other_local_prefixes(self):
        assert _is_local_model("RepublicOfKorokke/some-model")
        assert _is_local_model("arthurcollet/some-model")
        assert _is_local_model("inferencerlabs/some-model")


class TestGetEnv:
    def test_strips_claudecode(self):
        with patch.dict("os.environ", {"CLAUDECODE": "1", "HOME": "/tmp"}):
            env = _get_env()
            assert "CLAUDECODE" not in env
            assert env["CLAUDE_CODE_SIMPLE"] == "true"
            assert "HOME" in env


class TestGitBranchContext:
    def test_returns_branch_info(self, tmp_path):
        # Init a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=tmp_path, capture_output=True,
                       env={**__import__("os").environ,
                            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"})
        ctx = git_branch_context(tmp_path)
        assert "branch" in ctx
        assert "Do NOT switch branches" in ctx

    def test_non_git_dir_returns_empty(self, tmp_path):
        ctx = git_branch_context(tmp_path)
        assert ctx == ""


class TestMcpTools:
    def test_tools_defined(self):
        assert len(MCP_TOOLS) == 7
        names = {t["name"] for t in MCP_TOOLS}
        assert names == {"bash", "read", "grep", "edit", "write", "web_search", "web_fetch"}

    def test_all_have_input_schema(self):
        for tool in MCP_TOOLS:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"


class TestMcpHandlers:
    def test_bash_echo(self):
        result = _mcp_bash({"command": "echo hello"})
        assert "hello" in result

    def test_bash_timeout(self):
        result = _mcp_bash({"command": "sleep 10", "timeout": 1})
        assert "Timed out" in result

    def test_read_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = _mcp_read({"path": str(f)})
        assert "line1" in result
        assert "line2" in result

    def test_read_missing_file(self):
        result = _mcp_read({"path": "/nonexistent/file.txt"})
        assert "Not found" in result

    def test_edit_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = _mcp_edit({"path": str(f), "old_string": "hello", "new_string": "goodbye"})
        assert "Edited" in result
        assert f.read_text() == "goodbye world"

    def test_edit_not_found(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = _mcp_edit({"path": str(f), "old_string": "xyz", "new_string": "abc"})
        assert "Not found in" in result

    def test_write_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = _mcp_write({"path": str(f), "content": "new content"})
        assert "Wrote" in result
        assert f.read_text() == "new content"


class TestMcpServer:
    def test_tools_list_via_subprocess(self):
        """End-to-end: spawn MCP server, send tools/list, verify response."""
        mc_path = str(Path(__file__).parent.parent.parent / "src" / "langgraph_maestro" / "core" / "mc.py")
        proc = subprocess.Popen(
            [sys.executable, mc_path, "--mcp-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        stdout, _ = proc.communicate(input=request + "\n", timeout=5)
        resp = json.loads(stdout.strip())
        assert resp["id"] == 1
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert names == {"bash", "read", "grep", "edit", "write", "web_search", "web_fetch"}

    def test_initialize_via_subprocess(self):
        mc_path = str(Path(__file__).parent.parent.parent / "src" / "langgraph_maestro" / "core" / "mc.py")
        proc = subprocess.Popen(
            [sys.executable, mc_path, "--mcp-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        stdout, _ = proc.communicate(input=request + "\n", timeout=5)
        resp = json.loads(stdout.strip())
        assert "protocolVersion" in resp["result"]
        assert "serverInfo" in resp["result"]

    def test_tools_call_bash(self):
        mc_path = str(Path(__file__).parent.parent.parent / "src" / "langgraph_maestro" / "core" / "mc.py")
        proc = subprocess.Popen(
            [sys.executable, mc_path, "--mcp-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "bash", "arguments": {"command": "echo mc-test-ok"}}
        })
        stdout, _ = proc.communicate(input=request + "\n", timeout=5)
        resp = json.loads(stdout.strip())
        text = resp["result"]["content"][0]["text"]
        assert "mc-test-ok" in text


class TestCallAgentIntegration:
    """Verify call_agent routes to core.mc correctly (mocked — no real claude calls)."""

    def test_call_agent_uses_core_mc(self):
        """call_agent should import from langgraph_maestro.core.mc and use build_cmd/run_claude."""
        fake_final = {
            "result": "task completed",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "total_cost_usd": 0.001,
        }
        with patch("langgraph_maestro.core.mc.build_cmd", return_value=(["claude", "-p"], "prompt")) as mock_build, \
             patch("langgraph_maestro.core.mc.run_claude", return_value=(fake_final, 1.5, 0)) as mock_run:
            from langgraph_maestro.core.llm import call_agent
            result = call_agent(
                prompt="Say hello",
                models=["claude-sonnet-4-6"],
                cwd="/tmp",
            )
        assert result["content"] == "task completed"
        assert result["provider"] == "claude_code"
        assert result["model"] == "claude-sonnet-4-6"
        assert result["usage"]["input"] == 100
        assert result["elapsed"] == 1.5
        mock_build.assert_called_once()
        mock_run.assert_called_once()
