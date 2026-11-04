"""CLI entry point for PHEP 3 compliance checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from pyhc_actions.phep3.checker import check_pyproject
from pyhc_actions.phep3.schedule import (
    Schedule,
    fetch_latest_schedule,
    load_bundled_schedule,
)


def _load_default_schedule() -> Schedule | None:
    """Load the schedule to use when no --schedule or local schedule.json is given.

    Mirrors the GitHub Action: download the schedule.json published with the
    latest pyhc-actions release, falling back to the copy that ships with
    pyhc-actions when the download fails (e.g. offline).

    Returns:
        Schedule, or None if neither source is available
    """
    # Flushed so a slow network doesn't look like a hang when stdout is piped
    print("Note: Downloading schedule.json from the latest pyhc-actions release...", flush=True)
    try:
        schedule = fetch_latest_schedule()
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        reason = type(e).__name__
        schedule = load_bundled_schedule()
        if schedule is None:
            print(f"Note: Could not download schedule.json ({reason}).")
        else:
            print(
                f"Note: Could not download the latest schedule.json ({reason}); "
                f"using the copy bundled with pyhc-actions "
                f"(generated {schedule.generated_at:%Y-%m-%d})."
            )
    return schedule


def main(args: list[str] | None = None) -> int:
    """Main entry point for PHEP 3 compliance checker.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Check pyproject.toml compliance with PHEP 3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Check ./pyproject.toml
  %(prog)s path/to/pyproject.toml   # Check specific file
  %(prog)s path/to/project          # Check a project directory
  %(prog)s --fail-on-warning        # Treat warnings as errors
  %(prog)s --no-adoption-check      # Skip 6-month adoption check
        """,
    )

    parser.add_argument(
        "project_file",
        nargs="?",
        default="pyproject.toml",
        help="Path to pyproject.toml file or project directory (default: pyproject.toml)",
    )

    parser.add_argument(
        "--schedule",
        "-s",
        default=None,
        help=(
            "Path to schedule.json file with version release dates "
            "(default: ./schedule.json or one next to the project if present, "
            "else the latest pyhc-actions release's copy)"
        ),
    )

    parser.add_argument(
        "--fail-on-warning",
        "-w",
        action="store_true",
        help="Treat warnings as errors (return non-zero exit code)",
    )

    parser.add_argument(
        "--no-adoption-check",
        action="store_true",
        help="Skip checking 6-month adoption rule for new versions",
    )

    parser.add_argument(
        "--no-uv-fallback",
        action="store_true",
        help="Disable uv-based metadata extraction for projects with non-PEP 621 metadata",
    )

    parser.add_argument(
        "--generate-schedule",
        action="store_true",
        help="Generate/update schedule.json from PyPI (requires network)",
    )

    parser.add_argument(
        "--schedule-output",
        default="schedule.json",
        help="Output path for generated schedule (default: schedule.json)",
    )

    parser.add_argument(
        "--ignore-errors-for",
        default="",
        help="Comma-separated list of package names to treat errors as warnings",
    )

    parsed_args = parser.parse_args(args)

    # Handle schedule generation
    if parsed_args.generate_schedule:
        from pyhc_actions.phep3.pypi_fetcher import update_schedule_file

        update_schedule_file(parsed_args.schedule_output)
        return 0

    # Check that project file exists (a directory means its pyproject.toml)
    project_path = Path(parsed_args.project_file)
    if project_path.is_dir():
        project_dir = project_path
        project_path = project_dir / "pyproject.toml"
    elif project_path.name == "pyproject.toml":
        project_dir = project_path.parent
    else:
        project_dir = None

    if not project_path.exists():
        # If pyproject.toml doesn't exist, try fallback to setup.py/setup.cfg
        has_setup_files = project_dir is not None and (
            (project_dir / "setup.py").exists() or (project_dir / "setup.cfg").exists()
        )

        if has_setup_files and not parsed_args.no_uv_fallback:
            # uv fallback enabled and legacy packaging files (setup.py/setup.cfg) exist
            # Pass project directory to checker instead of pyproject.toml path
            project_path = project_dir
        elif has_setup_files:
            print(f"Error: File not found: {project_path}", file=sys.stderr)
            print("Hint: Enable uv fallback to support setup.py/setup.cfg", file=sys.stderr)
            return 1
        elif project_dir is not None and project_dir.is_dir():
            print(
                f"Error: No packaging metadata found in {project_dir.resolve()}",
                file=sys.stderr,
            )
            print("Hint: Expected pyproject.toml, setup.py, or setup.cfg", file=sys.stderr)
            return 1
        else:
            print(f"Error: File not found: {project_path}", file=sys.stderr)
            return 1

    # Find schedule file
    schedule_path = parsed_args.schedule
    schedule = None
    if schedule_path is None:
        # Look for a local schedule.json (e.g. from --generate-schedule) first
        project_dir = project_path if project_path.is_dir() else project_path.parent
        candidates = [
            Path("schedule.json"),
            project_dir / "schedule.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                schedule_path = candidate
                break
        else:
            schedule = _load_default_schedule()

    # Parse ignore-errors-for into a set of normalized package names
    ignore_errors_for: set[str] = set()
    if parsed_args.ignore_errors_for:
        ignore_errors_for = {
            name.strip().lower()
            for name in parsed_args.ignore_errors_for.split(",")
            if name.strip()
        }

    # Run compliance check
    passed, reporter = check_pyproject(
        pyproject_path=project_path,
        schedule_path=schedule_path,
        check_adoption=not parsed_args.no_adoption_check,
        fail_on_warning=parsed_args.fail_on_warning,
        use_uv_fallback=not parsed_args.no_uv_fallback,
        ignore_errors_for=ignore_errors_for,
        schedule=schedule,
    )

    # Output results
    reporter.print_report()
    reporter.write_github_summary()

    return reporter.get_exit_code(fail_on_warning=parsed_args.fail_on_warning)


if __name__ == "__main__":
    sys.exit(main())
