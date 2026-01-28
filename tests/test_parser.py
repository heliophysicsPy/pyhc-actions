"""Tests for common parser utilities."""

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from pyhc_actions.common.parser import (
    parse_dependency,
    extract_version_bounds,
    extract_python_version,
    ParsedDependency,
    VersionBounds,
)


class TestParseDependency:
    """Tests for parse_dependency function."""

    def test_simple_package(self):
        """Test parsing simple package name."""
        dep = parse_dependency("numpy")
        assert dep is not None
        assert dep.name == "numpy"
        assert dep.specifier is None
        assert dep.extras is None

    def test_package_with_version(self):
        """Test parsing package with version specifier."""
        dep = parse_dependency("numpy>=1.20")
        assert dep is not None
        assert dep.name == "numpy"
        assert dep.specifier == SpecifierSet(">=1.20")

    def test_package_with_complex_version(self):
        """Test parsing package with complex version specifier."""
        dep = parse_dependency("numpy>=1.20,<2.0")
        assert dep is not None
        assert dep.name == "numpy"
        assert dep.specifier == SpecifierSet(">=1.20,<2.0")

    def test_package_with_extras(self):
        """Test parsing package with extras."""
        dep = parse_dependency("sunpy[all]>=4.0")
        assert dep is not None
        assert dep.name == "sunpy"
        assert "[all]" in dep.extras
        assert dep.specifier == SpecifierSet(">=4.0")

    def test_package_with_markers(self):
        """Test parsing package with environment markers."""
        dep = parse_dependency('numpy>=1.20; python_version >= "3.9"')
        assert dep is not None
        assert dep.name == "numpy"
        assert dep.markers is not None
        assert "python_version" in dep.markers

    def test_url_dependency(self):
        """Test parsing URL dependency."""
        dep = parse_dependency("package @ https://example.com/package.tar.gz")
        assert dep is not None
        assert dep.name == "package"
        assert dep.is_url is True

    def test_empty_string(self):
        """Test parsing empty string returns None."""
        dep = parse_dependency("")
        assert dep is None

    def test_comment_line(self):
        """Test that comment-like strings can still be parsed if valid."""
        # This is actually just testing the regex, comments should be filtered before
        dep = parse_dependency("numpy")
        assert dep is not None


class TestExtractVersionBounds:
    """Tests for extract_version_bounds function."""

    def test_lower_bound_only(self):
        """Test extracting lower bound."""
        spec = SpecifierSet(">=1.20")
        bounds = extract_version_bounds(spec)
        assert bounds.lower == Version("1.20")
        assert bounds.lower_inclusive is True
        assert bounds.upper is None

    def test_strict_lower_bound(self):
        """Test extracting strict lower bound."""
        spec = SpecifierSet(">1.20")
        bounds = extract_version_bounds(spec)
        assert bounds.lower == Version("1.20")
        assert bounds.lower_inclusive is False

    def test_upper_bound_only(self):
        """Test extracting upper bound."""
        spec = SpecifierSet("<2.0")
        bounds = extract_version_bounds(spec)
        assert bounds.upper == Version("2.0")
        assert bounds.upper_inclusive is False
        assert bounds.has_upper_constraint is True

    def test_both_bounds(self):
        """Test extracting both bounds."""
        spec = SpecifierSet(">=1.20,<2.0")
        bounds = extract_version_bounds(spec)
        assert bounds.lower == Version("1.20")
        assert bounds.upper == Version("2.0")

    def test_exact_version(self):
        """Test extracting exact version."""
        spec = SpecifierSet("==1.20.0")
        bounds = extract_version_bounds(spec)
        assert bounds.exact == Version("1.20.0")

    def test_none_specifier(self):
        """Test with None specifier."""
        bounds = extract_version_bounds(None)
        assert bounds.lower is None
        assert bounds.upper is None
        assert bounds.exact is None


class TestExtractPythonVersion:
    """Tests for extract_python_version function."""

    def test_simple_version(self):
        """Test simple Python version."""
        version = extract_python_version(">=3.9")
        assert version == Version("3.9")

    def test_complex_specifier(self):
        """Test complex Python specifier."""
        version = extract_python_version(">=3.9,<4.0")
        assert version == Version("3.9")

    def test_none_input(self):
        """Test with None input."""
        version = extract_python_version(None)
        assert version is None

    def test_invalid_specifier(self):
        """Test with invalid specifier."""
        version = extract_python_version("invalid")
        assert version is None
