"""Tests for PHEP 3 compliance checker."""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.phep3.checker import check_compliance
from pyhc_actions.phep3.schedule import Schedule, VersionSchedule
from pyhc_actions.phep3.config import is_core_package, normalize_package_name


class TestCorePackageDetection:
    """Tests for core package detection."""

    def test_numpy_is_core(self):
        """Test numpy is detected as core package."""
        assert is_core_package("numpy") is True

    def test_scipy_is_core(self):
        """Test scipy is detected as core package."""
        assert is_core_package("scipy") is True

    def test_scikit_image_is_core(self):
        """Test scikit-image is detected as core package."""
        assert is_core_package("scikit-image") is True

    def test_random_package_not_core(self):
        """Test random package is not core."""
        assert is_core_package("requests") is False
        assert is_core_package("sunpy") is False

    def test_normalize_package_name(self):
        """Test package name normalization."""
        assert normalize_package_name("Scikit-Image") == "scikit-image"
        assert normalize_package_name("scikit_image") == "scikit-image"


class TestSchedule:
    """Tests for Schedule class."""

    def test_create_from_dict(self):
        """Test creating schedule from dictionary."""
        data = {
            "generated_at": "2024-01-01T00:00:00+00:00",
            "python": {
                "3.11": {
                    "release_date": "2022-10-24T00:00:00+00:00",
                    "drop_date": "2025-10-24T00:00:00+00:00",
                    "support_by": "2023-04-24T00:00:00+00:00",
                }
            },
            "packages": {
                "numpy": {
                    "1.26": {
                        "release_date": "2023-09-16T00:00:00+00:00",
                        "drop_date": "2025-09-16T00:00:00+00:00",
                        "support_by": "2024-03-16T00:00:00+00:00",
                    }
                }
            },
        }

        schedule = Schedule.from_dict(data)
        assert "3.11" in schedule.python
        assert "numpy" in schedule.packages
        assert "1.26" in schedule.packages["numpy"]

    def test_version_is_droppable(self):
        """Test version droppability check."""
        release_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        drop_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
        support_by = datetime(2020, 7, 1, tzinfo=timezone.utc)

        vs = VersionSchedule(
            version="3.8",
            release_date=release_date,
            drop_date=drop_date,
            support_by=support_by,
        )

        # After drop date
        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert vs.is_droppable(now) is True

        # Before drop date
        now = datetime(2022, 1, 1, tzinfo=timezone.utc)
        assert vs.is_droppable(now) is False


class TestCompliance:
    """Tests for compliance checking."""

    @pytest.fixture
    def schedule(self):
        """Create a test schedule."""
        now = datetime.now(timezone.utc)
        return Schedule(
            generated_at=now,
            python={
                "3.10": VersionSchedule(
                    version="3.10",
                    release_date=now - timedelta(days=400),
                    drop_date=now + timedelta(days=695),  # ~36 months from release
                    support_by=now - timedelta(days=217),  # 6 months from release
                ),
                "3.11": VersionSchedule(
                    version="3.11",
                    release_date=now - timedelta(days=365),
                    drop_date=now + timedelta(days=730),
                    support_by=now - timedelta(days=182),
                ),
                "3.12": VersionSchedule(
                    version="3.12",
                    release_date=now - timedelta(days=100),
                    drop_date=now + timedelta(days=995),
                    support_by=now + timedelta(days=83),
                ),
            },
            packages={
                "numpy": {
                    "1.25": VersionSchedule(
                        version="1.25",
                        release_date=now - timedelta(days=600),
                        drop_date=now + timedelta(days=130),  # ~24 months from release
                        support_by=now - timedelta(days=417),
                    ),
                    "1.26": VersionSchedule(
                        version="1.26",
                        release_date=now - timedelta(days=300),
                        drop_date=now + timedelta(days=430),
                        support_by=now - timedelta(days=117),
                    ),
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=100),
                        drop_date=now + timedelta(days=630),
                        support_by=now + timedelta(days=83),
                    ),
                },
            },
        )

    def test_compliant_pyproject(self, schedule):
        """Test checking a compliant pyproject.toml."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy>=1.25",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter)

            # Should pass (3.10 and numpy 1.25 are still supported)
            assert passed is True
            assert not reporter.has_errors

    def test_old_python_version(self, schedule):
        """Test checking pyproject with old Python version."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.8"
dependencies = []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter)

            # Should pass (no errors) but with warning - 3.8 is old but can still be supported
            # PHEP 3 says packages CAN drop old versions, not MUST drop
            assert passed is True
            assert reporter.has_warnings
            assert not reporter.has_errors

    def test_upper_bound_warning(self, schedule):
        """Test that upper bounds generate warnings."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26,<2.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter)

            # Should pass but with warnings
            assert passed is True
            assert reporter.has_warnings

    def test_exact_version_warning(self, schedule):
        """Test that exact versions generate warnings."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "numpy==1.26.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            # Disable adoption check to only test the exact constraint warning
            passed = check_compliance(f.name, schedule, reporter, check_adoption=False)

            # Should pass but with warnings for exact constraint
            assert passed is True
            assert reporter.has_warnings

    def test_non_core_package_ignored(self, schedule):
        """Test that non-core packages are ignored."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.0",
    "sunpy>=4.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter)

            # Should pass - these aren't core packages
            assert passed is True
            assert not reporter.has_errors

    def test_missing_pyproject(self, schedule):
        """Test handling missing pyproject.toml."""
        reporter = Reporter()
        passed = check_compliance("/nonexistent/pyproject.toml", schedule, reporter)

        assert passed is False
        assert reporter.has_errors
