"""Metadata extraction for non-PEP 621 project formats using uv."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyhc_actions.phep3.schedule import Schedule


@dataclass
class PackageMetadata:
    """Extracted package metadata."""

    name: str
    requires_python: str | None
    dependencies: list[str]
    optional_dependencies: dict[str, list[str]]
    extracted_via: str  # "pyproject.toml", "setup.py", "uv", etc.


def check_uv_available() -> bool:
    """Check if uv is available in PATH."""
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_min_phep3_python(schedule: "Schedule") -> str:
    """Get the oldest non-droppable Python version from schedule.

    Args:
        schedule: Schedule with Python version info

    Returns:
        Python version string (e.g., "3.12") or "3.12" as fallback
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    min_version = schedule.get_minimum_python_version(now)
    return min_version or "3.12"


def extract_metadata_with_uv(
    project_path: Path | str,
    python_version: str | None = None,
) -> PackageMetadata | None:
    """Extract package metadata using uv.

    This works for projects without PEP 621 metadata (setup.py, setup.cfg, Poetry) by:
    1. Creating a temporary venv with a specific Python version
    2. Installing the package without dependencies
    3. Reading metadata via importlib.metadata

    Args:
        project_path: Path to the project directory
        python_version: Python version to use (e.g., "3.10")

    Returns:
        PackageMetadata or None if extraction fails
    """
    project_path = Path(project_path)

    if not check_uv_available():
        return None

    python_version = python_version or "3.12"

    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / ".venv"

        # Create venv with specific Python
        try:
            result = subprocess.run(
                ["uv", "venv", "--python", python_version, str(venv_path)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(project_path),
            )
            if result.returncode != 0:
                return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        # Capture .dist-info directories BEFORE install
        # We use set difference (before vs after) to find the newly installed package.
        # This is more reliable than sorting by mtime, which can be wrong in seeded
        # venvs, concurrent installs, or when tools touch metadata post-install.
        list_dists_script = """
import os, sys, json
site_packages = [p for p in sys.path if 'site-packages' in p]
if site_packages:
    dists = [d for d in os.listdir(site_packages[0]) if d.endswith('.dist-info')]
    print(json.dumps(dists))
else:
    print(json.dumps([]))
"""
        try:
            result = subprocess.run(
                [str(venv_path / "bin" / "python"), "-c", list_dists_script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            dists_before = set(json.loads(result.stdout)) if result.returncode == 0 else set()
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            dists_before = set()

        # Install package without dependencies
        try:
            result = subprocess.run(
                [
                    "uv", "pip", "install",
                    "--no-deps",
                    "--python", str(venv_path / "bin" / "python"),
                    str(project_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(project_path),
            )
            if result.returncode != 0:
                return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        # Extract metadata using Python
        # Pass the "before" set so the script can find the newly installed package
        dists_before_json = json.dumps(list(dists_before))
        extract_script = f"""
import json
import sys
DISTS_BEFORE = set(json.loads('''{dists_before_json}'''))
try:
    from importlib.metadata import metadata, requires
    import os
    site_packages = [p for p in sys.path if 'site-packages' in p][0]
    dists_after = set(d for d in os.listdir(site_packages) if d.endswith('.dist-info'))

    # Find the newly installed package by set difference
    new_dists = dists_after - DISTS_BEFORE
    if not new_dists:
        print(json.dumps({{"error": "No new package found after install"}}))
        sys.exit(1)

    # Get package name from the new dist-info (format: NAME-VERSION.dist-info)
    new_dist = list(new_dists)[0]
    name_version = new_dist.replace('.dist-info', '')
    pkg_name = name_version.rsplit('-', 1)[0].replace('_', '-')

    meta = metadata(pkg_name)
    reqs = requires(pkg_name) or []

    # Separate optional dependencies
    main_deps = []
    optional_deps = {{}}
    for req in reqs:
        if ';' in req and 'extra' in req:
            # Parse extra name
            import re
            match = re.search(r'extra\\s*==\\s*[' + "'" + r'"]([^' + "'" + r'"]+)[' + "'" + r'"]', req)
            if match:
                extra_name = match.group(1)
                # Remove the marker
                dep = req.split(';')[0].strip()
                if extra_name not in optional_deps:
                    optional_deps[extra_name] = []
                optional_deps[extra_name].append(dep)
            else:
                main_deps.append(req.split(';')[0].strip())
        elif ';' in req:
            # Has marker but not extra
            main_deps.append(req.split(';')[0].strip())
        else:
            main_deps.append(req)

    print(json.dumps({{
        "name": meta.get("Name", pkg_name),
        "requires_python": meta.get("Requires-Python"),
        "dependencies": main_deps,
        "optional_dependencies": optional_deps,
    }}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
    sys.exit(1)
"""

        try:
            result = subprocess.run(
                [str(venv_path / "bin" / "python"), "-c", extract_script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)
            if "error" in data:
                return None

            return PackageMetadata(
                name=data.get("name", ""),
                requires_python=data.get("requires_python"),
                dependencies=data.get("dependencies", []),
                optional_dependencies=data.get("optional_dependencies", {}),
                extracted_via="uv",
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None


def extract_metadata_from_project(
    project_path: Path | str,
    schedule: "Schedule | None" = None,
) -> PackageMetadata | None:
    """Extract metadata from a project, trying multiple methods.

    Attempts extraction in order:
    1. PEP 621 pyproject.toml
    2. uv-based extraction (for projects without PEP 621 metadata)

    Args:
        project_path: Path to project directory or pyproject.toml
        schedule: Optional schedule for determining Python version

    Returns:
        PackageMetadata or None if all methods fail
    """
    project_path = Path(project_path)

    # If given a file path, get the directory
    if project_path.is_file():
        project_dir = project_path.parent
        pyproject_path = project_path
    else:
        project_dir = project_path
        pyproject_path = project_dir / "pyproject.toml"

    # Try PEP 621 pyproject.toml first
    if pyproject_path.exists():
        from pyhc_actions.common.parser import (
            parse_pyproject,
            get_dependencies_from_pyproject,
        )

        try:
            pyproject_data = parse_pyproject(pyproject_path)
            project = pyproject_data.get("project", {})

            # Check if it has the [project] section (PEP 621)
            if project:
                name = project.get("name", "")
                requires_python = project.get("requires-python")

                # Get dependencies
                deps = project.get("dependencies", [])
                optional_deps = project.get("optional-dependencies", {})

                return PackageMetadata(
                    name=name,
                    requires_python=requires_python,
                    dependencies=deps,
                    optional_dependencies=optional_deps,
                    extracted_via="pyproject.toml",
                )
        except Exception:
            pass

    # Try uv-based extraction (no PEP 621 metadata found)
    python_version = None
    if schedule:
        python_version = get_min_phep3_python(schedule)

    return extract_metadata_with_uv(project_dir, python_version)
