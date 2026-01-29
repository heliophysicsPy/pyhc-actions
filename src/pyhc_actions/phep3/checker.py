"""PHEP 3 compliance checking logic."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from packaging.version import Version

from pyhc_actions.common.parser import (
    ParsedDependency,
    extract_version_bounds,
    extract_python_version,
    get_dependencies_from_pyproject,
    parse_pyproject,
)
from pyhc_actions.common.reporter import Reporter
from pyhc_actions.phep3.config import (
    CORE_PACKAGES,
    PACKAGE_SUPPORT_MONTHS,
    PYTHON_SUPPORT_MONTHS,
    is_core_package,
    normalize_package_name,
)
from pyhc_actions.phep3.schedule import Schedule


def check_compliance(
    pyproject_path: Path | str,
    schedule: Schedule,
    reporter: Reporter,
    check_adoption: bool = True,
    now: datetime | None = None,
) -> bool:
    """Check pyproject.toml compliance with PHEP 3.

    Args:
        pyproject_path: Path to pyproject.toml
        schedule: Schedule with version release dates
        reporter: Reporter for output
        check_adoption: Whether to check 6-month adoption rule
        now: Current time (for testing)

    Returns:
        True if compliant (no errors), False otherwise
    """
    now = now or datetime.now(timezone.utc)
    pyproject_path = Path(pyproject_path)

    reporter.set_file_path(str(pyproject_path))

    try:
        pyproject_data = parse_pyproject(pyproject_path)
    except FileNotFoundError:
        reporter.add_error(
            package="pyproject.toml",
            message=f"File not found: {pyproject_path}",
        )
        return False
    except Exception as e:
        reporter.add_error(
            package="pyproject.toml",
            message=f"Failed to parse pyproject.toml: {e}",
        )
        return False

    project = pyproject_data.get("project", {})

    # Check Python version requirement
    requires_python = project.get("requires-python")
    _check_python_version(requires_python, schedule, reporter, now)

    # Check dependencies
    dependencies = get_dependencies_from_pyproject(pyproject_data)
    for dep in dependencies:
        _check_dependency(dep, schedule, reporter, check_adoption, now)

    return not reporter.has_errors


def _check_python_version(
    requires_python: str | None,
    schedule: Schedule,
    reporter: Reporter,
    now: datetime,
):
    """Check Python version requirement compliance."""
    if not requires_python:
        reporter.add_warning(
            package="python",
            message="No requires-python specified",
            details="Consider adding requires-python to specify supported Python versions",
        )
        return

    min_version = extract_python_version(requires_python)
    if not min_version:
        reporter.add_warning(
            package="python",
            message=f"Could not parse requires-python: {requires_python}",
        )
        return

    # Get the version string (e.g., "3.9" from Version("3.9.0"))
    version_str = f"{min_version.major}.{min_version.minor}"

    # Check if this Python version is in the schedule
    version_info = schedule.python.get(version_str)
    if not version_info:
        # Check if it's an older version not in schedule (likely too old)
        recommended = schedule.get_minimum_python_version(now)
        if recommended:
            # Compare versions
            rec_parts = [int(p) for p in recommended.split(".")]
            min_parts = [min_version.major, min_version.minor]
            if min_parts < rec_parts:
                # This is a WARNING, not an error - packages CAN drop old versions but don't have to
                reporter.add_warning(
                    package="python",
                    message=f"Python {version_str} support can be dropped per PHEP 3",
                    details=f"Python {version_str} is older than the minimum required version",
                    suggestion=f"Consider updating to >={recommended}",
                )
        return

    # Check if version can be dropped - this is informational (WARNING), not an error
    # PHEP 3 says packages CAN drop support after the window, not that they MUST
    if version_info.is_droppable(now):
        months = version_info.months_since_release(now)
        recommended = schedule.get_minimum_python_version(now)

        reporter.add_warning(
            package="python",
            message=f"Python {version_str} support can be dropped per PHEP 3",
            details=f"Python {version_str} released {months} months ago (>{PYTHON_SUPPORT_MONTHS} months)",
            suggestion=f"Consider updating to >={recommended}" if recommended else None,
        )


def _check_dependency(
    dep: ParsedDependency,
    schedule: Schedule,
    reporter: Reporter,
    check_adoption: bool,
    now: datetime,
):
    """Check a single dependency for PHEP 3 compliance."""
    # Only check core packages
    if not is_core_package(dep.name):
        return

    # URL dependencies can't be checked
    if dep.is_url:
        return

    # Get the normalized package name for schedule lookup
    pkg_name = _get_schedule_package_name(dep.name, schedule)
    if not pkg_name:
        # Package not in schedule - can't check
        return

    bounds = extract_version_bounds(dep.specifier)

    # Check for upper bound / exact constraints (warning)
    if bounds.has_max_constraint:
        if bounds.exact:
            reporter.add_warning(
                package=dep.name,
                message=f"{dep.raw} has exact version constraint",
                details="Exact constraints should only be used when absolutely necessary",
                suggestion=f"Remove exact constraint and use >= instead",
            )
        elif bounds.upper:
            reporter.add_warning(
                package=dep.name,
                message=f"{dep.raw} has upper bound constraint",
                details="Upper bounds should only be used when absolutely necessary",
                suggestion=f"Consider removing <{bounds.upper} unless required",
            )

    # Check lower bound
    if bounds.lower:
        _check_lower_bound(dep, pkg_name, bounds.lower, schedule, reporter, now)

    # Check adoption of new versions
    if check_adoption:
        _check_adoption(dep, pkg_name, schedule, reporter, now)


def _get_schedule_package_name(name: str, schedule: Schedule) -> str | None:
    """Find the package name as it appears in the schedule."""
    normalized = normalize_package_name(name)

    for pkg_name in schedule.packages:
        if normalize_package_name(pkg_name) == normalized:
            return pkg_name

    return None


def _check_lower_bound(
    dep: ParsedDependency,
    pkg_name: str,
    lower_bound: Version,
    schedule: Schedule,
    reporter: Reporter,
    now: datetime,
):
    """Check if the lower bound is too old."""
    pkg_versions = schedule.packages.get(pkg_name, {})
    if not pkg_versions:
        return

    # Get version string (e.g., "1.26" from Version("1.26.0"))
    version_str = f"{lower_bound.major}.{lower_bound.minor}"

    version_info = pkg_versions.get(version_str)
    if not version_info:
        # Lower bound might be older than anything in schedule - check
        min_supported = schedule.get_minimum_package_version(pkg_name, now)
        if min_supported:
            min_ver = Version(min_supported)
            if lower_bound < min_ver:
                # This is a WARNING - packages CAN drop old versions but don't have to
                reporter.add_warning(
                    package=dep.name,
                    message=f"{dep.name} {version_str} support can be dropped per PHEP 3",
                    details=f"Version {version_str} is older than the minimum required version",
                    suggestion=f"Consider updating to {dep.name}>={min_supported}",
                )
        return

    # Check if this version can be dropped - this is informational (WARNING), not an error
    # PHEP 3 says packages CAN drop support after the window, not that they MUST
    if version_info.is_droppable(now):
        months = version_info.months_since_release(now)
        min_supported = schedule.get_minimum_package_version(pkg_name, now)

        reporter.add_warning(
            package=dep.name,
            message=f"{dep.name} {version_str} support can be dropped per PHEP 3",
            details=f"Version {version_str} released {months} months ago (>{PACKAGE_SUPPORT_MONTHS} months)",
            suggestion=f"Consider updating to {dep.name}>={min_supported}" if min_supported else None,
        )


def _check_adoption(
    dep: ParsedDependency,
    pkg_name: str,
    schedule: Schedule,
    reporter: Reporter,
    now: datetime,
):
    """Check if new versions are being adopted within 6 months."""
    pkg_versions = schedule.packages.get(pkg_name, {})
    if not pkg_versions:
        return

    # Find versions that must be supported but might not be
    bounds = extract_version_bounds(dep.specifier)

    for version_str, version_info in pkg_versions.items():
        # Check if this version must be supported now
        if not version_info.must_be_supported(now):
            continue

        version = Version(version_str)

        # If there's an upper bound that excludes this version, it's a violation
        if bounds.upper:
            if bounds.upper_inclusive:
                excluded = version > bounds.upper
            else:
                excluded = version >= bounds.upper

            if excluded:
                reporter.add_error(
                    package=dep.name,
                    message=f"{dep.raw} does not support required version {version_str}",
                    details=f"Version {version_str} must be supported within 6 months of release",
                    suggestion=f"Update upper bound to include {version_str}",
                )

        # If there's an exact constraint that doesn't match, it's a violation
        if bounds.exact and bounds.exact != version:
            reporter.add_error(
                package=dep.name,
                message=f"{dep.raw} does not support required version {version_str}",
                details=f"Exact constraint prevents supporting {version_str}",
                suggestion=f"Remove exact constraint",
            )


def check_pyproject(
    pyproject_path: str | Path,
    schedule_path: str | Path | None = None,
    check_adoption: bool = True,
    fail_on_warning: bool = False,
) -> tuple[bool, Reporter]:
    """High-level function to check a pyproject.toml file.

    Args:
        pyproject_path: Path to pyproject.toml
        schedule_path: Path to schedule.json (optional, will use defaults)
        check_adoption: Whether to check 6-month adoption rule
        fail_on_warning: Whether warnings should cause failure

    Returns:
        Tuple of (passed, reporter)
    """
    reporter = Reporter(title="PHEP 3 Compliance Check")

    # Load or create schedule
    if schedule_path and Path(schedule_path).exists():
        schedule = Schedule.from_file(schedule_path)
    else:
        # Create minimal schedule from built-in Python dates
        from pyhc_actions.phep3.schedule import create_python_schedule

        schedule = Schedule(
            generated_at=datetime.now(timezone.utc),
            python=create_python_schedule(),
            packages={},
        )
        reporter.add_warning(
            package="schedule",
            message="No schedule.json found - using built-in Python schedule only",
            details="Core package version checking requires schedule.json",
        )

    passed = check_compliance(
        pyproject_path=pyproject_path,
        schedule=schedule,
        reporter=reporter,
        check_adoption=check_adoption,
    )

    # Adjust for fail_on_warning
    if fail_on_warning and reporter.has_warnings:
        passed = False

    return passed, reporter
