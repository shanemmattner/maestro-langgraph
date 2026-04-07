"""Tests for workflow template scaffolding."""

import py_compile
import yaml
from pathlib import Path

from langgraph_maestro.templates import scaffold_workflow


class TestScaffoldWorkflow:
    def test_creates_all_expected_files(self, tmp_path):
        created = scaffold_workflow(tmp_path / "wf", "test_workflow")
        names = {p.relative_to(tmp_path / "wf").as_posix() for p in created}
        assert "__init__.py" in names
        assert "graph.py" in names
        assert "nodes.py" in names
        assert "state.py" in names
        assert "config.yaml" in names
        assert "prompts/decomposer.txt" in names
        assert "prompts/implementer.txt" in names
        assert "prompts/reviewer.txt" in names

    def test_replaces_workflow_name(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "my_custom_wf")
        config = yaml.safe_load((tmp_path / "wf" / "config.yaml").read_text())
        assert config["workflow"] == "my_custom_wf"
        # Check no unreplaced tokens
        for f in (tmp_path / "wf").rglob("*"):
            if f.is_file():
                content = f.read_text()
                assert "WORKFLOW_NAME" not in content, f"Unreplaced token in {f.name}"

    def test_replaces_default_model(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "test_wf", default_model="claude-opus-4-6")
        config = yaml.safe_load((tmp_path / "wf" / "config.yaml").read_text())
        for phase_models in config["phases"].values():
            assert "claude-opus-4-6" in phase_models
        # No unreplaced DEFAULT_MODEL
        for f in (tmp_path / "wf").rglob("*"):
            if f.is_file():
                content = f.read_text()
                assert "DEFAULT_MODEL" not in content, f"Unreplaced token in {f.name}"

    def test_python_files_compile(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "compile_test")
        for py_file in (tmp_path / "wf").glob("*.py"):
            py_compile.compile(str(py_file), doraise=True)

    def test_config_valid_yaml(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "yaml_test")
        config = yaml.safe_load((tmp_path / "wf" / "config.yaml").read_text())
        assert "phases" in config
        assert "timeouts" in config
        assert "loops" in config

    def test_creates_target_dir(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "wf"
        scaffold_workflow(target, "nested_wf")
        assert target.exists()
        assert (target / "graph.py").exists()

    def test_description_in_init(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "desc_test", description="My cool workflow")
        init_content = (tmp_path / "wf" / "__init__.py").read_text()
        assert "My cool workflow" in init_content

    def test_prompts_have_placeholder_vars(self, tmp_path):
        scaffold_workflow(tmp_path / "wf", "prompt_test")
        decomposer = (tmp_path / "wf" / "prompts" / "decomposer.txt").read_text()
        assert "{task}" in decomposer
        reviewer = (tmp_path / "wf" / "prompts" / "reviewer.txt").read_text()
        assert "{task}" in reviewer
