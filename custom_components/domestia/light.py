"""Domestia dimmers (Type 6) - Config Entry + Coordinator + Auto-découverte."""

from __future__ import annotations

import asyncio
import time

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .udp import build_dimmer_payload, get_output_value, send_udp_command

HOLD_SECONDS = 6.0  
POST_COMMAND_REFRESH_DELAY = 0.35


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
        if info["type"] == 6:
            entities.append(
                DomestiaDimmerLight(coordinator, host, port, output_id, info["name"])
            )

    async_add_entities(entities)


class DomestiaDimmerLight(CoordinatorEntity, LightEntity):
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator, host: str, port: int, output_id: int, name: str) -> None:
        super().__init__(coordinator)
        self._host = str(host)
        self._port = int(port)
        self._id = int(output_id)

        self._attr_name = f"Domestia {name}"
        self._attr_unique_id = f"domestia_dimmer_{self._id}"

        self._hold_until = 0.0
        self._optimistic_is_on = False
        self._optimistic_brightness = 0

    def _hold_active(self) -> bool:
        return time.time() < self._hold_until

    @property
    def is_on(self) -> bool:
        if self._hold_active():
            return self._optimistic_is_on

        frame = self.coordinator.data
        if not frame:
            return False
        return get_output_value(frame, self._id) > 0

    @property
    def brightness(self) -> int:
        if self._hold_active():
            return self._optimistic_brightness

        frame = self.coordinator.data
        if not frame:
            return 0

        val = get_output_value(frame, self._id)  
        if val <= 0:
            return 0
        return int((val / 64) * 255)

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        brightness = max(0, min(255, int(brightness)))

        level = int((brightness / 255) * 64)
        if level <= 0:
            level = 1

        payload = build_dimmer_payload(self._id, level)

        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, payload)

        self._optimistic_is_on = True
        self._optimistic_brightness = brightness
        self._hold_until = time.time() + HOLD_SECONDS
        self.async_write_ha_state()

        await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        payload = build_dimmer_payload(self._id, 0)

        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, payload)

        self._optimistic_is_on = False
        self._optimistic_brightness = 0
        self._hold_until = time.time() + HOLD_SECONDS
        self.async_write_ha_state()

        await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()
