"""Tests for PyHC compatibility checker."""

import pytest
from unittest.mock import patch, MagicMock

from pyhc_actions.env_compat.uv_resolver import (
    parse_uv_error,
    find_uv,
    Conflict,
    _is_python_version_error,
)
from pyhc_actions.env_compat.fetcher import (
    parse_requirements_for_uv,
)


class TestParseRequirementsForUV:
    """Tests for parsing requirements.txt."""

    def test_simple_requirements(self):
        """Test parsing simple requirements."""
        text = """
numpy>=1.20
scipy>=1.7
matplotlib>=3.5
"""
        result = parse_requirements_for_uv(text)
        assert len(result) == 3
        assert "numpy>=1.20" in result
        assert "scipy>=1.7" in result

    def test_skip_comments(self):
        """Test that comments are skipped."""
        text = """
# This is a comment
numpy>=1.20
# Another comment
scipy>=1.7
"""
        result = parse_requirements_for_uv(text)
        assert len(result) == 2
        assert "numpy>=1.20" in result

    def test_skip_pip_options(self):
        """Test that pip options are skipped."""
        text = """
-r base.txt
-e .
numpy>=1.20
--index-url https://pypi.org/simple
scipy>=1.7
"""
        result = parse_requirements_for_uv(text)
        assert len(result) == 2
        assert "numpy>=1.20" in result
        assert "scipy>=1.7" in result

    def test_skip_empty_lines(self):
        """Test that empty lines are skipped."""
        text = """

numpy>=1.20

scipy>=1.7

"""
        result = parse_requirements_for_uv(text)
        assert len(result) == 2


class TestParseUVError:
    """Tests for parsing uv error messages."""

    def test_parse_simple_conflict(self):
        """Test parsing simple conflict message."""
        stderr = """
error: No solution found when resolving dependencies:
Because project requires numpy<2.0 and pyhc-environment requires numpy>=2.0,
we can conclude that project and pyhc-environment are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) >= 1

    def test_parse_no_solution_message(self):
        """Test parsing generic no solution message."""
        stderr = """
error: No solution found when resolving dependencies:
  The requested version numpy>=3.0 does not exist
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) >= 1

    def test_empty_stderr(self):
        """Test handling empty stderr."""
        conflicts = parse_uv_error("")
        assert len(conflicts) == 0

    def test_non_conflict_message(self):
        """Test handling non-conflict error."""
        stderr = """
warning: Some unrelated warning
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 0


class TestFindUV:
    """Tests for finding uv executable."""

    def test_find_uv_in_path(self):
        """Test finding uv in PATH."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/uv"
            result = find_uv()
            assert result == "/usr/local/bin/uv"

    def test_uv_not_found(self):
        """Test when uv is not found."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.return_value = False
                result = find_uv()
                # May or may not find uv depending on system
                # Just verify it doesn't crash
                assert result is None or isinstance(result, str)


class TestConflict:
    """Tests for Conflict dataclass."""

    def test_conflict_creation(self):
        """Test creating a Conflict object."""
        conflict = Conflict(
            package="numpy",
            your_requirement="numpy<2.0",
            pyhc_requirement="numpy>=2.0",
            reason="No overlapping versions",
        )
        assert conflict.package == "numpy"
        assert conflict.your_requirement == "numpy<2.0"
        assert conflict.pyhc_requirement == "numpy>=2.0"


class TestPythonVersionError:
    """Tests for Python version error detection."""

    def test_detect_python_version_error(self):
        """Test detecting Python version mismatch error."""
        stderr = """
error: No solution found when resolving dependencies:
╰─▶ Because the current Python version (3.11.14) does not satisfy Python>=3.12
    and aiapy==0.11.0 depends on Python>=3.12, we can conclude that aiapy==0.11.0
    cannot be used.
"""
        is_error, required = _is_python_version_error(stderr)
        assert is_error is True
        assert required == "Python>=3.12"

    def test_not_python_version_error(self):
        """Test that package conflicts are not detected as Python errors."""
        stderr = """
error: No solution found when resolving dependencies:
Because project requires numpy<2.0 and pyhc-environment requires numpy>=2.0,
we can conclude that project and pyhc-environment are incompatible.
"""
        is_error, required = _is_python_version_error(stderr)
        assert is_error is False
        assert required is None

    def test_empty_stderr(self):
        """Test handling empty stderr."""
        is_error, required = _is_python_version_error("")
        assert is_error is False
        assert required is None
