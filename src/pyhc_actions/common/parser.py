"""Parser utilities for pyproject.toml and requirements.txt files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
import tomlkit

if TYPE_CHECKING:
    from typing import Tuple


# PEP 508 dependency string pattern
# Matches: package[extras]>=version,<version; markers
PEP_DEPENDENCY_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9._,\s-]+\])?\s*([^;@]*)?(@.+)?(;.*)?$"
)


@dataclass
class VersionBounds:
    """Represents the lower and upper bounds of a version specifier."""

    lower: Version | None = None
    lower_inclusive: bool = True
    upper: Version | None = None
    upper_inclusive: bool = True
    exact: Version | None = None
    has_upper_constraint: bool = False
    exclusions: list[Version] | None = None
    is_wildcard: bool = False

    def __post_init__(self):
        if self.exclusions is None:
            self.exclusions = []

    @property
    def has_max_constraint(self) -> bool:
        """Returns True if there's an upper bound or exact version constraint."""
        return self.upper is not None or self.exact is not None


@dataclass
class ParsedDependency:
    """Represents a parsed dependency from pyproject.toml or requirements.txt."""

    name: str
    specifier: SpecifierSet | None
    extras: str | None = None
    markers: str | None = None
    is_url: bool = False
    raw: str = ""

    @property
    def normalized_name(self) -> str:
        """Return normalized package name (lowercase, hyphens to underscores)."""
        return self.name.lower().replace("-", "_").replace(".", "_")


def parse_pyproject(path: Path | str) -> dict:
    """Parse a pyproject.toml file and return its contents.

    Args:
        path: Path to the pyproject.toml file

    Returns:
        Dictionary containing the parsed TOML data

    Raises:
        FileNotFoundError: If the file doesn't exist
        tomlkit.exceptions.ParseError: If the file is invalid TOML
    """
    path = Path(path)
    with open(path) as f:
        return tomlkit.load(f)


def parse_requirements_txt(path: Path | str) -> list[ParsedDependency]:
    """Parse a requirements.txt file and return list of dependencies.

    Args:
        path: Path to the requirements.txt file

    Returns:
        List of ParsedDependency objects

    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    path = Path(path)
    dependencies = []

    with open(path) as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Skip -r, -e, and other pip options
            if line.startswith("-"):
                continue

            dep = parse_dependency(line)
            if dep:
                dependencies.append(dep)

    return dependencies


def parse_dependency(dep_str: str) -> ParsedDependency | None:
    """Parse a PEP 508 dependency string.

    Args:
        dep_str: Dependency string like "numpy>=1.20,<2.0" or "requests[security]>=2.25"

    Returns:
        ParsedDependency object or None if parsing fails
    """
    dep_str = dep_str.strip()
    if not dep_str:
        return None

    match = PEP_DEPENDENCY_RE.match(dep_str)
    if not match:
        return None

    name, extras, version_spec, url, markers = match.groups()

    # Handle URL dependencies
    if url:
        return ParsedDependency(
            name=name,
            specifier=None,
            extras=extras,
            markers=markers.strip("; ") if markers else None,
            is_url=True,
            raw=dep_str,
        )

    # Parse version specifier
    specifier = None
    if version_spec:
        version_spec = version_spec.strip()
        if version_spec:
            try:
                specifier = SpecifierSet(version_spec)
            except InvalidSpecifier:
                # Try to handle edge cases like "1.0" -> ">=1.0"
                try:
                    Version(version_spec)
                    specifier = SpecifierSet(f">={version_spec}")
                except InvalidVersion:
                    specifier = None

    return ParsedDependency(
        name=name,
        specifier=specifier,
        extras=extras,
        markers=markers.strip("; ") if markers else None,
        is_url=False,
        raw=dep_str,
    )


def extract_version_bounds(specifier: SpecifierSet | None) -> VersionBounds:
    """Extract lower and upper bounds from a specifier set.

    Args:
        specifier: A SpecifierSet object

    Returns:
        VersionBounds with extracted bounds
    """
    bounds = VersionBounds()

    if specifier is None:
        return bounds

    for spec in specifier:
        op = spec.operator
        version_str = spec.version

        # Handle wildcards like ==1.26.*
        if op == "==" and version_str.endswith(".*"):
            bounds.is_wildcard = True
            base_version = version_str[:-2]  # Remove ".*"
            parts = base_version.split(".")

            # Set lower bound
            try:
                bounds.lower = Version(base_version + ".0")
            except InvalidVersion:
                bounds.lower = Version(base_version)
            bounds.lower_inclusive = True

            # Set upper bound (next minor/major version)
            if len(parts) >= 2:
                # e.g., 1.26.* -> upper is 1.27.0
                upper_parts = parts[:-1] + [str(int(parts[-1]) + 1)]
                bounds.upper = Version(".".join(upper_parts) + ".0")
            else:
                # e.g., 1.* -> upper is 2.0
                bounds.upper = Version(str(int(parts[0]) + 1) + ".0")
            bounds.upper_inclusive = False
            bounds.has_upper_constraint = True
            continue

        try:
            version = Version(version_str)
        except InvalidVersion:
            # Skip invalid versions
            continue

        if op == ">=":
            if bounds.lower is None or version > bounds.lower:
                bounds.lower = version
                bounds.lower_inclusive = True
        elif op == ">":
            if bounds.lower is None or version >= bounds.lower:
                bounds.lower = version
                bounds.lower_inclusive = False
        elif op == "<=":
            # Only set upper bound if we don't have one or this is more restrictive
            if bounds.upper is None or version < bounds.upper:
                bounds.upper = version
                bounds.upper_inclusive = True
            bounds.has_upper_constraint = True
        elif op == "<":
            # Only set upper bound if we don't have one or this is more restrictive
            if bounds.upper is None or version < bounds.upper:
                bounds.upper = version
                bounds.upper_inclusive = False
            bounds.has_upper_constraint = True
        elif op == "==":
            bounds.exact = version
        elif op == "!=":
            # Track exclusions for later checking
            bounds.exclusions.append(version)
        elif op == "~=":
            # Compatible release: ~=X.Y means >=X.Y, <(X+1).0 or ~=X.Y.Z means >=X.Y.Z, <X.(Y+1).0
            bounds.lower = version
            bounds.lower_inclusive = True
            bounds.has_upper_constraint = True

            # Compute implicit upper bound
            release = version.release
            if len(release) >= 2:
                # ~=1.26 -> <2.0.0, ~=1.26.1 -> <1.27.0
                if len(release) == 2:
                    # ~=1.26 means >=1.26, <2.0
                    upper_parts = [str(release[0] + 1), "0", "0"]
                else:
                    # ~=1.26.1 means >=1.26.1, <1.27.0
                    upper_parts = [str(release[0]), str(release[1] + 1), "0"]
                bounds.upper = Version(".".join(upper_parts))
                bounds.upper_inclusive = False

    return bounds


def extract_python_version(requires_python: str | None) -> Version | None:
    """Extract the minimum Python version from requires-python.

    Args:
        requires_python: The requires-python string from pyproject.toml

    Returns:
        Minimum Python version or None
    """
    if not requires_python:
        return None

    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return None

    bounds = extract_version_bounds(specifier)
    return bounds.lower


def extract_python_bounds(requires_python: str | None) -> VersionBounds:
    """Extract full version bounds from requires-python.

    Args:
        requires_python: The requires-python string from pyproject.toml

    Returns:
        VersionBounds with lower and upper bounds
    """
    if not requires_python:
        return VersionBounds()

    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return VersionBounds()

    return extract_version_bounds(specifier)


def get_dependencies_from_pyproject(pyproject_data: dict) -> list[ParsedDependency]:
    """Extract all dependencies from a pyproject.toml dict.

    Args:
        pyproject_data: Parsed pyproject.toml data

    Returns:
        List of ParsedDependency objects
    """
    dependencies = []

    project = pyproject_data.get("project", {})

    # Main dependencies
    for dep_str in project.get("dependencies", []):
        dep = parse_dependency(dep_str)
        if dep:
            dependencies.append(dep)

    # Optional dependencies
    for group_deps in project.get("optional-dependencies", {}).values():
        for dep_str in group_deps:
            dep = parse_dependency(dep_str)
            if dep:
                dependencies.append(dep)

    return dependencies
