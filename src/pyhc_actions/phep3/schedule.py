"""Schedule management for PHEP 3 compliance checking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

from pyhc_actions.phep3.config import (
    PYTHON_RELEASES,
    PYTHON_SUPPORT_MONTHS,
    PACKAGE_SUPPORT_MONTHS,
    ADOPTION_MONTHS,
)


class VersionInfo(TypedDict):
    """Information about a specific version's support timeline."""

    release_date: str  # ISO format
    drop_date: str  # ISO format, when support can be dropped
    support_by: str  # ISO format, when support must be added


@dataclass
class VersionSchedule:
    """Parsed version schedule with datetime objects."""

    version: str
    release_date: datetime
    drop_date: datetime
    support_by: datetime

    @classmethod
    def from_dict(cls, version: str, data: VersionInfo) -> "VersionSchedule":
        """Create from dictionary data."""
        return cls(
            version=version,
            release_date=datetime.fromisoformat(data["release_date"]).replace(tzinfo=timezone.utc),
            drop_date=datetime.fromisoformat(data["drop_date"]).replace(tzinfo=timezone.utc),
            support_by=datetime.fromisoformat(data["support_by"]).replace(tzinfo=timezone.utc),
        )

    def is_droppable(self, now: datetime | None = None) -> bool:
        """Check if this version can be dropped (past drop_date)."""
        now = now or datetime.now(timezone.utc)
        return now > self.drop_date

    def must_be_supported(self, now: datetime | None = None) -> bool:
        """Check if this version must be supported (past support_by but not drop_date)."""
        now = now or datetime.now(timezone.utc)
        return now > self.support_by and now <= self.drop_date

    def months_since_release(self, now: datetime | None = None) -> int:
        """Return months since release date."""
        now = now or datetime.now(timezone.utc)
        delta = now - self.release_date
        return int(delta.days / 30.44)  # Average days per month


@dataclass
class Schedule:
    """Full schedule for Python and core packages."""

    generated_at: datetime
    python: dict[str, VersionSchedule]
    packages: dict[str, dict[str, VersionSchedule]]

    @classmethod
    def from_file(cls, path: Path | str) -> "Schedule":
        """Load schedule from JSON file."""
        path = Path(path)
        with open(path) as f:
            data = json.load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        """Create schedule from dictionary."""
        generated_at = datetime.fromisoformat(data.get("generated_at", datetime.now(timezone.utc).isoformat()))
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        python = {}
        for version, info in data.get("python", {}).items():
            python[version] = VersionSchedule.from_dict(version, info)

        packages = {}
        for pkg_name, versions in data.get("packages", {}).items():
            packages[pkg_name] = {}
            for version, info in versions.items():
                packages[pkg_name][version] = VersionSchedule.from_dict(version, info)

        return cls(generated_at=generated_at, python=python, packages=packages)

    def to_dict(self) -> dict:
        """Convert schedule to dictionary for JSON serialization."""
        result = {
            "generated_at": self.generated_at.isoformat(),
            "python": {},
            "packages": {},
        }

        for version, sched in self.python.items():
            result["python"][version] = {
                "release_date": sched.release_date.isoformat(),
                "drop_date": sched.drop_date.isoformat(),
                "support_by": sched.support_by.isoformat(),
            }

        for pkg_name, versions in self.packages.items():
            result["packages"][pkg_name] = {}
            for version, sched in versions.items():
                result["packages"][pkg_name][str(version)] = {
                    "release_date": sched.release_date.isoformat(),
                    "drop_date": sched.drop_date.isoformat(),
                    "support_by": sched.support_by.isoformat(),
                }

        return result

    def save(self, path: Path | str):
        """Save schedule to JSON file."""
        path = Path(path)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_minimum_python_version(self, now: datetime | None = None) -> str | None:
        """Get the minimum Python version that should be supported.

        Returns the oldest Python version that cannot yet be dropped.
        """
        now = now or datetime.now(timezone.utc)

        # Find all versions that cannot be dropped yet
        supported = [
            (v, sched)
            for v, sched in self.python.items()
            if not sched.is_droppable(now)
        ]

        if not supported:
            return None

        # Return the oldest (lowest version)
        sorted_versions = sorted(supported, key=lambda x: [int(p) for p in x[0].split(".")])
        return sorted_versions[0][0]

    def get_minimum_package_version(
        self, package: str, now: datetime | None = None
    ) -> str | None:
        """Get the minimum version of a package that should be supported.

        Returns the oldest version that cannot yet be dropped.
        """
        now = now or datetime.now(timezone.utc)

        pkg_versions = self.packages.get(package, {})
        if not pkg_versions:
            return None

        # Find all versions that cannot be dropped yet
        supported = [
            (v, sched)
            for v, sched in pkg_versions.items()
            if not sched.is_droppable(now)
        ]

        if not supported:
            return None

        # Return the oldest
        from packaging.version import Version
        sorted_versions = sorted(supported, key=lambda x: Version(x[0]))
        return sorted_versions[0][0]

    def get_latest_package_version(self, package: str) -> str | None:
        """Get the latest known version of a package."""
        pkg_versions = self.packages.get(package, {})
        if not pkg_versions:
            return None

        from packaging.version import Version
        return str(max(Version(v) for v in pkg_versions.keys()))


def create_python_schedule() -> dict[str, VersionSchedule]:
    """Create Python version schedule from known releases."""
    now = datetime.now(timezone.utc)
    schedule = {}

    for version, release_str in PYTHON_RELEASES.items():
        release_date = datetime.strptime(release_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        drop_date = release_date + timedelta(days=PYTHON_SUPPORT_MONTHS * 30.44)
        support_by = release_date + timedelta(days=ADOPTION_MONTHS * 30.44)

        # Only include if not yet droppable or recently droppable
        cutoff = now - timedelta(days=90)  # Include versions dropped in last quarter
        if drop_date > cutoff:
            schedule[version] = VersionSchedule(
                version=version,
                release_date=release_date,
                drop_date=drop_date,
                support_by=support_by,
            )

    return schedule


def calculate_dates(
    release_date: datetime, support_months: int = PACKAGE_SUPPORT_MONTHS
) -> tuple[datetime, datetime]:
    """Calculate drop_date and support_by from release date.

    Args:
        release_date: When the version was released
        support_months: How long to support (default 24 for packages)

    Returns:
        Tuple of (drop_date, support_by)
    """
    drop_date = release_date + timedelta(days=support_months * 30.44)
    support_by = release_date + timedelta(days=ADOPTION_MONTHS * 30.44)
    return drop_date, support_by
