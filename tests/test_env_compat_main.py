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
    monkeypatch.setattr(env_main, "load_pyhc_requirements", lambda _p: [])
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
    monkeypatch.setattr(env_main, "load_pyhc_requirements", lambda _p: [])
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
    monkeypatch.setattr(env_main, "load_pyhc_requirements", lambda _p: [])
    monkeypatch.setattr(env_main, "get_pyhc_python_version", lambda: "3.12.0")
    monkeypatch.setattr(env_main.Reporter, "print_report", lambda _self: None)
    monkeypatch.setattr(env_main.Reporter, "write_github_summary", lambda _self: None)

    exit_code = env_main.main([str(pyproject), "--extras", "foo,bogus"])

    assert exit_code == 1
    assert calls == [None, "foo"]
