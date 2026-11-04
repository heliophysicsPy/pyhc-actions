"""Tests for PHEP 3 schedule generation from PyPI."""

from datetime import datetime, timedelta, timezone

import pytest
import requests

from pyhc_actions.phep3 import pypi_fetcher
from pyhc_actions.phep3.config import CORE_PACKAGES
from pyhc_actions.phep3.schedule import VersionSchedule


def _fake_releases(package):
    """Return one recent release for a package."""
    now = datetime.now(timezone.utc)
    return {
        "1.0": VersionSchedule(
            version="1.0",
            release_date=now - timedelta(days=30),
            drop_date=now + timedelta(days=700),
            support_by=now + timedelta(days=150),
        )
    }


class FakeResponse:
    """Minimal stand-in for a PyPI simple API response."""

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class TestFetchPackageReleases:
    """Tests for retrying PyPI requests."""

    @pytest.fixture
    def sleeps(self, monkeypatch):
        """Record retry delays instead of sleeping."""
        recorded = []
        monkeypatch.setattr(pypi_fetcher.time, "sleep", recorded.append)
        return recorded

    def test_retries_transient_error(self, monkeypatch, sleeps):
        """Test a failed request is retried and its data used."""
        upload_time = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        responses = [
            requests.ConnectionError("connection reset"),
            FakeResponse({"files": [
                {"filename": "numpy-2.3.0-cp312-cp312-win_amd64.whl", "upload-time": upload_time},
            ]}),
        ]

        def fake_get(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(pypi_fetcher.requests, "get", fake_get)

        releases = pypi_fetcher.fetch_package_releases("numpy")

        assert list(releases) == ["2.3"]
        assert sleeps == [pypi_fetcher.RETRY_DELAY_SECONDS]

    def test_returns_empty_after_all_attempts_fail(self, monkeypatch, sleeps):
        """Test a package PyPI never serves yields no releases."""
        calls = []

        def fake_get(*args, **kwargs):
            calls.append(args)
            raise requests.Timeout("timed out")

        monkeypatch.setattr(pypi_fetcher.requests, "get", fake_get)

        assert pypi_fetcher.fetch_package_releases("numpy") == {}
        assert len(calls) == pypi_fetcher.FETCH_ATTEMPTS
        assert len(sleeps) == pypi_fetcher.FETCH_ATTEMPTS - 1


class TestScheduleGeneration:
    """Tests that generation never produces an incomplete schedule."""

    def test_all_packages_fetched(self, monkeypatch):
        """Test a complete fetch returns every core package."""
        monkeypatch.setattr(pypi_fetcher, "fetch_package_releases", _fake_releases)

        packages = pypi_fetcher.fetch_all_core_packages()

        assert set(packages) == CORE_PACKAGES
        assert all(packages.values())

    def test_package_without_releases_aborts(self, monkeypatch):
        """Test one package with no release data fails generation."""
        monkeypatch.setattr(
            pypi_fetcher,
            "fetch_package_releases",
            lambda package: {} if package in ("numpy", "zarr") else _fake_releases(package),
        )

        with pytest.raises(RuntimeError, match="No release data for numpy, zarr"):
            pypi_fetcher.fetch_all_core_packages()

    def test_update_schedule_file_keeps_old_file_on_failure(self, monkeypatch, tmp_path):
        """Test a failed fetch leaves schedule.json untouched (nothing to publish or commit)."""
        monkeypatch.setattr(
            pypi_fetcher,
            "fetch_package_releases",
            lambda package: {} if package == "numpy" else _fake_releases(package),
        )
        schedule_path = tmp_path / "schedule.json"
        schedule_path.write_text("previous schedule")

        with pytest.raises(RuntimeError, match="numpy"):
            pypi_fetcher.update_schedule_file(str(schedule_path))

        assert schedule_path.read_text() == "previous schedule"
