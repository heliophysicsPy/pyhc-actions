"""UV-based dependency conflict detection."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.utils import canonicalize_name
from packaging.version import Version, InvalidVersion

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.common.parser import parse_pyproject
from pyhc_actions.env_compat.fetcher import (
    load_pyhc_packages,
    load_pyhc_constraints,
    get_package_from_pyproject,
    get_pyhc_python_version,
)


def _normalize_spec(spec: str) -> str:
    """Normalize version specifier by trimming whitespace and trailing punctuation."""
    spec = spec.strip()
    return spec.rstrip(".,;")


def _canonicalize_package_name(name: str | None) -> str | None:
    """Canonicalize a package name for robust comparisons.

    Uses PEP 503 normalization semantics via packaging utilities.
    """
    if not name:
        return None
    return canonicalize_name(name)


def _extract_canonical_name_from_spec(spec: str) -> str | None:
    """Extract canonical package name from a requirement-like spec string.

    Handles extras (e.g., ``pyhc-core[tests]==0.0.7``), direct references,
    and versioned/unversioned requirements.
    """
    try:
        return canonicalize_name(Requirement(spec).name)
    except InvalidRequirement:
        # Fallback for non-standard lines: strip known operators and extras.
        base = (
            spec.split("==")[0]
            .split(">=")[0]
            .split("<=")[0]
            .split("!=")[0]
            .split("~=")[0]
            .split(">")[0]
            .split("<")[0]
            .split("[")[0]
            .split("@")[0]
            .strip()
        )
        return canonicalize_name(base) if base else None


def _python_version_for_uv(pyhc_python: str | None) -> str | None:
    """Convert Python version to uv-compatible major.minor form."""
    if not pyhc_python:
        return None
    try:
        parsed = Version(pyhc_python)
    except InvalidVersion:
        return None
    return f"{parsed.major}.{parsed.minor}"


def parse_resolved_versions(uv_output: str) -> dict[str, str]:
    """Parse resolved package versions from uv pip compile output.

    Args:
        uv_output: The stdout from 'uv pip compile' command

    Returns:
        Dict mapping package name to resolved version/range
    """
    resolved = {}
    for line in uv_output.split('\n'):
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            continue
        # Parse package specs:
        # - Version specs: "numpy==2.1.3" or "scipy>=1.13.0,<2.0"
        # - Editable/local installs: "pyspedas @ file:///path/to/package"
        # - Git installs: "package @ git+https://..."
        # Package names can contain letters, numbers, hyphens, underscores, and dots
        match = re.match(r'^([a-zA-Z0-9_.-]+)\s*(@\s+.+|[<>=!~].*)$', line)
        if match:
            pkg_name, spec = match.groups()
            # Add space before @ for proper formatting
            if spec.startswith('@'):
                resolved[pkg_name] = f"{pkg_name} {spec}"
            else:
                resolved[pkg_name] = f"{pkg_name}{spec}"
    return resolved


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
    pyhc_packages_source: str | Path | None = None,
    pyhc_packages: list[str] | None = None,
    pyhc_constraints_source: str | Path | None = None,
    pyhc_constraints: list[str] | None = None,
    pyhc_python: str | None = None,
    extra: str | None = None,
    context: str = "",
    report_as_warning: bool = False,
    reporter: Reporter | None = None,
) -> tuple[bool, list[Conflict]]:
    """Check if package is compatible with PyHC Environment using uv.

    Args:
        pyproject_path: Path to pyproject.toml
        pyhc_packages_source: URL or path to PyHC packages
        pyhc_packages: Pre-loaded PyHC packages list (skips fetching)
        pyhc_constraints_source: URL or path to PyHC constraints
        pyhc_constraints: Pre-loaded PyHC constraints list (skips fetching)
        pyhc_python: Pre-loaded PyHC Python version (skips fetching)
        extra: Optional extra group to install (e.g., "image")
        context: Optional context label for reporting (e.g., "base", "image")
        report_as_warning: Report errors as warnings (used for extras checks)
        reporter: Optional reporter for output

    Returns:
        Tuple of (is_compatible, list of conflicts)
    """
    pyproject_path = Path(pyproject_path)
    reporter = reporter or Reporter(title="PyHC Compatibility Check")
    context = context or ("base" if extra is None else extra)

    def _report_error(
        package: str,
        message: str,
        details: str = "",
        suggestion: str = "",
    ) -> None:
        if report_as_warning:
            reporter.add_warning(
                package=package,
                message=message,
                details=details,
                suggestion=suggestion,
                context=context,
            )
        else:
            reporter.add_error(
                package=package,
                message=message,
                details=details,
                suggestion=suggestion,
                context=context,
            )

    # Upfront Python version compatibility check
    # This catches Python incompatibilities with a clear error message
    # before running the full uv resolution
    try:
        pyproject_data = parse_pyproject(pyproject_path)
        requires_python = pyproject_data.get("project", {}).get("requires-python")
    except Exception:
        requires_python = None

    if pyhc_python is None:
        pyhc_python = get_pyhc_python_version()
    if pyhc_python and requires_python:
        is_python_compat, python_error = check_python_compatibility(
            requires_python, pyhc_python
        )
        if not is_python_compat:
            _report_error(
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
        _report_error(
            package="uv",
            message="uv not found",
            details="Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
        return False, []

    # Load PyHC packages
    if pyhc_packages is None:
        try:
            pyhc_packages = load_pyhc_packages(pyhc_packages_source)
        except Exception as e:
            _report_error(
                package="pyhc-packages",
                message=f"Failed to load PyHC packages: {e}",
            )
            return False, []

    # Load PyHC constraints
    if pyhc_constraints is None:
        try:
            pyhc_constraints = load_pyhc_constraints(pyhc_constraints_source)
        except Exception as e:
            _report_error(
                package="pyhc-constraints",
                message=f"Failed to load PyHC constraints: {e}",
            )
            return False, []

    # Get package path for local install
    package_path = get_package_from_pyproject(pyproject_path)

    # Get package name to filter from PyHC packages
    # (avoid conflict with package checking itself)
    package_name = None
    try:
        from pyhc_actions.common.parser import parse_pyproject
        pyproject_data = parse_pyproject(pyproject_path)
        package_name = pyproject_data.get("project", {}).get("name")
    except Exception:
        pass

    # For setup.py packages, try extracting name using uv
    if not package_name:
        try:
            from pyhc_actions.phep3.metadata_extractor import extract_metadata_with_uv
            project_dir = pyproject_path if pyproject_path.is_dir() else pyproject_path.parent
            metadata = extract_metadata_with_uv(project_dir)
            if metadata:
                package_name = metadata.name
        except Exception:
            pass
    package_name_canonical = _canonicalize_package_name(package_name)

    temp_constraints: str | None = None

    # Create temporary package list file combining both
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        # Write PyHC packages, excluding the package being checked
        for req in pyhc_packages:
            # Parse requirement to extract canonical package name.
            req_package_name = _extract_canonical_name_from_spec(req)

            # Skip if this is the package being checked
            if (
                package_name_canonical
                and req_package_name
                and req_package_name == package_name_canonical
            ):
                continue

            f.write(f"{req}\n")

        # Add the package being checked (use -e for local editable install)
        editable_spec = f"-e {package_path}"
        if extra:
            editable_spec = f"-e {package_path}[{extra}]"
        f.write(f"{editable_spec}\n")

        temp_packages = f.name

    if pyhc_constraints:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for constraint in pyhc_constraints:
                f.write(f"{constraint}\n")
            temp_constraints = f.name

    try:
        # Run uv pip compile to check if resolution is possible.
        command = [
            uv_path,
            "pip",
            "compile",
            "--no-config",
        ]
        uv_python_version = _python_version_for_uv(pyhc_python)
        if uv_python_version:
            command.extend(["--python-version", uv_python_version])
        command.append(temp_packages)
        if temp_constraints:
            command.extend(["-c", temp_constraints])

        # We used to force UV_NO_CACHE=1 here for fully cold resolves, but removed that
        # override to improve env-compat performance across repeated extras checks.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            # Handle both directory paths (setup.py) and file paths (pyproject.toml)
            cwd=pyproject_path if pyproject_path.is_dir() else pyproject_path.parent,
        )

        if result.returncode == 0:
            # Parse and display resolved package versions
            resolved = parse_resolved_versions(result.stdout)

            # Add the package being checked (uv doesn't output editable installs)
            if package_name:
                resolved[_canonicalize_package_name(package_name) or package_name.lower()] = (
                    f"{package_name} @ {package_path}"
                )

            if resolved:
                reporter.print(f"\n\nResolved Package Versions [{context}]:")
                reporter.print("-" * 40)
                for package in sorted(resolved.keys()):
                    reporter.print(f"  {resolved[package]}")
                reporter.print()

            return True, []

        # Check if error is platform-specific (not a real conflict)
        if _is_platform_specific_error(result.stderr):
            reporter.add_warning(
                package="platform",
                message="Platform-specific packages in PyHC Environment",
                details="Some packages (e.g., nvidia-nccl-cu12) are Linux-only.\n"
                "This check may fail locally on macOS/Windows but will pass on GitHub Actions.",
                context=context,
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
                context=context,
            )
            return True, []  # Not a package conflict

        # Check if error is due to package resolution issues (not on PyPI, no wheels, build issues)
        # Extract package name from pyproject.toml
        try:
            from pyhc_actions.common.parser import parse_pyproject
            pyproject_data = parse_pyproject(pyproject_path)
            package_name = pyproject_data.get("project", {}).get("name")
        except Exception:
            package_name = None

        if _is_unpublished_package_error(result.stderr, package_name):
            _report_error(
                package=package_name or "package",
                message="Unable to resolve package version",
                details=f"uv couldn't resolve the package. Possible causes:\n"
                "- Package not published to PyPI\n"
                "- No compatible wheels for this platform (may require compilation)\n"
                "- Build dependencies not available\n"
                "- Python version incompatibility\n\n"
                "This check works best on Linux with published packages that have wheels.\n"
                "Consider testing locally or on GitHub Actions (Linux) for accurate results.",
            )
            return False, [
                Conflict(
                    package=package_name or "package",
                    your_requirement="(unable to resolve)",
                    pyhc_requirement="PyHC Environment",
                    reason="Package resolution failed - see details above",
                )
            ]

        # Parse conflicts from error output
        conflicts = parse_uv_error(result.stderr, package_name)

        for conflict in conflicts:
            # Generate suggestion based on PyHC requirement
            suggestion = f"Support {conflict.pyhc_requirement}"
            if report_as_warning and context and context != "base":
                suggestion = f"{suggestion} in [{context}]"
            _report_error(
                package=conflict.package,
                message=f"Dependency conflict: {conflict.package}",
                details=f"Your requirement: {conflict.your_requirement}\n"
                f"PyHC Environment: {conflict.pyhc_requirement}\n"
                f"{conflict.reason}",
                suggestion=suggestion,
            )

        # If no conflicts were identified but uv failed, treat as compatible
        # This can happen when uv fails for reasons unrelated to package conflicts
        # (e.g., network issues, malformed requirements)
        if not conflicts:
            # uv failed but we couldn't parse conflicts; fail loudly to avoid false positives.
            stderr_text = result.stderr.strip() or "(uv stderr was empty)"
            stdout_text = result.stdout.strip() or "(uv stdout was empty)"
            _report_error(
                package="uv",
                message="uv resolution failed with no parsed conflicts",
                details=(
                    f"Exit code: {result.returncode}\n"
                    "STDERR:\n"
                    f"{stderr_text}\n"
                    "STDOUT:\n"
                    f"{stdout_text}"
                ),
            )
            return False, []

        return False, conflicts

    finally:
        # Clean up temp files
        Path(temp_packages).unlink(missing_ok=True)
        if temp_constraints:
            Path(temp_constraints).unlink(missing_ok=True)


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


def parse_uv_error(stderr: str, package_name: str | None = None) -> list[Conflict]:
    """Parse uv error output to extract conflict information.

    uv outputs messages in various formats:

    1. "Because project requires numpy<2.0 and pyhc-environment requires numpy>=2.0,
        we can conclude that project and pyhc-environment are incompatible."

    2. "Because package-a==1.0.0 depends on numpy>=2.0 and package-b==1.0.0
        depends on numpy<2.0..."

    3. "Because pyhc-core==0.0.7 depends on numpy<2 and you require numpy>=2.0,<2.3.0,
        we can conclude that your requirements and pyhc-core[tests]==0.0.7 are
        incompatible."

    Args:
        stderr: Standard error output from uv

    Returns:
        List of Conflict objects
    """
    conflicts = []
    seen_packages = set()  # Track packages we've already reported to avoid duplicates

    def _strip_extras(spec: str) -> str:
        """Normalize specifier by removing leading extras (e.g., [image])."""
        spec = _normalize_spec(spec)
        if spec.startswith("["):
            end = spec.find("]")
            if end != -1:
                return spec[end + 1 :]
        return spec

    def add_conflict(pkg1: str, spec1: str, pkg2: str, spec2: str, source1: str, source2: str) -> bool:
        """Add conflict if packages match and specs differ. Returns True if added."""
        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            spec1_clean = _normalize_spec(spec1)
            spec2_clean = _normalize_spec(spec2)
            spec1_norm = _strip_extras(spec1_clean)
            spec2_norm = _strip_extras(spec2_clean)
            if spec1_norm != spec2_norm:
                seen_packages.add(pkg1.lower())
                # Determine which is "your" (package's) requirement vs PyHC Environment
                # When uv says "X depends on" and "you require", the "you" refers to
                # the combined requirements (which includes PyHC). So:
                # - "depends on" side = user's package requirement
                # - "you require" side = PyHC Environment requirement
                if "you" in source2.lower():
                    # Pattern: "X depends on pkg<spec and you require pkg>=spec"
                    your_req, pyhc_req = f"{pkg1}{spec1_clean}", f"{pkg2}{spec2_clean}"
                elif "you" in source1.lower():
                    # Pattern: "you require pkg<spec and X depends on pkg>=spec"
                    your_req, pyhc_req = f"{pkg2}{spec2_clean}", f"{pkg1}{spec1_clean}"
                else:
                    # Default: first is user's, second is environment's
                    your_req, pyhc_req = f"{pkg1}{spec1_clean}", f"{pkg2}{spec2_clean}"
                conflicts.append(
                    Conflict(
                        package=pkg1,
                        your_requirement=your_req,
                        pyhc_requirement=pyhc_req,
                        reason=f"Incompatible version requirements",
                    )
                )
                return True
        return False

    # Package + version patterns
    # Package names can include hyphens/underscores; extras like [image] are supported.
    PKG_NAME = r"[a-zA-Z0-9_-]+"
    EXTRAS = r"(?:\[[^\]]+\])?"
    # Version spec pattern: handles <, >, =, !, ~ (for ~= compatible release)
    # Examples: >=1.0, <2.0, ==1.5, !=1.3, ~=1.20, >=1.0,<2.0
    # Capture comma-separated constraints but avoid trailing commas.
    VERSION_SPEC = r"[<>=!~]=?[^\\s,]+(?:,[<>=!~][^\\s,]+)*"

    # Pattern 1: "Because X requires pkg-spec and Y requires pkg-spec" style
    pattern1 = re.compile(
        rf"Because\s+(\S+)\s+requires\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s+and\s+(\S+)\s+requires\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s",
        re.IGNORECASE,
    )

    # Pattern 2: "X depends on pkg-spec and Y depends on pkg-spec" style
    pattern2 = re.compile(
        rf"(\S+)\s+depends\s+on\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s+and\s+(\S+)\s+depends\s+on\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s",
        re.IGNORECASE,
    )

    # Pattern 3: "X depends on pkg-spec and you require pkg-spec" style
    # This is the actual format uv uses when checking a local package against requirements
    pattern3 = re.compile(
        rf"(\S+)\s+depends\s+on\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s+and\s+(you)\s+require\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s",
        re.IGNORECASE,
    )

    # Pattern 4: Reverse of pattern 3 - "you require pkg-spec and X depends on pkg-spec"
    pattern4 = re.compile(
        rf"(you)\s+require\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s+and\s+(\S+)\s+depends\s+on\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC}),?\s",
        re.IGNORECASE,
    )

    # Try all patterns
    for pattern in [pattern1, pattern2, pattern3, pattern4]:
        for match in pattern.finditer(stderr):
            source1, pkg1, spec1, source2, pkg2, spec2 = match.groups()
            add_conflict(pkg1, spec1, pkg2, spec2, source1, source2)

    # Pattern 5: "only X<Y is available and Z depends on X[extra]>=Y"
    pattern_available_depends = re.compile(
        rf"only\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})\s+is\s+available\s+and\s+(\S+)\s+depends\s+on\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})",
        re.IGNORECASE,
    )
    for match in pattern_available_depends.finditer(stderr):
        avail_pkg, avail_spec, source, req_pkg, req_spec = match.groups()
        # If the "available" package is the one being checked locally, treat it as "your requirement"
        if package_name and avail_pkg.lower() == package_name.lower():
            add_conflict(avail_pkg, avail_spec, req_pkg, req_spec, "available", source)
        else:
            # Default: dependency requirement is treated as "your requirement"
            add_conflict(req_pkg, req_spec, avail_pkg, avail_spec, source, "available")

    # Pattern 6: "only X<Y is available and you require X>=Y"
    pattern_available_you = re.compile(
        rf"only\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})\s+is\s+available\s+and\s+(you)\s+require\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})",
        re.IGNORECASE,
    )
    for match in pattern_available_you.finditer(stderr):
        avail_pkg, avail_spec, you_token, req_pkg, req_spec = match.groups()
        # Ensure the "you" token is used to map your requirement to req_spec
        add_conflict(req_pkg, req_spec, avail_pkg, avail_spec, "available", you_token)

    # Pattern 7: "there is no version of X==Y and you require X==Y"
    pattern_no_version = re.compile(
        rf"no\s+version\s+of\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})\s+and\s+you\s+require\s+({PKG_NAME})({EXTRAS}{VERSION_SPEC})",
        re.IGNORECASE,
    )
    for match in pattern_no_version.finditer(stderr):
        pkg1, spec1, pkg2, spec2 = match.groups()
        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            seen_packages.add(pkg1.lower())
            conflicts.append(
                Conflict(
                    package=pkg1,
                    your_requirement="(not specified)",
                    pyhc_requirement=f"{pkg1}{spec1}",
                    reason="No matching distribution found",
                )
            )

    # Pattern 8: Look for explicit "X and Y are incompatible" with package names
    pattern5 = re.compile(
        rf"({PKG_NAME})({EXTRAS}[<>=!~]+[0-9][0-9.]*)\s+.*?\s+({PKG_NAME})({EXTRAS}[<>=!~]+[0-9][0-9.]*)\s+are\s+incompatible",
        re.IGNORECASE,
    )

    for match in pattern5.finditer(stderr):
        pkg1, spec1, pkg2, spec2 = match.groups()
        if pkg1.lower() == pkg2.lower() and pkg1.lower() not in seen_packages:
            spec1_clean = _normalize_spec(spec1)
            spec2_clean = _normalize_spec(spec2)
            if _strip_extras(spec1_clean) != _strip_extras(spec2_clean):
                seen_packages.add(pkg1.lower())
                conflicts.append(
                    Conflict(
                        package=pkg1,
                        your_requirement=f"{pkg1}{spec1_clean}",
                        pyhc_requirement=f"{pkg2}{spec2_clean}",
                        reason="Version requirements are incompatible",
                    )
                )

    # If still no conflicts found, try to extract package info from the error
    if not conflicts and "No solution found" in stderr:
        # Try to find any package with conflicting versions mentioned
        conflict = _extract_conflict_from_error(stderr)
        if conflict:
            conflicts.append(conflict)
        else:
            # Last resort: generic error with full details
            conflicts.append(
                Conflict(
                    package="dependencies",
                    your_requirement="(see details below)",
                    pyhc_requirement="PyHC Environment",
                    reason=_extract_error_summary(stderr),
                )
            )

    return conflicts


def discover_optional_extras(pyproject_path: Path | str) -> list[str]:
    """Discover optional dependency groups from a project.

    Attempts to read [project.optional-dependencies] from pyproject.toml.
    Falls back to uv-based metadata extraction for legacy formats.
    """
    pyproject_path = Path(pyproject_path)
    pyproject_file = pyproject_path
    if pyproject_path.is_dir():
        pyproject_file = pyproject_path / "pyproject.toml"

    if pyproject_file.exists():
        try:
            pyproject_data = parse_pyproject(pyproject_file)
            project = pyproject_data.get("project", {})
            optional_deps = project.get("optional-dependencies", {})
            if isinstance(optional_deps, dict):
                return sorted(optional_deps.keys())
        except Exception:
            pass

    # Fallback to uv-based metadata extraction (setup.py / Poetry)
    try:
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_with_uv

        project_dir = pyproject_path if pyproject_path.is_dir() else pyproject_path.parent
        metadata = extract_metadata_with_uv(project_dir)
        if metadata and metadata.optional_dependencies:
            return sorted(metadata.optional_dependencies.keys())
    except Exception:
        pass

    return []


def _extract_conflict_from_error(stderr: str) -> Conflict | None:
    """Try to extract conflict info from error message when patterns don't match.

    This is a fallback that looks for package names and version specs mentioned
    in the error, even if they don't match our expected patterns.
    """
    # Look for patterns like "depends on numpy<2" or "requires numpy>=2.0"
    # Note: [<>=!~]+ handles multi-char operators like >=, <=, !=, ==, ~=
    pkg_version_pattern = re.compile(
        r"(?:depends\s+on|requires?)\s+([a-zA-Z0-9_-]+)(\[[^\]]+\])?([<>=!~]+[0-9][^\s,]*)",
        re.IGNORECASE,
    )

    def _strip_extras_from_spec(spec: str) -> str:
        spec = _normalize_spec(spec)
        if spec.startswith("["):
            end = spec.find("]")
            if end != -1:
                return spec[end + 1 :]
        return spec

    matches = pkg_version_pattern.findall(stderr)
    if len(matches) >= 2:
        # Group by package name
        by_package: dict[str, list[str]] = {}
        by_package_norm: dict[str, set[str]] = {}
        for pkg, extras, spec in matches:
            extras = extras or ""
            spec = _normalize_spec(spec)
            full_spec = f"{pkg}{extras}{spec}"
            pkg_lower = pkg.lower()
            if pkg_lower not in by_package:
                by_package[pkg_lower] = []
                by_package_norm[pkg_lower] = set()
            if full_spec not in by_package[pkg_lower]:
                by_package[pkg_lower].append(full_spec)
            by_package_norm[pkg_lower].add(_strip_extras_from_spec(f"{extras}{spec}"))

        # Find a package with multiple different specs (conflict)
        for pkg_lower, specs in by_package.items():
            if len(by_package_norm.get(pkg_lower, set())) >= 2:
                # Extract package name from the first spec (e.g., "requests" from "requests<2.0")
                pkg_name = re.split(r"[<>=!]", specs[0])[0]
                return Conflict(
                    package=pkg_name,
                    your_requirement=specs[0],
                    pyhc_requirement=specs[1],
                    reason="Conflicting version requirements detected",
                )

    return None


def _is_unpublished_package_error(stderr: str, package_name: str | None = None) -> bool:
    """Check if error is due to package not being published on PyPI.

    Args:
        stderr: Error output from uv
        package_name: Optional package name to check for

    Returns:
        True if this looks like an unpublished package error
    """
    indicators = [
        "no version of",
        "because there is no version of",
        "could not find a version that satisfies",
    ]

    stderr_lower = stderr.lower()

    # Check if any indicator matches
    for indicator in indicators:
        if indicator in stderr_lower:
            # If package name provided, verify it's about that package
            if package_name:
                pattern = f"{indicator}\\s+{re.escape(package_name.lower())}"
                if re.search(pattern, stderr_lower):
                    return True
            else:
                return True

    return False


def _extract_error_summary(stderr: str) -> str:
    """Extract the main error content from uv output.

    Returns the error message without hints, formatted for display.
    """
    lines = stderr.strip().split("\n")
    summary_lines = []

    for line in lines:
        line = line.strip()
        # Skip empty lines and hints
        if not line or line.lower().startswith("hint:"):
            continue
        # Clean up uv's tree characters
        line = line.replace("╰─▶", "→").replace("│", " ").replace("├", " ")
        summary_lines.append(line)

    # Return full error, not truncated
    return "\n".join(summary_lines)


def run_uv_lock_check(
    pyproject_path: Path | str,
    pyhc_packages: list[str],
    reporter: Reporter | None = None,
) -> tuple[bool, str]:
    """Alternative check using uv lock with a temporary project.

    This helper is currently unused in the primary env-compat flow.

    Creates a temporary pyproject.toml that depends on both the package
    and all PyHC packages, then runs uv lock.

    Args:
        pyproject_path: Path to the package's pyproject.toml
        pyhc_packages: List of PyHC package specs
        reporter: Optional reporter

    Returns:
        Tuple of (success, error_message)
    """
    uv_path = find_uv()
    if not uv_path:
        return False, "uv not found"

    pyproject_path = Path(pyproject_path)
    package_path = get_package_from_pyproject(pyproject_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create temporary pyproject.toml
        temp_pyproject = {
            "project": {
                "name": "pyhc-compat-check",
                "version": "0.0.0",
                "requires-python": ">=3.11",
                "dependencies": [
                    package_path,  # The package being checked
                    *pyhc_packages,  # All PyHC packages
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
