"""Tests for PHEP 3 schedule generation from PyPI."""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from pyhc_actions.phep3 import pypi_fetcher
from pyhc_actions.phep3.config import CORE_PACKAGES
from pyhc_actions.phep3.schedule import VersionSchedule

REPO_ROOT = Path(__file__).resolve().parents[1]

# How release.yml and update-schedule.yml generate schedule.json
GENERATE_COMMAND = (
    "from pyhc_actions.phep3.pypi_fetcher import update_schedule_file; "
    "update_schedule_file('schedule.json')"
)


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


def _upload_time(days_ago=30):
    """Return a PyPI upload-time string for a recent upload."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _fake_pypi(failing_package, failure, requested):
    """Fake requests.get where every package but failing_package has a usable release."""

    def fake_get(url, *args, **kwargs):
        package = url.rsplit("/", 1)[-1]
        requested.append(package)
        name = package.replace("-", "_")
        if package != failing_package:
            filenames = [f"{name}-1.0.0-py3-none-any.whl"]
        elif failure == "request-error":
            raise requests.ConnectionError("connection reset")
        else:
            # Pre-release, patch release, and sdist: none give an X.Y.0 version
            filenames = [
                f"{name}-3.1.0rc1-py3-none-any.whl",
                f"{name}-3.0.1-py3-none-any.whl",
                f"{name}-3.1.0.tar.gz",
            ]
        return FakeResponse({"files": [
            {"filename": filename, "upload-time": _upload_time()} for filename in filenames
        ]})

    return fake_get


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
        responses = [
            requests.ConnectionError("connection reset"),
            FakeResponse({"files": [
                {"filename": "numpy-2.3.0-cp312-cp312-win_amd64.whl", "upload-time": _upload_time()},
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

    @pytest.mark.parametrize("failure", ["request-error", "no-usable-versions"])
    def test_update_schedule_file_keeps_old_file_on_failure(self, monkeypatch, tmp_path, failure):
        """Test the last package failing leaves schedule.json byte-for-byte unchanged."""
        failing_package = sorted(CORE_PACKAGES)[-1]
        requested = []
        monkeypatch.setattr(
            pypi_fetcher.requests, "get", _fake_pypi(failing_package, failure, requested)
        )
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        schedule_path = tmp_path / "schedule.json"
        previous = b'{"generated_at": "2026-11-01T00:00:00+00:00", "packages": {}}\n'
        schedule_path.write_bytes(previous)

        with pytest.raises(RuntimeError, match=f"No release data for {failing_package};"):
            pypi_fetcher.update_schedule_file(str(schedule_path))

        # Every other package was fetched successfully before the failure
        assert set(requested) == CORE_PACKAGES
        assert schedule_path.read_bytes() == previous

    def test_workflow_command_exits_nonzero(self, tmp_path):
        """Test the workflows' generation command fails and keeps schedule.json."""
        for workflow in ("release.yml", "update-schedule.yml"):
            assert GENERATE_COMMAND in (REPO_ROOT / ".github" / "workflows" / workflow).read_text()

        # Make every PyPI request fail without touching the network or waiting on retries
        offline = (
            "import requests, time\n"
            "def fail(*args, **kwargs): raise requests.ConnectionError('PyPI unreachable')\n"
            "requests.get = fail\n"
            "time.sleep = lambda seconds: None\n"
        )
        schedule_path = tmp_path / "schedule.json"
        previous = b'{"generated_at": "2026-11-01T00:00:00+00:00", "packages": {}}\n'
        schedule_path.write_bytes(previous)

        result = subprocess.run(
            [sys.executable, "-c", offline + GENERATE_COMMAND],
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "RuntimeError: No release data for" in result.stderr
        assert schedule_path.read_bytes() == previous
