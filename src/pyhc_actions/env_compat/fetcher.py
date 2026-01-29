"""Fetch PyHC Environment requirements."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import requests
import yaml

if TYPE_CHECKING:
    pass


# Default URL to PyHC Environment requirements.txt
PYHC_REQUIREMENTS_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main/docker/pyhc-environment/contents/requirements.txt"
)

# Default URL to PyHC Environment environment.yml (conda environment file)
PYHC_ENVIRONMENT_YML_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main/docker/pyhc-environment/contents/environment.yml"
)


def fetch_pyhc_requirements(url: str | None = None) -> str:
    """Fetch PyHC Environment requirements.txt content.

    Args:
        url: URL to fetch from (default: official GitHub raw URL)

    Returns:
        Contents of requirements.txt as string

    Raises:
        requests.RequestException: If fetch fails
    """
    url = url or PYHC_REQUIREMENTS_URL

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return response.text


def parse_requirements_for_uv(requirements_text: str) -> list[str]:
    """Parse requirements.txt and return list suitable for uv.

    Filters out comments, blank lines, and incompatible lines.

    Args:
        requirements_text: Raw requirements.txt content

    Returns:
        List of requirement strings
    """
    requirements = []

    for line in requirements_text.split("\n"):
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

        requirements.append(line)

    return requirements


def load_pyhc_requirements(
    source: str | Path | None = None,
) -> list[str]:
    """Load PyHC requirements from URL or local file.

    Args:
        source: URL or path to requirements file (None uses default URL)

    Returns:
        List of requirement strings
    """
    if source is None:
        # Fetch from default URL
        text = fetch_pyhc_requirements()
    elif isinstance(source, Path) or (isinstance(source, str) and not source.startswith("http")):
        # Load from local file
        path = Path(source)
        with open(path) as f:
            text = f.read()
    else:
        # Fetch from URL
        text = fetch_pyhc_requirements(str(source))

    return parse_requirements_for_uv(text)


def get_package_from_pyproject(pyproject_path: Path | str) -> str:
    """Get package specification from pyproject.toml for use in requirements.

    Args:
        pyproject_path: Path to pyproject.toml

    Returns:
        Package specification string (either "." for local or package name)
    """
    pyproject_path = Path(pyproject_path)

    # If pyproject.toml exists in directory, use "." for editable install
    if pyproject_path.exists():
        return str(pyproject_path.parent.resolve())

    return "."


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
