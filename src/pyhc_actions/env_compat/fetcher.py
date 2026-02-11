"""Fetch PyHC Environment package and constraint files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import requests
import yaml

# Default URL to PyHC Environment packages.txt
PYHC_PACKAGES_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main-v2/docker/pyhc-environment/contents/packages.txt"
)

# Default URL to PyHC Environment constraints.txt
PYHC_CONSTRAINTS_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main-v2/docker/pyhc-environment/contents/constraints.txt"
)

# Default URL to PyHC Environment environment.yml (conda environment file)
PYHC_ENVIRONMENT_YML_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main-v2/docker/pyhc-environment/contents/environment.yml"
)


def fetch_pyhc_packages(url: str | None = None) -> str:
    """Fetch PyHC Environment packages.txt content.

    Args:
        url: URL to fetch from (default: official GitHub raw URL)

    Returns:
        Contents of packages.txt as string

    Raises:
        requests.RequestException: If fetch fails
    """
    url = url or PYHC_PACKAGES_URL

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return response.text


def fetch_pyhc_constraints(url: str | None = None) -> str:
    """Fetch PyHC Environment constraints.txt content.

    Args:
        url: URL to fetch from (default: official GitHub raw URL)

    Returns:
        Contents of constraints.txt as string

    Raises:
        requests.RequestException: If fetch fails
    """
    url = url or PYHC_CONSTRAINTS_URL

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return response.text


def parse_package_specs_for_uv(raw_text: str) -> list[str]:
    """Parse package-spec text and return entries suitable for uv.

    Filters out comments, blank lines, and incompatible lines.

    Args:
        raw_text: Raw text from packages.txt or constraints.txt

    Returns:
        List of package spec strings
    """
    package_specs = []

    for line in raw_text.split("\n"):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Skip pip options (-r, -e, etc.)
        if line.startswith("-"):
            continue

        # Skip editable installs and path installs
        if line.startswith(".") or line.startswith("/"):
            continue

        package_specs.append(line)

    return package_specs


def _load_from_source(
    source: str | Path | None,
    fetcher: Callable[[str | None], str],
) -> str:
    """Load text from URL or local file."""
    if source is None:
        return fetcher()

    if isinstance(source, Path) or (
        isinstance(source, str) and not source.startswith("http")
    ):
        path = Path(source)
        with open(path) as f:
            return f.read()

    return fetcher(str(source))


def load_pyhc_packages(source: str | Path | None = None) -> list[str]:
    """Load PyHC packages from URL or local file.

    Args:
        source: URL or path to packages file (None uses default URL)

    Returns:
        List of package spec strings
    """
    text = _load_from_source(source, fetch_pyhc_packages)
    return parse_package_specs_for_uv(text)


def load_pyhc_constraints(source: str | Path | None = None) -> list[str]:
    """Load PyHC constraints from URL or local file.

    Args:
        source: URL or path to constraints file (None uses default URL)

    Returns:
        List of constraint spec strings
    """
    text = _load_from_source(source, fetch_pyhc_constraints)
    return parse_package_specs_for_uv(text)


def get_package_from_pyproject(pyproject_path: Path | str) -> str:
    """Get package directory path for local editable install specs.

    Handles both file paths (pyproject.toml) and directory paths (for setup.py
    packages where main.py passes the project directory directly).

    Args:
        pyproject_path: Path to pyproject.toml file OR project directory

    Returns:
        Absolute path to the package directory
    """
    pyproject_path = Path(pyproject_path)

    # If it's a directory (setup.py packages), return that directory
    if pyproject_path.is_dir():
        return str(pyproject_path.resolve())

    # If it's a file path (or expected to be one), return its parent directory
    # This works whether the file exists or not
    return str(pyproject_path.parent.resolve())


def fetch_pyhc_environment_yml(url: str | None = None) -> str:
    """Fetch PyHC Environment environment.yml content.

    Args:
        url: URL to fetch from (default: official GitHub raw URL)

    Returns:
        Contents of environment.yml as string

    Raises:
        requests.RequestException: If fetch fails
    """
    url = url or PYHC_ENVIRONMENT_YML_URL

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return response.text


def parse_python_version_from_env_yml(yaml_content: str) -> str | None:
    """Parse Python version from environment.yml content.

    The Python line in environment.yml can have various formats:
    - conda-forge::python=3.12.9=h9e4cc4f_0_cpython  (with channel and build string)
    - python=3.12.12                                   (simple)
    - python>=3.12                                     (version specifier)

    Args:
        yaml_content: Raw YAML content of environment.yml

    Returns:
        Python version string (e.g., "3.12.9" or "3.12") or None if not found
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list):
        return None

    # Regex to extract version from various formats
    # Matches: python=3.12.9, python=3.12, python>=3.12, python==3.12.9
    # Also handles channel prefix: conda-forge::python=3.12.9=build_string
    python_version_re = re.compile(
        r"(?:.*::)?python[<>=!]*=?(\d+\.\d+(?:\.\d+)?)"
    )

    for dep in dependencies:
        if not isinstance(dep, str):
            continue

        if dep.startswith("python") or "::python" in dep:
            match = python_version_re.match(dep)
            if match:
                return match.group(1)

    return None


def get_pyhc_python_version(url: str | None = None) -> str | None:
    """Fetch and parse the Python version from PyHC Environment.

    Convenience function that fetches environment.yml and extracts
    the Python version in one call.

    Args:
        url: URL to environment.yml (default: official GitHub raw URL)

    Returns:
        Python version string or None if unable to determine
    """
    try:
        yaml_content = fetch_pyhc_environment_yml(url)
        return parse_python_version_from_env_yml(yaml_content)
    except requests.RequestException:
        return None
