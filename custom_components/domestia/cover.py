"""Domestia roller shutters (Covers) - Type 1 et 2 - Auto-découverte."""

from __future__ import annotations

import asyncio

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .udp import build_relay_payload, get_output_value, send_udp_command

POST_COMMAND_REFRESH_DELAY = 0.5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    host = data["host"]
    port = data["port"]
    devices = data["devices"]

    entities = []
    
    for output_id, info in devices.items():
        if info["type"] in (1, 2):
            entities.append(
                DomestiaCover(coordinator, host, port, output_id, info["name"])
            )

    async_add_entities(entities)


class DomestiaCover(CoordinatorEntity, CoverEntity):
    
    _attr_supported_features = (
        CoverEntityFeature.OPEN | 
        CoverEntityFeature.CLOSE | 
        CoverEntityFeature.STOP
    )

    def __init__(self, coordinator, host: str, port: int, output_id: int, name: str) -> None:
        super().__init__(coordinator)
        self._host = str(host)
        self._port = int(port)
        self._id = int(output_id)

        self._attr_name = f"Domestia {name}"
        self._attr_unique_id = f"domestia_cover_{self._id}"

    @property
    def current_cover_position(self) -> int | None:
        frame = self.coordinator.data
        if not frame:
            return None
        val = get_output_value(frame, self._id)
        return val % 128

    @property
    def is_closed(self) -> bool:
        pos = self.current_cover_position
        if pos is None:
            return None
        return pos == 0

    @property
    def is_opening(self) -> bool:
        frame = self.coordinator.data
        if not frame:
            return False
        val = get_output_value(frame, self._id)
        return val >= 128

    @property
    def is_closing(self) -> bool:
        return self.is_opening

    async def async_open_cover(self, **kwargs) -> None:
        payload = build_relay_payload(self._id, True)
        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, payload)
        await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs) -> None:
        payload = build_relay_payload(self._id, False)
        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, payload)
        await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs) -> None:
        payload = build_relay_payload(self._id, True)
        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, payload)
        await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()
