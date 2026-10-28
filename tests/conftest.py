"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from crosswalk_mcp import store
from crosswalk_mcp.tools import common
from tests.fixtures import write_raw_dir


@pytest.fixture(scope="session")
def tiny_store_path(tmp_path_factory) -> Path:
    """A store built once per session from the tiny export."""
    base = tmp_path_factory.mktemp("tiny")
    raw = write_raw_dir(base)
    out = base / "store.sqlite"
    store.build(raw, out)
    return out


@pytest.fixture
def tiny_store(tiny_store_path: Path):
    """Point the tools at the tiny store for one test, then detach."""
    common.configure_store(tiny_store_path)
    yield tiny_store_path
    common.configure_store(None)
