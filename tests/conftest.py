"""Shared fixture and import path for the orchestrator tests."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log  # noqa: E402


@pytest.fixture
def con():
    c = log.open_db(":memory:")
    yield c
    c.close()
