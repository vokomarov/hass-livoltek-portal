"""Shared fixtures for the Livoltek Portal tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

# pytest-homeassistant-custom-component self-registers via a pytest11 entry
# point; declaring it again here as `pytest_plugins` double-registers it
# under a conflicting name and pytest refuses to start.

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in every test."""
    return


@pytest.fixture(autouse=True)
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test tries to resolve a real host.

    The test constants use the portal's real hostname, so a mock that misses
    one layer sends the suite at the live API. Name resolution is the first
    thing every such attempt does, so blocking it catches them all before a
    connection exists.
    """

    def _blocked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            f"A test tried to resolve {args[0]!r}. The suite is offline: mock "
            "the transport instead."
        )

    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


def load_fixture(name: str) -> Any:
    """Read a JSON fixture from tests/fixtures."""
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def telemetry_payload() -> dict[str, Any]:
    """The `data` object of a recorded energyStorageInfo response."""
    return load_fixture("energy_storage_info.json")


@pytest.fixture
def device_list_envelope() -> dict[str, Any]:
    """A recorded findAllByCustomer envelope."""
    return load_fixture("find_all_by_customer.json")
