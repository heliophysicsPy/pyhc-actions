"""CLI entry point for PyHC Environment compatibility checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyhc_actions.common.reporter import Reporter
from pyhc_actions.env_compat.uv_resolver import (
    check_compatibility,
    find_uv,
    discover_optional_extras,
)
from pyhc_actions.env_compat.fetcher import (
    PYHC_REQUIREMENTS_URL,
    load_pyhc_requirements,
    get_pyhc_python_version,
)


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
    parser.add_argument(
        "--extras",
        default="auto",
        help=(
            "Extras selection: 'auto' (default) runs base + each extra + 'all' if defined; "
            "'none' runs base only; or provide a comma-separated list of extras to check."
        ),
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
        # If pyproject.toml doesn't exist, check for setup.py/setup.cfg
        # The checker can extract metadata from these using the project directory
        project_dir = project_path.parent if project_path.name == "pyproject.toml" else Path(".")
        setup_py = project_dir / "setup.py"
        setup_cfg = project_dir / "setup.cfg"

        if setup_py.exists() or setup_cfg.exists():
            # Pass project directory instead of pyproject.toml path
            project_path = project_dir
        else:
            print(f"Error: File not found: {project_path}", file=sys.stderr)
            print(f"Hint: No setup.py or setup.cfg found for fallback", file=sys.stderr)
            return 1

    # Create reporter
    reporter = Reporter(title="PyHC Environment Compatibility Check")
    reporter.set_file_path(str(project_path))

    # Pre-load PyHC requirements once to avoid repeated downloads
    try:
        pyhc_requirements = load_pyhc_requirements(parsed_args.requirements)
    except Exception as e:
        reporter.add_error(
            package="pyhc-requirements",
            message=f"Failed to load PyHC requirements: {e}",
            context="base",
        )
        reporter.print_report()
        reporter.write_github_summary()
        return 1

    pyhc_python = get_pyhc_python_version()

    # Discover extras
    optional_extras = discover_optional_extras(project_path)

    # Resolve extras selection
    extras_arg = (parsed_args.extras or "auto").strip().lower()
    extras_to_check: list[str] = []

    if extras_arg in {"none", "base", "no"}:
        extras_to_check = []
    elif extras_arg == "auto":
        extras_to_check = [e for e in optional_extras if e != "all"]
        if "all" in optional_extras:
            extras_to_check.append("all")
    else:
        requested = [e.strip() for e in parsed_args.extras.split(",") if e.strip()]
        unknown = [e for e in requested if e not in optional_extras]
        if unknown:
            reporter.add_error(
                package="extras",
                message="Unknown extras requested",
                details=", ".join(sorted(unknown)),
                suggestion="Check [project.optional-dependencies] names",
                context="config",
            )
        extras_to_check = [e for e in requested if e in optional_extras]

    # Run compatibility checks
    overall_compatible = True

    # Always run base check
    is_compatible, _ = check_compatibility(
        pyproject_path=project_path,
        pyhc_requirements=pyhc_requirements,
        pyhc_python=pyhc_python,
        extra=None,
        context="base",
        report_as_warning=False,
        reporter=reporter,
    )
    overall_compatible = overall_compatible and is_compatible

    # Run per-extra checks
    for extra in extras_to_check:
        is_compatible, _ = check_compatibility(
            pyproject_path=project_path,
            pyhc_requirements=pyhc_requirements,
            pyhc_python=pyhc_python,
            extra=extra,
            context=extra,
            report_as_warning=True,
            reporter=reporter,
        )

    # Output results
    reporter.print_report()
    reporter.write_github_summary()

    return 0 if overall_compatible and not reporter.has_errors else 1


if __name__ == "__main__":
    sys.exit(main())
