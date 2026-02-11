"""PHEP 3 compliance checking logic."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from packaging.markers import Marker, InvalidMarker, default_environment
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version

from pyhc_actions.common.parser import (
    ParsedDependency,
    VersionBounds,
    extract_version_bounds,
    extract_python_version,
    extract_python_bounds,
    parse_dependency,
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
    use_uv_fallback: bool = True,
    ignore_errors_for: set[str] | None = None,
) -> bool:
    """Check pyproject.toml compliance with PHEP 3.

    Args:
        pyproject_path: Path to pyproject.toml
        schedule: Schedule with version release dates
        reporter: Reporter for output
        check_adoption: Whether to check 6-month adoption rule
        now: Current time (for testing)
        use_uv_fallback: Whether to use uv for projects with non-PEP 621 metadata
        ignore_errors_for: Set of package names (lowercase) to treat errors as warnings

    Returns:
        True if compliant (no errors), False otherwise
    """
    now = now or datetime.now(timezone.utc)
    pyproject_path = Path(pyproject_path)

    reporter.set_file_path(str(pyproject_path))

    requires_python = None
    base_dependencies: list[ParsedDependency] = []
    extras_dependencies: dict[str, list[ParsedDependency]] = {}
    extraction_method = None

    # Try parsing pyproject.toml first
    try:
        pyproject_data = parse_pyproject(pyproject_path)
        project = pyproject_data.get("project", {})

        if project:
            # PEP 621 format
            requires_python = project.get("requires-python")
            # Extract base dependencies
            for dep_str in project.get("dependencies", []):
                dep = parse_dependency(dep_str)
                if dep:
                    base_dependencies.append(dep)
            # Extract optional dependencies by group
            for group_name, group_deps in project.get("optional-dependencies", {}).items():
                extras_dependencies[group_name] = []
                for dep_str in group_deps:
                    dep = parse_dependency(dep_str)
                    if dep:
                        extras_dependencies[group_name].append(dep)
            extraction_method = "pyproject.toml"
    except (FileNotFoundError, IsADirectoryError):
        if use_uv_fallback:
            reporter.print("Note: 'pyproject.toml' not found; attempting uv metadata extraction.")
        else:
            reporter.print("Note: 'pyproject.toml' not found.")
        pyproject_data = None
        project = {}
    except Exception as e:
        reporter.add_warning(
            package="-",
            message=f"Failed to parse pyproject.toml: {e}",
            details="Will attempt uv-based extraction if available",
            suggestion="Consider using pyproject.toml",
        )
        pyproject_data = None
        project = {}

    # Try uv fallback if needed
    if extraction_method is None and use_uv_fallback:
        from pyhc_actions.phep3.metadata_extractor import extract_metadata_from_project

        project_dir = pyproject_path.parent if pyproject_path.suffix == ".toml" else pyproject_path
        metadata = extract_metadata_from_project(project_dir, schedule)

        if metadata:
            requires_python = metadata.requires_python
            # Extract base dependencies
            base_dependencies = [
                parse_dependency(dep)
                for dep in metadata.dependencies
                if parse_dependency(dep) is not None
            ]
            # Extract optional dependencies by group
            for group_name, group_deps in metadata.optional_dependencies.items():
                extras_dependencies[group_name] = []
                for dep_str in group_deps:
                    dep = parse_dependency(dep_str)
                    if dep:
                        extras_dependencies[group_name].append(dep)
            if metadata.extracted_via and metadata.extracted_via != "uv":
                extraction_method = f"uv (from {metadata.extracted_via})"
                reporter.print(
                    f"Note: Using {extraction_method} metadata extraction for non-PEP 621 metadata."
                )
            else:
                extraction_method = "uv"
                reporter.print("Note: Using uv metadata extraction for non-PEP 621 metadata.")

    # If still no data, report error
    if extraction_method is None:
        reporter.add_error(
            package="pyproject.toml",
            message=f"Could not extract metadata from {pyproject_path}",
            details="No PEP 621 [project] section found and uv extraction failed",
        )
        return False

    # Check Python version requirement
    _check_python_version(requires_python, schedule, reporter, now)

    supported_python_versions = _get_supported_python_versions(
        requires_python, schedule, now
    )

    # Check base dependencies (violations are errors, unless in ignore_errors_for)
    ignore_set = ignore_errors_for or set()
    for dep in base_dependencies:
        should_warn = dep.name.lower() in ignore_set
        _check_dependency(
            dep,
            schedule,
            reporter,
            check_adoption,
            now,
            supported_python_versions,
            context="base",
            report_as_warning=should_warn,
        )

    # Check extras dependencies (violations are warnings)
    for group_name, deps in extras_dependencies.items():
        for dep in deps:
            _check_dependency(
                dep,
                schedule,
                reporter,
                check_adoption,
                now,
                supported_python_versions,
                context=group_name,
                report_as_warning=True,
            )

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
            suggestion="Consider using requires-python to specify supported Python versions",
        )
        return

    bounds = extract_python_bounds(requires_python)
    min_version = bounds.lower

    # For exact pins without lower bound, use the exact version as the effective lower bound
    if not min_version and bounds.exact:
        min_version = bounds.exact

    if not min_version:
        reporter.add_warning(
            package="python",
            message=f"Could not parse requires-python: {requires_python}",
        )
        return

    # Get the version string (e.g., "3.9" from Version("3.9.0"))
    version_str = f"{min_version.major}.{min_version.minor}"

    # Get the minimum Python version that MUST be supported (cannot be dropped)
    min_required = schedule.get_minimum_python_version(now)

    if min_required:
        min_required_ver = Version(min_required)
        # ERROR if lower bound is higher than minimum required (drops support too early)
        if min_version > min_required_ver:
            reporter.add_error(
                package="python",
                message=f"requires-python = \"{requires_python}\" drops support for Python {min_required} too early",
                details=f"Python {min_required} must still be supported per PHEP 3",
                suggestion=f"Change to requires-python = \">={min_required}\"",
            )

    # Check if lower bound is an older version that CAN be dropped (informational)
    version_info = schedule.python.get(version_str)
    if version_info and version_info.is_droppable(now):
        months = version_info.months_since_release(now)
        details = f"Python {version_str} released {months} months ago (>{PYTHON_SUPPORT_MONTHS} months)"
        if min_required:
            details += f". The minimum required version is {min_required}"

        reporter.add_warning(
            package="python",
            message=f"Python {version_str} support can be dropped per PHEP 3",
            details=details,
            suggestion=f"Minimum required version: {min_required}" if min_required else None,
        )
    elif not version_info and min_required:
        # Version not in schedule - check if it's older than minimum
        rec_parts = [int(p) for p in min_required.split(".")]
        min_parts = [min_version.major, min_version.minor]
        if min_parts < rec_parts:
            reporter.add_warning(
                package="python",
                message=f"Python {version_str} support can be dropped per PHEP 3",
                details=f"Python {version_str} is older than the minimum required version ({min_required})",
                suggestion=f"Minimum required version: {min_required}",
            )

    # Check upper bound - ERROR if it excludes a Python version that must_be_supported(now)
    if bounds.has_upper_constraint and bounds.upper:
        for py_version, py_info in schedule.python.items():
            if py_info.must_be_supported(now):
                py_ver = Version(py_version)
                # Check if this required version is excluded by the upper bound
                if bounds.upper_inclusive:
                    excluded = py_ver > bounds.upper
                else:
                    excluded = py_ver >= bounds.upper

                if excluded:
                    reporter.add_error(
                        package="python",
                        message=f"requires-python = \"{requires_python}\" blocks adoption of Python {py_version}",
                        details=f"Python {py_version} must be supported within 6 months of release per PHEP 3",
                        suggestion=f"Remove upper bound or update to include Python {py_version}",
                    )

    # Check exclusions - ERROR if a required version is excluded
    if bounds.exclusions:
        for py_version, py_info in schedule.python.items():
            if py_info.must_be_supported(now):
                py_ver = Version(py_version)
                # Check if excluded (need to match major.minor)
                for excl in bounds.exclusions:
                    if excl.major == py_ver.major and excl.minor == py_ver.minor:
                        reporter.add_error(
                            package="python",
                            message=f"requires-python = \"{requires_python}\" excludes required Python {py_version}",
                            details=f"Python {py_version} must be supported per PHEP 3",
                            suggestion=f"Remove !={excl} from requires-python",
                        )

    # Check exact pin (non-wildcard) - ERROR if it excludes a required version
    if bounds.exact and not bounds.is_wildcard:
        for py_version, py_info in schedule.python.items():
            if py_info.must_be_supported(now):
                py_ver = Version(py_version)
                # Exact pin only allows the pinned version
                if not (bounds.exact.major == py_ver.major and bounds.exact.minor == py_ver.minor):
                    reporter.add_error(
                        package="python",
                        message=f"requires-python = \"{requires_python}\" excludes required Python {py_version}",
                        details=f"Exact pin only allows Python {bounds.exact.major}.{bounds.exact.minor}, but {py_version} must be supported per PHEP 3",
                        suggestion=f"Use >= instead of == to allow newer Python versions",
                    )


def _check_dependency(
    dep: ParsedDependency,
    schedule: Schedule,
    reporter: Reporter,
    check_adoption: bool,
    now: datetime,
    supported_python_versions: list[str],
    context: str = "base",
    report_as_warning: bool = False,
):
    """Check a single dependency for PHEP 3 compliance.

    Args:
        dep: The parsed dependency to check
        schedule: Version release schedule
        reporter: Reporter for output
        check_adoption: Whether to check 6-month adoption rule
        now: Current time
        supported_python_versions: List of Python versions to consider
        context: Context label for reporting (e.g., "base", "dev", "image")
        report_as_warning: If True, report errors as warnings (used for extras)
    """
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

    marker_applicability = _get_python_marker_applicability(
        dep.markers, supported_python_versions
    )
    if marker_applicability == "none":
        return

    downgrade_lower_bound = marker_applicability == "some"

    # Helper to report issues with correct severity
    def _report_warning(package: str, message: str, details: str = "", suggestion: str = ""):
        reporter.add_warning(
            package=package,
            message=message,
            details=details,
            suggestion=suggestion,
            context=context if context != "base" else "",
        )

    def _report_error(package: str, message: str, details: str = "", suggestion: str = ""):
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
                context=context if context != "base" else "",
            )

    # Check for upper bound / exact constraints (warning)
    if bounds.has_max_constraint:
        if bounds.exact:
            if bounds.is_wildcard:
                _report_warning(
                    package=dep.name,
                    message=f"{dep.raw} has wildcard version constraint",
                    details=f"Wildcard constraints create an implicit upper bound (<{bounds.upper})",
                    suggestion=f"Consider using >= instead for better compatibility",
                )
            else:
                _report_warning(
                    package=dep.name,
                    message=f"{dep.raw} has exact version constraint",
                    details="Exact constraints should only be used when absolutely necessary",
                    suggestion=f"Remove exact constraint and use >= instead",
                )
        elif bounds.upper:
            # Check if this is from a ~= constraint
            has_tilde_equals = any(
                spec.operator == "~=" for spec in (dep.specifier or [])
            )
            if has_tilde_equals:
                _report_warning(
                    package=dep.name,
                    message=f"{dep.raw} has implicit upper bound from ~=",
                    details=f"The ~= operator creates an implicit upper bound (<{bounds.upper})",
                    suggestion=f"Consider using >= instead for better compatibility",
                )
            else:
                _report_warning(
                    package=dep.name,
                    message=f"{dep.raw} has upper bound constraint",
                    details="Upper bounds should only be used when absolutely necessary",
                    suggestion=f"Consider removing <{bounds.upper} unless required",
                )

    # Check lower bound
    if bounds.lower:
        _check_lower_bound(
            dep,
            pkg_name,
            bounds.lower,
            schedule,
            reporter,
            now,
            downgrade_lower_bound,
            context=context,
            report_as_warning=report_as_warning,
        )

    # Check adoption of new versions
    if check_adoption:
        _check_adoption(
            dep,
            pkg_name,
            schedule,
            reporter,
            now,
            context=context,
            report_as_warning=report_as_warning,
        )


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
    downgrade_error: bool = False,
    context: str = "base",
    report_as_warning: bool = False,
):
    """Check if the lower bound violates PHEP 3 requirements."""
    pkg_versions = schedule.packages.get(pkg_name, {})
    if not pkg_versions:
        return

    # Get version string (e.g., "1.26" from Version("1.26.0"))
    version_str = f"{lower_bound.major}.{lower_bound.minor}"

    # Get the minimum version that MUST still be supported
    min_supported = schedule.get_minimum_package_version(pkg_name, now)

    # Context for reporting (omit "base" from output)
    report_context = context if context != "base" else ""

    if min_supported:
        min_ver = Version(min_supported)
        # ERROR if lower bound is higher than minimum required (drops support too early)
        if lower_bound > min_ver:
            if downgrade_error or report_as_warning:
                reporter.add_warning(
                    package=dep.name,
                    message=f"{dep.raw} drops support for {dep.name} {min_supported} too early",
                    details=f"{dep.name} {min_supported} should still be supported per PHEP 3",
                    suggestion=f"Drops PHEP 3 min ({min_supported}); marker allows min for some supported Pythons",
                    context=report_context,
                )
            else:
                reporter.add_error(
                    package=dep.name,
                    message=f"{dep.raw} drops support for {dep.name} {min_supported} too early",
                    details=f"{dep.name} {min_supported} must still be supported per PHEP 3",
                    suggestion=f"Change to {dep.name}>={min_supported}",
                    context=report_context,
                )

    # Check if the lower bound version itself can be dropped (informational)
    version_info = pkg_versions.get(version_str)
    if version_info and version_info.is_droppable(now):
        months = version_info.months_since_release(now)
        details = f"Version {version_str} released {months} months ago (>{PACKAGE_SUPPORT_MONTHS} months)"
        if min_supported:
            details += f". The minimum required version is {dep.name}>={min_supported}"

        reporter.add_warning(
            package=dep.name,
            message=f"{dep.name} {version_str} support can be dropped per PHEP 3",
            details=details,
            suggestion=f"Minimum required version: {dep.name}>={min_supported}" if min_supported else None,
            context=report_context,
        )
    elif not version_info and min_supported:
        # Version not in schedule - check if it's older than minimum
        min_ver = Version(min_supported)
        if lower_bound < min_ver:
            reporter.add_warning(
                package=dep.name,
                message=f"{dep.name} {version_str} support can be dropped per PHEP 3",
                details=f"Version {version_str} is older than the minimum required version ({dep.name}>={min_supported})",
                suggestion=f"Minimum required version: {dep.name}>={min_supported}",
                context=report_context,
            )


def _check_adoption(
    dep: ParsedDependency,
    pkg_name: str,
    schedule: Schedule,
    reporter: Reporter,
    now: datetime,
    context: str = "base",
    report_as_warning: bool = False,
):
    """Check if new versions are being adopted within 6 months."""
    pkg_versions = schedule.packages.get(pkg_name, {})
    if not pkg_versions:
        return

    # Find all versions that must be supported now
    bounds = extract_version_bounds(dep.specifier)

    # Collect all required versions and check which are allowed
    required_versions = []
    for version_str, version_info in pkg_versions.items():
        if version_info.must_be_supported(now):
            required_versions.append((version_str, Version(version_str)))

    if not required_versions:
        return

    # Check each required version
    excluded_by_upper = []
    excluded_by_exact = []
    excluded_by_not_equal = []

    for version_str, version in required_versions:
        # Check if excluded by upper bound
        if bounds.upper:
            if bounds.upper_inclusive:
                excluded = version > bounds.upper
            else:
                excluded = version >= bounds.upper

            if excluded:
                excluded_by_upper.append(version_str)
                continue

        # Check if excluded by exact constraint
        if bounds.exact:
            # For exact constraints, only the exact version is allowed
            # Check if major.minor matches (e.g., ==1.26.0 should allow 1.26)
            if not (bounds.exact.major == version.major and bounds.exact.minor == version.minor):
                excluded_by_exact.append(version_str)
                continue

        # Check if excluded by != constraints
        if bounds.exclusions:
            for excl in bounds.exclusions:
                # Match on major.minor
                if excl.major == version.major and excl.minor == version.minor:
                    excluded_by_not_equal.append(version_str)
                    break

    # Context for reporting (omit "base" from output)
    report_context = context if context != "base" else ""

    # Helper to report errors (as warnings if report_as_warning is True)
    def _report_error(package: str, message: str, details: str, suggestion: str):
        if report_as_warning:
            reporter.add_warning(
                package=package,
                message=message,
                details=details,
                suggestion=suggestion,
                context=report_context,
            )
        else:
            reporter.add_error(
                package=package,
                message=message,
                details=details,
                suggestion=suggestion,
                context=report_context,
            )

    # Report errors for versions excluded by upper bound
    for version_str in excluded_by_upper:
        _report_error(
            package=dep.name,
            message=f"{dep.raw} does not support required version {version_str}",
            details=f"Version {version_str} must be supported within 6 months of release",
            suggestion=f"Update upper bound to include {version_str}",
        )

    # Report errors for versions excluded by exact constraint
    for version_str in excluded_by_exact:
        _report_error(
            package=dep.name,
            message=f"{dep.raw} does not support required version {version_str}",
            details=f"Exact constraint prevents supporting {version_str}",
            suggestion=f"Remove exact constraint",
        )

    # For != exclusions, only error if ALL required versions are excluded
    # (e.g., numpy!=2.0 is fine if 2.1 is also required and allowed)
    allowed_versions = [
        v for v, _ in required_versions
        if v not in excluded_by_upper and v not in excluded_by_exact and v not in excluded_by_not_equal
    ]

    if excluded_by_not_equal and not allowed_versions:
        # All required versions are excluded
        _report_error(
            package=dep.name,
            message=f"{dep.raw} excludes all required versions",
            details=f"Exclusions prevent supporting any of: {', '.join(excluded_by_not_equal)}",
            suggestion=f"Remove exclusions or ensure at least one required version is allowed",
        )


def _get_supported_python_versions(
    requires_python: str | None, schedule: Schedule, now: datetime
) -> list[str]:
    """Return Python versions that are supported per PHEP 3 and requires-python."""
    supported = schedule.get_non_droppable_python_versions(now)
    if not requires_python:
        return supported

    try:
        spec = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return supported

    return [v for v in supported if spec.contains(v, prereleases=True)]


def _get_python_marker_applicability(
    markers: str | None, supported_python_versions: list[str]
) -> str | None:
    """Determine whether a python_version marker applies to none, some, or all supported Pythons."""
    if not markers or not supported_python_versions:
        return None

    if "python_version" not in markers and "python_full_version" not in markers:
        return None

    try:
        marker = Marker(markers)
    except InvalidMarker:
        return None

    results = []
    for version in supported_python_versions:
        env = default_environment()
        env["python_version"] = version
        env["python_full_version"] = f"{version}.0"
        results.append(marker.evaluate(env))

    if all(results):
        return "all"
    if any(results):
        return "some"
    return "none"


def check_pyproject(
    pyproject_path: str | Path,
    schedule_path: str | Path | None = None,
    check_adoption: bool = True,
    fail_on_warning: bool = False,
    use_uv_fallback: bool = True,
    ignore_errors_for: set[str] | None = None,
) -> tuple[bool, Reporter]:
    """High-level function to check a pyproject.toml file.

    Args:
        pyproject_path: Path to pyproject.toml
        schedule_path: Path to schedule.json (optional, will use defaults)
        check_adoption: Whether to check 6-month adoption rule
        fail_on_warning: Whether warnings should cause failure
        use_uv_fallback: Whether to use uv for projects with non-PEP 621 metadata
        ignore_errors_for: Set of package names (lowercase) to treat errors as warnings

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
        use_uv_fallback=use_uv_fallback,
        ignore_errors_for=ignore_errors_for,
    )

    # Adjust for fail_on_warning
    if fail_on_warning and reporter.has_warnings:
        passed = False

    return passed, reporter
