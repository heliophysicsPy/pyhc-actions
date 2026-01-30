"""Tests for PyHC environment fetcher module."""

import pytest
import tempfile
from pathlib import Path

from pyhc_actions.env_compat.fetcher import (
    get_package_from_pyproject,
    parse_requirements_for_uv,
)


class TestGetPackageFromPyproject:
    """Tests for get_package_from_pyproject function.

    This function must handle both:
    1. File paths (pyproject.toml) - for modern packages
    2. Directory paths - for setup.py packages (main.py passes directory)
    """

    def test_with_existing_pyproject_file(self):
        """Test with path to an existing pyproject.toml file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text("[project]\nname = 'test'")

            result = get_package_from_pyproject(pyproject_path)

            # Should return the parent directory (the package root)
            assert result == str(Path(tmpdir).resolve())

    def test_with_nonexistent_pyproject_file(self):
        """Test with path to a pyproject.toml that doesn't exist.

        This happens when a package only has setup.py but we still pass
        the expected pyproject.toml path.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # pyproject.toml doesn't exist, only the directory does
            pyproject_path = Path(tmpdir) / "pyproject.toml"

            result = get_package_from_pyproject(pyproject_path)

            # Should still return the parent directory
            assert result == str(Path(tmpdir).resolve())

    def test_with_directory_path(self):
        """Test with a directory path (setup.py packages).

        For setup.py packages, main.py passes the project directory
        instead of a file path. This must return the directory itself,
        NOT its parent.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a setup.py to simulate a legacy package
            setup_py = Path(tmpdir) / "setup.py"
            setup_py.write_text("from setuptools import setup\nsetup()")

            # Pass the directory path (as main.py does for setup.py packages)
            result = get_package_from_pyproject(Path(tmpdir))

            # Should return the directory itself, NOT its parent
            assert result == str(Path(tmpdir).resolve())

    def test_with_string_path(self):
        """Test that string paths work the same as Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text("[project]\nname = 'test'")

            # Pass as string
            result = get_package_from_pyproject(str(pyproject_path))

            assert result == str(Path(tmpdir).resolve())

    def test_directory_vs_file_path_difference(self):
        """Test the critical difference between directory and file paths.

        This is the bug that was fixed: when passed a directory,
        the old code would return directory.parent (WRONG).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pyproject_path = tmpdir_path / "pyproject.toml"

            # For a file path, parent is the package directory
            file_result = get_package_from_pyproject(pyproject_path)
            assert file_result == str(tmpdir_path.resolve())

            # For a directory path, the directory IS the package directory
            dir_result = get_package_from_pyproject(tmpdir_path)
            assert dir_result == str(tmpdir_path.resolve())

            # Both should return the SAME result
            assert file_result == dir_result

    def test_nested_directory_structure(self):
        """Test with nested directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create /tmpdir/mypackage/pyproject.toml
            package_dir = Path(tmpdir) / "mypackage"
            package_dir.mkdir()
            pyproject_path = package_dir / "pyproject.toml"
            pyproject_path.write_text("[project]\nname = 'mypackage'")

            # File path should return package_dir
            result_file = get_package_from_pyproject(pyproject_path)
            assert result_file == str(package_dir.resolve())

            # Directory path should also return package_dir
            result_dir = get_package_from_pyproject(package_dir)
            assert result_dir == str(package_dir.resolve())

    def test_returns_absolute_path(self):
        """Test that the returned path is always absolute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Even with relative-ish paths, should return absolute
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text("[project]\nname = 'test'")

            result = get_package_from_pyproject(pyproject_path)

            assert Path(result).is_absolute()


class TestParseRequirementsForUVEditable:
    """Tests for parse_requirements_for_uv handling of editable installs.

    When we write -e /path/to/package to a temp requirements file,
    the parsing function should skip it (it's for resolution input,
    not output). This verifies the skip behavior.
    """

    def test_skip_editable_installs(self):
        """Test that -e lines are skipped."""
        text = """
numpy>=1.20
-e /path/to/local/package
scipy>=1.7
-e .
matplotlib>=3.5
"""
        result = parse_requirements_for_uv(text)

        # Should only include the regular packages, not -e lines
        assert len(result) == 3
        assert "numpy>=1.20" in result
        assert "scipy>=1.7" in result
        assert "matplotlib>=3.5" in result
        # -e lines should be excluded
        assert not any("-e" in req for req in result)
        assert not any("/path" in req for req in result)

    def test_skip_path_installs(self):
        """Test that path-based installs are skipped."""
        text = """
numpy>=1.20
/absolute/path/to/package
./relative/path
../parent/path
scipy>=1.7
"""
        result = parse_requirements_for_uv(text)

        # Should only include the regular packages
        assert len(result) == 2
        assert "numpy>=1.20" in result
        assert "scipy>=1.7" in result
