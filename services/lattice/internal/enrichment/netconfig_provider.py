from __future__ import annotations

from .interfaces import DeviceContextProvider
from .providers import DeviceContextRecord


class NetconfigDeviceContextProvider(DeviceContextProvider):
    """
    Stub for Netconfig backed device enrichment.

    Intended use:
    - datacenter
    - pop
    - region
    - site_code
    - role
    - topology placement metadata
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def get_device_context(self, device: str) -> DeviceContextRecord | None:
        # TODO:
        # 1. Query device metadata from Netconfig
        # 2. Map inventory fields into DeviceContextRecord
        return None
