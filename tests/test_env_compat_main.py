"""Tests for the pyhc-env-compat-check CLI entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyhc_actions.env_compat import main as env_main
from pyhc_actions.env_compat.uv_resolver import Conflict, ConflictOrigin


def _write_min_pyproject(path: Path) -> None:
    path.write_text(
        """
[project]
name = "demo"
"""
    )


def test_main_extras_auto(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)

    calls: list[str | None] = []

    def fake_check_compatibility(*, extra=None, **_kwargs):
        calls.append(extra)
        return True, []

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: ["bar", "all", "foo"])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "auto"])

    assert exit_code == 0
    assert calls == [None, "bar", "foo", "all"]


def test_main_extras_none(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)

    calls: list[str | None] = []

    def fake_check_compatibility(*, extra=None, **_kwargs):
        calls.append(extra)
        return True, []

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: ["bar", "all", "foo"])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "none"])

    assert exit_code == 0
    assert calls == [None]


def test_main_skips_extras_when_pyhc_baseline_is_unavailable(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)

    calls: list[str | None] = []

    def fake_check_compatibility(*, extra=None, **_kwargs):
        calls.append(extra)
        return False, [
            Conflict(
                package="vanished-child",
                your_requirement="(not involved)",
                pyhc_requirement="PyHC Environment baseline",
                reason="PyHC Environment baseline could not be resolved",
                origin=ConflictOrigin.PYHC_ENVIRONMENT,
            )
        ]

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: ["foo", "bar"])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "auto"])

    assert exit_code == 1
    assert calls == [None]


def test_main_extras_unknown(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)

    calls: list[str | None] = []

    def fake_check_compatibility(*, extra=None, **_kwargs):
        calls.append(extra)
        return True, []

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: ["foo"])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "foo,bogus"])

    assert exit_code == 1
    assert calls == [None, "foo"]


def test_main_writes_conflicts_output_on_success(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    def fake_check_compatibility(*, extra=None, **_kwargs):
        if extra is None:
            return True, []
        if extra == "foo":
            return False, ["c1", "c2"]
        if extra == "bar":
            return False, ["c3"]
        return True, []

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: ["foo", "bar"])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "auto"])

    assert exit_code == 0
    assert github_output.exists()
    assert "conflicts=3" in github_output.read_text().splitlines()


def test_main_does_not_write_conflicts_output_on_failure(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    def fake_check_compatibility(*, extra=None, **_kwargs):
        if extra is None:
            return False, ["c1"]
        return True, []

    monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
    monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "none"])

    assert exit_code == 1
    assert not github_output.exists()


def test_main_fails_when_constraints_load_fails(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    _write_min_pyproject(pyproject)

    monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
    monkeypatch.setattr(
        env_main,
        "load_pyhc_constraints",
        lambda _p: (_ for _ in ()).throw(RuntimeError("constraints boom")),
    )
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject)])
    assert exit_code == 1


SETUP_PY = "from setuptools import setup\nsetup()\n"


class TestProjectPathResolution:
    """Tests for how the project_file argument is resolved."""

    @pytest.fixture
    def checked_paths(self, monkeypatch):
        """Stub out resolution and record the project paths main() checks."""
        paths: list[Path] = []

        def fake_check_compatibility(*, pyproject_path, **_kwargs):
            paths.append(pyproject_path)
            return True, []

        monkeypatch.setattr(env_main, "check_compatibility", fake_check_compatibility)
        monkeypatch.setattr(env_main, "discover_optional_extras", lambda _p: [])
        monkeypatch.setattr(env_main, "load_pyhc_packages", lambda _p: [])
        monkeypatch.setattr(env_main, "load_pyhc_constraints", lambda _p: [])
        monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
        monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
        monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)
        return paths

    def test_directory_uses_its_pyproject(self, tmp_path, checked_paths):
        _write_min_pyproject(tmp_path / "pyproject.toml")

        exit_code = env_main.main([str(tmp_path)])

        assert exit_code == 0
        assert checked_paths == [tmp_path / "pyproject.toml"]

    def test_directory_with_setup_py_uses_project_dir(self, tmp_path, checked_paths):
        (tmp_path / "setup.py").write_text(SETUP_PY)

        exit_code = env_main.main([str(tmp_path)])

        assert exit_code == 0
        assert checked_paths == [tmp_path]

    def test_missing_pyproject_falls_back_to_setup_cfg_beside_it(self, tmp_path, checked_paths):
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = demo\n")

        exit_code = env_main.main([str(tmp_path / "pyproject.toml")])

        assert exit_code == 0
        assert checked_paths == [tmp_path]

    def test_default_path_in_setup_py_project_uses_cwd(self, tmp_path, monkeypatch, checked_paths):
        """setup.py-only projects work with the default argument, as in the GitHub Action."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "setup.py").write_text(SETUP_PY)

        exit_code = env_main.main([])

        assert exit_code == 0
        assert checked_paths == [Path(".")]

    def test_empty_directory_fails(self, tmp_path, checked_paths, capsys):
        exit_code = env_main.main([str(tmp_path)])

        assert exit_code == 1
        assert checked_paths == []
        err = capsys.readouterr().err
        assert "No packaging metadata found" in err
        assert "pyproject.toml, setup.py, or setup.cfg" in err

    def test_default_path_in_empty_directory_fails(self, tmp_path, monkeypatch, checked_paths, capsys):
        monkeypatch.chdir(tmp_path)

        exit_code = env_main.main([])

        assert exit_code == 1
        assert checked_paths == []
        assert "No packaging metadata found" in capsys.readouterr().err

    def test_missing_path_does_not_check_cwd_instead(self, tmp_path, monkeypatch, checked_paths, capsys):
        """A typo'd path must not fall back to a setup.py in the cwd."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "setup.py").write_text(SETUP_PY)

        exit_code = env_main.main(["does-not-exist"])

        assert exit_code == 1
        assert checked_paths == []
        assert "File not found: does-not-exist" in capsys.readouterr().err

    def test_missing_pyproject_in_missing_directory_fails(self, tmp_path, checked_paths, capsys):
        missing = tmp_path / "missing" / "pyproject.toml"

        exit_code = env_main.main([str(missing)])

        assert exit_code == 1
        assert checked_paths == []
        assert f"File not found: {missing}" in capsys.readouterr().err
