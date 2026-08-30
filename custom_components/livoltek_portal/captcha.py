"""Serve portal captcha images from Home Assistant's own origin.

The portal returns the captcha as base64 image bytes bound to the session that
asked for it (probe 02: bare base64 JPEG). The browser cannot render that
inline in a config-flow form, so the integration decodes it and re-serves the
bytes under an opaque token. Tokens are not deleted on use or on flow
completion; the store simply caps itself at a handful of entries (see
`_MAX_ENTRIES` below) and evicts the oldest once that cap is hit.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .api import LivoltekApiError
from .const import DOMAIN

CAPTCHA_URL = f"/api/{DOMAIN}/captcha"
_STORE_KEY: HassKey[LivoltekCaptchaStore] = HassKey(f"{DOMAIN}_captcha_store")

# Keep a handful so a user who reloads the form a few times still sees an image.
_MAX_ENTRIES = 8
_DEFAULT_CONTENT_TYPE = "image/jpeg"

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"<svg", "image/svg+xml"),
)


class LivoltekCaptchaStore:
    """In-memory, per-instance captcha images keyed by an opaque token."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[bytes, str]] = {}

    async def async_store(self, image: bytes, content_type: str) -> str:
        token = secrets.token_urlsafe(32)
        self._entries[token] = (image, content_type)
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.pop(next(iter(self._entries)))
        return token

    async def async_get(self, token: str) -> tuple[bytes, str] | None:
        return self._entries.get(token)


class LivoltekCaptchaView(HomeAssistantView):
    """Serve one stored captcha image.

    Unauthenticated by necessity: the config-flow login form is rendered before
    the user has a Home Assistant session in some setups, and the browser
    fetches the image directly. The token is 32 random URL-safe bytes and maps
    to nothing but a throwaway captcha bitmap.
    """

    url = f"{CAPTCHA_URL}/{{token}}"
    name = f"api:{DOMAIN}:captcha"
    requires_auth = False

    def __init__(self, store: LivoltekCaptchaStore) -> None:
        self._store = store

    async def get(self, request: web.Request, token: str) -> web.Response:
        entry = await self._store.async_get(token)
        if entry is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        image, content_type = entry
        return web.Response(
            body=image,
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )


@callback
def async_register_view(hass: HomeAssistant) -> LivoltekCaptchaStore:
    """Register the view once; return the shared store."""
    if (store := hass.data.get(_STORE_KEY)) is not None:
        return store
    store = LivoltekCaptchaStore()
    hass.data[_STORE_KEY] = store
    hass.http.register_view(LivoltekCaptchaView(store))
    return store


def decode_captcha_image(image_field: str) -> tuple[bytes, str]:
    """Resolve the API's `data.image` into raw bytes and a content type.

    Probe 02 showed the portal returns bare base64 JPEG (`/9j/4AAQ...`), so
    that is the only path that has to work. A `data:` prefix is still stripped
    because it costs one line; the URL shape the OpenAPI hinted at does not
    exist and is not handled.
    """
    field = (image_field or "").strip()
    if not field:
        raise LivoltekApiError("captcha.empty", "The portal returned no captcha image")

    # "data:image/jpeg;base64,/9j/..." -> "/9j/..."
    if field.startswith("data:"):
        field = field.partition(",")[2]

    image = _decode(field)
    return image, _sniff(image)


def _decode(payload: str) -> bytes:
    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as err:
        raise LivoltekApiError(
            "captcha.decode_failed", "The captcha image could not be decoded"
        ) from err


def _sniff(image: bytes) -> str:
    for magic, content_type in _MAGIC:
        if image.startswith(magic):
            return content_type
    return _DEFAULT_CONTENT_TYPE


def captcha_markdown(token: str) -> dict[str, Any]:
    """Description placeholders that put the image in the form."""
    return {"captcha_url": f"{CAPTCHA_URL}/{token}"}
