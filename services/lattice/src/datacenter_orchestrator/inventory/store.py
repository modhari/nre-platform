"""
Inventory store.

Ruff notes
- Use built in generics like dict and list.
- Import Iterable from collections.abc.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from datacenter_orchestrator.core.types import DeviceRecord


@dataclass
class InventoryStore:
    """
    Simple in memory device registry keyed by device name.

    Sources populate it and plugins enrich it.
    Fabric graph builder consumes it.
    """

    _devices: dict[str, DeviceRecord] | None = None

    def __post_init__(self) -> None:
        if self._devices is None:
            self._devices = {}

    def add(self, dev: DeviceRecord) -> None:
        """Add or replace a device record."""
        self._devices[dev.name] = dev  # type: ignore[index]

    def get(self, name: str) -> DeviceRecord | None:
        """Return device record if present."""
        return self._devices.get(name) if self._devices else None

    def all(self) -> list[DeviceRecord]:
        """Return all devices as a list."""
        return list(self._devices.values()) if self._devices else []

    def names(self) -> list[str]:
        """Return sorted device names for deterministic behavior."""
        return sorted(self._devices.keys()) if self._devices else []

    def __iter__(self) -> Iterable[DeviceRecord]:
        """Allow for loops over InventoryStore."""
        return iter(self._devices.values()) if self._devices else iter(())
