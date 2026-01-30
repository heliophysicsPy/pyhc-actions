# PyHC GitHub Actions

Reusable GitHub Actions for PyHC (Python in Heliophysics Community) package compliance checking.

## Actions

### 1. PHEP 3 Compliance Checker

Validates package requirements against [PHEP 3](https://doi.org/10.5281/zenodo.17794207):

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

#### Example Output

```
PHEP 3 Compliance Check
========================

ERRORS:
[ERROR] requires-python = ">=3.9" violates PHEP 3
        Python 3.9 released Oct 2020 (>36 months ago)
        Suggested: >=3.11

[ERROR] numpy>=1.19 violates PHEP 3
        Version 1.19 released Jun 2020 (>24 months ago)
        Suggested: numpy>=1.26

WARNINGS:
[WARN] scipy<1.14 has upper bound constraint
       Consider removing unless absolutely necessary

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

#### Example Output

```
PyHC Environment Compatibility Check
=====================================

ERRORS:
[ERROR] Dependency conflict with PyHC Environment
        Your package: numpy<2.0
        PyHC Environment: numpy>=2.0,<2.3.0
        No overlapping versions

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

# Run PyHC Environment compatibility check (requires uv)
pyhc-env-compat-check pyproject.toml

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

- [PHEP 3](https://doi.org/10.5281/zenodo.17794207) - PyHC Python & Upstream Package Support Policy
- [SPEC 0](https://scientific-python.org/specs/spec-0000/) - Scientific Python Minimum Supported Versions
- [PyHC Environment](https://github.com/heliophysicsPy/pyhc-docker-environment) - Docker environment with all PyHC packages
