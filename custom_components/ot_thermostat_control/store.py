"""JSON persistence for OT Thermostat Control adaptive state."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class OTStore:
    """Persistent JSON storage for adaptive state.

    Stores per-room data such as previous air temperature, MRT, setpoint,
    overshoot counts, and adaptive coast cycles. Data is persisted to
    .storage/ot_thermostat_control_{entry_id} as JSON.
    """

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._hass = hass
        self._path = Path(
            hass.config.path(f".storage/ot_thermostat_control_{entry_id}")
        )
        self._data: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        """Load stored data from disk."""
        try:
            data = await self._hass.async_add_executor_job(self._read_file)
            if isinstance(data, dict):
                self._data = data
            else:
                self._data = {}
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as err:
            _LOGGER.warning("Failed to load OT store %s: %s", self._path, err)
            self._data = {}
        return self._data

    async def async_save(self) -> None:
        """Save data to disk."""
        try:
            await self._hass.async_add_executor_job(self._write_file)
        except OSError as err:
            _LOGGER.error("Failed to save OT store %s: %s", self._path, err)

    def _read_file(self) -> Any:
        """Read JSON file (runs in executor)."""
        with open(self._path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write_file(self) -> None:
        """Write JSON file (runs in executor)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        tmp.replace(self._path)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the store."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in the store."""
        self._data[key] = value
