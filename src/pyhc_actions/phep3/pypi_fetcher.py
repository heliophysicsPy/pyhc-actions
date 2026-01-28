"""Fetch package release dates from PyPI."""

from __future__ import annotations

import collections
from datetime import datetime, timedelta, timezone

import requests
from packaging.version import Version, InvalidVersion

from pyhc_actions.phep3.config import CORE_PACKAGES, PACKAGE_SUPPORT_MONTHS, ADOPTION_MONTHS
from pyhc_actions.phep3.schedule import Schedule, VersionSchedule, create_python_schedule


PYPI_SIMPLE_URL = "https://pypi.org/simple/{package}"


def fetch_package_releases(
    package: str, support_months: int = PACKAGE_SUPPORT_MONTHS
) -> dict[str, VersionSchedule]:
    """Fetch release dates for a package from PyPI.

    Based on PHEP 3's reference implementation.

    Args:
        package: Package name to fetch
        support_months: Support window in months (default 24)

    Returns:
        Dictionary mapping version strings to VersionSchedule objects
    """
    releases = {}

    # Calculate cutoff - include releases from 9 months ago to catch recent drops
    now = datetime.now(timezone.utc)
    current_quarter_start = datetime(
        now.year, ((now.month - 1) // 3) * 3 + 1, 1, tzinfo=timezone.utc
    )
    cutoff = current_quarter_start - timedelta(days=270)  # ~9 months

    try:
        response = requests.get(
            PYPI_SIMPLE_URL.format(package=package),
            headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"Warning: Could not fetch release data for {package}: {e}")
        return releases

    # Group upload times by version
    file_dates: dict[Version, list[datetime]] = collections.defaultdict(list)

    for file_info in data.get("files", []):
        filename = file_info.get("filename", "")

        # Extract version from filename (format: package-version-...)
        parts = filename.split("-")
        if len(parts) < 2:
            continue

        ver_str = parts[1]

        try:
            version = Version(ver_str)
        except InvalidVersion:
            continue

        # Skip pre-releases and patch versions (we only care about X.Y.0)
        if version.is_prerelease or version.micro != 0:
            continue

        # Parse upload time
        upload_time_str = file_info.get("upload-time", "")
        if not upload_time_str:
            continue

        release_date = None
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"]:
            try:
                release_date = datetime.strptime(upload_time_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        if release_date:
            file_dates[version].append(release_date)

    # Use earliest upload time as release date
    for version, dates in file_dates.items():
        release_date = min(dates)
        drop_date = release_date + timedelta(days=support_months * 30.44)

        # Only include if drop date is after cutoff
        if drop_date >= cutoff:
            support_by = release_date + timedelta(days=ADOPTION_MONTHS * 30.44)
            version_str = f"{version.major}.{version.minor}"

            releases[version_str] = VersionSchedule(
                version=version_str,
                release_date=release_date,
                drop_date=drop_date,
                support_by=support_by,
            )

    return releases


def fetch_all_core_packages() -> dict[str, dict[str, VersionSchedule]]:
    """Fetch release dates for all core Scientific Python packages.

    Returns:
        Dictionary mapping package names to version schedules
    """
    packages = {}

    for package in sorted(CORE_PACKAGES):
        print(f"Fetching releases for {package}...", end=" ", flush=True)
        releases = fetch_package_releases(package)
        packages[package] = releases
        print(f"found {len(releases)} versions")

    return packages


def generate_schedule() -> Schedule:
    """Generate a complete schedule for Python and core packages.

    Returns:
        Schedule object with all version information
    """
    print("Generating PHEP 3 schedule...")

    python_schedule = create_python_schedule()
    packages_schedule = fetch_all_core_packages()

    return Schedule(
        generated_at=datetime.now(timezone.utc),
        python=python_schedule,
        packages=packages_schedule,
    )


def update_schedule_file(path: str = "schedule.json"):
    """Update the schedule.json file with fresh data from PyPI.

    Args:
        path: Path to save the schedule file
    """
    schedule = generate_schedule()
    schedule.save(path)
    print(f"Schedule saved to {path}")
