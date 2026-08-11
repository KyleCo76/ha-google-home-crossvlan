"""Tests for Google Home config-entry setup and option updates."""

# Ruff treats Home Assistant as first-party; Pylint treats it as third-party.
# pylint: disable=wrong-import-order

from datetime import timedelta
from typing import cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession
from zeroconf import Zeroconf

from custom_components.google_home import async_setup_entry, async_update_entry
from custom_components.google_home.const import (
    CONF_DEVICE_ADDRESSES,
    CONF_UPDATE_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.google_home.types import GoogleHomeConfigEntry
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


def _make_hass() -> tuple[HomeAssistant, MagicMock]:
    """Create a Home Assistant mock with mutable integration data."""
    hass_mock = MagicMock(spec=HomeAssistant)
    hass_mock.data = {}
    hass_mock.config_entries.async_forward_entry_setups = AsyncMock()
    return cast("HomeAssistant", hass_mock), hass_mock


def _make_entry(options: dict[str, object]) -> GoogleHomeConfigEntry:
    """Create a typed config-entry mock."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "entry-id"
    entry.data = {
        "username": "user@example.invalid",
        "password": "app-password",
        "master_token": "master-token",
        "android_id": "android-id",
    }
    entry.options = options
    return cast("GoogleHomeConfigEntry", entry)


class TestSetupEntry(IsolatedAsyncioTestCase):
    """Test config-entry setup option propagation."""

    async def test_setup_passes_device_addresses_to_api_client(self) -> None:
        """The stored exact-name mapping reaches the API client."""
        addresses = {"Kitchen Speaker": "192.0.2.50"}
        hass, hass_mock = _make_hass()
        entry = _make_entry(
            {CONF_UPDATE_INTERVAL: 180, CONF_DEVICE_ADDRESSES: addresses}
        )
        session = MagicMock(spec=ClientSession)
        zeroconf_instance = MagicMock(spec=Zeroconf)
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.async_config_entry_first_refresh = AsyncMock()

        with (
            patch(
                "custom_components.google_home.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.google_home.zeroconf.async_get_instance",
                new=AsyncMock(return_value=zeroconf_instance),
            ),
            patch(
                "custom_components.google_home.GlocaltokensApiClient"
            ) as client_class,
            patch(
                "custom_components.google_home.DataUpdateCoordinator",
                return_value=coordinator,
            ),
        ):
            await async_setup_entry(hass, entry)

        client_class.assert_called_once_with(
            hass=hass,
            session=session,
            username="user@example.invalid",
            password="app-password",
            master_token="master-token",
            android_id="android-id",
            zeroconf_instance=zeroconf_instance,
            device_addresses=addresses,
        )
        hass_mock.config_entries.async_forward_entry_setups.assert_awaited_once()


class TestUpdateEntry(IsolatedAsyncioTestCase):
    """Test reload and in-place option-update boundaries."""

    async def test_changed_mapping_schedules_reload_before_interval_mutation(
        self,
    ) -> None:
        """Entity-shaping address changes reload and leave this client untouched."""
        hass, hass_mock = _make_hass()
        entry = _make_entry(
            {
                CONF_UPDATE_INTERVAL: 240,
                CONF_DEVICE_ADDRESSES: {"Kitchen Speaker": "192.0.2.51"},
            }
        )
        client = MagicMock()
        client.device_addresses = {"Kitchen Speaker": "192.0.2.50"}
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        original_interval = timedelta(seconds=180)
        coordinator.update_interval = original_interval
        hass.data = {
            DOMAIN: {
                entry.entry_id: {
                    DATA_CLIENT: client,
                    DATA_COORDINATOR: coordinator,
                }
            }
        }

        await async_update_entry(hass, entry)

        hass_mock.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )
        assert coordinator.update_interval is original_interval

    async def test_unchanged_mapping_updates_interval_without_reload(self) -> None:
        """Polling-only changes retain the existing in-place update path."""
        addresses = {"Kitchen Speaker": "192.0.2.50"}
        hass, hass_mock = _make_hass()
        entry = _make_entry(
            {CONF_UPDATE_INTERVAL: 240, CONF_DEVICE_ADDRESSES: addresses}
        )
        client = MagicMock()
        client.device_addresses = addresses.copy()
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.update_interval = timedelta(seconds=180)
        hass.data = {
            DOMAIN: {
                entry.entry_id: {
                    DATA_CLIENT: client,
                    DATA_COORDINATOR: coordinator,
                }
            }
        }

        await async_update_entry(hass, entry)

        hass_mock.config_entries.async_schedule_reload.assert_not_called()
        assert coordinator.update_interval == timedelta(seconds=240)
