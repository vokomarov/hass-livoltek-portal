"""The four endpoints the integration uses.

`findAllDevice`, `getDeviceBySn`, `powerstation/inverterSelect` and
`energystorage/findAllNew` were all considered and are unnecessary:
`findAllByCustomer` returns the numeric device id directly.

`POST /nbp/logout` is deliberately never called. Unloading a config entry is not
a sign-out, and Home Assistant reloads entries routinely.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import aiohttp

from .auth import LivoltekAuth
from .errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekConnectionError,
    LivoltekTokenError,
)
from .models import DeviceRef
from .transport import async_request

_LOGGER = logging.getLogger(__name__)

CAPTCHA_PATH: Final = "/nbp/image/code"
DEVICE_LIST_PATH: Final = "/ctrller-manager/energystorage/findAllByCustomer"
TELEMETRY_PATH: Final = "/ctrller-manager/app/energystorage/energyStorageInfo"

# Also returned for some auth failures, so it earns one re-login and retry.
_RETRYABLE_SERVER_CODE: Final = "service_error"


def _should_relogin(err: LivoltekApiError) -> bool:
    if isinstance(err, LivoltekTokenError):
        return True
    if isinstance(err, LivoltekAuthError):
        # Wrong password, unknown account, captcha lockout: retrying loops.
        return False
    return err.msg_code == _RETRYABLE_SERVER_CODE


class LivoltekClient:
    """Endpoint methods over an authenticated session."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, auth: LivoltekAuth
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._auth = auth

    @property
    def auth(self) -> LivoltekAuth:
        return self._auth

    async def async_get_captcha(self) -> tuple[str, str]:
        """Fetch a captcha. Returns `(image_id, image)`.

        Probe 02 confirmed `data` carries `id`, `image` and `time_out`. The id
        key is `id`, NOT `image_id`, even though the login request that
        consumes the value sends it back as `image_id`. `image` is bare base64
        JPEG. `time_out` is ignored: an expired captcha just fails the login.
        """
        envelope = await async_request(
            self._session, "GET", f"{self._base_url}{CAPTCHA_PATH}"
        )
        data = envelope.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise LivoltekConnectionError("Captcha response carried no id")
        return str(data["id"]), str(data.get("image") or "")

    async def async_list_devices(self) -> list[DeviceRef]:
        """List the account's energy-storage devices.

        No paging parameters are documented and a single-device account cannot
        show whether the endpoint paginates, so this is handled defensively:
        compare `total` against the returned length, retry once with the paging
        shape the spec models for the sibling `findAllDevice`, then warn. It
        never silently presents a truncated list.
        """
        envelope = await self._async_authed_request(
            "POST", DEVICE_LIST_PATH, json_body={}
        )
        entries = _entries(envelope)
        total = envelope.get("total")

        if isinstance(total, int) and total > len(entries):
            paged = await self._async_authed_request(
                "POST", DEVICE_LIST_PATH, json_body={"start": 0, "pageSize": total}
            )
            paged_entries = _entries(paged)
            if len(paged_entries) > len(entries):
                entries = paged_entries
            if len(entries) < total:
                _LOGGER.warning(
                    "Livoltek returned %s of %s devices; some may be missing from "
                    "the picker",
                    len(entries),
                    total,
                )

        return [ref for ref in map(DeviceRef.from_payload, entries) if ref is not None]

    async def async_get_telemetry(self, device: DeviceRef) -> dict[str, Any]:
        """Fetch one device's realtime payload.

        The request body is ignored by the server — the recorded call sent
        literal placeholder strings and still returned the right device. The
        `?id=` query parameter is what selects it. A well-formed body is sent
        for fidelity with the portal; nothing may depend on it being read.

        `isUseChangeUnit=false` asks for base units at full precision. With
        `true` the server rounds as it rescales: probe 01 saw 2.09 MWh where
        `false` reported 2085.5 kWh — a 4.5 kWh error and 10 kWh resolution
        steps on a total_increasing Energy-dashboard sensor.
        """
        envelope = await self._async_authed_request(
            "POST",
            TELEMETRY_PATH,
            params={"id": str(device.device_id), "isUseChangeUnit": "false"},
            json_body={
                "id": str(device.device_id),
                "templateId": "" if device.template is None else str(device.template),
            },
        )
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise LivoltekConnectionError("Telemetry response carried no data object")
        return data

    async def _async_authed_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Any = None,
    ) -> dict[str, Any]:
        """Issue an authenticated request, with at most one re-login retry."""
        url = f"{self._base_url}{path}"
        token = await self._auth.async_get_token()
        try:
            return await async_request(
                self._session,
                method,
                url,
                json_body=json_body,
                params=params,
                token=token,
            )
        except LivoltekApiError as err:
            if not _should_relogin(err):
                raise

        # Exactly one retry. A second failure propagates, so a locked account or
        # a changed password cannot put the integration into a login loop.
        self._auth.invalidate()
        token = await self._auth.async_get_token()
        return await async_request(
            self._session, method, url, json_body=json_body, params=params, token=token
        )


def _entries(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    data = envelope.get("data")
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]
