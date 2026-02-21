"""Domestia virtual outputs as buttons."""

from __future__ import annotations

import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VIRTUAL_BUTTONS
from .udp import build_relay_payload, send_udp_command


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    host = data["host"]
    port = data["port"]

    entities = [
        DomestiaVirtualButton(host, port, output_id, name)
        for output_id, name in VIRTUAL_BUTTONS.items()
    ]
    async_add_entities(entities)


class DomestiaVirtualButton(ButtonEntity):
    def __init__(self, host: str, port: int, output_id: int, name: str):
        self._host = host
        self._port = port
        self._id = int(output_id)
        self._attr_name = f"Domestia {name}"
        self._attr_unique_id = f"domestia_virtual_{self._id}"

    async def async_press(self) -> None:
        on_payload = build_relay_payload(self._id, True)
        off_payload = build_relay_payload(self._id, False)

        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, on_payload)
        await asyncio.sleep(0.2)
        await self.hass.async_add_executor_job(send_udp_command, self._host, self._port, off_payload)