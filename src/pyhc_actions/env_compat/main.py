"""CLI entry point for PyHC Environment compatibility checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.env_compat.uv_resolver import check_compatibility, find_uv
from pyhc_actions.env_compat.fetcher import PYHC_REQUIREMENTS_URL


def main(args: list[str] | None = None) -> int:
    """Main entry point for PyHC compatibility checker.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Check package compatibility with PyHC Environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Check ./pyproject.toml
  %(prog)s path/to/pyproject.toml       # Check specific file
  %(prog)s --requirements local.txt     # Use local requirements file
        """,
    )

    parser.add_argument(
        "project_file",
        nargs="?",
        default="pyproject.toml",
        help="Path to pyproject.toml file (default: pyproject.toml)",
    )

    parser.add_argument(
        "--requirements",
        "-r",
        default=None,
        help=f"Path or URL to PyHC requirements.txt (default: {PYHC_REQUIREMENTS_URL})",
    )

    parser.add_argument(
        "--check-uv",
        action="store_true",
        help="Only check if uv is installed and exit",
    )

    parsed_args = parser.parse_args(args)

    # Check if uv is available
    if parsed_args.check_uv:
        uv_path = find_uv()
        if uv_path:
            print(f"uv found at: {uv_path}")
            return 0
        else:
            print("uv not found")
            print("Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
            return 1

    # Check that project file exists
    project_path = Path(parsed_args.project_file)
    if not project_path.exists():
        print(f"Error: File not found: {project_path}", file=sys.stderr)
        return 1

    # Create reporter
    reporter = Reporter(title="PyHC Environment Compatibility Check")
    reporter.set_file_path(str(project_path))

    # Run compatibility check
    is_compatible, conflicts = check_compatibility(
        pyproject_path=project_path,
        pyhc_requirements_source=parsed_args.requirements,
        reporter=reporter,
    )

    # Output results
    reporter.print_report()
    reporter.write_github_summary()

    return 0 if is_compatible else 1


if __name__ == "__main__":
    sys.exit(main())
