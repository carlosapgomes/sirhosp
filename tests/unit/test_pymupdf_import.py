# mypy: ignore-errors
"""Regression tests for PyMuPDF import stability in the container."""

from __future__ import annotations

import subprocess
import sys


def test_pymupdf_import_does_not_crash_python() -> None:
    """Importing PyMuPDF must not segfault the Python interpreter."""
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", "import pymupdf"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
