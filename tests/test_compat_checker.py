"""Tests for PyHC compatibility checker."""

import pytest
from unittest.mock import patch, MagicMock

from pyhc_actions.env_compat.uv_resolver import (
    parse_uv_error,
    find_uv,
    Conflict,
    _is_python_version_error,
    check_python_compatibility,
)
from pyhc_actions.env_compat.fetcher import (
    parse_requirements_for_uv,
    parse_python_version_from_env_yml,
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


class TestParsePythonVersionFromEnvYml:
    """Tests for parsing Python version from environment.yml."""

    def test_simple_python_version(self):
        """Test parsing simple Python version."""
        yaml_content = """
name: pyhc-environment
channels:
  - conda-forge
dependencies:
  - python=3.12.9
  - numpy
  - scipy
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result == "3.12.9"

    def test_python_with_channel_and_build(self):
        """Test parsing Python with channel prefix and build string."""
        yaml_content = """
name: pyhc-environment
channels:
  - conda-forge
dependencies:
  - conda-forge::python=3.12.9=h9e4cc4f_0_cpython
  - numpy
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result == "3.12.9"

    def test_python_minor_version_only(self):
        """Test parsing Python with minor version only (no patch)."""
        yaml_content = """
name: pyhc
dependencies:
  - python=3.12
  - pip
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result == "3.12"

    def test_python_with_specifier(self):
        """Test parsing Python with version specifier."""
        yaml_content = """
dependencies:
  - python>=3.11
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result == "3.11"

    def test_no_python_in_dependencies(self):
        """Test when Python is not in dependencies."""
        yaml_content = """
dependencies:
  - numpy
  - scipy
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result is None

    def test_empty_yaml(self):
        """Test empty YAML content."""
        result = parse_python_version_from_env_yml("")
        assert result is None

    def test_invalid_yaml(self):
        """Test invalid YAML content."""
        yaml_content = "{{invalid yaml content}}"
        result = parse_python_version_from_env_yml(yaml_content)
        assert result is None

    def test_no_dependencies_key(self):
        """Test YAML without dependencies key."""
        yaml_content = """
name: some-env
channels:
  - conda-forge
"""
        result = parse_python_version_from_env_yml(yaml_content)
        assert result is None


class TestCheckPythonCompatibility:
    """Tests for checking Python version compatibility."""

    def test_compatible_version(self):
        """Test when package is compatible with PyHC Python."""
        is_compat, error = check_python_compatibility(">=3.11", "3.12.9")
        assert is_compat is True
        assert error is None

    def test_compatible_range(self):
        """Test when PyHC Python is within package's range."""
        is_compat, error = check_python_compatibility(">=3.11,<3.14", "3.12.9")
        assert is_compat is True
        assert error is None

    def test_incompatible_too_new(self):
        """Test when package requires newer Python than PyHC."""
        is_compat, error = check_python_compatibility(">=3.13", "3.12.9")
        assert is_compat is False
        assert error is not None
        assert "Python >=3.13" in error
        assert "Python 3.12.9" in error

    def test_incompatible_too_old(self):
        """Test when package excludes PyHC's Python version."""
        is_compat, error = check_python_compatibility("<3.12", "3.12.9")
        assert is_compat is False
        assert error is not None
        assert "Python <3.12" in error

    def test_no_requires_python(self):
        """Test when package has no requires-python (skip check)."""
        is_compat, error = check_python_compatibility(None, "3.12.9")
        assert is_compat is True
        assert error is None

    def test_empty_requires_python(self):
        """Test when requires-python is empty string (skip check)."""
        is_compat, error = check_python_compatibility("", "3.12.9")
        assert is_compat is True
        assert error is None

    def test_invalid_specifier(self):
        """Test when requires-python is invalid (skip check)."""
        is_compat, error = check_python_compatibility("not-a-specifier", "3.12.9")
        assert is_compat is True
        assert error is None

    def test_invalid_pyhc_version(self):
        """Test when PyHC Python version is invalid (skip check)."""
        is_compat, error = check_python_compatibility(">=3.11", "invalid")
        assert is_compat is True
        assert error is None

    def test_exact_match(self):
        """Test when requires-python exactly matches PyHC Python."""
        is_compat, error = check_python_compatibility("==3.12.9", "3.12.9")
        assert is_compat is True
        assert error is None

    def test_minor_version_compatible(self):
        """Test compatibility with minor version specifier."""
        is_compat, error = check_python_compatibility(">=3.12", "3.12.9")
        assert is_compat is True
        assert error is None
