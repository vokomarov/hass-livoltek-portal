"""Diagnostics are pasted into public GitHub issues. Nothing identifying may
survive the redaction."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from .test_init import build_entry

SECRETS = (
    "user@example.com",
    "5f4dcc3b5aa765d61d8327deb882cf99",
    "HP1XXXXHSC1XXXXX",
    "9001",
)

# Telemetry keys that identify the owner or their home rather than describing
# the hardware. Listed by key, not by value: a hardcoded value list is what let
# `stationName` and the timezone fields ship unredacted through a green suite,
# because nobody thought to add "Home" and "Springfield" to SECRETS. The test below
# reads each key's value out of the fixture, so a new identifying field is
# caught the moment it is added to the recorded payload.
#
# DELIBERATELY a second list, not derived from `TO_REDACT_TELEMETRY`. Deriving
# it would delete the only thing this test can prove: a key dropped from the
# production set would vanish from the expectation in the same edit, and the
# test would go green on the leak it exists to catch. The duplication is the
# mechanism. Do not "fix" it.
#
# Known limit: both lists are hand-maintained, so a genuinely NEW identifying
# field in a future firmware's payload ships unredacted until someone adds it
# to both. Closing that needs an allowlist -- dump only known-safe keys --
# which trades away the raw payload's value for discovering unmodelled fields.
# That is a product call, not a test tweak. See the ledger's R31.
IDENTIFYING_TELEMETRY_KEYS = (
    "inverterSn",
    "wifiSn",
    "battery1Sn",
    "name",
    "stationName",
    "stationId",
    "countryName",
    "timezone",
    "registrationTimezone",
    "updateTimeZone",
)


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """See tests/test_sensor.py for why this override is needed."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


async def test_diagnostics_match_the_snapshot(
    hass: HomeAssistant,
    hass_client,
    telemetry_payload: dict,
    snapshot: SnapshotAssertion,
) -> None:
    # build_entry() stamps token_expires_at from datetime.now(UTC); that field
    # is deliberately unredacted (see diagnostics.py), so it must be frozen or
    # the snapshot compares yesterday's wall clock against today's.
    with freeze_time("2026-08-01T00:00:00+00:00"):
        entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=telemetry_payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result == snapshot


async def test_no_secret_survives_the_dump(
    hass: HomeAssistant, hass_client, telemetry_payload: dict
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=telemetry_payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    dumped = json.dumps(result)
    for secret in SECRETS:
        assert secret not in dumped, f"{secret!r} leaked into diagnostics"
    assert entry.data["access_token"] not in dumped

    for key in IDENTIFYING_TELEMETRY_KEYS:
        value = telemetry_payload.get(key)
        assert value is not None, (
            f"{key!r} is missing from the recorded fixture, so this assertion "
            "proves nothing -- update the key list or the fixture."
        )
        assert str(value) not in dumped, (
            f"{key!r} leaked into diagnostics as {value!r}; add it to "
            "TO_REDACT_TELEMETRY"
        )


async def test_the_telemetry_payload_is_included_for_debugging(
    hass: HomeAssistant, hass_client, telemetry_payload: dict
) -> None:
    """The payload is the point of the dump; only its identifying fields go."""
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=telemetry_payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    device = result["devices"][0]
    assert device["telemetry"]["batteryRestSoc"] == telemetry_payload["batteryRestSoc"]
    assert device["telemetry"]["wifiSn"] == "**REDACTED**"
