"""Tests for core.skills skill injection system."""

import pytest
from langgraph_maestro.core.skills import load_skill, get_model_overlay, inject_skills


class TestLoadSkill:
    def test_load_skill_from_instructions_md(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "instructions.md").write_text("Do the thing.")
        result = load_skill("my-skill", search_paths=[str(tmp_path)])
        assert result == "Do the thing."

    def test_load_skill_from_txt(self, tmp_path):
        (tmp_path / "my-skill.txt").write_text("Text skill.")
        result = load_skill("my-skill", search_paths=[str(tmp_path)])
        assert result == "Text skill."

    def test_load_skill_from_md(self, tmp_path):
        (tmp_path / "my-skill.md").write_text("# Skill")
        result = load_skill("my-skill", search_paths=[str(tmp_path)])
        assert result == "# Skill"

    def test_load_skill_missing_returns_empty(self, tmp_path):
        result = load_skill("nonexistent", search_paths=[str(tmp_path)])
        assert result == ""

    def test_load_skill_prefers_instructions_md(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "instructions.md").write_text("From instructions.md")
        (tmp_path / "my-skill.txt").write_text("From txt")
        result = load_skill("my-skill", search_paths=[str(tmp_path)])
        assert result == "From instructions.md"


class TestGetModelOverlay:
    def test_minimax_overlay(self):
        config = {"skills": {"model_overlays": {"minimax": "JSON only"}}}
        assert get_model_overlay("MiniMax-M2.5-highspeed", config) == "JSON only"

    def test_local_overlay(self):
        config = {"skills": {"model_overlays": {"local": "Be concise."}}}
        assert get_model_overlay("mlx-community/phi-3", config) == "Be concise."
        assert get_model_overlay("local-llama", config) == "Be concise."

    def test_claude_overlay(self):
        config = {"skills": {"model_overlays": {"claude": "Use tools."}}}
        assert get_model_overlay("claude-sonnet-4-6-20250501", config) == "Use tools."

    def test_no_overlay_returns_empty(self):
        assert get_model_overlay("some-model", {}) == ""

    def test_missing_key_returns_empty(self):
        config = {"skills": {"model_overlays": {"minimax": "JSON"}}}
        assert get_model_overlay("claude-sonnet-4-6-20250501", config) == ""


class TestInjectSkills:
    def test_no_config_returns_unchanged(self):
        p, s = inject_skills("prompt", "system", "model")
        assert p == "prompt"
        assert s == "system"

    def test_model_overlay_appended(self):
        config = {"skills": {"model_overlays": {"minimax": "JSON only."}}}
        p, s = inject_skills("prompt", "system", "MiniMax-M2.5", config=config)
        assert p == "prompt"
        assert "system" in s
        assert "JSON only." in s

    def test_phase_skills_loaded(self, tmp_path):
        skill_dir = tmp_path / "code-patterns"
        skill_dir.mkdir()
        (skill_dir / "instructions.md").write_text("Use SOLID principles.")

        config = {
            "skills": {
                "phase_skills": {"execute": ["code-patterns"]},
                "skill_source": str(tmp_path),
            }
        }
        _, s = inject_skills("p", "sys", "model", phase="execute", config=config)
        assert "SOLID principles" in s

    def test_always_skills_loaded(self, tmp_path):
        (tmp_path / "web-search.txt").write_text("Search the web.")
        config = {
            "skills": {
                "always": ["web-search"],
                "skill_source": str(tmp_path),
            }
        }
        _, s = inject_skills("p", "sys", "model", config=config)
        assert "Search the web." in s

    def test_no_phase_no_crash(self):
        config = {"skills": {"model_overlays": {"minimax": "JSON"}}}
        p, s = inject_skills("p", "sys", "MiniMax", phase=None, config=config)
        assert "JSON" in s


class TestInjectSkillsEdgeCases:
    def test_empty_skills_config(self):
        config = {"skills": {}}
        p, s = inject_skills("p", "sys", "model", config=config)
        assert p == "p"
        assert s == "sys"

    def test_overlay_and_phase_skills_combined(self, tmp_path):
        """Both model overlay and phase skills should be in system_prompt."""
        skill_dir = tmp_path / "code-patterns"
        skill_dir.mkdir()
        (skill_dir / "instructions.md").write_text("Use SOLID.")

        config = {
            "skills": {
                "model_overlays": {"minimax": "JSON only."},
                "phase_skills": {"execute": ["code-patterns"]},
                "skill_source": str(tmp_path),
            }
        }
        _, s = inject_skills("p", "sys", "MiniMax-M2.5", phase="execute", config=config)
        assert "JSON only." in s
        assert "Use SOLID." in s
        assert "sys" in s

    def test_phase_with_no_matching_skills(self):
        config = {"skills": {"phase_skills": {"review": ["nonexistent-skill"]}}}
        _, s = inject_skills("p", "sys", "model", phase="review", config=config)
        # System prompt shouldn't change beyond original (empty skill returns "")
        assert s == "sys"

    def test_multiple_always_skills(self, tmp_path):
        (tmp_path / "skill-a.txt").write_text("Skill A content")
        (tmp_path / "skill-b.txt").write_text("Skill B content")
        config = {
            "skills": {
                "always": ["skill-a", "skill-b"],
                "skill_source": str(tmp_path),
            }
        }
        _, s = inject_skills("p", "sys", "model", config=config)
        assert "Skill A content" in s
        assert "Skill B content" in s

    def test_skill_source_in_config(self, tmp_path):
        """skill_source should be used as a search path."""
        (tmp_path / "my-skill.txt").write_text("Custom source skill.")
        config = {"skills": {"always": ["my-skill"], "skill_source": str(tmp_path)}}
        _, s = inject_skills("p", "sys", "model", config=config)
        assert "Custom source skill." in s


class TestGetModelOverlayEdgeCases:
    def test_empty_model_overlays(self):
        config = {"skills": {"model_overlays": {}}}
        assert get_model_overlay("MiniMax-M2.5", config) == ""

    def test_overlays_key_missing(self):
        config = {"skills": {"phase_skills": {}}}
        assert get_model_overlay("MiniMax-M2.5", config) == ""


class TestLoadSkillEdgeCases:
    def test_empty_search_paths(self):
        """With no search paths, falls back to repo search."""
        result = load_skill("definitely-nonexistent-skill-xyz", search_paths=[])
        assert result == ""

    def test_none_search_paths(self):
        result = load_skill("definitely-nonexistent-skill-xyz", search_paths=None)
        assert result == ""

    def test_skill_with_empty_file(self, tmp_path):
        (tmp_path / "empty.txt").write_text("")
        result = load_skill("empty", search_paths=[str(tmp_path)])
        # Empty file still loads as empty string
        assert result == ""
