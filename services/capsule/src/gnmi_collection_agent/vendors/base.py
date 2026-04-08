from __future__ import annotations

from dataclasses import dataclass
from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.client import GnmiPath


@dataclass(frozen=True)
class SensorGroup:
    name: str
    sample_interval_s: float
    paths: List[GnmiPath]


class VendorPack:
    def match(self, ident: DeviceIdentity) -> bool:
        raise NotImplementedError

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        raise NotImplementedError
