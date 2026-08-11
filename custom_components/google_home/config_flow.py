"""Adds config flow for Google Home."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import IPv4Address
import logging
from typing import TYPE_CHECKING, Self

from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_DEVICE_ADDRESSES,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_REQUEST_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
    MANUFACTURER,
    MAX_PASSWORD_LENGTH,
    TIMEOUT,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken

if TYPE_CHECKING:
    from .types import ConfigFlowDict, GoogleHomeConfigEntry, OptionsFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


def validate_device_addresses(value: object) -> dict[str, str]:
    """Validate and copy an exact-name to IPv4-address mapping."""
    if not isinstance(value, Mapping):
        raise vol.Invalid("Device addresses must be a mapping")

    validated: dict[str, str] = {}
    for name, address in value.items():
        if not isinstance(name, str) or not name.strip():
            raise vol.Invalid("Device names must be non-empty strings")
        if not isinstance(address, str):
            raise vol.Invalid("Device addresses must be strings")
        try:
            IPv4Address(address)
        except ValueError as err:
            raise vol.Invalid("Device addresses must be valid IPv4 addresses") from err
        validated[name] = address
    return validated


class GoogleHomeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self.username: str | None = None
        self._errors: dict[str, str] = {}

    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow is matching this flow."""
        return other_flow.username == self.username

    async def async_step_user(
        self,
        user_input: ConfigFlowDict | None = None,  # type: ignore[override]
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            session = async_create_clientsession(self.hass)
            username = user_input.get(CONF_USERNAME, "")
            self.username = username
            password = user_input.get(CONF_PASSWORD, "")
            master_token = user_input.get(CONF_MASTER_TOKEN, "")

            if master_token or (username and password):
                client = None
                title = username

                if master_token:
                    client = GlocaltokensApiClient(
                        hass=self.hass,
                        session=session,
                        username="",
                        password="",
                        master_token=master_token,
                    )
                    access_token = await self._get_access_token(client)
                    if access_token:
                        title = f"{MANUFACTURER} (master_token)"
                    else:
                        self._errors["base"] = "master-token-invalid"
                # master_token not provided, so use username/password authentication
                elif len(password) < MAX_PASSWORD_LENGTH:
                    client = GlocaltokensApiClient(
                        hass=self.hass,
                        session=session,
                        username=username,
                        password=password,
                    )
                    master_token = await self._get_master_token(client)
                    if not master_token:
                        self._errors["base"] = "auth"
                else:
                    self._errors["base"] = "pass-len"

                if client and not self._errors:
                    config_data: dict[str, str] = {}
                    config_data[CONF_MASTER_TOKEN] = master_token
                    config_data[CONF_USERNAME] = username
                    config_data[CONF_PASSWORD] = password
                    config_data[CONF_ANDROID_ID] = await client.get_android_id()
                    return self.async_create_entry(title=title, data=config_data)
            else:
                self._errors["base"] = "missing-inputs"
        return await self._show_config_form()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: GoogleHomeConfigEntry,
    ) -> GoogleHomeOptionsFlowHandler:
        """Handle options flow."""
        return GoogleHomeOptionsFlowHandler()

    async def _show_config_form(self) -> ConfigFlowResult:
        """Show the configuration form to edit login information."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_MASTER_TOKEN): str,
                }
            ),
            errors=self._errors,
        )

    @staticmethod
    async def _get_master_token(client: GlocaltokensApiClient) -> str:
        """Return master token if credentials are valid."""
        master_token = ""
        try:
            master_token = await client.async_get_master_token()
        except (InvalidMasterToken, RequestException):
            _LOGGER.exception("Failed to get master token")
        return master_token

    @staticmethod
    async def _get_access_token(client: GlocaltokensApiClient) -> str:
        """Return access token if master token is valid."""
        access_token = ""
        try:
            access_token = await client.async_get_access_token()
        except (InvalidMasterToken, RequestException):
            _LOGGER.exception("Failed to get access token")
        return access_token


class GoogleHomeOptionsFlowHandler(OptionsFlow):
    """Config flow options handler for GoogleHome."""

    async def async_step_init(
        self, user_input: OptionsFlowDict | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        defaults: Mapping[str, object] = self.config_entry.options

        if user_input is not None:
            defaults = user_input
            try:
                device_addresses = validate_device_addresses(
                    user_input.get(CONF_DEVICE_ADDRESSES, {})
                )
            except vol.Invalid:
                errors[CONF_DEVICE_ADDRESSES] = "invalid_device_addresses"
            else:
                if CONF_DEVICE_ADDRESSES in user_input:
                    user_input[CONF_DEVICE_ADDRESSES] = device_addresses
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=defaults.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL),
                    ): int,
                    vol.Optional(
                        CONF_DEVICE_ADDRESSES,
                        default=defaults.get(CONF_DEVICE_ADDRESSES, {}),
                    ): selector.ObjectSelector(),
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT,
                        default=defaults.get(CONF_REQUEST_TIMEOUT, TIMEOUT),
                    ): vol.All(int, vol.Range(min=1)),
                }
            ),
            errors=errors,
        )
