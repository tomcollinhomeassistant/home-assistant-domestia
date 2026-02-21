"""Domestia integration (Config Entry + Coordinator + socket UDP persistant + auto-découverte)."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
)
from .udp import _get_client, discover_domestia_devices

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["switch", "light", "button", "cover"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    _LOGGER.info("Démarrage de la découverte matérielle Domestia sur %s...", host)
    discovered_devices = await hass.async_add_executor_job(
        discover_domestia_devices, host, port
    )
    _LOGGER.info("%d modules Domestia découverts !", len(discovered_devices))

    client = _get_client(host=host, port=port, timeout=2.5)
    last_frame: bytes | None = None

    async def _update_method() -> bytes:
        nonlocal last_frame
        try:
            frame = await hass.async_add_executor_job(client.read_states)
            if frame:
                last_frame = frame
                return frame
            if last_frame:
                return last_frame
            raise UpdateFailed("Aucune donnée reçue du contrôleur Domestia")
        except Exception as err:
            raise UpdateFailed(f"Erreur UDP: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=_update_method,
        update_interval=timedelta(seconds=scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "host": host,
        "port": port,
        "client": client,
        "devices": discovered_devices,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data and "client" in data:
            await hass.async_add_executor_job(data["client"].close)
    return unload_ok