"""Tests for core.validation.validate_subtasks."""

import pytest
from langgraph_maestro.core.validation import validate_subtasks


class TestValidSubtasks:
    """Test valid subtasks pass with no warnings."""

    def test_valid_subtasks_pass(self):
        """Valid subtasks with good descriptions should have no warnings."""
        subtasks = [
            {
                "id": "1",
                "description": "Create a new utility function in src/utils.py that handles user authentication with OAuth2.",
            },
            {
                "id": "2",
                "description": "Modify the API endpoint in app/routes.py to add rate limiting using the rate_limit() function.",
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is True
        assert result["phase"] == "validate_subtasks"
        assert len(result["warnings"]) == 0

    def test_valid_subtasks_with_file_paths(self):
        """Subtasks with file paths should pass validation."""
        subtasks = [
            {
                "id": "task-1",
                "description": "Update the configuration in config/settings.yaml to enable debug mode for development.",
            },
            {
                "id": "task-2",
                "description": "Add a new test case in tests/test_api.py to verify the response status code.",
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is True
        assert len(result["warnings"]) == 0


class TestShortDescription:
    """Test short description triggers warning."""

    def test_short_description_triggers_warning(self):
        """Description under 50 chars should trigger VAGUE warning."""
        subtasks = [
            {
                "id": "1",
                "description": "Fix the bug",  # Only 13 chars - also no file/function
            },
        ]
        result = validate_subtasks(subtasks)

        assert len(result["warnings"]) >= 1  # Can have multiple warnings per subtask
        vague_warnings = [w for w in result["warnings"] if w["severity"] == "VAGUE"]
        assert len(vague_warnings) >= 1
        assert any("too short" in w["message"] for w in vague_warnings)
        # Should still be valid (vague is non-blocking)
        assert result["valid"] is True

    def test_exactly_50_chars_passes(self):
        """Description with exactly 50 chars should pass."""
        subtasks = [
            {
                "id": "1",
                "description": "a" * 50,  # Exactly 50 chars
            },
        ]
        result = validate_subtasks(subtasks)

        # No length warning
        length_warnings = [w for w in result["warnings"] if "too short" in w["message"]]
        assert len(length_warnings) == 0


class TestMissingFilePathOrFunction:
    """Test missing file path or function triggers warning."""

    def test_missing_file_path_triggers_warning(self):
        """Description without file path or function should trigger warning."""
        subtasks = [
            {
                "id": "1",
                "description": "This is a very long description that is over fifty characters but has no file path or function",  # No /, .py, .ts, .js, or ()
            },
        ]
        result = validate_subtasks(subtasks)

        vague_warnings = [w for w in result["warnings"] if w["severity"] == "VAGUE"]
        assert any("missing file path or function" in w["message"] for w in vague_warnings)

    def test_has_function_passes(self):
        """Description with function name containing () should pass."""
        subtasks = [
            {
                "id": "1",
                "description": "Call the authenticate_user() function to verify credentials before allowing access.",
            },
        ]
        result = validate_subtasks(subtasks)

        # No file/function warning
        file_warnings = [w for w in result["warnings"] if "missing file path" in w["message"]]
        assert len(file_warnings) == 0


class TestDuplicateDescriptions:
    """Test duplicate descriptions detected."""

    def test_duplicate_descriptions_detected(self):
        """Exact duplicate descriptions should trigger DUPLICATE warning."""
        subtasks = [
            {
                "id": "task-1",
                "description": "Implement the login functionality in auth.py using the login() function.",
            },
            {
                "id": "task-2",
                "description": "Implement the login functionality in auth.py using the login() function.",
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is False
        dup_warnings = [w for w in result["warnings"] if w["severity"] == "DUPLICATE"]
        assert len(dup_warnings) == 1
        assert "Duplicate" in dup_warnings[0]["message"]

    def test_multiple_duplicates_detected(self):
        """Multiple different duplicates should each trigger a warning."""
        subtasks = [
            {"id": "a", "description": "Fix bug in file.py using fix_bug()"},
            {"id": "b", "description": "Fix bug in file.py using fix_bug()"},
            {"id": "c", "description": "Add feature to module.ts with add_feature()"},
            {"id": "d", "description": "Add feature to module.ts with add_feature()"},
        ]
        result = validate_subtasks(subtasks)

        dup_warnings = [w for w in result["warnings"] if w["severity"] == "DUPLICATE"]
        assert len(dup_warnings) == 2
        assert result["valid"] is False

    def test_no_false_positives_on_similar(self):
        """Similar but not identical descriptions should not trigger duplicate."""
        subtasks = [
            {"id": "1", "description": "Fix bug in file.py using fix_bug()"},
            {"id": "2", "description": "Fix bug in file.py using fix_bug() "},  # trailing space
        ]
        result = validate_subtasks(subtasks)

        dup_warnings = [w for w in result["warnings"] if w["severity"] == "DUPLICATE"]
        assert len(dup_warnings) == 0


class TestEmptyId:
    """Test empty id triggers warning."""

    def test_empty_id_triggers_warning(self):
        """Subtask with empty id should trigger VAGUE warning."""
        subtasks = [
            {
                "id": "",
                "description": "Create a new utility function in src/utils.py that handles user authentication.",
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is True  # VAGUE is non-blocking
        id_warnings = [w for w in result["warnings"] if "empty 'id'" in w["message"]]
        assert len(id_warnings) == 1

    def test_missing_id_key_triggers_warning(self):
        """Subtask missing id key should trigger warning."""
        subtasks = [
            {
                "description": "Create a new utility function in src/utils.py that handles user authentication.",
            },
        ]
        result = validate_subtasks(subtasks)

        id_warnings = [w for w in result["warnings"] if "empty 'id'" in w["message"]]
        assert len(id_warnings) == 1


class TestValidWithVagueWarnings:
    """Test valid=True when only vague warnings (no duplicates)."""

    def test_valid_true_with_vague_warnings(self):
        """valid should be True when only VAGUE warnings present (no DUPLICATE)."""
        subtasks = [
            {
                "id": "1",
                "description": "Fix the bug",  # Too short - VAGUE, also no file/function
            },
            {
                "id": "2",
                "description": "Do something important but vague without any files or functions mentioned",  # No file/function - VAGUE
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is True
        vague_warnings = [w for w in result["warnings"] if w["severity"] == "VAGUE"]
        assert len(vague_warnings) >= 2  # At least 2 vague warnings expected
        assert all(w["severity"] == "VAGUE" for w in result["warnings"])

    def test_valid_false_with_duplicate(self):
        """valid should be False when DUPLICATE warning present."""
        subtasks = [
            {
                "id": "1",
                "description": "Create a new utility function in src/utils.py that handles user authentication with OAuth2.",
            },
            {
                "id": "2",
                "description": "Create a new utility function in src/utils.py that handles user authentication with OAuth2.",
            },
        ]
        result = validate_subtasks(subtasks)

        assert result["valid"] is False
        assert any(w["severity"] == "DUPLICATE" for w in result["warnings"])


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_subtasks_list(self):
        """Empty list of subtasks should be valid with no warnings."""
        result = validate_subtasks([])

        assert result["valid"] is True
        assert len(result["warnings"]) == 0

    def test_subtask_with_all_issues(self):
        """Subtask with short desc, no file/function, and empty id."""
        subtasks = [
            {
                "id": "",
                "description": "short",
            },
        ]
        result = validate_subtasks(subtasks)

        # Should have 3 VAGUE warnings (length, file/function, empty id)
        assert len(result["warnings"]) == 3
        assert result["valid"] is True  # VAGUE warnings don't make it invalid

    def test_none_description_handled(self):
        """Subtask with None description should be handled gracefully."""
        subtasks = [
            {
                "id": "1",
                "description": None,  # type: ignore
            },
        ]
        result = validate_subtasks(subtasks)  # Should not raise

        # Should get warnings about length (0) and file/function (empty)
        assert len(result["warnings"]) >= 1

    def test_phase_field_set(self):
        """Result should always include phase field."""
        subtasks = [{"id": "1", "description": "a" * 50}]
        result = validate_subtasks(subtasks)

        assert result["phase"] == "validate_subtasks"

    def test_multiple_issues_same_subtask(self):
        """Multiple issues on same subtask should each get a warning."""
        subtasks = [
            {
                "id": "",
                "description": "short",
            },
        ]
        result = validate_subtasks(subtasks)

        # Should have warnings for: short, no file/function, empty id
        assert len(result["warnings"]) == 3
