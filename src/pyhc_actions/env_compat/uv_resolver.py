"""UV-based dependency conflict detection."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.common.parser import parse_pyproject
from pyhc_actions.env_compat.fetcher import (
    load_pyhc_requirements,
    get_package_from_pyproject,
    get_pyhc_python_version,
)


@dataclass
class Conflict:
    """Represents a dependency conflict."""

    package: str
    your_requirement: str
    pyhc_requirement: str
    reason: str


def check_python_compatibility(
    requires_python: str | None,
    pyhc_python: str,
) -> tuple[bool, str | None]:
    """Check if package's requires-python is compatible with PyHC Environment.

    This is an upfront check to catch Python version incompatibilities before
    running uv resolution, providing a clearer error message.

    Args:
        requires_python: The requires-python string from pyproject.toml (e.g., ">=3.11,<3.14")
        pyhc_python: The Python version used by PyHC Environment (e.g., "3.12.9")

    Returns:
        Tuple of (is_compatible, error_message or None)
        If is_compatible is True, error_message is None.
        If is_compatible is False, error_message explains the incompatibility.
    """
    # If no requires-python specified, skip this check
    # Let uv handle any compatibility issues from wheel/sdist metadata
    if not requires_python:
        return True, None

    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        # If we can't parse the specifier, skip this check and let uv handle it
        return True, None

    try:
        pyhc_version = Version(pyhc_python)
    except InvalidVersion:
        # If we can't parse the PyHC version, skip this check
        return True, None

    # Check if PyHC's Python version satisfies the package's requirements
    if pyhc_version in specifier:
        return True, None

    # PyHC's Python version is incompatible
    error_msg = (
        f"Your package requires: Python {requires_python}\n"
        f"PyHC Environment uses: Python {pyhc_python}\n"
        f"Your package cannot be installed in the PyHC Environment."
    )
    return False, error_msg


def find_uv() -> str | None:
    """Find the uv executable.

    Returns:
        Path to uv executable or None if not found
    """
    # Check if uv is in PATH
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    # Check common installation locations
    home = Path.home()
    candidates = [
        home / ".cargo" / "bin" / "uv",
        home / ".local" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def check_compatibility(
    pyproject_path: Path | str,
    pyhc_requirements_source: str | Path | None = None,
    reporter: Reporter | None = None,
) -> tuple[bool, list[Conflict]]:
    """Check if package is compatible with PyHC Environment using uv.

    Args:
        pyproject_path: Path to pyproject.toml
        pyhc_requirements_source: URL or path to PyHC requirements
        reporter: Optional reporter for output

    Returns:
        Tuple of (is_compatible, list of conflicts)
    """
    pyproject_path = Path(pyproject_path)
    reporter = reporter or Reporter(title="PyHC Compatibility Check")

    # Upfront Python version compatibility check
    # This catches Python incompatibilities with a clear error message
    # before running the full uv resolution
    try:
        pyproject_data = parse_pyproject(pyproject_path)
        requires_python = pyproject_data.get("project", {}).get("requires-python")
    except Exception:
        requires_python = None

    pyhc_python = get_pyhc_python_version()
    if pyhc_python and requires_python:
        is_python_compat, python_error = check_python_compatibility(
            requires_python, pyhc_python
        )
        if not is_python_compat:
            reporter.add_error(
                package="python",
                message="Python version incompatible with PyHC Environment",
                details=python_error,
            )
            return False, [
                Conflict(
                    package="python",
                    your_requirement=f"Python {requires_python}",
                    pyhc_requirement=f"Python {pyhc_python}",
                    reason="Python version requirements are incompatible",
                )
            ]

    # Find uv
    uv_path = find_uv()
    if not uv_path:
        reporter.add_error(
            package="uv",
            message="uv not found",
            details="Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
        return False, []

    # Load PyHC requirements
    try:
        pyhc_requirements = load_pyhc_requirements(pyhc_requirements_source)
    except Exception as e:
        reporter.add_error(
            package="pyhc-requirements",
            message=f"Failed to load PyHC requirements: {e}",
        )
        return False, []

    # Get package path for local install
    package_path = get_package_from_pyproject(pyproject_path)

    # Create temporary requirements file combining both
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        # Write PyHC requirements
        for req in pyhc_requirements:
            f.write(f"{req}\n")

        # Add the package being checked
        f.write(f"{package_path}\n")

        temp_requirements = f.name

    try:
        # Run uv pip compile to check if resolution is possible
        result = subprocess.run(
            [
                uv_path,
                "pip",
                "compile",
                temp_requirements,
                "--quiet",
            ],
            capture_output=True,
            text=True,
            cwd=pyproject_path.parent if pyproject_path.exists() else None,
            env={**os.environ, "UV_NO_CACHE": "1"},
        )

        if result.returncode == 0:
            return True, []

        # Check if error is platform-specific (not a real conflict)
        if _is_platform_specific_error(result.stderr):
            reporter.add_warning(
                package="platform",
                message="Platform-specific packages in PyHC Environment",
                details="Some packages (e.g., nvidia-nccl-cu12) are Linux-only.\n"
                "This check may fail locally on macOS/Windows but will pass on GitHub Actions.",
            )
            return True, []  # Not a real conflict

        # Check if error is due to Python version mismatch
        is_python_error, required_version = _is_python_version_error(result.stderr)
        if is_python_error:
            reporter.add_warning(
                package="python",
                message="Python version mismatch with PyHC Environment",
                details=f"The PyHC Environment requires {required_version}.\n"
                "Your current Python version doesn't satisfy this requirement.\n"
                "Run with a compatible Python version to verify package compatibility.",
            )
            return True, []  # Not a package conflict

        # Parse conflicts from error output
        conflicts = parse_uv_error(result.stderr)

        for conflict in conflicts:
            reporter.add_error(
                package=conflict.package,
                message=f"Dependency conflict: {conflict.package}",
                details=f"Your requirement: {conflict.your_requirement}\n"
                f"PyHC Environment: {conflict.pyhc_requirement}\n"
                f"{conflict.reason}",
            )

        return False, conflicts

    finally:
        # Clean up temp file
        Path(temp_requirements).unlink(missing_ok=True)


def _is_platform_specific_error(stderr: str) -> bool:
    """Check if the error is due to platform-specific packages.

    These are not real conflicts - they occur when packages like
    nvidia-nccl-cu12 are only available for Linux.
    """
    platform_indicators = [
        "no wheels with a matching platform tag",
        "no matching distribution",
        "manylinux",
        "macosx",
        "win_amd64",
        "nvidia-nccl",
        "nvidia-cuda",
    ]
    stderr_lower = stderr.lower()
    return any(indicator in stderr_lower for indicator in platform_indicators)


def _is_python_version_error(stderr: str) -> tuple[bool, str | None]:
    """Check if the error is due to Python version mismatch.

    This occurs when the Python version running the check doesn't satisfy
    the requirements of packages in the PyHC Environment. This could be:
    - Running too OLD a Python (package requires >=3.12, you have 3.11)
    - Running too NEW a Python (package requires <3.14, you have 3.14)

    This is not a conflict with the package being tested - it's a limitation
    of the test environment.

    Returns:
        Tuple of (is_python_error, required_version or None)
    """
    # Look for "current Python version (X.Y.Z) does not satisfy Python>=X.Y"
    # or "current Python version (X.Y.Z) does not satisfy Python<X.Y"
    match = re.search(
        r"current python version \([\d.]+\) does not satisfy python([<>=!]+[\d.]+)",
        stderr.lower(),
    )
    if match:
        return True, f"Python{match.group(1)}"

    return False, None


def parse_uv_error(stderr: str) -> list[Conflict]:
    """Parse uv error output to extract conflict information.

    uv outputs messages like:
    "Because project requires numpy<2.0 and pyhc-environment requires numpy>=2.0,
     we can conclude that project and pyhc-environment are incompatible."

    Or:
    "error: No solution found when resolving dependencies:
      ╰─▶ Because package-a==1.0.0 depends on numpy>=2.0 and package-b==1.0.0 depends on numpy<2.0..."

    Args:
        stderr: Standard error output from uv

    Returns:
        List of Conflict objects
    """
    conflicts = []
    seen_packages = set()  # Track packages we've already reported to avoid duplicates

    # Pattern 1: "X requires pkg-spec and Y requires pkg-spec" style
    # This captures: "Because foo requires numpy<2.0 and bar requires numpy>=2.0"
    pattern1 = re.compile(
        r"Because\s+(\S+)\s+requires\s+([a-zA-Z0-9_-]+)([<>=!][^\s,]+)\s+and\s+(\S+)\s+requires\s+([a-zA-Z0-9_-]+)([<>=!][^\s,]+)",
        re.IGNORECASE,
    )

    # Pattern 2: "X depends on pkg-spec and Y depends on pkg-spec" style
    pattern2 = re.compile(
        r"(\S+)\s+depends\s+on\s+([a-zA-Z0-9_-]+)([<>=!][^\s,]+)\s+and\s+(\S+)\s+depends\s+on\s+([a-zA-Z0-9_-]+)([<>=!][^\s,]+)",
        re.IGNORECASE,
    )

    # Try pattern 1
    for match in pattern1.finditer(stderr):
        source1, pkg1, spec1, source2, pkg2, spec2 = match.groups()

        # Only report if it's the same package with different specs
        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            # Check specs are actually different (not identical)
            if spec1 != spec2:
                seen_packages.add(pkg1.lower())
                conflicts.append(
                    Conflict(
                        package=pkg1,
                        your_requirement=f"{pkg1}{spec1}",
                        pyhc_requirement=f"{pkg2}{spec2}",
                        reason=f"Incompatible requirements from {source1} and {source2}",
                    )
                )

    # Try pattern 2
    for match in pattern2.finditer(stderr):
        source1, pkg1, spec1, source2, pkg2, spec2 = match.groups()

        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            if spec1 != spec2:
                seen_packages.add(pkg1.lower())
                conflicts.append(
                    Conflict(
                        package=pkg1,
                        your_requirement=f"{pkg1}{spec1}",
                        pyhc_requirement=f"{pkg2}{spec2}",
                        reason=f"Incompatible requirements from {source1} and {source2}",
                    )
                )

    # Pattern 3: Look for explicit "X and Y are incompatible" with package names
    pattern3 = re.compile(
        r"([a-zA-Z0-9_-]+)([<>=!]+[0-9][0-9.]*)\s+.*?\s+([a-zA-Z0-9_-]+)([<>=!]+[0-9][0-9.]*)\s+are\s+incompatible",
        re.IGNORECASE,
    )

    for match in pattern3.finditer(stderr):
        pkg1, spec1, pkg2, spec2 = match.groups()
        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            if spec1 != spec2:
                seen_packages.add(pkg1.lower())
                conflicts.append(
                    Conflict(
                        package=pkg1,
                        your_requirement=f"{pkg1}{spec1}",
                        pyhc_requirement=f"{pkg2}{spec2}",
                        reason="Version requirements are incompatible",
                    )
                )

    # If still no conflicts found, create a generic one from the error message
    if not conflicts and "No solution found" in stderr:
        conflicts.append(
            Conflict(
                package="dependencies",
                your_requirement="(see error details)",
                pyhc_requirement="PyHC Environment",
                reason=_extract_error_summary(stderr),
            )
        )

    return conflicts


def _extract_error_summary(stderr: str) -> str:
    """Extract a summary from uv error output."""
    # Get first few lines of error
    lines = stderr.strip().split("\n")
    summary_lines = []

    for line in lines[:5]:
        line = line.strip()
        if line and not line.startswith("hint:"):
            summary_lines.append(line)

    return " ".join(summary_lines)


def run_uv_lock_check(
    pyproject_path: Path | str,
    pyhc_requirements: list[str],
    reporter: Reporter | None = None,
) -> tuple[bool, str]:
    """Alternative check using uv lock with a temporary project.

    Creates a temporary pyproject.toml that depends on both the package
    and all PyHC packages, then runs uv lock.

    Args:
        pyproject_path: Path to the package's pyproject.toml
        pyhc_requirements: List of PyHC requirements
        reporter: Optional reporter

    Returns:
        Tuple of (success, error_message)
    """
    uv_path = find_uv()
    if not uv_path:
        return False, "uv not found"

    pyproject_path = Path(pyproject_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create temporary pyproject.toml
        temp_pyproject = {
            "project": {
                "name": "pyhc-compat-check",
                "version": "0.0.0",
                "requires-python": ">=3.11",
                "dependencies": [
                    str(pyproject_path.parent.resolve()),  # The package being checked
                    *pyhc_requirements,  # All PyHC packages
                ],
            }
        }

        import tomlkit
        pyproject_file = tmpdir / "pyproject.toml"
        with open(pyproject_file, "w") as f:
            tomlkit.dump(temp_pyproject, f)

        # Run uv lock
        result = subprocess.run(
            [uv_path, "lock"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        if result.returncode == 0:
            return True, ""

        return False, result.stderr
