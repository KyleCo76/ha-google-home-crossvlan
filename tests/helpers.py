"""Test helpers for Google Home."""

from collections.abc import Callable
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from custom_components.google_home.api import GlocaltokensApiClient

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from homeassistant.core import HomeAssistant


class ImmediateExecutor:
    """Run executor jobs synchronously for unit tests."""

    async def async_add_executor_job[T](self, target: Callable[[], T]) -> T:
        """Run and return an executor target."""
        return target()


def make_client() -> tuple[GlocaltokensApiClient, MagicMock]:
    """Create an API client without constructing a real glocaltokens client."""
    with patch(
        "custom_components.google_home.api.GLocalAuthenticationTokens"
    ) as client_class:
        client = GlocaltokensApiClient(
            hass=cast("HomeAssistant", ImmediateExecutor()),
            session=cast("ClientSession", MagicMock()),
        )
    return client, client_class.return_value
