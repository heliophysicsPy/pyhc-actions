"""Tests for env_compat main extras handling."""

from __future__ import annotations

from pathlib import Path

from pyhc_actions.env_compat import main as env_main


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
