"""Smoke tests for the package scaffold."""

from quant_hunter import __version__


def test_package_exposes_distribution_version() -> None:
    """The importable package and project metadata stay aligned."""
    assert __version__ == "0.1.0"
