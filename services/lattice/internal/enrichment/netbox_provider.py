from __future__ import annotations

from .interfaces import InterfaceContextProvider
from .providers import InterfaceContextRecord


class NetBoxInterfaceContextProvider(InterfaceContextProvider):
    """
    Stub for NetBox backed interface enrichment.

    Intended use:
    - customer attachment metadata
    - service or circuit identifiers
    - peer annotations if modeled
    """

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.token = token

    def get_interface_context(
        self,
        device: str,
        interface: str,
    ) -> InterfaceContextRecord | None:
        # TODO:
        # 1. Query NetBox device/interface
        # 2. Resolve custom fields or related objects
        # 3. Return InterfaceContextRecord
        return None
