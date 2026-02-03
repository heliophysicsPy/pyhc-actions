# PyHC GitHub Actions

Reusable GitHub Actions for PyHC (Python in Heliophysics Community) package compliance checking.

## Actions

### 1. PHEP 3 Compliance Checker

Validates package requirements against [PHEP 3](https://github.com/heliophysicsPy/standards/blob/main/pheps/phep-0003.md):

- Python versions supported for **36 months** after release
- Core Scientific Python packages (numpy, scipy, matplotlib, pandas, scikit-image, networkx, scikit-learn, xarray, ipython, zarr) supported for **24 months** after release
- New versions adopted within **6 months** of release
- Warnings on max/exact constraints (e.g., `numpy<2`, `scipy==1.10`)

#### Usage

```yaml
name: PHEP 3 Compliance
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: heliophysicsPy/pyhc-actions/phep3-compliance@v1
```

#### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `project-file` | Path to pyproject.toml | `pyproject.toml` |
| `fail-on-warning` | Treat warnings as errors | `false` |
| `check-adoption` | Check 6-month adoption rule | `true` |
| `schedule-path` | Path to schedule.json | (auto-download) |
| `use-uv-fallback` | Use uv for metadata extraction from legacy formats | `true` |

#### Outputs

| Output | Description |
|--------|-------------|
| `passed` | Whether the check passed |
| `errors` | Number of errors found (not populated yet) |
| `warnings` | Number of warnings found (not populated yet) |

#### Example Output

```
PHEP 3 Compliance Check
========================

ERRORS:
[ERROR] requires-python = ">=3.13" drops support for Python 3.12 too early
        Python 3.12 must still be supported per PHEP 3
        Suggested: Change to requires-python = ">=3.12"

[ERROR] numpy<2 does not support required version 2.0
        Version 2.0 must be supported within 6 months of release
        Suggested: Update upper bound to include 2.0

WARNINGS:
[WARN] scipy<1.14 has upper bound constraint
        Upper bounds should only be used when absolutely necessary
        Suggested: Consider removing <1.14 unless required

Summary: 2 error(s), 1 warning(s)
Status: FAILED
```

### 2. PyHC Environment Compatibility Checker

Detects dependency conflicts with the [PyHC Environment](https://github.com/heliophysicsPy/pyhc-docker-environment).

Uses **[uv](https://github.com/astral-sh/uv)** for fast, accurate dependency resolution that catches transitive conflicts.

#### Usage

```yaml
name: PyHC Compatibility
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: heliophysicsPy/pyhc-actions/pyhc-env-compat@v1
```

#### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `project-file` | Path to pyproject.toml | `pyproject.toml` |
| `pyhc-requirements-url` | URL to PyHC requirements.txt | (official GitHub URL) |

#### Outputs

| Output | Description |
|--------|-------------|
| `compatible` | Whether the package is compatible |
| `conflicts` | Number of conflicts found (only set on success) |

#### Example Output

```
PyHC Environment Compatibility Check
=====================================

ERRORS:
[ERROR] Dependency conflict: numpy
        Your requirement: numpy<2.0
        PyHC Environment: numpy>=2.0,<2.3.0
        Incompatible version requirements
        Suggested: Support numpy>=2.0,<2.3.0

Summary: 1 error(s), 0 warning(s)
Status: FAILED
```

## Local Usage

You can also run the checks locally:

```bash
# Install
pip install -e .

# Run PHEP 3 check
phep3-check pyproject.toml

# Run PHEP 3 check with legacy format (setup.py/setup.cfg/Poetry) via uv fallback
phep3-check path/to/project

# Disable uv fallback
phep3-check --no-uv-fallback pyproject.toml

# Run PyHC Environment compatibility check (requires uv)
pyhc-env-compat-check pyproject.toml

# Use a local requirements.txt or alternate URL
pyhc-env-compat-check --requirements ./requirements.txt pyproject.toml

# Only check that uv is installed
pyhc-env-compat-check --check-uv

# Generate fresh schedule.json
phep3-check --generate-schedule
```

## Development

```bash
# Clone repository
git clone https://github.com/heliophysicsPy/pyhc-actions.git
cd pyhc-actions

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## Releases and Tagging

This repository follows the standard GitHub Actions versioning pattern with major version tags:

- **Specific version tags** (`v1.0.0`, `v1.0.1`, `v1.1.0`, etc.) - Immutable releases
- **Major version tag** (`v1`) - Floating tag that points to the latest v1.x.x release

### For Maintainers: Creating a New Release

When releasing a new version:

```bash
# Create and push the specific version tag
git tag v1.0.1
git push origin v1.0.1

# Update the major version tag to point to the new release
git tag -f v1 v1.0.1
git push -f origin v1

# Create the GitHub release
gh release create v1.0.1 --title "v1.0.1" --notes "Release notes here"
```

### Why Both Tags?

- Users reference `@v1` in their workflows to automatically get the latest v1.x.x updates
- The floating `v1` tag must be manually updated after each release
- Specific version tags (`v1.0.0`) remain immutable for reproducibility

## Schedule Updates

The `schedule.json` file contains release dates for Python and core Scientific Python packages. It's automatically updated monthly via GitHub Actions cron job.

To manually update:

```bash
phep3-check --generate-schedule --schedule-output schedule.json
```

## Core Scientific Python Packages

As defined by [SPEC 0](https://scientific-python.org/specs/spec-0000/):

- numpy
- scipy
- matplotlib
- pandas
- scikit-image
- networkx
- scikit-learn
- xarray
- ipython
- zarr

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please open issues or pull requests on GitHub.

## Related

- [PHEP 3](https://github.com/heliophysicsPy/standards/blob/main/pheps/phep-0003.md) - PyHC Python & Upstream Package Support Policy
- [SPEC 0](https://scientific-python.org/specs/spec-0000/) - Scientific Python Minimum Supported Versions
- [PyHC Environment](https://github.com/heliophysicsPy/pyhc-docker-environment) - Docker environment with all PyHC packages
