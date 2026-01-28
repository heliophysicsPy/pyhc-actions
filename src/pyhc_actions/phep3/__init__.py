"""PHEP 3 compliance checker."""

from pyhc_actions.phep3.checker import check_compliance
from pyhc_actions.phep3.config import CORE_PACKAGES, PYTHON_SUPPORT_MONTHS, PACKAGE_SUPPORT_MONTHS, ADOPTION_MONTHS

__all__ = [
    "check_compliance",
    "CORE_PACKAGES",
    "PYTHON_SUPPORT_MONTHS",
    "PACKAGE_SUPPORT_MONTHS",
    "ADOPTION_MONTHS",
]
