from __future__ import annotations

from dataclasses import asdict
from typing import Any


def _normalize(obj: Any) -> Any:
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def to_json_safe_dict(obj: Any) -> dict[str, Any]:
    """
    Convert a dataclass object into a JSON safe dict.

    This is intended for transport only.
    """
    raw = asdict(obj)
    normalized = _normalize(raw)
    if not isinstance(normalized, dict):
        raise TypeError("expected dict after normalization")
    return normalized


def inventory_store_to_json(inventory: Any) -> dict[str, Any]:
    """
    InventoryStore transport shape.

    We only rely on inventory.all returning DeviceRecord dataclasses.
    """
    devices = []
    for dev in inventory.all():
        devices.append(to_json_safe_dict(dev))
    return {"devices": devices}
