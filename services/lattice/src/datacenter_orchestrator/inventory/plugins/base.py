"""
Inventory plugin interfaces.

Goal
Provide pluggable inventory ingestion so the orchestration engine is source agnostic.

Inventory is normalized into InventoryStore and DeviceRecord objects.

We keep the interface narrow so it is easy to mock in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from datacenter_orchestrator.inventory.store import InventoryStore


class InventoryPlugin(Protocol):
    """
    Inventory plugin interface.

    load returns a fully populated InventoryStore.
    """

    def load(self) -> InventoryStore:
        """Load inventory into an InventoryStore."""


@dataclass(frozen=True)
class InventoryLoadResult:
    """
    Optional result type if you want evidence.

    store is the normalized inventory.
    evidence is structured metadata about source and counts.
    """

    store: InventoryStore
    evidence: dict[str, object]
