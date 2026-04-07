"""
Static inventory plugin.

Reads a local json file that contains a list of devices.
This is useful for dev, tests, and small demos.

Schema example
{
  "devices": [
    {
      "name": "leaf1",
      "role": "leaf",
      "identity": {"vendor": "arista", "model": "7050", "os_name": "eos", "os_version": "4.30"},
      "endpoints": {"mgmt_host": "10.0.0.1", "gnmi_host": "10.0.0.1"},
      "location": {"pod": "pod1", "rack": "r1"},
      "links": [
        {"local_intf": "e1", "peer_device": "spine1", "peer_intf": "e1", "kind": "fabric"}
      ]
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    Link,
    LinkKind,
)
from datacenter_orchestrator.inventory.plugins.base import InventoryPlugin
from datacenter_orchestrator.inventory.store import InventoryStore


def _parse_role(role: str) -> DeviceRole:
    """
    Convert a role string to DeviceRole.

    This assumes DeviceRole is a StrEnum in your types module.
    """
    return DeviceRole(role)


def _parse_link_kind(kind: str) -> LinkKind:
    """Convert a link kind string to LinkKind."""
    return LinkKind(kind)


def _device_from_dict(obj: dict[str, Any]) -> DeviceRecord:
    """Convert a device dict into a DeviceRecord."""
    name = str(obj["name"])
    role = _parse_role(str(obj["role"]))

    identity_obj = obj.get("identity", {}) or {}
    endpoints_obj = obj.get("endpoints", {}) or {}
    location_obj = obj.get("location", {}) or {}

    identity = DeviceIdentity(
        vendor=str(identity_obj.get("vendor", "unknown")),
        model=str(identity_obj.get("model", "unknown")),
        os_name=str(identity_obj.get("os_name", "unknown")),
        os_version=str(identity_obj.get("os_version", "unknown")),
    )

    endpoints = DeviceEndpoints(
        mgmt_host=str(endpoints_obj.get("mgmt_host", "")),
        gnmi_host=str(endpoints_obj.get("gnmi_host", "")),
    )

    location = FabricLocation(
        pod=str(location_obj.get("pod", "")),
        rack=str(location_obj.get("rack", "")),
    )

    dev = DeviceRecord(
        name=name,
        role=role,
        identity=identity,
        endpoints=endpoints,
        location=location,
        links=[],
    )

    links_obj = obj.get("links", []) or []
    for raw in links_obj:
        if not isinstance(raw, dict):
            continue
        dev.links.append(
            Link(
                local_intf=str(raw.get("local_intf", "")),
                peer_device=str(raw.get("peer_device", "")),
                peer_intf=str(raw.get("peer_intf", "")),
                kind=_parse_link_kind(str(raw.get("kind", "fabric"))),
            )
        )

    return dev


@dataclass(frozen=True)
class StaticInventoryPlugin(InventoryPlugin):
    """
    Load inventory from a local json file.

    path points to a json file that matches the schema described in the module docstring.
    """

    path: Path

    def load(self) -> InventoryStore:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        devices = data.get("devices", [])

        store = InventoryStore()
        if isinstance(devices, list):
            for obj in devices:
                if isinstance(obj, dict):
                    store.add(_device_from_dict(obj))

        return store
