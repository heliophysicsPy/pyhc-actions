"""Tests for PHEP 3 metadata extractor module."""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestExtractScriptSyntax:
    """Tests for the embedded Python script syntax in metadata_extractor.

    The extract_metadata_with_uv function builds a Python script as an f-string
    and runs it in a subprocess. All literal braces must be escaped as {{ and }}
    otherwise Python raises a SyntaxError.
    """

    def test_fstring_braces_are_valid_python(self):
        """Test that the f-string generates valid Python code.

        This test extracts the script-building logic and verifies
        that the resulting string is syntactically valid Python.
        """
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_with_uv
        import inspect

        # Get the source code of the function
        source = inspect.getsource(extract_metadata_with_uv)

        # The function should contain properly escaped braces
        # These patterns indicate correct escaping in the f-string:
        assert "optional_deps = {{}}" in source, \
            "optional_deps initialization should use escaped braces {{}}"

        assert "json.dumps({{" in source, \
            "json.dumps dict should use escaped braces {{"

    def test_embedded_script_is_syntactically_valid(self):
        """Test that the generated script is valid Python when evaluated.

        We verify the ACTUAL f-string from the source code produces valid Python.
        """
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_with_uv
        import inspect
        import re

        # Get the source code
        source = inspect.getsource(extract_metadata_with_uv)

        # Extract the f-string content (the part between f''' and ''')
        # The f-string starts after 'extract_script = f"""' and ends at '"""'
        match = re.search(r'extract_script = f"""(.+?)"""', source, re.DOTALL)
        assert match is not None, "Could not find extract_script f-string in source"

        fstring_content = match.group(1)

        # Simulate the f-string evaluation with a sample value
        # The f-string has one interpolation: {dists_before_json}
        dists_before_json = '["pip-24.0.dist-info"]'

        # Replace the interpolation placeholder
        # The f-string has: '''{dists_before_json}'''
        script = fstring_content.replace("{dists_before_json}", dists_before_json)

        # Replace escaped braces: {{ -> { and }} -> }
        script = script.replace("{{", "{").replace("}}", "}")

        # This should compile without syntax errors
        try:
            compile(script, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated script has syntax error at line {e.lineno}: {e.msg}\n"
                       f"Problematic line: {e.text}")

    def test_empty_dict_literal_escaping(self):
        """Test that empty dict {} is properly escaped in f-strings."""
        # In an f-string, {} would be interpreted as an expression
        # Must be {{}} to produce literal {}

        # This is what the code does:
        test_fstring = f"optional_deps = {{}}"
        assert test_fstring == "optional_deps = {}"

        # Without escaping, this would fail:
        # f"optional_deps = {}" -> SyntaxError or empty string

    def test_dict_in_function_call_escaping(self):
        """Test that dict literals in function calls are properly escaped."""
        # json.dumps needs a dict literal
        error_msg = "test error"

        # Properly escaped:
        test_fstring = f'print(json.dumps({{"error": "{error_msg}"}}))'
        assert test_fstring == 'print(json.dumps({"error": "test error"}))'

        # The generated string should be valid Python
        # (we can't actually run it, but we can compile it)
        try:
            compile(test_fstring, "<test>", "eval")
        except SyntaxError as e:
            pytest.fail(f"Dict in function call has syntax error: {e}")


class TestMetadataExtraction:
    """Tests for metadata extraction functionality."""

    def test_check_uv_available(self):
        """Test uv availability check."""
        from pyhc_actions.phep3.metadata_extractor import check_uv_available

        # This will return True if uv is installed, False otherwise
        result = check_uv_available()
        assert isinstance(result, bool)

    def test_get_min_phep3_python(self):
        """Test getting minimum Python version from schedule."""
        from pyhc_actions.phep3.metadata_extractor import get_min_phep3_python
        from pyhc_actions.phep3.schedule import Schedule, VersionSchedule
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        schedule = Schedule(
            generated_at=now,
            python={
                "3.10": VersionSchedule(
                    version="3.10",
                    release_date=now - timedelta(days=800),
                    drop_date=now + timedelta(days=200),
                    support_by=now - timedelta(days=600),
                ),
                "3.11": VersionSchedule(
                    version="3.11",
                    release_date=now - timedelta(days=500),
                    drop_date=now + timedelta(days=500),
                    support_by=now - timedelta(days=300),
                ),
            },
            packages={},
        )

        result = get_min_phep3_python(schedule)

        # Should return the oldest non-droppable version
        assert result in ["3.10", "3.11", "3.12"]

    def test_package_metadata_dataclass(self):
        """Test PackageMetadata dataclass."""
        from pyhc_actions.phep3.metadata_extractor import PackageMetadata

        metadata = PackageMetadata(
            name="test-package",
            requires_python=">=3.10",
            dependencies=["numpy>=1.20", "scipy>=1.7"],
            optional_dependencies={"dev": ["pytest", "black"]},
            extracted_via="pyproject.toml",
        )

        assert metadata.name == "test-package"
        assert metadata.requires_python == ">=3.10"
        assert len(metadata.dependencies) == 2
        assert "dev" in metadata.optional_dependencies
        assert metadata.extracted_via == "pyproject.toml"


class TestExtractMetadataFromProject:
    """Tests for extract_metadata_from_project function."""

    def test_extract_from_pyproject_toml(self):
        """Test extracting metadata from a PEP 621 pyproject.toml."""
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_from_project

        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text("""
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy>=1.20",
    "scipy>=1.7",
]

[project.optional-dependencies]
dev = ["pytest", "black"]
""")

            result = extract_metadata_from_project(pyproject_path)

            assert result is not None
            assert result.name == "test-package"
            assert result.requires_python == ">=3.10"
            assert "numpy>=1.20" in result.dependencies
            assert "dev" in result.optional_dependencies
            assert result.extracted_via == "pyproject.toml"

    def test_extract_from_directory_with_pyproject(self):
        """Test extracting metadata when given a directory path."""
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_from_project

        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text("""
[project]
name = "dir-test"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = ["requests"]
""")

            # Pass directory instead of file
            result = extract_metadata_from_project(Path(tmpdir))

            assert result is not None
            assert result.name == "dir-test"
            assert result.extracted_via == "pyproject.toml"

    def test_extract_returns_none_for_empty_directory(self):
        """Test that extraction returns None for empty directory."""
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_from_project

        with tempfile.TemporaryDirectory() as tmpdir:
            # No pyproject.toml, no setup.py
            result = extract_metadata_from_project(Path(tmpdir))

            # Without uv fallback available, should return None
            # (uv fallback only works if uv is installed and can build the package)
            # For truly empty directory, there's nothing to extract
            assert result is None

    def test_extract_from_poetry_style_pyproject(self):
        """Test that Poetry-style pyproject.toml falls back to uv."""
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_from_project

        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            # Poetry uses [tool.poetry] instead of [project]
            pyproject_path.write_text("""
[tool.poetry]
name = "poetry-package"
version = "1.0.0"
description = "A poetry package"

[tool.poetry.dependencies]
python = "^3.10"
numpy = "^1.20"
""")

            result = extract_metadata_from_project(pyproject_path)

            # Without [project] section, should try uv fallback
            # If uv isn't available or can't extract, returns None
            # Either way, shouldn't crash
            assert result is None or result.extracted_via == "uv"
