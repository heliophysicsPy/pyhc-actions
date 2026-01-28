"""Tests for reporter utilities."""

import pytest
from io import StringIO

from pyhc_actions.common.reporter import (
    Reporter,
    Violation,
    Warning,
    Issue,
    Severity,
)


class TestIssue:
    """Tests for Issue class."""

    def test_violation_severity(self):
        """Test that violations have ERROR severity."""
        v = Violation(package="test", message="Test error")
        assert v.severity == Severity.ERROR

    def test_warning_severity(self):
        """Test that warnings have WARNING severity."""
        w = Warning(package="test", message="Test warning")
        assert w.severity == Severity.WARNING

    def test_format_plain(self):
        """Test plain text formatting."""
        v = Violation(
            package="numpy",
            message="Version too old",
            details="numpy 1.19 is >24 months old",
            suggestion="numpy>=1.26",
        )
        formatted = v.format_plain()
        assert "[ERROR]" in formatted
        assert "Version too old" in formatted
        assert "numpy 1.19" in formatted
        assert "Suggested: numpy>=1.26" in formatted

    def test_format_github(self):
        """Test GitHub annotation formatting."""
        v = Violation(
            package="numpy",
            message="Version too old",
            details="numpy 1.19 is >24 months old",
        )
        formatted = v.format_github("pyproject.toml")
        assert "::error" in formatted
        assert "file=pyproject.toml" in formatted
        assert "numpy" in formatted


class TestReporter:
    """Tests for Reporter class."""

    def test_add_error(self):
        """Test adding errors."""
        reporter = Reporter()
        reporter.add_error(package="numpy", message="Test error")
        assert len(reporter.errors) == 1
        assert reporter.has_errors is True

    def test_add_warning(self):
        """Test adding warnings."""
        reporter = Reporter()
        reporter.add_warning(package="numpy", message="Test warning")
        assert len(reporter.warnings) == 1
        assert reporter.has_warnings is True

    def test_no_issues(self):
        """Test reporter with no issues."""
        reporter = Reporter()
        assert reporter.has_errors is False
        assert reporter.has_warnings is False

    def test_exit_code_success(self):
        """Test exit code for success."""
        reporter = Reporter()
        assert reporter.get_exit_code() == 0

    def test_exit_code_error(self):
        """Test exit code for errors."""
        reporter = Reporter()
        reporter.add_error(package="test", message="error")
        assert reporter.get_exit_code() == 1

    def test_exit_code_warning_default(self):
        """Test exit code for warnings (default: success)."""
        reporter = Reporter()
        reporter.add_warning(package="test", message="warning")
        assert reporter.get_exit_code() == 0

    def test_exit_code_warning_fail(self):
        """Test exit code for warnings with fail_on_warning."""
        reporter = Reporter()
        reporter.add_warning(package="test", message="warning")
        assert reporter.get_exit_code(fail_on_warning=True) == 1

    def test_print_report(self):
        """Test printing report."""
        output = StringIO()
        reporter = Reporter(title="Test Report", output=output, github_actions=False)
        reporter.add_error(package="numpy", message="Test error")
        reporter.add_warning(package="scipy", message="Test warning")
        reporter.print_report()

        result = output.getvalue()
        assert "Test Report" in result
        assert "ERRORS:" in result
        assert "WARNINGS:" in result
        assert "Test error" in result
        assert "Test warning" in result
        assert "Status: FAILED" in result

    def test_print_report_passing(self):
        """Test printing report when passing."""
        output = StringIO()
        reporter = Reporter(title="Test Report", output=output, github_actions=False)
        reporter.print_report()

        result = output.getvalue()
        assert "Status: PASSED" in result
