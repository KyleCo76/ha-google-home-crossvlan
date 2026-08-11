"""Tests for the Google Home API client."""

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from zeroconf import Zeroconf

from custom_components.google_home.models import GoogleHomeDevice

from .helpers import make_client, make_client_with_addresses


class TestGetGoogleDevices(IsolatedAsyncioTestCase):
    """Test glocaltokens discovery arguments."""

    async def test_absent_mapping_uses_exact_stock_call(self) -> None:
        """An absent mapping adds no arguments to the stock discovery call."""
        zeroconf_instance = MagicMock(spec=Zeroconf)
        client, glocaltokens_client = make_client()
        client.zeroconf_instance = zeroconf_instance
        glocaltokens_client.get_google_devices.return_value = []

        await client.get_google_devices()

        glocaltokens_client.get_google_devices.assert_called_once_with(
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=True,
        )

    async def test_empty_mapping_uses_exact_stock_call(self) -> None:
        """An empty mapping adds no arguments to the stock discovery call."""
        zeroconf_instance = MagicMock(spec=Zeroconf)
        client, glocaltokens_client = make_client_with_addresses({}, zeroconf_instance)
        glocaltokens_client.get_google_devices.return_value = []

        await client.get_google_devices()

        glocaltokens_client.get_google_devices.assert_called_once_with(
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=True,
        )

    async def test_nonempty_mapping_disables_discovery_for_all_devices(self) -> None:
        """A non-empty mapping switches the whole call to manual mode."""
        zeroconf_instance = MagicMock(spec=Zeroconf)
        addresses = {"Kitchen speaker": "192.0.2.50"}
        client, glocaltokens_client = make_client_with_addresses(
            addresses, zeroconf_instance
        )
        glocaltokens_client.get_google_devices.return_value = []

        await client.get_google_devices()

        glocaltokens_client.get_google_devices.assert_called_once_with(
            addresses=addresses,
            disable_discovery=True,
            zeroconf_instance=zeroconf_instance,
            force_homegraph_reload=True,
        )


class TestUpdateGoogleDevicesInformation(IsolatedAsyncioTestCase):
    """Test coordinator device updates."""

    async def test_ipless_device_warns_on_first_refresh_when_unavailable(self) -> None:
        """An initially unavailable IP-less device warns on the first refresh."""
        device = GoogleHomeDevice("device-1", "Bedroom display", "token")
        device.available = False
        client, _ = make_client()
        client.google_devices = [device]

        with (
            patch.object(
                client, "collect_data_from_endpoints", new_callable=AsyncMock
            ) as collect,
            patch("custom_components.google_home.api._LOGGER.warning") as warning,
        ):
            result = await client.update_google_devices_information()

        assert result == [device]
        assert not device.available
        collect.assert_not_awaited()
        warning.assert_called_once()
        assert warning.call_args.args[-1] == "Bedroom display"

    async def test_ipless_device_warns_once_per_client_runtime(self) -> None:
        """Repeated refreshes do not repeat a device's missing-IP warning."""
        device = GoogleHomeDevice("device-1", "Bedroom display", "token")
        client, _ = make_client()
        client.google_devices = [device]

        with patch("custom_components.google_home.api._LOGGER.warning") as warning:
            await client.update_google_devices_information()
            await client.update_google_devices_information()

        warning.assert_called_once()

    async def test_only_addressable_authenticated_devices_are_polled(self) -> None:
        """Polling keeps its stock subset while returning every device in order."""
        valid = GoogleHomeDevice("device-valid", "Addressable", "token", "192.0.2.10")
        ipless = GoogleHomeDevice("device-ipless", "No address", "token")
        tokenless = GoogleHomeDevice("device-tokenless", "No token", None, "192.0.2.11")
        devices = [valid, ipless, tokenless]
        client, _ = make_client()
        client.google_devices = devices

        with patch.object(
            client,
            "collect_data_from_endpoints",
            new_callable=AsyncMock,
            side_effect=lambda device: device,
        ) as collect:
            result = await client.update_google_devices_information()

        collect.assert_awaited_once_with(valid)
        assert result == devices

    async def test_each_ipless_device_id_warns_with_its_exact_name(self) -> None:
        """Warnings retain exact case and spacing for every distinct device ID."""
        first = GoogleHomeDevice("device-1", "Bedroom display", "token")
        second = GoogleHomeDevice("device-2", " bedroom Display ", "token")
        client, _ = make_client()
        client.google_devices = [first, second]

        with patch("custom_components.google_home.api._LOGGER.warning") as warning:
            await client.update_google_devices_information()

        assert warning.call_count == 2
        assert [warning_call.args[-1] for warning_call in warning.call_args_list] == [
            "Bedroom display",
            " bedroom Display ",
        ]
        assert "exact" in warning.call_args_list[0].args[0].lower()
        assert "spacing" in warning.call_args_list[0].args[0].lower()
