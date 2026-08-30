"""The client is the only place that knows endpoint shapes and the retry rule."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.livoltek_portal.api.auth import LivoltekAuth
from custom_components.livoltek_portal.api.client import LivoltekClient
from custom_components.livoltek_portal.api.errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekConnectionError,
    LivoltekTokenError,
)
from custom_components.livoltek_portal.api.models import DeviceRef

from .test_api_auth import BASE_URL, LOGIN_URL, login_envelope, make_token

DEVICE_LIST_URL = f"{BASE_URL}/ctrller-manager/energystorage/findAllByCustomer"
TELEMETRY_RE = re.compile(
    r"^https://evs\.livoltek-portal\.test/ctrller-manager/app/energystorage/"
    r"energyStorageInfo\?.*$"
)
CAPTCHA_URL = f"{BASE_URL}/nbp/image/code"

DEVICE = DeviceRef(
    device_id=12345,
    inverter_sn="HP1XXXXHSC1XXXXX",
    name="HP1XXXXHSC1XXXXX(Hyper-6000)",
    product_type_name="Hyper-6000",
    template=44,
    power_station_name="Home",
)


def build_client(session: ClientSession) -> LivoltekClient:
    auth = LivoltekAuth(
        session,
        BASE_URL,
        "u",
        "p",
        token=make_token(datetime.now(UTC) + timedelta(days=30)),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    return LivoltekClient(session, BASE_URL, auth)


async def test_list_devices_posts_an_empty_body(device_list_envelope: dict) -> None:
    with aioresponses() as mocked:
        mocked.post(DEVICE_LIST_URL, payload=device_list_envelope)
        async with ClientSession() as session:
            devices = await build_client(session).async_list_devices()

    assert [d.device_id for d in devices] == [12345]
    assert devices[0].inverter_sn == "HP1XXXXHSC1XXXXX"
    assert next(iter(mocked.requests.values()))[0].kwargs["json"] == {}


async def test_list_devices_retries_paged_when_total_exceeds_the_page(
    device_list_envelope: dict,
) -> None:
    truncated = {**device_list_envelope, "total": 2}
    second = {
        **device_list_envelope,
        "total": 2,
        "data": [
            device_list_envelope["data"][0],
            {**device_list_envelope["data"][0], "id": 12346, "inverter_sn": "HP2"},
        ],
    }
    with aioresponses() as mocked:
        mocked.post(DEVICE_LIST_URL, payload=truncated)
        mocked.post(DEVICE_LIST_URL, payload=second)
        async with ClientSession() as session:
            devices = await build_client(session).async_list_devices()

    assert [d.device_id for d in devices] == [12345, 12346]
    calls = next(iter(mocked.requests.values()))
    assert calls[1].kwargs["json"] == {"start": 0, "pageSize": 2}


async def test_list_devices_warns_but_proceeds_when_the_paged_retry_still_truncates(
    device_list_envelope: dict, caplog: pytest.LogCaptureFixture
) -> None:
    truncated = {**device_list_envelope, "total": 5}
    with aioresponses() as mocked:
        mocked.post(DEVICE_LIST_URL, payload=truncated)
        mocked.post(DEVICE_LIST_URL, payload=truncated)
        async with ClientSession() as session:
            devices = await build_client(session).async_list_devices()

    assert len(devices) == 1
    assert "1 of 5" in caplog.text


async def test_list_devices_skips_entries_that_are_not_usable(
    device_list_envelope: dict,
) -> None:
    payload = {
        **device_list_envelope,
        "total": 2,
        "data": [device_list_envelope["data"][0], {"id": None, "inverter_sn": None}],
    }
    with aioresponses() as mocked:
        mocked.post(DEVICE_LIST_URL, payload=payload)
        mocked.post(DEVICE_LIST_URL, payload=payload)
        async with ClientSession() as session:
            devices = await build_client(session).async_list_devices()
    assert len(devices) == 1


async def test_telemetry_drives_the_device_from_the_query_string(
    telemetry_payload: dict,
) -> None:
    """The recorded call sent literal placeholder strings in the body and still
    returned the right device: `?id=` is what selects it."""
    with aioresponses() as mocked:
        mocked.post(
            TELEMETRY_RE,
            payload={"data": telemetry_payload, "msg_code": "operate.success"},
        )
        async with ClientSession() as session:
            data = await build_client(session).async_get_telemetry(DEVICE)

    assert data["batteryRestSoc"] == "95"
    url = str(next(iter(mocked.requests.keys()))[1])
    assert "id=12345" in url
    assert "isUseChangeUnit=false" in url
    body = next(iter(mocked.requests.values()))[0].kwargs["json"]
    assert body == {"id": "12345", "templateId": "44"}


async def test_telemetry_without_a_data_object_is_a_connection_error() -> None:
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"data": None, "msg_code": "operate.success"})
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await build_client(session).async_get_telemetry(DEVICE)


async def test_a_token_error_triggers_one_relogin_and_one_retry(
    telemetry_payload: dict,
) -> None:
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"msg_code": "token.expired"})
        mocked.post(LOGIN_URL, payload=login_envelope(fresh))
        mocked.post(
            TELEMETRY_RE,
            payload={"data": telemetry_payload, "msg_code": "operate.success"},
        )
        async with ClientSession() as session:
            client = build_client(session)
            data = await client.async_get_telemetry(DEVICE)

    assert data["batteryRestSoc"] == "95"
    assert client.auth.token == fresh


async def test_a_second_token_error_propagates_instead_of_looping(
    telemetry_payload: dict,
) -> None:
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"msg_code": "token.expired"}, repeat=True)
        mocked.post(LOGIN_URL, payload=login_envelope(fresh), repeat=True)
        async with ClientSession() as session:
            with pytest.raises(LivoltekTokenError):
                await build_client(session).async_get_telemetry(DEVICE)

    logins = mocked.requests[("POST", __import__("yarl").URL(LOGIN_URL))]
    assert len(logins) == 1


async def test_service_error_is_retried_once_after_relogin(
    telemetry_payload: dict,
) -> None:
    """service_error is also returned for some auth failures, so it earns one
    re-login. If the retry succeeds it was an auth failure."""
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"msg_code": "service_error"})
        mocked.post(LOGIN_URL, payload=login_envelope(fresh))
        mocked.post(
            TELEMETRY_RE,
            payload={"data": telemetry_payload, "msg_code": "operate.success"},
        )
        async with ClientSession() as session:
            data = await build_client(session).async_get_telemetry(DEVICE)
    assert data["batteryRestSoc"] == "95"


async def test_a_second_service_error_propagates_as_an_api_error() -> None:
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"msg_code": "service_error"}, repeat=True)
        mocked.post(LOGIN_URL, payload=login_envelope(fresh), repeat=True)
        async with ClientSession() as session:
            with pytest.raises(LivoltekApiError) as excinfo:
                await build_client(session).async_get_telemetry(DEVICE)
    assert excinfo.value.msg_code == "service_error"
    assert not isinstance(excinfo.value, LivoltekAuthError)


async def test_a_wrong_password_is_never_retried() -> None:
    """Retrying err.password against a locked account would burn login attempts."""
    with aioresponses() as mocked:
        mocked.post(TELEMETRY_RE, payload={"msg_code": "err.password"})
        async with ClientSession() as session:
            with pytest.raises(LivoltekAuthError):
                await build_client(session).async_get_telemetry(DEVICE)
    assert ("POST", __import__("yarl").URL(LOGIN_URL)) not in mocked.requests


async def test_captcha_is_fetched_unauthenticated() -> None:
    with aioresponses() as mocked:
        mocked.get(
            CAPTCHA_URL,
            payload={
                # Probe 02: the key is `id`, and `image` is bare base64 JPEG.
                "data": {"id": "i-1", "image": "/9j/4AAQ", "time_out": 300},
                "msg_code": "operate.success",
            },
        )
        async with ClientSession() as session:
            image_id, image = await build_client(session).async_get_captcha()

    assert (image_id, image) == ("i-1", "/9j/4AAQ")
    headers = next(iter(mocked.requests.values()))[0].kwargs["headers"]
    assert "Authorization" not in headers


async def test_a_captcha_keyed_as_image_id_is_rejected() -> None:
    """Guards the probe-02 finding: `image_id` is the login request's spelling,
    never the captcha response's. Reading it back would silently break."""
    with aioresponses() as mocked:
        mocked.get(
            CAPTCHA_URL,
            payload={
                "data": {"image_id": "i-1", "image": "/9j/4AAQ"},
                "msg_code": "operate.success",
            },
        )
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await build_client(session).async_get_captcha()


async def test_captcha_without_an_image_id_is_a_connection_error() -> None:
    with aioresponses() as mocked:
        mocked.get(CAPTCHA_URL, payload={"data": {}, "msg_code": "operate.success"})
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await build_client(session).async_get_captcha()
