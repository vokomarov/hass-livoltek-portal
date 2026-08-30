"""Setup, captcha, reauth, and options."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.livoltek_portal.api import (
    DeviceRef,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
    LivoltekUnknownAccountError,
    Session,
)
from custom_components.livoltek_portal.const import (
    CONF_ACCOUNT_TYPE,
    CONF_DEVICES,
    CONF_LOGIN_ACCOUNT,
    CONF_PASSWORD_MD5,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DOMAIN,
)

from .test_init import DEVICE_OPTION, build_entry

DEVICE = DeviceRef(
    device_id=12345,
    inverter_sn="HP1XXXXHSC1XXXXX",
    name="HP1XXXXHSC1XXXXX(Hyper-6000)",
    product_type_name="Hyper-6000",
    template=44,
    power_station_name="Home",
)
CREDENTIALS = {
    CONF_LOGIN_ACCOUNT: "user@example.com",
    "password": "hunter2",
    CONF_ACCOUNT_TYPE: "email",
}
EXPIRY = datetime.now(UTC) + timedelta(days=30)


@pytest.fixture
def mock_login():
    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        AsyncMock(return_value=Session("tok", EXPIRY, "9001")),
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_devices():
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_list_devices",
        AsyncMock(return_value=[DEVICE]),
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_setup_entry():
    with patch(
        "custom_components.livoltek_portal.async_setup_entry",
        AsyncMock(return_value=True),
    ) as mocked:
        yield mocked


async def start(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REGION: "emea"}
    )


async def test_the_happy_path_creates_an_entry(
    hass: HomeAssistant, mock_login, mock_devices, mock_setup_entry
) -> None:
    result = await start(hass)
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["step_id"] == "devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICES: ["12345"], CONF_SCAN_INTERVAL: 120}
    )
    assert result["step_id"] == "names"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"12345": "Loft inverter"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["options"][CONF_DEVICES][0]["display_name"] == "Loft inverter"
    # The plaintext password is never stored; only its MD5 digest, which the
    # portal accepts verbatim, so treat it as password-equivalent.
    assert "password" not in result["data"]
    assert result["data"][CONF_PASSWORD_MD5] == ("2ab96390c7dbe3439de74d0c9b0b1767")
    assert result["data"][CONF_TOKEN] == "tok"
    assert result["options"][CONF_DEVICES][0]["device_id"] == 12345


async def test_two_devices_cannot_share_one_entity_id_prefix(
    hass: HomeAssistant, mock_login, mock_setup_entry
) -> None:
    """Different text, one slug: Home Assistant would suffix the second
    device's entities with `_2` and never say why. The form has to catch it,
    because nothing downstream does."""
    second = replace(DEVICE, device_id=12346, inverter_sn="HP2XXXXHSC2XXXXX")
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_list_devices",
        AsyncMock(return_value=[DEVICE, second]),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DEVICES: ["12345", "12346"], CONF_SCAN_INTERVAL: 120},
        )
        assert result["step_id"] == "names"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"12345": "Loft inverter", "12346": "loft-inverter"}
        )
        assert result["errors"] == {"12346": "duplicate_device_name"}

        # A name that slugifies to nothing is the same trap by another route.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"12345": "Loft", "12346": "  ---  "}
        )
        assert result["errors"] == {"12346": "invalid_device_name"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"12345": "Loft", "12346": "Garage"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [d["display_name"] for d in result["options"][CONF_DEVICES]] == [
        "Loft",
        "Garage",
    ]


async def test_a_captcha_challenge_shows_the_image_step(
    hass: HomeAssistant, mock_devices, mock_setup_entry
) -> None:
    calls: list[dict] = []

    async def login(self, *, image_id=None, image_code=None):
        calls.append({"image_id": image_id, "image_code": image_code})
        if image_code is None:
            raise LivoltekCaptchaRequiredError("err.code", "captcha required")
        return Session("tok", EXPIRY, "9001")

    with (
        patch(
            "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login", login
        ),
        patch(
            "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_captcha",
            AsyncMock(return_value=("img-1", "/9j/4AAQaGk=")),
        ),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["step_id"] == "captcha"
        assert "captcha_url" in result["description_placeholders"]

        # The captcha form carries the sign-in fields, so the whole set is
        # resubmitted alongside the code, not the code alone.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CREDENTIALS, "image_code": "A1B2"}
        )
        assert result["step_id"] == "devices"

    assert calls[-1] == {"image_id": "img-1", "image_code": "A1B2"}


async def test_a_wrong_captcha_re_renders_the_step_with_a_new_image(
    hass: HomeAssistant, mock_setup_entry
) -> None:
    with (
        patch(
            "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
            AsyncMock(side_effect=LivoltekCaptchaRequiredError("err.code", "bad")),
        ),
        patch(
            "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_captcha",
            AsyncMock(return_value=("img-2", "/9j/4AAQaGk=")),
        ),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CREDENTIALS, "image_code": "WRONG"}
        )

    assert result["step_id"] == "captcha"
    assert result["errors"] == {"base": "invalid_captcha"}
    assert "captcha_url" in result["description_placeholders"]


async def test_wrong_password_after_captcha_re_renders_the_captcha_form(
    hass: HomeAssistant, mock_setup_entry
) -> None:
    """The captcha form carries the sign-in fields, so a rejected password
    re-renders it in place (with a fresh image and captcha_url), not a bounce
    back to the credentials step."""

    async def login(self, *, image_id=None, image_code=None):
        if image_code is None:
            raise LivoltekCaptchaRequiredError("err.password.need.verify", "verify")
        raise LivoltekAuthError("err.password", "bad")

    with (
        patch(
            "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login", login
        ),
        patch(
            "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_captcha",
            AsyncMock(return_value=("img-3", "/9j/4AAQaGk=")),
        ),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["step_id"] == "captcha"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CREDENTIALS, "image_code": "A1B2"}
        )

    assert result["step_id"] == "captcha"
    assert result["errors"] == {"base": "invalid_auth"}
    assert "captcha_url" in result["description_placeholders"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LivoltekAuthError("err.password", "bad"), "invalid_auth"),
        (LivoltekUnknownAccountError("err.user.not.exist", "no"), "unknown_account"),
        (LivoltekConnectionError("down"), "cannot_connect"),
    ],
)
async def test_login_failures_map_to_form_errors(
    hass: HomeAssistant, error, expected
) -> None:
    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        AsyncMock(side_effect=error),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )

    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": expected}


async def test_an_account_cannot_be_added_twice(
    hass: HomeAssistant, mock_login, mock_devices
) -> None:
    build_entry().add_to_hass(hass)

    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_no_devices_aborts_with_a_useful_reason(
    hass: HomeAssistant, mock_login
) -> None:
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_list_devices",
        AsyncMock(return_value=[]),
    ):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices"


async def test_reauth_asks_only_for_the_password(
    hass: HomeAssistant, mock_login, mock_setup_entry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "newpass"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD_MD5] != "5f4dcc3b5aa765d61d8327deb882cf99"


async def test_reauth_that_needs_a_captcha_routes_through_the_captcha_step(
    hass: HomeAssistant, mock_setup_entry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)

    async def login(self, *, image_id=None, image_code=None):
        if image_code is None:
            raise LivoltekCaptchaRequiredError("err.code", "need")
        return Session("tok", EXPIRY, "9001")

    with (
        patch(
            "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login", login
        ),
        patch(
            "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_captcha",
            AsyncMock(return_value=("img-3", "/9j/4AAQaGk=")),
        ),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass"}
        )
        assert result["step_id"] == "captcha"
        assert "captcha_url" in result["description_placeholders"]

        # The reauth captcha form is password + code (no account/region field).
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass", "image_code": "A1B2"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_a_failed_reauth_attempt_re_renders_the_same_form(
    hass: HomeAssistant,
) -> None:
    """A wrong password on retry must not lose the placeholder or the mask."""
    entry = build_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        AsyncMock(side_effect=LivoltekAuthError("err.password", "bad")),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "wrong"}
        )

    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["description_placeholders"]["account"] == "user@example.com"
    password_field = next(
        value
        for key, value in result["data_schema"].schema.items()
        if key == "password"
    )
    assert password_field.config["type"] == "password"


async def test_reauth_with_a_different_account_aborts_without_updating_the_entry(
    hass: HomeAssistant,
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    original_token = entry.data[CONF_TOKEN]

    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        AsyncMock(return_value=Session("new-tok", EXPIRY, "9999")),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_TOKEN] == original_token


async def test_options_flow_changes_the_interval_and_the_device_set(
    hass: HomeAssistant, mock_devices
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.livoltek_portal.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_DEVICES: ["12345"], CONF_SCAN_INTERVAL: 300}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 300
    assert result["data"][CONF_DEVICES] == [DEVICE_OPTION]


async def test_options_flow_survives_an_unreachable_portal(hass: HomeAssistant) -> None:
    """The user must still be able to change the poll interval offline."""
    entry = build_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.livoltek_portal.async_setup_entry",
            AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.livoltek_portal.api.client.LivoltekClient.async_list_devices",
            AsyncMock(side_effect=LivoltekConnectionError("down")),
        ),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_DEVICES: ["12345"], CONF_SCAN_INTERVAL: 300}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICES] == [DEVICE_OPTION]
