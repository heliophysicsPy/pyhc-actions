"""PHEP 3 configuration constants."""

# Support windows as defined by PHEP 3
# Python versions supported for 36 months after release
PYTHON_SUPPORT_MONTHS = 36

# Core Scientific Python packages supported for 24 months after release
PACKAGE_SUPPORT_MONTHS = 24

# New versions must be adopted within 6 months of release
ADOPTION_MONTHS = 6

# Core Scientific Python packages covered by PHEP 3 / SPEC 0
# From: https://scientific-python.org/specs/core-projects/
CORE_PACKAGES = frozenset([
    "numpy",
    "scipy",
    "matplotlib",
    "pandas",
    "scikit-image",
    "networkx",
    "scikit-learn",
    "xarray",
    "ipython",
    "zarr",
])

# Normalized names for core packages (for matching)
CORE_PACKAGES_NORMALIZED = frozenset([
    name.lower().replace("-", "_") for name in CORE_PACKAGES
])

# Known Python release dates (from PHEP 3)
# Updated periodically; can be supplemented by schedule.json
PYTHON_RELEASES = {
    "3.9": "2020-10-05",
    "3.10": "2021-10-04",
    "3.11": "2022-10-24",
    "3.12": "2023-10-02",
    "3.13": "2024-10-07",
    "3.14": "2025-10-07",  # Expected
}


def normalize_package_name(name: str) -> str:
    """Normalize a package name for comparison.

    PEP 503: Names should be lowercased with runs of underscores,
    hyphens, and periods replaced with a single hyphen.

    Args:
        name: Package name to normalize

    Returns:
        Normalized package name
    """
    return name.lower().replace("_", "-").replace(".", "-")


def is_core_package(name: str) -> bool:
    """Check if a package is a core Scientific Python package.

    Args:
        name: Package name to check

    Returns:
        True if the package is a core package
    """
    normalized = normalize_package_name(name)
    # Also check with underscores for packages like scikit_image
    alt_normalized = name.lower().replace("-", "_").replace(".", "_")

    return normalized in [normalize_package_name(p) for p in CORE_PACKAGES] or alt_normalized in CORE_PACKAGES_NORMALIZED
