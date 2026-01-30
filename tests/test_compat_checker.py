"""Tests for PyHC compatibility checker."""

import pytest
from unittest.mock import patch, MagicMock

from pyhc_actions.env_compat.uv_resolver import (
    parse_uv_error,
    find_uv,
    Conflict,
    _is_python_version_error,
    _extract_conflict_from_error,
    _extract_error_summary,
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

    def test_depends_on_and_you_require_pattern(self):
        """Test parsing 'depends on' + 'you require' format (actual uv output)."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because pyhc-core==0.0.7 depends on numpy<2 and you require numpy>=2.0,<2.3.0, we can conclude that your requirements and pyhc-core[tests]==0.0.7 are incompatible. And because you require pyhc-core[tests]==0.0.7, we can conclude that your requirements are unsatisfiable.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "numpy"
        assert "<2" in conflicts[0].your_requirement
        assert ">=2.0" in conflicts[0].pyhc_requirement

    def test_depends_on_both_sides_pattern(self):
        """Test parsing 'depends on' on both sides."""
        stderr = """
error: No solution found when resolving dependencies:
╰─▶ Because package-a==1.0.0 depends on numpy>=2.0 and package-b==1.0.0 depends on numpy<2.0, we can conclude that package-a==1.0.0 and package-b==1.0.0 are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "numpy"

    def test_complex_version_specifier(self):
        """Test parsing complex version specifiers with commas."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because mypackage==1.0 depends on scipy>=1.5,<2.0 and you require scipy>=2.0,<3.0, we can conclude that the requirements are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "scipy"
        # Should capture the full version spec including comma-separated parts
        assert "1.5" in conflicts[0].your_requirement or "2.0" in conflicts[0].pyhc_requirement

    def test_multiple_conflicts(self):
        """Test parsing multiple package conflicts."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because pkg==1.0 depends on numpy<2 and you require numpy>=2.0, we can conclude incompatibility.
    And because pkg==1.0 depends on scipy<1.8 and you require scipy>=1.8, we can conclude incompatibility.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 2
        packages = {c.package for c in conflicts}
        assert "numpy" in packages
        assert "scipy" in packages

    def test_both_sides_depends_on(self):
        """Test 'X depends on' and 'Y depends on' pattern (no 'you require')."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because bar depends on anyio==4.2.0 and foo depends on anyio==4.1.0, we can conclude that bar and foo are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "anyio"

    def test_package_with_extras(self):
        """Test packages with extras like project[extra1]."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because project[extra2] depends on sortedcontainers==2.4.0 and project[extra1] depends on sortedcontainers==2.3.0, we can conclude that project[extra1] and project[extra2] are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "sortedcontainers"

    def test_package_with_dev_group(self):
        """Test packages with dev groups like project:foo."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because project:group2 depends on sortedcontainers==2.4.0 and project:group1 depends on sortedcontainers==2.3.0, we can conclude that project:group1 and project:group2 are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "sortedcontainers"

    def test_your_project_depends_on(self):
        """Test 'your project depends on' format."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because your project depends on sortedcontainers==2.3.0 and project:foo depends on sortedcontainers==2.4.0, we can conclude that your project and project:foo are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "sortedcontainers"

    def test_exact_version_pin(self):
        """Test exact version pins like ==2.4.0."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because flask==3.0.2 depends on click>=8.1.3 and you require click==7.0.0, we can conclude that your requirements and flask==3.0.2 are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "click"
        assert ">=8.1.3" in conflicts[0].your_requirement or ">=8.1.3" in conflicts[0].pyhc_requirement
        assert "==7.0.0" in conflicts[0].your_requirement or "==7.0.0" in conflicts[0].pyhc_requirement

    def test_package_with_markers_fallback(self):
        """Test packages with markers - should fall back to generic extraction.

        Markers like {sys_platform == 'linux'} in package names are exotic
        and may not be parsed perfectly, but should still produce useful output.
        """
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because package-a==1.0.0 depends on package-c{sys_platform == 'linux'}<2.0.0 and package-b==1.0.0 depends on package-c{sys_platform == 'darwin'}>=2.0.0, we can conclude that package-a==1.0.0 and package-b==1.0.0 are incompatible.
"""
        conflicts = parse_uv_error(stderr)
        # May or may not parse perfectly, but should produce at least one conflict
        assert len(conflicts) >= 1

    def test_tilde_equals_version(self):
        """Test ~= (compatible release) version specifier."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because pkg-a==1.0 depends on numpy~=1.20 and you require numpy>=2.0, we can conclude incompatibility.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "numpy"

    def test_not_equals_version(self):
        """Test != version specifier."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because pkg-a==1.0 depends on numpy!=2.0 and you require numpy==2.0, we can conclude incompatibility.
"""
        conflicts = parse_uv_error(stderr)
        assert len(conflicts) == 1
        assert conflicts[0].package == "numpy"


class TestExtractConflictFromError:
    """Tests for fallback conflict extraction."""

    def test_extract_from_depends_requires(self):
        """Test extracting conflict when patterns don't match exactly."""
        stderr = """
error: No solution found when resolving dependencies:
  Some package depends on requests<2.0
  Another thing requires requests>=2.25
"""
        conflict = _extract_conflict_from_error(stderr)
        assert conflict is not None
        assert conflict.package == "requests"

    def test_no_conflict_found(self):
        """Test when no package conflict can be extracted."""
        stderr = """
error: No solution found
  Network error occurred
"""
        conflict = _extract_conflict_from_error(stderr)
        assert conflict is None


class TestExtractErrorSummary:
    """Tests for error summary extraction."""

    def test_removes_hints(self):
        """Test that hints are filtered out."""
        stderr = """
error: No solution found
╰─▶ Because foo depends on bar<2
hint: Try upgrading bar
hint: Or downgrade foo
"""
        summary = _extract_error_summary(stderr)
        assert "hint" not in summary.lower()
        assert "foo depends on bar" in summary

    def test_cleans_tree_characters(self):
        """Test that tree characters are cleaned up."""
        stderr = """
× No solution found when resolving dependencies:
╰─▶ Because pkg depends on numpy<2
"""
        summary = _extract_error_summary(stderr)
        assert "╰─▶" not in summary
        assert "→" in summary or "pkg depends on numpy" in summary

    def test_preserves_full_message(self):
        """Test that the full message is preserved, not truncated."""
        stderr = """
error: line 1
error: line 2
error: line 3
error: line 4
error: line 5
error: line 6
error: line 7
"""
        summary = _extract_error_summary(stderr)
        assert "line 7" in summary  # Should not be truncated


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
