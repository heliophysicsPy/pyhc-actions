"""Reporter utilities for GitHub Actions output formatting."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import TextIO


class Severity(Enum):
    """Severity level for issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Issue:
    """Represents a compliance issue."""

    severity: Severity
    package: str
    message: str
    details: str = ""
    suggestion: str = ""

    def format_plain(self) -> str:
        """Format issue for plain text output."""
        prefix = {
            Severity.ERROR: "[ERROR]",
            Severity.WARNING: "[WARN]",
            Severity.INFO: "[INFO]",
        }[self.severity]

        lines = [f"{prefix} {self.message}"]
        if self.details:
            for detail in self.details.split("\n"):
                lines.append(f"        {detail}")
        if self.suggestion:
            lines.append(f"        Suggested: {self.suggestion}")

        return "\n".join(lines)

    def format_github(self, file_path: str = "") -> str:
        """Format issue as GitHub Actions annotation."""
        level = self.severity.value
        title = f"PHEP 3: {self.package}"
        msg = self.message
        if self.details:
            msg += f" - {self.details}"

        if file_path:
            return f"::{level} file={file_path},title={title}::{msg}"
        return f"::{level} title={title}::{msg}"


# Convenience aliases
@dataclass
class Violation(Issue):
    """A compliance error that should fail the check."""

    severity: Severity = field(default=Severity.ERROR, init=False)


@dataclass
class Warning(Issue):
    """A compliance warning that may or may not fail the check."""

    severity: Severity = field(default=Severity.WARNING, init=False)


class Reporter:
    """Formats and outputs compliance check results."""

    def __init__(
        self,
        title: str = "Compliance Check",
        github_actions: bool | None = None,
        output: TextIO | None = None,
    ):
        """Initialize the reporter.

        Args:
            title: Title for the report
            github_actions: Whether to output GitHub Actions annotations.
                           Auto-detected if None.
            output: Output stream (defaults to stdout)
        """
        self.title = title
        self.github_actions = (
            github_actions if github_actions is not None else os.environ.get("GITHUB_ACTIONS") == "true"
        )
        self.output = output or sys.stdout
        self.issues: list[Issue] = []
        self.file_path: str = ""

    def set_file_path(self, path: str):
        """Set the file path for GitHub annotations."""
        self.file_path = path

    def add_issue(self, issue: Issue):
        """Add an issue to the report."""
        self.issues.append(issue)

    def add_error(
        self, package: str, message: str, details: str = "", suggestion: str = ""
    ):
        """Add an error issue."""
        self.add_issue(
            Violation(package=package, message=message, details=details, suggestion=suggestion)
        )

    def add_warning(
        self, package: str, message: str, details: str = "", suggestion: str = ""
    ):
        """Add a warning issue."""
        self.add_issue(
            Warning(package=package, message=message, details=details, suggestion=suggestion)
        )

    @property
    def errors(self) -> list[Issue]:
        """Return all error-level issues."""
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        """Return all warning-level issues."""
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        """Return True if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Return True if there are any warnings."""
        return len(self.warnings) > 0

    def print(self, text: str = ""):
        """Print text to output stream."""
        print(text, file=self.output)

    def print_report(self):
        """Print the full report."""
        self.print(self.title)
        self.print("=" * len(self.title))
        self.print()

        if self.errors:
            self.print("ERRORS:")
            for issue in self.errors:
                self.print(issue.format_plain())
                self.print()

        if self.warnings:
            self.print("WARNINGS:")
            for issue in self.warnings:
                self.print(issue.format_plain())
                self.print()

        # Print GitHub Actions annotations
        if self.github_actions:
            for issue in self.issues:
                self.print(issue.format_github(self.file_path))

        # Print summary
        n_errors = len(self.errors)
        n_warnings = len(self.warnings)
        self.print(f"Summary: {n_errors} error(s), {n_warnings} warning(s)")

        if self.has_errors:
            self.print("Status: FAILED")
        elif self.has_warnings:
            self.print("Status: PASSED (with warnings)")
        else:
            self.print("Status: PASSED")

    def write_github_summary(self):
        """Write a job summary for GitHub Actions."""
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if not summary_file:
            return

        with open(summary_file, "a") as f:
            f.write(f"## {self.title}\n\n")

            if not self.issues:
                f.write("All checks passed.\n")
                return

            # Errors table
            if self.errors:
                f.write("### Errors\n\n")
                f.write("| Package | Issue | Suggestion |\n")
                f.write("|---------|-------|------------|\n")
                for issue in self.errors:
                    suggestion = issue.suggestion or "-"
                    f.write(f"| {issue.package} | {issue.message} | {suggestion} |\n")
                f.write("\n")

            # Warnings table
            if self.warnings:
                f.write("### Warnings\n\n")
                f.write("| Package | Issue | Suggestion |\n")
                f.write("|---------|-------|------------|\n")
                for issue in self.warnings:
                    suggestion = issue.suggestion or "-"
                    f.write(f"| {issue.package} | {issue.message} | {suggestion} |\n")
                f.write("\n")

    def get_exit_code(self, fail_on_warning: bool = False) -> int:
        """Return appropriate exit code.

        Args:
            fail_on_warning: If True, warnings also cause failure

        Returns:
            0 for success, 1 for failure
        """
        if self.has_errors:
            return 1
        if fail_on_warning and self.has_warnings:
            return 1
        return 0
