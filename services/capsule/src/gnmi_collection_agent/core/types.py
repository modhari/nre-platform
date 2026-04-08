from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    vendor: str
    os_name: str
    model: str
    mgmt_address: str


@dataclass(frozen=True)
class CapabilityProfile:
    device_id: str
    supports_openconfig: bool
    supported_models: Dict[str, str]
    origins: Dict[str, str]
