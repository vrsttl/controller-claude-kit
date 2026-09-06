# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Kit-wide constants and path helpers.

Single place for filesystem layout so every report module resolves the same
folders. The `RIPORTOK_DIR` environment variable overrides the default
`~/Riportok` project root (tests and the runner use it).
"""

from __future__ import annotations

import os
from pathlib import Path

KIT_VERSION = "0.1.0"

RIPORTOK_DIR = Path(os.environ.get("RIPORTOK_DIR", Path.home() / "Riportok"))


def riportok_dir() -> Path:
    """Project root, re-read from the environment on every call."""
    return Path(os.environ.get("RIPORTOK_DIR", Path.home() / "Riportok"))


def scripts_dir() -> Path:
    return riportok_dir() / "scripts"


def reports_dir() -> Path:
    return riportok_dir() / "reports"


def data_dir() -> Path:
    return riportok_dir() / "data"


def default_db_path() -> Path:
    return data_dir() / "invoices.db"
