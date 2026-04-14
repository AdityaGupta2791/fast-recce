"""Pytest fixtures shared across test modules."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
