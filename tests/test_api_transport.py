"""Every upstream response is HTTP 200; the envelope is the only success
signal, so these mappings are the whole error-handling surface."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.livoltek_portal.api.errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
    LivoltekTokenError,
    LivoltekUnknownAccountError,
)
from custom_components.livoltek_portal.api.models import DeviceRef
from custom_components.livoltek_portal.api.transport import (
    async_request,
    check_envelope,
)


def test_success_envelope_returns_itself() -> None:
    envelope = {"data": {"a": 1}, "msg_code": "operate.success", "total": 1}
    assert check_envelope(envelope) == envelope


def test_msg_code_wins_over_msg_code_camel_case() -> None:
    """Both keys appear in every recorded response; snake_case is authoritative."""
    with pytest.raises(LivoltekAuthError):
        check_envelope(
            {"data": None, "msg_code": "err.password", "msgCode": "operate.success"}
        )


def test_camel_case_is_used_when_snake_case_is_missing() -> None:
    envelope = {"data": [], "msgCode": "operate.success"}
    assert check_envelope(envelope) is envelope


@pytest.mark.parametrize(
    ("msg_code", "expected"),
    [
        ("err.password", LivoltekAuthError),
        ("err.password.need.verify", LivoltekCaptchaRequiredError),
        ("err.user.not.exist", LivoltekUnknownAccountError),
        ("err.account.not.exist", LivoltekUnknownAccountError),
        ("token.not.set", LivoltekTokenError),
        ("token.expired", LivoltekTokenError),
        ("token.invalid", LivoltekTokenError),
        ("service_error", LivoltekApiError),
        ("something.unmapped", LivoltekApiError),
    ],
)
def test_error_codes_map_to_their_exception(
    msg_code: str, expected: type[Exception]
) -> None:
    with pytest.raises(expected) as excinfo:
        check_envelope({"data": None, "msg_code": msg_code, "message": "boom"})
    assert excinfo.value.msg_code == msg_code


def test_captcha_error_is_not_confused_with_a_plain_password_error() -> None:
    """err.password.need.verify must reach the captcha step, not invalid_auth."""
    with pytest.raises(LivoltekCaptchaRequiredError):
        check_envelope({"msg_code": "err.password.need.verify"})


def test_token_error_is_an_auth_error_but_a_password_error_is_not_a_token_error() -> (
    None
):
    with pytest.raises(LivoltekTokenError):
        check_envelope({"msg_code": "token.expired"})
    with pytest.raises(LivoltekAuthError) as excinfo:
        check_envelope({"msg_code": "err.password"})
    assert not isinstance(excinfo.value, LivoltekTokenError)


@pytest.mark.parametrize("payload", [None, [], "text", 42])
def test_non_object_responses_are_connection_errors(payload: Any) -> None:
    with pytest.raises(LivoltekConnectionError):
        check_envelope(payload)


def test_envelope_without_msg_code_is_a_connection_error() -> None:
    with pytest.raises(LivoltekConnectionError):
        check_envelope({"data": {"a": 1}})


async def test_async_request_sends_the_bearer_header_and_unwraps() -> None:
    with aioresponses() as mocked:
        mocked.post(
            "https://example.test/x",
            payload={"data": {"ok": True}, "msg_code": "operate.success"},
        )
        async with ClientSession() as session:
            envelope = await async_request(
                session, "POST", "https://example.test/x", json_body={}, token="T"
            )
    assert envelope["data"] == {"ok": True}
    request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["headers"]["Authorization"] == "Bearer T"


async def test_async_request_omits_the_header_when_unauthenticated() -> None:
    with aioresponses() as mocked:
        mocked.get(
            "https://example.test/c",
            payload={"data": {"image_id": "1"}, "msg_code": "operate.success"},
        )
        async with ClientSession() as session:
            await async_request(session, "GET", "https://example.test/c")
    request = next(iter(mocked.requests.values()))[0]
    assert "Authorization" not in request.kwargs["headers"]


async def test_async_request_wraps_transport_failures() -> None:
    with aioresponses() as mocked:
        mocked.post("https://example.test/x", exception=TimeoutError())
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await async_request(session, "POST", "https://example.test/x")


async def test_async_request_wraps_connection_failures() -> None:
    """Connection-refused / DNS-failure style errors surface the same way as a
    timeout — the generic `aiohttp.ClientError` catch-all."""
    with aioresponses() as mocked:
        mocked.post("https://example.test/x", exception=aiohttp.ClientConnectionError())
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await async_request(session, "POST", "https://example.test/x")


async def test_async_request_wraps_non_json_bodies() -> None:
    with aioresponses() as mocked:
        mocked.post("https://example.test/x", body="<html>502</html>", status=200)
        async with ClientSession() as session:
            with pytest.raises(LivoltekConnectionError):
                await async_request(session, "POST", "https://example.test/x")


def test_device_ref_from_recorded_payload(device_list_envelope: dict) -> None:
    ref = DeviceRef.from_payload(device_list_envelope["data"][0])
    assert ref is not None
    assert ref.device_id == 12345
    assert ref.inverter_sn == "HP1XXXXHSC1XXXXX"
    assert ref.product_type_name == "Hyper-6000"
    assert ref.template == 44
    assert ref.label == "HP1XXXXHSC1XXXXX(Hyper-6000) — Home"


def test_device_ref_rejects_entries_without_an_id_or_serial() -> None:
    assert DeviceRef.from_payload({"inverter_sn": "X"}) is None
    assert DeviceRef.from_payload({"id": 1}) is None
    assert DeviceRef.from_payload({"id": 1, "inverter_sn": ""}) is None


def test_device_ref_round_trips_through_entry_options(
    device_list_envelope: dict,
) -> None:
    ref = DeviceRef.from_payload(device_list_envelope["data"][0])
    assert ref is not None
    assert DeviceRef.from_dict(ref.as_dict()) == ref
