"""Tests for the phep3-check CLI entry point."""

from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.phep3 import main as phep3_main
from pyhc_actions.phep3 import schedule as schedule_module
from pyhc_actions.phep3.schedule import Schedule, create_python_schedule

REPO_ROOT = Path(__file__).parent.parent

PEP621_PYPROJECT = """
[project]
name = "demo"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = []
"""


def _schedule(generated_at: datetime | None = None) -> Schedule:
    return Schedule(
        generated_at=generated_at or datetime(2026, 11, 1, tzinfo=timezone.utc),
        python=create_python_schedule(),
        packages={},
    )


def _fail(*_args, **_kwargs):
    raise AssertionError("should not be called")


@pytest.fixture(autouse=True)
def no_schedule_download(monkeypatch):
    """Fail any test that would download schedule.json without opting in."""
    monkeypatch.setattr(phep3_main, "fetch_latest_schedule", _fail)
    monkeypatch.setattr(Reporter, "write_github_summary", lambda _self: None)


@pytest.fixture
def captured(monkeypatch):
    """Replace check_pyproject and record the arguments main() passes it."""
    kwargs = {}

    def fake_check_pyproject(**kw):
        kwargs.update(kw)
        return True, Reporter()

    monkeypatch.setattr(phep3_main, "check_pyproject", fake_check_pyproject)
    return kwargs


class TestProjectPathResolution:
    """Tests for how the project_file argument is resolved."""

    def test_directory_uses_its_pyproject(self, tmp_path, captured):
        (tmp_path / "pyproject.toml").write_text(PEP621_PYPROJECT)

        exit_code = phep3_main.main([str(tmp_path), "--schedule", "unused.json"])

        assert exit_code == 0
        assert captured["pyproject_path"] == tmp_path / "pyproject.toml"

    def test_directory_with_pyproject_is_read_directly(self, tmp_path, monkeypatch, capsys):
        """No misleading "not found" note, and no uv extraction, for a PEP 621 project."""
        (tmp_path / "pyproject.toml").write_text(PEP621_PYPROJECT)
        schedule_file = tmp_path / "schedule.json"
        _schedule().save(schedule_file)
        monkeypatch.setattr(
            "pyhc_actions.phep3.metadata_extractor.extract_metadata_from_project", _fail
        )

        exit_code = phep3_main.main([str(tmp_path), "--schedule", str(schedule_file)])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "not found" not in out
        assert "uv" not in out

    def test_empty_directory_fails(self, tmp_path, captured, capsys):
        exit_code = phep3_main.main([str(tmp_path), "--schedule", "unused.json"])

        assert exit_code == 1
        assert captured == {}
        err = capsys.readouterr().err
        assert "No packaging metadata found" in err
        assert "pyproject.toml, setup.py, or setup.cfg" in err

    def test_relative_empty_directory_fails(self, tmp_path, monkeypatch, captured, capsys):
        """A bare directory name like "six" must never reach uv as a PyPI requirement."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "six").mkdir()

        exit_code = phep3_main.main(["six", "--schedule", "unused.json"])

        assert exit_code == 1
        assert captured == {}
        assert "No packaging metadata found" in capsys.readouterr().err

    def test_default_path_in_empty_directory_fails(self, tmp_path, monkeypatch, captured, capsys):
        monkeypatch.chdir(tmp_path)

        exit_code = phep3_main.main(["--schedule", "unused.json"])

        assert exit_code == 1
        assert captured == {}
        assert "No packaging metadata found" in capsys.readouterr().err

    def test_directory_with_setup_py_uses_uv_fallback(self, tmp_path, captured):
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")

        exit_code = phep3_main.main([str(tmp_path), "--schedule", "unused.json"])

        assert exit_code == 0
        assert captured["pyproject_path"] == tmp_path
        assert captured["use_uv_fallback"] is True

    def test_directory_with_setup_cfg_without_uv_fallback_fails(self, tmp_path, captured, capsys):
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = demo\n")

        exit_code = phep3_main.main(
            [str(tmp_path), "--no-uv-fallback", "--schedule", "unused.json"]
        )

        assert exit_code == 1
        assert captured == {}
        assert "Enable uv fallback" in capsys.readouterr().err

    def test_missing_path_does_not_check_cwd_instead(self, tmp_path, monkeypatch, captured, capsys):
        """A nonexistent path must not fall back to a setup.py in the cwd."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")

        exit_code = phep3_main.main(["does-not-exist", "--schedule", "unused.json"])

        assert exit_code == 1
        assert captured == {}
        assert "File not found: does-not-exist" in capsys.readouterr().err

    def test_missing_pyproject_in_missing_directory_fails(self, tmp_path, captured, capsys):
        missing = tmp_path / "missing" / "pyproject.toml"

        exit_code = phep3_main.main([str(missing), "--schedule", "unused.json"])

        assert exit_code == 1
        assert captured == {}
        assert f"File not found: {missing}" in capsys.readouterr().err


class TestScheduleSelection:
    """Tests for which schedule.json the CLI uses when --schedule is not given."""

    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        """A PEP 621 project, run from a cwd with no schedule.json."""
        monkeypatch.chdir(tmp_path)
        project = tmp_path / "pkg"
        project.mkdir()
        (project / "pyproject.toml").write_text(PEP621_PYPROJECT)
        return project

    def test_downloads_latest_release_schedule(self, project, monkeypatch, captured, capsys):
        downloaded = _schedule()
        printed_before_download = []

        def fake_fetch():
            # The note must already be out before a slow download starts
            printed_before_download.append(capsys.readouterr().out)
            return downloaded

        monkeypatch.setattr(phep3_main, "fetch_latest_schedule", fake_fetch)
        monkeypatch.setattr(phep3_main, "load_bundled_schedule", _fail)

        exit_code = phep3_main.main([str(project)])

        assert exit_code == 0
        assert captured["schedule"] is downloaded
        assert captured["schedule_path"] is None
        assert printed_before_download == [
            "Note: Downloading schedule.json from the latest pyhc-actions release...\n"
        ]
        assert "Could not download" not in capsys.readouterr().out

    def test_falls_back_to_bundled_schedule_when_offline(self, project, monkeypatch, captured, capsys):
        def offline():
            raise requests.ConnectionError("offline")

        bundled = _schedule()
        monkeypatch.setattr(phep3_main, "fetch_latest_schedule", offline)
        monkeypatch.setattr(phep3_main, "load_bundled_schedule", lambda: bundled)

        exit_code = phep3_main.main([str(project)])

        assert exit_code == 0
        assert captured["schedule"] is bundled
        out = capsys.readouterr().out
        assert "(ConnectionError)" in out
        assert "bundled with pyhc-actions (generated 2026-11-01)" in out

    def test_falls_back_to_bundled_schedule_on_invalid_download(self, project, monkeypatch, captured):
        def invalid():
            raise KeyError("release_date")

        bundled = _schedule()
        monkeypatch.setattr(phep3_main, "fetch_latest_schedule", invalid)
        monkeypatch.setattr(phep3_main, "load_bundled_schedule", lambda: bundled)

        assert phep3_main.main([str(project)]) == 0
        assert captured["schedule"] is bundled

    def test_no_schedule_when_offline_and_nothing_bundled(self, project, monkeypatch, captured):
        def offline():
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(phep3_main, "fetch_latest_schedule", offline)
        monkeypatch.setattr(phep3_main, "load_bundled_schedule", lambda: None)

        assert phep3_main.main([str(project)]) == 0
        assert captured["schedule"] is None
        assert captured["schedule_path"] is None

    def test_offline_check_still_covers_core_packages(self, project, monkeypatch, capsys):
        """End to end: offline runs use the bundled copy instead of skipping core checks."""
        def offline():
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(phep3_main, "fetch_latest_schedule", offline)

        phep3_main.main([str(project)])

        out = capsys.readouterr().out
        assert "bundled with pyhc-actions" in out
        assert "No schedule.json found" not in out

    def test_local_schedule_in_cwd_skips_download(self, project, captured):
        Path("schedule.json").write_text("{}")

        assert phep3_main.main([str(project)]) == 0
        assert captured["schedule_path"] == Path("schedule.json")
        assert captured["schedule"] is None

    def test_local_schedule_next_to_legacy_project_skips_download(self, project, captured):
        (project / "pyproject.toml").unlink()
        (project / "setup.py").write_text("from setuptools import setup\nsetup()\n")
        (project / "schedule.json").write_text("{}")

        assert phep3_main.main([str(project)]) == 0
        assert captured["pyproject_path"] == project
        assert captured["schedule_path"] == project / "schedule.json"


class TestScheduleSources:
    """Tests for the downloaded and bundled schedule.json loaders."""

    def test_fetch_latest_schedule(self, monkeypatch):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return _schedule().to_dict()

        calls = []

        def fake_get(url, timeout):
            calls.append((url, timeout))
            return FakeResponse()

        monkeypatch.setattr(schedule_module.requests, "get", fake_get)

        schedule = schedule_module.fetch_latest_schedule()

        # Short (connect, read) timeouts so an unresponsive server falls back quickly
        assert calls == [(schedule_module.SCHEDULE_RELEASE_URL, (5, 10))]
        assert schedule.generated_at == datetime(2026, 11, 1, tzinfo=timezone.utc)

    def test_bundled_schedule_prefers_package_data(self, tmp_path, monkeypatch):
        generated_at = datetime(2001, 1, 1, tzinfo=timezone.utc)
        _schedule(generated_at).save(tmp_path / "schedule.json")
        monkeypatch.setattr(schedule_module, "files", lambda _package: tmp_path)

        assert schedule_module.load_bundled_schedule().generated_at == generated_at

    def test_bundled_schedule_from_source_checkout(self):
        """Editable installs and source checkouts read the repository root copy."""
        expected = Schedule.from_file(REPO_ROOT / "schedule.json")

        assert schedule_module.load_bundled_schedule().generated_at == expected.generated_at

    def test_wheel_ships_schedule_json(self):
        """load_bundled_schedule() looks for the file where the wheel puts it."""
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            wheel_config = tomllib.load(f)["tool"]["hatch"]["build"]["targets"]["wheel"]

        assert wheel_config["force-include"] == {
            "schedule.json": "pyhc_actions/phep3/schedule.json"
        }
