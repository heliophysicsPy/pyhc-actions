"""CLI entry point for PHEP 3 compliance checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyhc_actions.phep3.checker import check_pyproject


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
  %(prog)s --fail-on-warning        # Treat warnings as errors
  %(prog)s --no-adoption-check      # Skip 6-month adoption check
        """,
    )

    parser.add_argument(
        "project_file",
        nargs="?",
        default="pyproject.toml",
        help="Path to pyproject.toml file (default: pyproject.toml)",
    )

    parser.add_argument(
        "--schedule",
        "-s",
        default=None,
        help="Path to schedule.json file with version release dates",
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
        help="Disable uv-based metadata extraction for legacy formats",
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

    parsed_args = parser.parse_args(args)

    # Handle schedule generation
    if parsed_args.generate_schedule:
        from pyhc_actions.phep3.pypi_fetcher import update_schedule_file

        update_schedule_file(parsed_args.schedule_output)
        return 0

    # Check that project file exists
    project_path = Path(parsed_args.project_file)
    if not project_path.exists():
        print(f"Error: File not found: {project_path}", file=sys.stderr)
        return 1

    # Find schedule file
    schedule_path = parsed_args.schedule
    if schedule_path is None:
        # Look for schedule.json in common locations
        candidates = [
            Path("schedule.json"),
            project_path.parent / "schedule.json",
            Path(__file__).parent.parent.parent.parent / "schedule.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                schedule_path = candidate
                break

    # Run compliance check
    passed, reporter = check_pyproject(
        pyproject_path=project_path,
        schedule_path=schedule_path,
        check_adoption=not parsed_args.no_adoption_check,
        fail_on_warning=parsed_args.fail_on_warning,
        use_uv_fallback=not parsed_args.no_uv_fallback,
    )

    # Output results
    reporter.print_report()
    reporter.write_github_summary()

    return reporter.get_exit_code(fail_on_warning=parsed_args.fail_on_warning)


if __name__ == "__main__":
    sys.exit(main())
