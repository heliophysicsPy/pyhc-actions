"""Fetch PyHC Environment requirements."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    pass


# Default URL to PyHC Environment requirements.txt
PYHC_REQUIREMENTS_URL = (
    "https://raw.githubusercontent.com/heliophysicsPy/pyhc-docker-environment/"
    "main/docker/pyhc-environment/contents/requirements.txt"
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
