"""Tests for the Google Home config flow."""

# Ruff treats Home Assistant as first-party; Pylint treats it as third-party.
# pylint: disable=wrong-import-order

from typing import TYPE_CHECKING, cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from custom_components.google_home.config_flow import (
    GoogleHomeOptionsFlowHandler,
    validate_device_addresses,
)
from custom_components.google_home.const import (
    CONF_DEVICE_ADDRESSES,
    CONF_UPDATE_INTERVAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector

if TYPE_CHECKING:
    from custom_components.google_home.types import OptionsFlowDict


def _schema_field(result: dict[str, object], field_name: str) -> object:
    """Return a validator from a flow-result schema by field name."""
    data_schema = cast("vol.Schema", result["data_schema"])
    for marker, field_validator in data_schema.schema.items():
        if isinstance(marker, vol.Marker) and marker.schema == field_name:
            return field_validator
    raise AssertionError(f"Missing schema field: {field_name}")


def _make_options_flow(
    options: dict[str, object] | None = None,
) -> GoogleHomeOptionsFlowHandler:
    """Create an options flow backed by a mock config entry."""
    flow = GoogleHomeOptionsFlowHandler()
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock(spec=ConfigEntry)
    entry.options = options or {}
    hass.config_entries.async_get_known_entry.return_value = entry
    flow.hass = cast("HomeAssistant", hass)
    flow.handler = "entry-id"
    return flow


class TestValidateDeviceAddresses(TestCase):
    """Test strict manual-address validation."""

    def test_empty_mapping_is_valid(self) -> None:
        """An empty mapping preserves automatic discovery."""
        assert not validate_device_addresses({})

    def test_valid_mapping_preserves_exact_name_and_address(self) -> None:
        """Validation does not normalize case, spacing, or the IPv4 value."""
        addresses = {"  Kitchen Speaker  ": "192.0.2.50"}

        assert validate_device_addresses(addresses) == addresses

    def test_non_mapping_is_invalid(self) -> None:
        """The option must be an object mapping."""
        with pytest.raises(vol.Invalid):
            validate_device_addresses(["Kitchen Speaker", "192.0.2.50"])

    def test_blank_device_names_are_invalid(self) -> None:
        """Device names must contain non-whitespace characters."""
        for name in ("", "   "):
            with self.subTest(name=name), pytest.raises(vol.Invalid):
                validate_device_addresses({name: "192.0.2.50"})

    def test_non_string_device_name_is_invalid(self) -> None:
        """Device names must be strings."""
        with pytest.raises(vol.Invalid):
            validate_device_addresses({42: "192.0.2.50"})

    def test_non_string_address_is_invalid(self) -> None:
        """Device addresses must be strings."""
        with pytest.raises(vol.Invalid):
            validate_device_addresses({"Kitchen Speaker": 192002050})

    def test_malformed_ipv4_is_invalid(self) -> None:
        """Malformed IPv4 addresses are rejected."""
        with pytest.raises(vol.Invalid):
            validate_device_addresses({"Kitchen Speaker": "192.0.2.999"})

    def test_ipv6_is_invalid(self) -> None:
        """IPv6 addresses are deliberately rejected."""
        with pytest.raises(vol.Invalid):
            validate_device_addresses({"Kitchen Speaker": "2001:db8::50"})


class TestGoogleHomeOptionsFlowHandler(IsolatedAsyncioTestCase):
    """Test manual-address options handling."""

    async def test_valid_mapping_is_stored_unchanged(self) -> None:
        """A valid exact-name mapping is stored without normalization."""
        flow = _make_options_flow()
        addresses = {"  Kitchen Speaker  ": "192.0.2.50"}

        result = await flow.async_step_init(
            cast(
                "OptionsFlowDict",
                {
                    CONF_UPDATE_INTERVAL: 180,
                    CONF_DEVICE_ADDRESSES: addresses,
                },
            )
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] is not None
        assert result["data"][CONF_DEVICE_ADDRESSES] == addresses

    async def test_invalid_mapping_returns_field_error_and_preserves_input(
        self,
    ) -> None:
        """Invalid objects remain in the form so users can correct them."""
        flow = _make_options_flow()
        invalid_addresses = {"Kitchen Speaker": "2001:db8::50"}

        result = await flow.async_step_init(
            cast(
                "OptionsFlowDict",
                {
                    CONF_UPDATE_INTERVAL: 180,
                    CONF_DEVICE_ADDRESSES: invalid_addresses,
                },
            )
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] is not None
        assert result["errors"][CONF_DEVICE_ADDRESSES] == "invalid_device_addresses"
        data_schema = cast("vol.Schema", result["data_schema"])
        assert data_schema({})[CONF_DEVICE_ADDRESSES] == invalid_addresses

    async def test_form_uses_native_object_selector(self) -> None:
        """The address mapping uses Home Assistant's object selector."""
        flow = _make_options_flow()

        result = await flow.async_step_init()

        assert isinstance(
            _schema_field(cast("dict[str, object]", result), CONF_DEVICE_ADDRESSES),
            selector.ObjectSelector,
        )

    async def test_omitted_and_empty_mappings_are_allowed(self) -> None:
        """Both absent and empty mappings preserve stock discovery semantics."""
        for user_input in (
            {CONF_UPDATE_INTERVAL: 180},
            {CONF_UPDATE_INTERVAL: 180, CONF_DEVICE_ADDRESSES: {}},
        ):
            with self.subTest(user_input=user_input):
                flow = _make_options_flow()
                result = await flow.async_step_init(cast("OptionsFlowDict", user_input))

                assert result["type"] is FlowResultType.CREATE_ENTRY
                assert result["data"] == user_input
