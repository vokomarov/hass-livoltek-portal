"""Captcha bytes reach the browser through Home Assistant, not the portal."""

from __future__ import annotations

import base64

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.livoltek_portal.captcha import (
    async_register_view,
    decode_captcha_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
# What the portal actually sends (probe 02): JPEG magic, bare base64.
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


def test_bare_base64_jpeg_is_decoded() -> None:
    """The real wire format from probe 02."""
    data, content_type = decode_captcha_image(base64.b64encode(JPEG).decode())
    assert data == JPEG
    assert content_type == "image/jpeg"


def test_a_data_uri_prefix_is_stripped() -> None:
    field = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    data, content_type = decode_captcha_image(field)
    assert data == JPEG
    assert content_type == "image/jpeg"


def test_png_magic_still_sniffs_as_png() -> None:
    """The content type comes from the bytes, not from the declared prefix."""
    data, content_type = decode_captcha_image(base64.b64encode(PNG).decode())
    assert data == PNG
    assert content_type == "image/png"


def test_an_unusable_field_raises() -> None:
    from custom_components.livoltek_portal.api import LivoltekApiError

    with pytest.raises(LivoltekApiError):
        decode_captcha_image("")


async def test_the_view_serves_stored_bytes_and_404s_on_a_bad_token(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    assert await async_setup_component(hass, "http", {})
    store = async_register_view(hass)
    token = await store.async_store(PNG, "image/png")

    client = await hass_client_no_auth()
    response = await client.get(f"/api/livoltek_portal/captcha/{token}")
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("image/png")
    assert await response.read() == PNG

    assert (await client.get("/api/livoltek_portal/captcha/nope")).status == 404


async def test_registering_the_view_twice_is_harmless(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "http", {})
    assert async_register_view(hass) is async_register_view(hass)
