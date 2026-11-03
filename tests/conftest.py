"""Shared test fixtures, available to every test file automatically."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from inferx.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client with the app's startup and shutdown running.

    Forces the mock backend, so tests never depend on the developer's
    environment variables or on a running model server.
    """
    monkeypatch.setenv("INFERX_BACKEND", "mock")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()