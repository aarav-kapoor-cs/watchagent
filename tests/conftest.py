"""Shared test fixtures.

The API module builds a module-level ``Storage`` at import time, so we point
``DATABASE_PATH`` at a temp file before importing it. Each test then gets a
fresh, isolated database via the ``storage`` fixture — no shared state, no real
network, no writes to the container's /data path.
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Must be set before app.main / app.storage read DATABASE_PATH at import time.
_TMPDIR = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_PATH", os.path.join(_TMPDIR, "import_time.db"))

from app.storage import Storage  # noqa: E402


@pytest.fixture
def storage(tmp_path):
    """A fresh Storage backed by a per-test temporary SQLite file."""
    return Storage(path=str(tmp_path / "test.db"))
