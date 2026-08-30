"""Config and options flows."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify

from .api import (
    DeviceRef,
    LivoltekApiError,
    LivoltekAuth,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekClient,
    LivoltekConnectionError,
    LivoltekUnknownAccountError,
    Session,
    hash_password,
)
from .captcha import async_register_view, captcha_markdown, decode_captcha_image
from .const import (
    ACCOUNT_TYPES,
    CONF_ACCOUNT_TYPE,
    CONF_DEVICES,
    CONF_LOGIN_ACCOUNT,
    CONF_OWNER_ID,
    CONF_PASSWORD_MD5,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_ACCOUNT_TYPE,
    DEFAULT_REGION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

CONF_PASSWORD = "password"
CONF_IMAGE_CODE = "image_code"

REGION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REGION, default=DEFAULT_REGION): SelectSelector(
            SelectSelectorConfig(
                options=list(REGIONS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="region",
            )
        )
    }
)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN_ACCOUNT): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
        vol.Required(CONF_ACCOUNT_TYPE, default=DEFAULT_ACCOUNT_TYPE): SelectSelector(
            SelectSelectorConfig(
                options=list(ACCOUNT_TYPES),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="account_type",
            )
        ),
    }
)

# The captcha rides on the sign-in fields, not a form of its own: when the
# portal demands a code, the user confirms account and password on the same
# form, and a wrong password re-renders here with a fresh image.
CAPTCHA_SCHEMA = CREDENTIALS_SCHEMA.extend(
    {
        vol.Required(CONF_IMAGE_CODE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        )
    }
)

REAUTH_CONFIRM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        )
    }
)

# Reauth has no account or region field, so its captcha form is password + code.
REAUTH_CAPTCHA_SCHEMA = REAUTH_CONFIRM_SCHEMA.extend(
    {
        vol.Required(CONF_IMAGE_CODE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        )
    }
)

INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=3600,
        step=10,
        unit_of_measurement="s",
        mode=NumberSelectorMode.BOX,
    )
)


def _names_schema(devices: list[DeviceRef]) -> vol.Schema:
    """One text field per chosen device, keyed by its portal id."""
    return vol.Schema(
        {
            vol.Required(str(d.device_id), default=d.ha_name): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            )
            for d in devices
        }
    )


def _apply_names(
    devices: list[DeviceRef], user_input: dict[str, Any]
) -> tuple[list[DeviceRef], dict[str, str]]:
    """Attach the names the user typed, or report per-field errors.

    Uniqueness is checked on the slug, not the typed text, because the slug is
    what Home Assistant builds entity ids from: "Loft Inverter" and "loft
    inverter" are two names but one entity id, and letting both through means
    Home Assistant silently suffixes one set of entities with `_2`.
    """
    named: list[DeviceRef] = []
    seen: set[str] = set()
    errors: dict[str, str] = {}
    for device in devices:
        field = str(device.device_id)
        name = str(user_input.get(field, "")).strip()
        slug = slugify(name)
        # Tested against the name, not the slug: slugify() never returns an
        # empty string -- "---" comes back as "unknown", which would sail
        # through an emptiness check and produce `sensor.unknown_battery_soc`.
        if not any(character.isalnum() for character in name):
            errors[field] = "invalid_device_name"
        elif slug in seen:
            errors[field] = "duplicate_device_name"
        else:
            seen.add(slug)
            named.append(replace(device, display_name=name))
    return named, errors


def _device_options(devices: list[DeviceRef]) -> list[dict[str, str]]:
    return [{"value": str(d.device_id), "label": d.label} for d in devices]


class LivoltekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Region -> credentials -> (captcha) -> devices."""

    VERSION = 1

    def __init__(self) -> None:
        self._region: str = DEFAULT_REGION
        self._credentials: dict[str, Any] = {}
        self._auth: LivoltekAuth | None = None
        self._client: LivoltekClient | None = None
        self._devices: list[DeviceRef] = []
        self._chosen: list[DeviceRef] = []
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._image_id: str | None = None
        self._captcha_token: str | None = None
        self._reauth_entry: ConfigEntry | None = None
        self._session: Session | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LivoltekOptionsFlow:
        return LivoltekOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=REGION_SCHEMA)
        self._region = user_input[CONF_REGION]
        return await self.async_step_credentials()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="credentials", data_schema=CREDENTIALS_SCHEMA
            )
        self._credentials = {
            CONF_LOGIN_ACCOUNT: user_input[CONF_LOGIN_ACCOUNT],
            CONF_PASSWORD_MD5: hash_password(user_input[CONF_PASSWORD]),
            CONF_ACCOUNT_TYPE: user_input.get(CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE),
        }
        return await self._async_try_login(step_id="credentials")

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return await self._async_show_captcha()
        # The captcha form carries the sign-in fields too, so a rejected
        # password can be corrected here instead of bouncing back a step.
        if self._reauth_entry is not None:
            entry = self._reauth_entry
            self._credentials = {
                CONF_LOGIN_ACCOUNT: entry.data[CONF_LOGIN_ACCOUNT],
                CONF_PASSWORD_MD5: hash_password(user_input[CONF_PASSWORD]),
                CONF_ACCOUNT_TYPE: entry.data.get(
                    CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE
                ),
            }
        else:
            self._credentials = {
                CONF_LOGIN_ACCOUNT: user_input[CONF_LOGIN_ACCOUNT],
                CONF_PASSWORD_MD5: hash_password(user_input[CONF_PASSWORD]),
                CONF_ACCOUNT_TYPE: user_input.get(
                    CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE
                ),
            }
        return await self._async_try_login(
            step_id="captcha", image_code=user_input[CONF_IMAGE_CODE]
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="devices",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_DEVICES,
                            default=[str(d.device_id) for d in self._devices],
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=_device_options(self._devices),
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                        vol.Required(
                            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                        ): INTERVAL_SELECTOR,
                    }
                ),
            )

        selected = {str(value) for value in user_input[CONF_DEVICES]}
        chosen = [d for d in self._devices if str(d.device_id) in selected]
        if not chosen:
            return self.async_show_form(
                step_id="devices", errors={"base": "no_devices_selected"}
            )
        self._chosen = chosen
        self._scan_interval = int(user_input[CONF_SCAN_INTERVAL])
        return await self.async_step_names()

    async def async_step_names(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name each device, which is what every entity id is built from."""
        if user_input is None:
            return self.async_show_form(
                step_id="names", data_schema=_names_schema(self._chosen)
            )

        chosen, errors = _apply_names(self._chosen, user_input)
        if errors:
            return self.async_show_form(
                step_id="names",
                data_schema=self.add_suggested_values_to_schema(
                    _names_schema(self._chosen), user_input
                ),
                errors=errors,
            )

        assert self._session is not None
        return self.async_create_entry(
            title=self._credentials[CONF_LOGIN_ACCOUNT],
            data={
                CONF_REGION: self._region,
                **self._credentials,
                CONF_TOKEN: self._session.access_token,
                CONF_TOKEN_EXPIRES_AT: (
                    self._session.expires_at.isoformat()
                    if self._session.expires_at
                    else None
                ),
                CONF_OWNER_ID: self._session.owner_id,
            },
            options={
                CONF_DEVICES: [d.as_dict() for d in chosen],
                CONF_SCAN_INTERVAL: self._scan_interval,
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._region = entry_data.get(CONF_REGION, DEFAULT_REGION)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._reauth_entry
        assert entry is not None
        if user_input is None:
            return self._show_reauth_confirm()
        self._credentials = {
            CONF_LOGIN_ACCOUNT: entry.data[CONF_LOGIN_ACCOUNT],
            CONF_PASSWORD_MD5: hash_password(user_input[CONF_PASSWORD]),
            CONF_ACCOUNT_TYPE: entry.data.get(CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE),
        }
        return await self._async_try_login(step_id="reauth_confirm")

    def _build_client(self) -> LivoltekClient:
        session = async_get_clientsession(self.hass)
        self._auth = LivoltekAuth(
            session,
            REGIONS[self._region],
            self._credentials[CONF_LOGIN_ACCOUNT],
            self._credentials[CONF_PASSWORD_MD5],
            account_type=self._credentials[CONF_ACCOUNT_TYPE],
        )
        self._client = LivoltekClient(session, REGIONS[self._region], self._auth)
        return self._client

    async def _async_try_login(
        self, *, step_id: str, image_code: str | None = None
    ) -> ConfigFlowResult:
        """One login attempt; every failure lands back on a form."""
        # Always start a fresh client: the aiohttp session (and its cookie jar,
        # which the captcha image id is bound to) is shared, so a rebuild keeps
        # the challenge valid while discarding any half-built auth state.
        client = self._build_client()
        assert self._auth is not None

        try:
            self._session = await self._auth.async_login(
                image_id=self._image_id if image_code else None,
                image_code=image_code,
            )
        except LivoltekCaptchaRequiredError:
            errors = {"base": "invalid_captcha"} if image_code else None
            return await self._async_show_captcha(errors=errors)
        except LivoltekUnknownAccountError:
            return await self._fail(step_id, "unknown_account")
        except LivoltekAuthError:
            return await self._fail(step_id, "invalid_auth")
        except LivoltekConnectionError:
            return await self._fail(step_id, "cannot_connect")
        except LivoltekApiError as err:
            # `unknown` means the portal returned a msg_code we do not map yet.
            # Log it (a status code, not account data) so it is diagnosable
            # instead of vanishing into a generic form error.
            _LOGGER.warning(
                "Login returned an unmapped portal msg_code %r: %s",
                err.msg_code,
                err.message or "",
            )
            return await self._fail(step_id, "unknown")

        assert self._session is not None
        await self.async_set_unique_id(self._session.owner_id)

        if self._reauth_entry is not None:
            # Reject credentials for a different account rather than silently
            # rebinding this entry (and every entity on it) to that account.
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates={
                    CONF_PASSWORD_MD5: self._credentials[CONF_PASSWORD_MD5],
                    CONF_TOKEN: self._session.access_token,
                    CONF_TOKEN_EXPIRES_AT: (
                        self._session.expires_at.isoformat()
                        if self._session.expires_at
                        else None
                    ),
                },
            )

        self._abort_if_unique_id_configured()

        try:
            self._devices = await client.async_list_devices()
        except (LivoltekApiError, LivoltekConnectionError):
            return await self._fail(step_id, "cannot_connect")
        if not self._devices:
            return self.async_abort(reason="no_devices")
        return await self.async_step_devices()

    async def _fail(self, step_id: str, error: str) -> ConfigFlowResult:
        """Re-show the form the attempt came from with an error.

        A captcha submission re-renders the captcha form itself (a fresh image
        plus the sign-in fields), so a rejected password or account is corrected
        in place. Re-showing that step needs the captcha_url placeholder --
        without it the frontend throws MISSING_VALUE and blanks the form -- which
        is why the captcha path goes through `_async_show_captcha`, not the plain
        `_retry`.
        """
        if step_id == "captcha":
            return await self._async_show_captcha(errors={"base": error})
        return self._retry(step_id, error)

    def _retry(self, step_id: str, error: str) -> ConfigFlowResult:
        """Re-show the credentials form (or the reauth form) with an error."""
        errors = {"base": error}
        if step_id == "reauth_confirm":
            return self._show_reauth_confirm(errors=errors)
        return self.async_show_form(
            step_id="credentials", data_schema=CREDENTIALS_SCHEMA, errors=errors
        )

    def _show_reauth_confirm(
        self, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        entry = self._reauth_entry
        assert entry is not None
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_CONFIRM_SCHEMA,
            errors=errors,
            description_placeholders={"account": entry.data[CONF_LOGIN_ACCOUNT]},
        )

    async def _async_show_captcha(
        self, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Fetch a fresh challenge; a used image id is never valid twice."""
        if self._client is None:
            self._build_client()
        assert self._client is not None
        store = async_register_view(self.hass)
        try:
            image_id, image_field = await self._client.async_get_captcha()
            image, content_type = decode_captcha_image(image_field)
        except (LivoltekApiError, LivoltekConnectionError):
            fallback = "reauth_confirm" if self._reauth_entry else "credentials"
            return self._retry(fallback, "cannot_connect")

        self._image_id = image_id
        self._captcha_token = await store.async_store(image, content_type)
        if self._reauth_entry is not None:
            schema: vol.Schema = REAUTH_CAPTCHA_SCHEMA
        else:
            # Prefill the account and type the user already typed; the password
            # field (a PASSWORD selector) is intentionally left blank to retype.
            schema = self.add_suggested_values_to_schema(
                CAPTCHA_SCHEMA,
                {
                    CONF_LOGIN_ACCOUNT: self._credentials.get(CONF_LOGIN_ACCOUNT, ""),
                    CONF_ACCOUNT_TYPE: self._credentials.get(
                        CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE
                    ),
                },
            )
        return self.async_show_form(
            step_id="captcha",
            data_schema=schema,
            errors=errors,
            description_placeholders=captcha_markdown(self._captcha_token),
        )


class LivoltekOptionsFlow(OptionsFlow):
    """Poll interval and device selection.

    Deliberately no renaming step. Home Assistant applies a changed device name
    to the device registry but never moves the entity ids that were generated
    from the old one, so an options rename would appear to work and leave every
    automation pointing at the old ids. Its own device-page rename dialog is
    the only thing that migrates entity ids, and it already asks.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        known = [
            DeviceRef.from_dict(raw) for raw in entry.options.get(CONF_DEVICES, [])
        ]

        if user_input is not None:
            selected = {str(value) for value in user_input[CONF_DEVICES]}
            catalog = {str(d.device_id): d for d in await self._async_catalog()}
            # `known` last: an already-configured device keeps the name the
            # user gave it, which a fresh portal listing does not carry.
            catalog.update({str(d.device_id): d for d in known})
            chosen = [catalog[key] for key in selected if key in catalog]
            if not chosen:
                return self.async_show_form(
                    step_id="init", errors={"base": "no_devices_selected"}
                )
            return self.async_create_entry(
                data={
                    CONF_DEVICES: [d.as_dict() for d in chosen],
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }
            )

        # Merge so a device that is temporarily missing from the portal listing
        # is still offered, and so the currently selected set stays checked.
        merged = {str(d.device_id): d for d in await self._async_catalog()}
        for device in known:
            merged.setdefault(str(device.device_id), device)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICES, default=[str(d.device_id) for d in known]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_device_options(list(merged.values())),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): INTERVAL_SELECTOR,
                }
            ),
        )

    async def _async_catalog(self) -> list[DeviceRef]:
        """Best-effort live device list; offline must not block the form."""
        from . import build_client

        try:
            return await build_client(self.hass, self.config_entry).async_list_devices()
        except Exception as err:  # options must stay usable offline
            _LOGGER.debug("Could not refresh the device list: %s", err)
            return []
