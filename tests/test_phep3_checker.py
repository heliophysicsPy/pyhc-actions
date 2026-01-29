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
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

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
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should pass (no errors) but with warning - 3.8 is old but can still be supported
            # PHEP 3 says packages CAN drop old versions, not MUST drop
            assert passed is True
            assert reporter.has_warnings
            assert not reporter.has_errors

    def test_upper_bound_warning(self, schedule):
        """Test that upper bounds generate warnings when they don't exclude required versions."""
        # Create a schedule where numpy 2.0 is not yet required (support_by in future)
        now = datetime.now(timezone.utc)
        limited_schedule = Schedule(
            generated_at=now,
            python=schedule.python,
            packages={
                "numpy": {
                    "1.26": VersionSchedule(
                        version="1.26",
                        release_date=now - timedelta(days=300),
                        drop_date=now + timedelta(days=430),
                        support_by=now - timedelta(days=117),  # Must support
                    ),
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=50),  # Recently released
                        drop_date=now + timedelta(days=680),
                        support_by=now + timedelta(days=133),  # NOT YET REQUIRED
                    ),
                },
            },
        )
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
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
            passed = check_compliance(f.name, limited_schedule, reporter, use_uv_fallback=False)

            # Should pass but with warnings (upper bound doesn't exclude required versions)
            assert passed is True
            assert reporter.has_warnings

    def test_exact_version_warning(self, schedule):
        """Test that exact versions generate warnings when they match required versions."""
        # Create a schedule where only numpy 1.26 must be supported
        now = datetime.now(timezone.utc)
        limited_schedule = Schedule(
            generated_at=now,
            python=schedule.python,
            packages={
                "numpy": {
                    "1.26": VersionSchedule(
                        version="1.26",
                        release_date=now - timedelta(days=300),
                        drop_date=now + timedelta(days=430),
                        support_by=now - timedelta(days=117),  # Must support
                    ),
                },
            },
        )
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
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
            passed = check_compliance(f.name, limited_schedule, reporter, check_adoption=False, use_uv_fallback=False)

            # Should pass but with warnings for exact constraint (version matches required)
            assert passed is True
            assert reporter.has_warnings

    def test_non_core_package_ignored(self, schedule):
        """Test that non-core packages are ignored."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
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
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should pass - these aren't core packages
            assert passed is True
            assert not reporter.has_errors

    def test_missing_pyproject(self, schedule):
        """Test handling missing pyproject.toml."""
        reporter = Reporter()
        passed = check_compliance("/nonexistent/pyproject.toml", schedule, reporter, use_uv_fallback=False)

        assert passed is False
        assert reporter.has_errors


class TestPHEP3Errors:
    """Tests for PHEP 3 error conditions (actual violations)."""

    @pytest.fixture
    def schedule(self):
        """Create a test schedule with specific dates for testing."""
        now = datetime.now(timezone.utc)
        return Schedule(
            generated_at=now,
            python={
                "3.10": VersionSchedule(
                    version="3.10",
                    release_date=now - timedelta(days=800),
                    drop_date=now + timedelta(days=295),  # Still valid
                    support_by=now - timedelta(days=617),  # Already past adoption
                ),
                "3.11": VersionSchedule(
                    version="3.11",
                    release_date=now - timedelta(days=500),
                    drop_date=now + timedelta(days=595),  # Still valid
                    support_by=now - timedelta(days=317),  # Already past adoption
                ),
                "3.12": VersionSchedule(
                    version="3.12",
                    release_date=now - timedelta(days=300),
                    drop_date=now + timedelta(days=795),  # Still valid
                    support_by=now - timedelta(days=117),  # Already past adoption
                ),
                "3.13": VersionSchedule(
                    version="3.13",
                    release_date=now - timedelta(days=100),
                    drop_date=now + timedelta(days=995),  # Still valid
                    support_by=now + timedelta(days=83),  # Not yet required
                ),
            },
            packages={
                "numpy": {
                    "1.25": VersionSchedule(
                        version="1.25",
                        release_date=now - timedelta(days=600),
                        drop_date=now + timedelta(days=130),  # Still valid
                        support_by=now - timedelta(days=417),  # Past adoption
                    ),
                    "1.26": VersionSchedule(
                        version="1.26",
                        release_date=now - timedelta(days=400),
                        drop_date=now + timedelta(days=330),  # Still valid
                        support_by=now - timedelta(days=217),  # Past adoption
                    ),
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=200),
                        drop_date=now + timedelta(days=530),  # Still valid
                        support_by=now - timedelta(days=17),  # Past adoption (must support)
                    ),
                    "2.1": VersionSchedule(
                        version="2.1",
                        release_date=now - timedelta(days=50),
                        drop_date=now + timedelta(days=680),  # Still valid
                        support_by=now + timedelta(days=133),  # Not yet required
                    ),
                },
            },
        )

    def test_python_lower_bound_too_high_is_error(self, schedule):
        """Test that >=3.13 when 3.10 is still required produces an ERROR."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.13"
dependencies = []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should fail - 3.10 must still be supported
            assert passed is False
            assert reporter.has_errors
            # Check the error message mentions dropping Python too early
            error_messages = [e.message for e in reporter.errors]
            assert any("drops support" in msg for msg in error_messages)

    def test_python_upper_bound_excludes_required(self, schedule):
        """Test that <3.12 when 3.12 must be supported produces an ERROR."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10,<3.12"
dependencies = []
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should fail - 3.12 must be supported but is blocked
            assert passed is False
            assert reporter.has_errors
            error_messages = [e.message for e in reporter.errors]
            assert any("blocks adoption" in msg for msg in error_messages)

    def test_package_lower_bound_too_high_is_error(self, schedule):
        """Test that numpy>=2.0 when 1.25 must be supported produces an ERROR."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy>=2.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should fail - numpy 1.25 must still be supported
            assert passed is False
            assert reporter.has_errors
            error_messages = [e.message for e in reporter.errors]
            assert any("drops support" in msg for msg in error_messages)

    def test_exclusion_of_all_required_versions_is_error(self, schedule):
        """Test that numpy!=2.0 when only 2.0 is required produces an ERROR."""
        # Create a schedule where only 2.0 must be supported
        now = datetime.now(timezone.utc)
        limited_schedule = Schedule(
            generated_at=now,
            python=schedule.python,
            packages={
                "numpy": {
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=200),
                        drop_date=now + timedelta(days=530),
                        support_by=now - timedelta(days=17),  # Past adoption
                    ),
                },
            },
        )

        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy>=1.25,!=2.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, limited_schedule, reporter, use_uv_fallback=False)

            # Should fail - all required versions are excluded
            assert passed is False
            assert reporter.has_errors

    def test_partial_exclusion_is_ok(self, schedule):
        """Test that numpy!=2.0 is fine if 2.1 is also required and allowed."""
        # Create a schedule where both 2.0 and 2.1 must be supported
        now = datetime.now(timezone.utc)
        multi_schedule = Schedule(
            generated_at=now,
            python=schedule.python,
            packages={
                "numpy": {
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=200),
                        drop_date=now + timedelta(days=530),
                        support_by=now - timedelta(days=17),  # Past adoption
                    ),
                    "2.1": VersionSchedule(
                        version="2.1",
                        release_date=now - timedelta(days=190),  # Also past adoption
                        drop_date=now + timedelta(days=540),
                        support_by=now - timedelta(days=7),  # Past adoption
                    ),
                },
            },
        )

        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy>=2.0,!=2.0.0",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, multi_schedule, reporter, use_uv_fallback=False)

            # Should pass - 2.1 is still allowed even though 2.0.0 is excluded
            # Note: Exclusion is for 2.0.0, but 2.1 (which is also required) is allowed
            # The test passes because excluding 2.0.0 doesn't exclude all of 2.0.x
            assert passed is True

    def test_tilde_equals_warns_about_upper_bound(self, schedule):
        """Test that numpy~=1.26 produces a warning about implicit upper bound."""
        content = """
[project]
name = "test-package"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "numpy~=1.26",
]
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()

            reporter = Reporter()
            passed = check_compliance(f.name, schedule, reporter, use_uv_fallback=False)

            # Should have warnings about implicit upper bound
            assert reporter.has_warnings
            warning_messages = [w.message for w in reporter.warnings]
            assert any("implicit upper bound" in msg for msg in warning_messages)


class TestScheduleHelpers:
    """Tests for Schedule helper methods."""

    @pytest.fixture
    def schedule(self):
        """Create a test schedule."""
        now = datetime.now(timezone.utc)
        return Schedule(
            generated_at=now,
            python={
                "3.10": VersionSchedule(
                    version="3.10",
                    release_date=now - timedelta(days=800),
                    drop_date=now + timedelta(days=295),
                    support_by=now - timedelta(days=617),
                ),
                "3.11": VersionSchedule(
                    version="3.11",
                    release_date=now - timedelta(days=500),
                    drop_date=now + timedelta(days=595),
                    support_by=now - timedelta(days=317),
                ),
                "3.12": VersionSchedule(
                    version="3.12",
                    release_date=now - timedelta(days=300),
                    drop_date=now + timedelta(days=795),
                    support_by=now - timedelta(days=117),
                ),
            },
            packages={
                "numpy": {
                    "1.25": VersionSchedule(
                        version="1.25",
                        release_date=now - timedelta(days=600),
                        drop_date=now + timedelta(days=130),
                        support_by=now - timedelta(days=417),
                    ),
                    "2.0": VersionSchedule(
                        version="2.0",
                        release_date=now - timedelta(days=200),
                        drop_date=now + timedelta(days=530),
                        support_by=now - timedelta(days=17),
                    ),
                },
            },
        )

    def test_get_required_python_versions(self, schedule):
        """Test get_required_python_versions returns versions that must be supported."""
        now = datetime.now(timezone.utc)
        required = schedule.get_required_python_versions(now)

        # All versions with support_by in the past and drop_date in the future
        assert "3.10" in required
        assert "3.11" in required
        assert "3.12" in required

    def test_get_required_package_versions(self, schedule):
        """Test get_required_package_versions for numpy."""
        now = datetime.now(timezone.utc)
        required = schedule.get_required_package_versions("numpy", now)

        # Both 1.25 and 2.0 have support_by in the past and drop_date in the future
        assert "1.25" in required
        assert "2.0" in required

    def test_get_non_droppable_python_versions(self, schedule):
        """Test get_non_droppable_python_versions."""
        now = datetime.now(timezone.utc)
        non_droppable = schedule.get_non_droppable_python_versions(now)

        # Should be sorted oldest to newest
        assert non_droppable == ["3.10", "3.11", "3.12"]

    def test_get_non_droppable_package_versions(self, schedule):
        """Test get_non_droppable_package_versions for numpy."""
        now = datetime.now(timezone.utc)
        non_droppable = schedule.get_non_droppable_package_versions("numpy", now)

        # Both versions are non-droppable
        assert "1.25" in non_droppable
        assert "2.0" in non_droppable
