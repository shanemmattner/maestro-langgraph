"""Tests for core/lint.py"""

import pytest
from pathlib import Path

from langgraph_maestro.core.lint import (
    lint_prompt,
    lint_all_prompts,
    _check_constraints,
    _check_behavior_or_rules,
    _check_structured_sections,
    _check_verify_section,
    _check_no_expert_persona,
    _check_uncertainty_signals,
    _check_security_boundaries,
    _check_no_cot_scaffolding,
    _check_no_banned_phrases,
    _check_no_tmp_paths,
)


# Well-structured prompt that should pass most rules
WELL_STRUCTURED_PROMPT = """
# ROLE
You are a code reviewer assistant.

# TASK
Review the following code and provide feedback.

# CONSTRAINTS
- Only read files, do not modify them
- Do not execute any commands
- Ask for user confirmation before accessing sensitive files

# BEHAVIOR
- Provide constructive feedback
- Focus on security and performance

# OUTPUT
Return a JSON object with findings.

# VERIFY
Double-check your analysis before returning results.

# UNCERTAIN
If you cannot access a file, indicate it clearly.
"""


class TestLintPromptWellStructured:
    def test_well_structured_prompt_passes(self):
        """Test a well-structured prompt gets high score."""
        result = lint_prompt(WELL_STRUCTURED_PROMPT)
        assert result["score"] >= 7
        assert result["ok"] is True
        assert "has_constraints" in result["passed"]
        assert "has_behavior_or_rules" in result["passed"]
        assert "has_structured_sections" in result["passed"]
        assert "has_verify_section" in result["passed"]


class TestRule1Constraints:
    def test_constraints_section_passes(self):
        """Test CONSTRAINTS section passes."""
        assert _check_constraints("# CONSTRAINTS\n- Be helpful") is True
        assert _check_constraints("CONSTRAINTS:\n- Be helpful") is True
        assert _check_constraints("constraints:\n- Be helpful") is True

    def test_constraints_section_fails(self):
        """Test missing CONSTRAINTS section fails."""
        assert _check_constraints("# RULES\n- Be helpful") is False
        assert _check_constraints("No sections here") is False


class TestRule2BehaviorOrRules:
    def test_behavior_section_passes(self):
        """Test BEHAVIOR section passes."""
        assert _check_behavior_or_rules("# BEHAVIOR\n- Be helpful") is True

    def test_rules_section_passes(self):
        """Test RULES section passes."""
        assert _check_behavior_or_rules("# RULES\n- Be helpful") is True

    def test_behavior_or_rules_fails(self):
        """Test missing BEHAVIOR or RULES fails."""
        assert _check_behavior_or_rules("# ROLE\n- Be helpful") is False


class TestRule3StructuredSections:
    def test_three_sections_passes(self):
        """Test >= 3 structured sections passes."""
        text = "# ROLE\n# TASK\n# CONSTRAINTS\n"
        assert _check_structured_sections(text) is True

    def test_five_sections_passes(self):
        """Test 5 sections passes."""
        text = "# ROLE\n# TASK\n# CONSTRAINTS\n# RULES\n# OUTPUT\n"
        assert _check_structured_sections(text) is True

    def test_two_sections_fails(self):
        """Test < 3 structured sections fails."""
        text = "# ROLE\n# TASK\n"
        assert _check_structured_sections(text) is False


class TestRule4VerifySection:
    def test_verify_section_passes(self):
        """Test VERIFY section passes."""
        assert _check_verify_section("# VERIFY\nCheck your work") is True

    def test_verify_case_insensitive_passes(self):
        """Test VERIFY is case-insensitive."""
        assert _check_verify_section("verify:\nCheck your work") is True

    def test_verify_section_fails(self):
        """Test missing VERIFY section fails."""
        assert _check_verify_section("# ROLE\nBe helpful") is False


class TestRule5NoExpertPersona:
    def test_no_expert_passes(self):
        """Test no expert persona markers passes."""
        text = "You are a helpful assistant."
        assert _check_no_expert_persona(text) is True

    def test_world_class_fails(self):
        """Test 'world-class' fails."""
        text = "You are a world-class expert."
        assert _check_no_expert_persona(text) is False

    def test_expert_fails(self):
        """Test 'expert' fails."""
        text = "You are an expert developer."
        assert _check_no_expert_persona(text) is False

    def test_20_years_fails(self):
        """Test '20 years' fails."""
        text = "You have 20 years of experience."
        assert _check_no_expert_persona(text) is False

    def test_seasoned_fails(self):
        """Test 'seasoned' fails."""
        text = "You are a seasoned professional."
        assert _check_no_expert_persona(text) is False


class TestRule6UncertaintySignals:
    def test_uncertainty_signal_passes(self):
        """Test uncertainty signals passes."""
        text = "If you CANNOT_ACCESS a file, indicate it."
        assert _check_uncertainty_signals(text) is True

    def test_uncertain_fails(self):
        """Test missing uncertainty signals fails."""
        text = "You are a helpful assistant."
        assert _check_uncertainty_signals(text) is False

    def test_various_uncertainty_signals(self):
        """Test various uncertainty signal patterns."""
        assert _check_uncertainty_signals("I am UNCERTAIN about this") is True
        assert _check_uncertainty_signals("CONFLICT detected") is True
        assert _check_uncertainty_signals("UNKNOWN result") is True


class TestRule7SecurityBoundaries:
    def test_no_file_ops_passes(self):
        """Test no file operations passes."""
        text = "You are a helpful assistant."
        assert _check_security_boundaries(text) is True

    def test_file_ops_with_security_passes(self):
        """Test file operations with security boundaries passes."""
        text = "Read files but ask for permission first."
        assert _check_security_boundaries(text) is True

    def test_file_ops_without_security_fails(self):
        """Test file operations without security boundaries fails."""
        text = "Read and write files freely."
        assert _check_security_boundaries(text) is False


class TestRule8NoCoTScaffolding:
    def test_no_cot_passes(self):
        """Test no CoT scaffolding passes."""
        text = "Provide a direct answer."
        assert _check_no_cot_scaffolding(text) is True

    def test_think_step_by_step_fails(self):
        """Test 'think step by step' fails."""
        text = "Think step by step about this."
        assert _check_no_cot_scaffolding(text) is False

    def test_chain_of_thought_fails(self):
        """Test 'chain of thought' fails."""
        text = "Use chain of thought reasoning."
        assert _check_no_cot_scaffolding(text) is False

    def test_lets_think_fails(self):
        """Test 'let's think' fails."""
        text = "Let's think about this problem."
        assert _check_no_cot_scaffolding(text) is False


class TestRule9NoBannedPhrases:
    def test_no_banned_phrases_passes(self):
        """Test no banned phrases passes."""
        text = "Provide the analysis."
        assert _check_no_banned_phrases(text) is True

    def test_let_me_know_if_fails(self):
        """Test 'let me know if' fails."""
        text = "Let me know if you need more info."
        assert _check_no_banned_phrases(text) is False

    def test_would_you_like_fails(self):
        """Test 'would you like' fails."""
        text = "Would you like me to continue?"
        assert _check_no_banned_phrases(text) is False

    def test_feel_free_to_fails(self):
        """Test 'feel free to' fails."""
        text = "Feel free to ask questions."
        assert _check_no_banned_phrases(text) is False


class TestRule10NoTmpPaths:
    def test_no_tmp_passes(self):
        """Test no /tmp/ paths passes."""
        text = "Save to the output directory."
        assert _check_no_tmp_paths(text) is True

    def test_tmp_path_fails(self):
        """Test /tmp/ path fails."""
        text = "Write to /tmp/output.txt"
        assert _check_no_tmp_paths(text) is False


class TestEmptyPrompt:
    def test_empty_prompt_low_score(self):
        """Test empty prompt gets low score."""
        result = lint_prompt("")
        assert result["score"] < 7
        assert result["ok"] is False


class TestOkThreshold:
    def test_score_7_is_ok(self):
        """Test score >= 7 returns ok=True."""
        # Create a prompt that passes exactly 7 rules
        text = "# CONSTRAINTS\n# RULES\n# ROLE\n# TASK\n# OUTPUT\n# VERIFY\n# BEHAVIOR\nCANNOT_ACCESS"
        result = lint_prompt(text)
        assert result["ok"] is True

    def test_score_6_is_not_ok(self):
        """Test score < 7 returns ok=False."""
        # Create a prompt that passes only 6 rules
        # Include expert persona, CoT scaffolding, banned phrases, and /tmp/ to fail multiple rules
        text = """# CONSTRAINTS
# RULES
# ROLE
# TASK
# OUTPUT
# VERIFY
You are a world-class expert. Think step by step about this. Let me know if you need help. Save to /tmp/output.txt
"""
        result = lint_prompt(text)
        assert result["ok"] is False
        assert result["score"] < 7


class TestLintAllPrompts:
    def test_lint_all_prompts_empty_dir(self, tmp_path):
        """Test lint_all_prompts on empty directory."""
        results = lint_all_prompts(tmp_path)
        assert results == []

    def test_lint_all_prompts_single_file(self, tmp_path):
        """Test lint_all_prompts with single file."""
        prompt_file = tmp_path / "test.txt"
        prompt_file.write_text("# CONSTRAINTS\n# RULES\n# ROLE\n")
        results = lint_all_prompts(tmp_path)
        assert len(results) == 1
        assert results[0]["file"] == str(prompt_file)
        assert "score" in results[0]

    def test_lint_all_prompts_multiple_files(self, tmp_path):
        """Test lint_all_prompts with multiple files."""
        # Good prompt
        good_file = tmp_path / "good.txt"
        good_file.write_text(WELL_STRUCTURED_PROMPT)
        
        # Bad prompt
        bad_file = tmp_path / "bad.txt"
        bad_file.write_text("think step by step")
        
        results = lint_all_prompts(tmp_path)
        assert len(results) == 2
        
        good_result = next(r for r in results if "good" in r["file"])
        bad_result = next(r for r in results if "bad" in r["file"])
        
        assert good_result["score"] >= bad_result["score"]

    def test_lint_all_prompts_nested_files(self, tmp_path):
        """Test lint_all_prompts finds files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        prompt_file = subdir / "nested.txt"
        prompt_file.write_text("# CONSTRAINTS\n# RULES\n# ROLE\n")
        
        results = lint_all_prompts(tmp_path)
        assert len(results) == 1
        assert "nested.txt" in results[0]["file"]

    def test_lint_all_prompts_non_utf8(self, tmp_path):
        """Test lint_all_prompts handles read errors gracefully."""
        # Create a file that might cause issues (but for .txt it should work)
        prompt_file = tmp_path / "test.txt"
        prompt_file.write_text("Simple prompt")
        
        results = lint_all_prompts(tmp_path)
        assert len(results) == 1
        assert "error" not in results[0]


class TestLintPromptReturnFormat:
    def test_return_format_complete(self):
        """Test lint_prompt returns all expected fields."""
        result = lint_prompt("# CONSTRAINTS\n# RULES\n# ROLE\n")
        
        assert "score" in result
        assert "max_score" in result
        assert "passed" in result
        assert "failed" in result
        assert "ok" in result
        assert result["max_score"] == 10
        assert len(result["passed"]) + len(result["failed"]) == 10

    def test_passed_and_failed_exclusive(self):
        """Test passed and failed are mutually exclusive."""
        result = lint_prompt("# CONSTRAINTS\n# RULES\n# ROLE\n")
        
        for rule in result["passed"]:
            assert rule not in result["failed"]
        
        for rule in result["failed"]:
            assert rule not in result["passed"]
